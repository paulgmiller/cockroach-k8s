# CockroachDB with scalable local storage

CockroachDB v26.2.7 runs in namespace `cockroach` on context `zebu`.
The current desired size is **one database replica**, with no high availability.
The configuration uses multi-node startup and can scale when more workers exist.
Kubeconfig: `/home/pmiller/.kube/config`; credentials are excluded from Git.

## Apply and connect

```bash
export KUBECONFIG=/home/pmiller/.kube/config
kubectl --context=zebu apply -k manifests
kubectl --context=zebu -n cockroach rollout status statefulset/cockroachdb --timeout=300s
kubectl --context=zebu -n cockroach wait --for=condition=complete job/cockroachdb-init --timeout=600s
kubectl --context=zebu -n cockroach get pods,pvc,services
```

The init Job recognizes an existing initialized cluster. On a fresh store it
runs `cockroach init`. Headless service DNS publishes unready pods to allow
bootstrap and joining. Each node advertises its stable StatefulSet DNS name and
uses the first three ordinals as join addresses. Data replication is configured
for three copies; while only one database node runs, ranges are under-replicated.

SQL endpoint within this namespace:
`postgresql://root@cockroachdb.cockroach.svc.cluster.local:26257/defaultdb?sslmode=disable`.
Local access:

```bash
kubectl --kubeconfig=/home/pmiller/.kube/config --context=zebu -n cockroach \
  port-forward --address=127.0.0.1 service/cockroachdb 26257:26257 8080:8080
```

SQL: `postgresql://root@localhost:26257/defaultdb?sslmode=disable`.
DB Console: <http://localhost:8080>.

## Scale up

After adding at least three Ready workers with enough available CPU, memory and
disk space, run from this repository:

```bash
./scripts/scale.sh 3
# Later, with at least five usable workers:
./scripts/scale.sh 5
```

The helper updates the manifest replica count, applies it and waits for rollout.
Commit the updated manifest afterward. It rejects scale-down and fewer than
three replicas, and checks the count of Ready, schedulable Linux workers.
Taints, available resources and storage capacity can still prevent scheduling;
the worker count is a preliminary check, not a complete placement guarantee.
`KUBECONFIG` and `KUBE_CONTEXT` can override its defaults.

Each replica receives its own `local-data-cockroachdb-N` PVC via
`volumeClaimTemplates`. A dedicated Rancher Local Path Provisioner creates the
local directory and **local-type PV** automatically on the scheduled worker.
You do not need to create PV YAML for additional replicas. Required pod
anti-affinity places one database replica per worker. PVCs and PVs are retained
when replicas are removed or the StatefulSet is deleted.

After rollout, verify database health, not just pod readiness:

```bash
kubectl --context=zebu -n cockroach exec cockroachdb-0 -- \
  /cockroach/cockroach node status --insecure --host=localhost:26257 --ranges
```

All active database nodes should be live; allow replication to converge, then
check the DB Console for under-replicated and unavailable ranges. Three database
nodes on separate workers provide the intended three replicas; five database
nodes add capacity but do not automatically change the replication factor to five.
Review CockroachDB licensing before multi-node use, as well as TLS and workload sizing.

## Storage and tradeoffs

| Choice | Benefit | Tradeoff |
| --- | --- | --- |
| `start`, per-replica PVCs, join DNS and init Job | Supports adding database nodes without rewriting storage or startup | More configuration than `start-single-node`; init is explicit and scale-down requires decommissioning. One running node still provides no HA. |
| Automatic local PV provisioning | Adding workers and replicas creates storage automatically | Adds a controller, helper pods with host-directory access, and cluster-scoped RBAC. This is a directory provisioner, not disk management or replicated storage. |
| Local node directories, 10Gi declared capacity | No additional managed disks for new replicas | No enforced quota, reserved disk space, automatic expansion or backup. Worker root filesystem is shared; monitor it. Node deletion/reimaging/replacement can lose the store. |
| Required anti-affinity, PV node affinity | One database pod per worker and each store stays on its owning worker | Requires enough usable workers. A pod with an existing claim cannot simply fail over to another worker; recover the failed database node with a fresh store using CockroachDB's node-replacement procedure. |
| `Retain` for claims and PVs | Protects data from routine scale/namespace deletion | Old claims, PVs and directories require manual reclamation. Retention does not protect against disk loss. Never reuse a decommissioned node's store for a new node. |
| Insecure SQL and ClusterIP/ingress NetworkPolicy | Simple development access with no public load balancer | No TLS or password authentication; reachable clients can act as root. NetworkPolicy enforcement depends on the cluster network and does not replace authentication. |
| 250m CPU / 512Mi memory requested; 1 CPU / 1Gi limited per database pod | Small development footprint | CPU throttling and OOM restarts under load. Each pod has 128Mi cache/SQL memory budgets and 1Gi SQL temporary disk cap. Production needs workload sizing. |
| Pinned image versions, plain manifests | Reviewable installation with no CockroachDB operator | Tags are not immutable digests; upgrades, backups, certificates and recovery remain manual. |

The provisioner is v0.0.37, customized from the upstream deployment, scoped to
StorageClass `cockroach-local-auto` using provisioner ID `cockroach.local/local-path`.
It runs in `cockroach-storage` and uses `/var/lib/cockroachdb/volumes` on new
workers, creating a unique directory per PV. This StorageClass is not the cluster
default. Capacity requests are metadata; the provisioner does not enforce them.
The provisioner needs Kubernetes API permissions to manage PVs and helper pods;
its names are prefixed to avoid collisions with other installations.

Replica 0 retains the existing static PV `cockroachdb-local`, pointing to
`/var/lib/cockroachdb/cockroach` on `aks-main-11118102-vmss000001`. Other replicas
use automatically created PVs. The old `cockroach-local` StorageClass is unused.

For a fresh cluster, either prepare that bootstrap directory on the designated
worker and adjust its PV affinity, or omit the static bootstrap PV document in
`manifests/storage.yaml` so replica 0 is also dynamically provisioned. On this
existing cluster, preserve that PV to keep the current database.

## Scale down, pause and recovery

The database PodDisruptionBudget uses the integer `maxUnavailable: 1`, so the
number of pods required to stay Ready grows with the StatefulSet: two at three
replicas, four at five replicas. At one replica it permits complete downtime;
at two replicas it does not preserve a two-voter quorum. The budget controls
voluntary evictions such as node drains, not unexpected worker failures, direct
pod deletion, or the StatefulSet's own rolling updates. It tracks pod readiness,
not per-range replication health.

The current storage remains local PVs with required anti-affinity. A PDB alone
does not make those stores movable during worker replacement. To run three
database pods on two permanent workers through planned AKS upgrades, migrate
to per-replica managed CSI disks, use preferred anti-affinity, provide compatible
surge capacity and disk topology, and verify replication catches up between
evictions. That storage/placement conversion has not been applied.

Do not decrease replicas on an active multi-node database without first draining
and decommissioning the affected database nodes. Database node IDs are not pod
ordinals: obtain them with `cockroach node status`. Remove highest StatefulSet
ordinals first, wait for `cockroach node decommission ID --wait=all` to complete,
then reduce the desired replicas in the manifest and apply. Keep enough nodes
for the configured replication factor. A two-node cluster is not an HA target.

Retained claims for permanently decommissioned nodes must not be reused for
later scale-up. After verifying decommissioning and that the pod is gone, remove
that node's claim/store under a deliberate cleanup procedure. For dynamically
provisioned test volumes, changing the PV policy to `Delete` before deleting the
claim allows the provisioner's teardown to remove its directory. Do not do this
to stores containing needed data or to the retained bootstrap PV.

To pause the entire development database, scale it to zero (all SQL becomes
unavailable). Reapplying manifests resumes it on its retained stores:

```bash
kubectl --context=zebu -n cockroach scale statefulset/cockroachdb --replicas=0
```

Deleting namespace `cockroach` deletes its claims. Local PVs and directories
remain under `Retain`; the old Azure rollback disk uses `Delete` and is destroyed.
The provisioner namespace/RBAC and StorageClasses remain unless separately removed.
A Released local PV retains the old claim UID. Before reuse, stop any pod that
could access its directory, verify the intended data and new claim, and clear
its stale `spec.claimRef`; bind it explicitly to the intended replacement PVC.
For the bootstrap store that claim is `cockroach/local-data-cockroachdb-0`.
Do not clear bindings or repoint node affinity while stores are active.

On worker/disk loss, use CockroachDB's replacement/decommissioning process to
replicate onto a new empty store if healthy replicas remain. For total data loss,
restore an off-node backup. Merely moving PV affinity cannot recover missing data.
Automated off-node backups and tested recovery are still needed.

## Migration history

The initial minimal deployment used `start-single-node` and an Azure disk. Its
store was copied offline to the host directory using
[operations/migrate-to-host.yaml](operations/migrate-to-host.yaml), then wrapped
in a static local PV/PVC. The scalable conversion stopped the database, retained
that PV, rebound it to `local-data-cockroachdb-0`, and recreated the StatefulSet
with per-replica claims. The existing initialized database and data were preserved.

[operations/enable-replication.sql](operations/enable-replication.sql) changes
single-node-created replication overrides to three; it was executed once during
conversion. Do not blindly apply it to a cluster with custom zone policies.
The original Azure PVC `data-cockroachdb-0` remains an unused rollback copy and
still incurs disk charges. It is frozen at the earlier host migration; it has no
subsequent writes. Rollback to that old snapshot requires stopping the current
database and restoring the original manifest from commit `957fc8f`. Preserve new
writes using backup/restore or a compatible offline migration before rollback.

## Sources and verification

- [CockroachDB Kubernetes deployment](https://www.cockroachlabs.com/docs/stable/deploy-cockroachdb-with-kubernetes)
- [Local Path Provisioner v0.0.37](https://github.com/rancher/local-path-provisioner/tree/v0.0.37) ([Apache 2.0 license](LOCAL-PATH-LICENSE))
- [Kubernetes local volumes](https://kubernetes.io/docs/concepts/storage/volumes/#local)
- [Kubernetes PodDisruptionBudget semantics](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
- [CockroachDB licensing](https://www.cockroachlabs.com/docs/stable/licensing-faqs)

See [VERIFICATION.md](VERIFICATION.md) for checks on the actual cluster.
