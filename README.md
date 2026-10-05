# CockroachDB on AKS with managed CSI storage

Namespace: `cockroach`. Context: `zebu`.
Kubeconfig: `/home/pmiller/.kube/config` (not committed).
Current deployment: one CockroachDB v26.2.7 pod with a fresh 10Gi `managed-csi`
PVC, preferred anti-affinity, and a PDB with `maxUnavailable: 1`.

The database was deliberately reset at the user's request. Previous data was
not migrated. The old local store, local PV/PVC, original Azure rollback disk,
local provisioner namespace/RBAC and custom local StorageClasses were removed.
Only the new managed disk claim remains in this namespace.

## Operator recommendation

Cockroach Labs now labels the older manual Kubernetes deployment approach as
legacy and recommends the newer CockroachDB Operator for new deployments.
For ongoing scaling and lifecycle management, prefer that newer operator over
extending these manual manifests. The older Public operator on the legacy guide
is a separate implementation.

No CockroachDB operator or CRD is currently installed. This repository still
contains the manually managed deployment. An operator conversion needs its
chart settings checked against the intended replica count, managed-csi storage,
small development resources, pod placement and disruption budget. The example
operator deployment uses substantially larger resources than this deployment.
Installing it adds controller overhead and Kubernetes CRDs/RBAC, but does not
remove the need for quorum, compatible disk topology or spare upgrade capacity.

- [Legacy deployment guide](https://docs.cockroachlabs.com/docs/stable/deploy-cockroachdb-with-kubernetes)
- [Recommended operator deployment guide](https://docs.cockroachlabs.com/docs/stable/deploy-cockroachdb-with-cockroachdb-operator)

## Apply and access

```bash
export KUBECONFIG=/home/pmiller/.kube/config
kubectl --context=zebu apply -k manifests
kubectl --context=zebu -n cockroach rollout status statefulset/cockroachdb --timeout=300s
kubectl --context=zebu -n cockroach wait --for=condition=complete job/cockroachdb-init --timeout=600s
kubectl --context=zebu -n cockroach get pods,pvc,pdb
```

The init Job initializes a fresh cluster and recognizes an already initialized
cluster. Nodes use `cockroach start`, stable per-pod DNS and join addresses for
the first three ordinals. The headless service publishes unready addresses for
bootstrap. Each replica gets a separate `data-cockroachdb-N` claim through the
StatefulSet's volumeClaimTemplates.

SQL endpoint within this namespace:
`postgresql://root@cockroachdb.cockroach.svc.cluster.local:26257/defaultdb?sslmode=disable`.
Local access:

```bash
kubectl --context=zebu -n cockroach port-forward --address=127.0.0.1 \
  service/cockroachdb 26257:26257 8080:8080
```

SQL: `postgresql://root@localhost:26257/defaultdb?sslmode=disable`.
DB Console: <http://localhost:8080>.

## Scaling and planned upgrades

For the current manual deployment, `./scripts/scale.sh 3` updates the saved
replica count, applies it and waits for rollout. Commit the changed manifest.
The helper checks for at least two Ready, schedulable Linux workers; it does not
verify taints, available CPU/memory, disk-attachment slots or Azure quotas.
It rejects scale-down and target counts below three. Operator-managed scaling
would instead use the operator's cluster specification/chart values.

Preferred anti-affinity favors separate workers but allows multiple database
pods on one worker. Three pods can therefore run on two sufficiently provisioned
workers. This does not guarantee survival of a worker failure: losing the worker
hosting two pods can remove quorum. Three workers with suitable placement are
needed for worker-failure tolerance with three voting replicas.

For planned AKS worker upgrades, managed disks can detach and reattach to a
replacement pod on another compatible worker. Use adequate surge capacity
(e.g. maxSurge 1), compatible disk topology and the PDB. AKS surge settings have
not been changed by this repository. A one-replica database still has downtime
through termination, disk reattachment and startup. PDB maxUnavailable 1 permits
that single replica's eviction. With three replicas it requires two Ready; with
five it requires four. PDBs govern voluntary evictions, not unexpected failure,
direct deletion or the StatefulSet's own rolling updates. Readiness is not proof
of per-range replication convergence; check database health between disruptions.

The fresh cluster uses CockroachDB's standard replication policies: user data
requests three replicas and critical system ranges request five. With one live
node it is under-replicated and has no HA. Inspect zone policies and range health
when scaling; three pods alone do not satisfy every default five-copy policy.

## Tradeoffs and lifecycle

| Choice | Benefit | Limitation |
| --- | --- | --- |
| Per-replica managed-csi disks | Automatic disk provisioning and reattachment across eligible workers | Disk charges, attachment delays, per-node disk limits and topology constraints. Observed class uses StandardSSD_LRS; Azure billing tiers may exceed the requested 10Gi. |
| Preferred anti-affinity | Allows three database pods on two workers | Sharing a worker creates a correlated failure risk. |
| PDB maxUnavailable 1 | Budget grows automatically with replica count | Does not protect a single replica from downtime or verify database quorum. |
| StatefulSet PVC retention | Scaling or deleting the StatefulSet keeps claims | Explicit PVC/namespace deletion destroys disks because managed-csi uses reclaim policy Delete. |
| Small development resources | 250m CPU / 512Mi requested, 1 CPU / 1Gi limited per pod | Not production sizing; load can cause throttling or OOM. Cache and SQL budgets are 128Mi each, SQL temporary disk cap 1Gi. |
| Insecure SQL, ClusterIP and ingress NetworkPolicy | Simple development access without public exposure | No TLS/password authentication. Reachable clients can act as root; policy depends on cluster networking. |
| Manual manifests | Small installation with no database operator | Initialization, upgrades, decommissioning, certificates and backups require manual handling. Current vendor guidance favors the newer operator. |

Pause the entire development database with `kubectl --context=zebu -n cockroach
scale statefulset/cockroachdb --replicas=0`; reapplying manifests resumes it.
For permanent scale-down, decommission the affected database node IDs first,
wait for their replicas to move, then reduce highest pod ordinals. Do not reuse a
decommissioned node's store as a new node. Preserve sufficient voting replicas.

Explicitly deleting PVCs or namespace cockroach deletes their managed disks and
all database data. No off-cluster backups are configured. Review CockroachDB
licensing before production or multi-node use.

The historical local-store cleanup Job in
[operations/cleanup-local-store.yaml](operations/cleanup-local-store.yaml) is
excluded from Kustomize. It was run once and removed; it must not be run against
an active local database. It has no role in the current CSI deployment.

## Sources and verification

- [AKS Azure Disk CSI storage](https://learn.microsoft.com/en-us/azure/aks/create-volume-azure-disk)
- [AKS upgrade options](https://learn.microsoft.com/en-us/azure/aks/upgrade-options)
- [Kubernetes PDB semantics](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
- [CockroachDB licensing](https://www.cockroachlabs.com/docs/stable/licensing-faqs)

See [VERIFICATION.md](VERIFICATION.md) for checks and limitations.
