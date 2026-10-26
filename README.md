# CockroachDB Operator on AKS

Namespace `cockroach`; Kubernetes context `zebu`. The kubeconfig at
`/home/pmiller/.kube/config` is never committed.

This deployment uses the **current CockroachDB Operator**, three CockroachDB
v26.2.7 replicas, each with a 10Gi `managed-csi-zrs` Azure disk. One operator controller
runs separately in `cockroach-operator-system`, watching only `cockroach`.
The default database is **secure: TLS with chart-managed self-signed certificates
and password authentication**. Clients use `sslmode=require`; no client CA or
client certificate mount is needed. This encrypts traffic without verifying the
server identity.

## Configuration and resource ownership

The main custom resource is **CrdbCluster**, API
`crdb.cockroachlabs.com/v1beta1`, named `cockroachdb-secure`. The operator creates a
**CrdbNode**, pod and PVC for each database node; it handles cluster initialization,
joining nodes, rolling changes and decommissioning. This is the newer operator,
not the legacy Public operator.

- `helm/database-values.yaml`: database image, node count, managed storage,
  resource limits and preferred anti-affinity. This is the scaling source of truth.
- `helm/operator-values.yaml`: one controller, region `westus3`, namespace scope.
- `charts/`: pinned upstream operator chart 1.1.0 and database chart 26.2.4.
  The database image overrides the latter's default v26.2.5 with **v26.2.7**.
- `rendered/`: reviewable chart-generated YAML; regenerate with `scripts/render.sh`.
  Deploy through Helm, rather than applying these files directly.
- `manifests/`: namespace, NetworkPolicies and the ZRS StorageClass.
- `sql/replication-three.sql`: current three-copy replication policy,
  used by the scale helper.
- [STORAGE.md](STORAGE.md): ZRS/LRS tradeoffs, dated West US 3 pricing,
  billing tiers, migration and recovery lessons.

Helm manages the CrdbCluster and chart resources. The operator registers CRDs,
webhooks, and manages CrdbNodes, database pods, PVCs, discovery services and the
PDB. Avoid hand-editing those generated objects: reconciliation can undo changes.
The operator is namespace-scoped for reconciliation, but still has cluster-wide
RBAC for CRDs, webhooks and node discovery. Its internal controller certificates
are generated at runtime and are not committed; they do not secure SQL access.

## Apply and access

Requires Helm, kubectl, Python 3 and PyYAML (used by the scale helper).

```bash
./scripts/apply.sh
```

The script installs the operator, creates the root bootstrap Secret if missing,
then installs Helm release `cockroachdb-secure`. It waits for initialization,
`PostInitSQLApplied` and pod readiness. It defaults to context `zebu` and the
kubeconfig above; override `KUBE_CONTEXT` and `KUBECONFIG` if needed.

`scripts/bootstrap-root.py` generates a random 48-byte token once and stores it
in Secret `cockroach/cockroachdb-root`, with keys `password` and `init.sql`.
The CrdbCluster references that SQL through `spec.postInitSQL.secretRef` to set
root's password. Subsequent deployments reuse the Secret; they do not rotate the
password. The script refuses to generate replacement credentials if the Secret
is missing from an initialized secure cluster. Protect and back up this Secret.
No credentials are written to checked-in files or rendered manifests.

The application connection string is:

```text
postgresql://root:PASSWORD@cockroachdb-secure-public.cockroach.svc.cluster.local:26257/DBNAME?sslmode=require
```

Use the saved password and an existing database name. The migrated cluster has
`lunch`, `horsebets` and `aggrovites`; `defaultdb` was absent on the source and remains
absent after full-cluster restore. SQL uses port **26257**; inter-node RPC uses
**26258**. No LoadBalancer or public ingress is installed. The NetworkPolicy
allows SQL from `aggrovites`, `horsebets`, `lunch` and `dragonqr`, as well as
same-namespace and operator traffic.

The three migrated Deployments now read `DATABASE_URL` from their own namespace's
Secret `cockroachdb-connection`. Each URL preserves the application's database
name and includes the saved root password with `sslmode=require`. Applications
need no cross-namespace mounts. Existing MSSQL Secrets are unrelated and are
not modified. Deployment source manifests maintained elsewhere must preserve
these Secret references so future application deploys do not revert the change.

```bash
kubectl --context=zebu -n cockroach port-forward --address=127.0.0.1 \
  service/cockroachdb-secure-public 26257:26257 8080:8080
```

SQL locally uses the same password with host `localhost` and `sslmode=require`.
DB Console: <https://localhost:8080> (the certificate is privately signed).
The operator also uses certificate authentication for administrative operations.
Password authentication is enforced for SQL clients without client certificates;
`sslmode=require` does not verify the database server's identity.

Check password authentication from all three application namespaces with:

```bash
python3 scripts/verify-password.py
```

This uses each application's saved connection URL without certificate mounts,
and verifies that incorrect and missing passwords fail. Verification Jobs expire
automatically after the checks finish.

See [VERIFICATION.md](VERIFICATION.md) for the completed migration, data checks
and old-database teardown. The one-time migration helper has been removed.

## Scale up

```bash
./scripts/scale.sh 3
# Review and commit helm/database-values.yaml and rendered/database.yaml.
```

This saves `cockroachdb.crdbCluster.regions[0].nodes: 3`, upgrades the Helm release,
waits for operator reconciliation, applies the three-copy policy, and waits for
live database nodes with no unavailable or under-replicated ranges. **No manual
PV creation is needed**: each new CrdbNode gets its own dynamically provisioned
managed-csi-zrs disk. Any count of three or more is accepted for scale-up.

The helper requires at least two Ready, schedulable Linux workers. It does not
validate taints, spare CPU/memory, disk-attachment slots or Azure quotas. Preferred
anti-affinity allows three database pods on two sufficiently provisioned workers.
That saves worker cost but cannot guarantee survival of a worker failure: losing
the worker holding two pods can remove quorum. Three workers and suitable
placement are needed for three-copy worker-failure tolerance.

The deployed cluster uses **three copies** for default, system, meta and liveness
policies, including critical system ranges. The scale helper applies this policy
on each run. This supports the three-node database and its upgrade checks, at the
cost of reducing those critical ranges' five-copy redundancy. Additional
application zone overrides are not rewritten. Adding five database nodes later
does not automatically change this policy to five copies; review zone policies
separately.

## Worker upgrades and database upgrades

The operator owns `cockroachdb-secure-pdb` and defaults to a disruption budget of one.
It implements this as **minAvailable = node count minus one**, equivalent to the
requested maxUnavailable 1 for the desired cluster size. At one node it is zero;
at three it becomes two; at five it becomes four. Do not install a second PDB
or patch this generated PDB. Readiness and PDB permission are not proof that all
ranges have converged.

For planned AKS upgrades, provide adequate temporary surge capacity (for example,
maxSurge 1), compatible disk topology, and enough resources on replacement
workers. **AKS surge settings have not been changed here**. Azure disks can detach
and reattach to compatible replacement workers; that takes time. A single database
replica still has downtime during eviction, disk attachment and restart.
PDBs govern voluntary eviction, not worker failure or direct pod deletion.

Operator 1.1.0 checks under-replicated ranges before disruptive rolling changes
and decommissioning, holding progress if ranges are under-replicated or the check
fails. Worker eviction and pod recovery can still happen, but database rolling
upgrades may be held until replication policies and live node counts agree. The
documented `skip-under-replicated-ranges-check` feature is a recovery override, not enabled
here. Let replication converge before protected rolling database upgrades.
Upgrade the operator chart before the database chart when updating versions, and
keep saved values and rendered YAML in sync.

The scale helper refuses scale-down. The operator supports decommissioning, but
reducing node count must be planned around replication policies, sufficient live
nodes, and its health checks. Do not manually delete a CrdbNode or reuse a
previously decommissioned store to shrink the cluster.

### Recovery after changing worker zones

The October 2026 recovery used a temporary nonzonal worker because the original
disk's PV required an empty `topology.disk.csi.azure.com/zone` value, while the
replacement `main` workers advertised `westus3-1` and `westus3-2`. Waiting or
preempting pods cannot resolve that topology mismatch.

After the original database pod started on the temporary worker, that worker was
cordoned to keep new database disks on the permanent workers. The database was
scaled to four replicas and three-copy policies were applied. Only after all
ranges were fully replicated was the original CrdbNode marked with
`crdb.cockroachlabs.com/decommission=true` and the Helm replica count reduced to
three. The operator transferred its replicas and retired the original node before
the temporary pool was deleted. Decommissioning removed the original PVC. The old
disk was initially protected with `Retain` reclamation, then deleted along with
its released PV after verification and the user's cleanup request. A decommissioned
store must not be started again as a live database node.
See [VERIFICATION.md](VERIFICATION.md) for the recovery checks.

Zonal LRS disks require workers in their original zones. The database has since
migrated to ZRS disks, which can reattach to workers in different zones in the
region. Disk detach/attach and pod startup still take time; this does not provide
continuous quorum if a failed worker hosted two database replicas.

### StorageClass changes

`managed-csi-zrs` uses StandardSSD_ZRS, WaitForFirstConsumer and Retain reclamation.
The saved Helm template uses this class for new database volumes.

A live test on operator 1.1.0 changed only the volume template's storage class to
`managed-csi-zrs`. The operator updated the first CrdbNode and restarted its pod,
but retained its original LRS PVC and logged:
`ignore conflicting data storage class name existing managed-csi, but got managed-csi-zrs`.
The template was restored before the other replicas were changed; all three
CrdbNodes and PVCs retained their identities and the database remained healthy.
Changing this template does not migrate an existing disk on the tested version.
Disk capacity expansion is a separate supported operation.

The LRS-to-ZRS migration used three explicit replacement cycles. Each cycle
scaled from three to four replicas, verified the new disk's Azure SKU, waited for
zero unavailable and under-replicated ranges, marked one original LRS CrdbNode
with `crdb.cockroachlabs.com/decommission=true`, and reduced the desired count to
three. Before the next cycle, the retired node had to be fully decommissioned
with zero replicas and the remaining three nodes had to be healthy. A full-cluster
safety backup was copied outside the database disks and onto a new ZRS disk.
Old LRS disks were protected with Retain reclamation through verification and
cleaned up afterward. The final desired count is three and capacity remains 10Gi.

The operator behavior and migration request are tracked in
[helm-charts#693](https://github.com/cockroachdb/helm-charts/issues/693).
See [STORAGE.md](STORAGE.md) for the storage decision and pricing comparison.

## Tradeoffs and data lifecycle

| Choice | Benefit | Cost or limitation |
| --- | --- | --- |
| Operator | Node creation, disk provisioning, initialization and lifecycle reconciliation | One extra controller; chart requests 500m CPU and 1000Mi RAM, limits 2 CPU/4000Mi. A single controller is not redundant, although its outage does not stop existing database pods. |
| Three database replicas on two workers | Three copies of each range | Losing the worker hosting two replicas can remove quorum; three workers with suitable placement are needed for worker-failure tolerance. |
| managed-csi-zrs per-node disks | Provision automatically and can reattach across zones in the region | StandardSSD_ZRS costs more than LRS; attachment delays and limits still apply. Requested 10Gi disks bill at the 16Gi tier. |
| Preferred anti-affinity | Supports three database pods on two workers | Correlated worker failure can lose quorum. |
| Operator-managed disruption budget 1 | Adjusts when the desired node count grows | Cannot make one replica highly available or protect against unexpected failures. |
| Retain PV reclamation and PVC retention settings | Retain reclamation preserves the disk even if its PVC is removed | The operator can remove PVCs during decommissioning despite `whenDeleted: Retain`. Released disks require explicit cleanup and continue costing money. |
| Small database limits | Requests 250m CPU/512Mi RAM; limits 1 CPU/1Gi | Development sizing, below vendor guidance. Load can throttle or OOM. Cache/SQL budgets are 128Mi each; temporary disk cap is 1Gi. |
| Secure SQL, password authentication and internal-only service | Encrypted access with a single connection string | `sslmode=require` skips server identity verification; application URLs currently use root. |

No recurring off-cluster backup policy is configured. One-time migration archives
do not provide an ongoing backup policy. Review CockroachDB licensing for your
intended use.

The manual deployment was replaced with a fresh operator-managed database using
the user's authorization to discard data. Its old managed disk was deleted after
SQL verification. Earlier local volumes/provisioner were already removed. Old
StatefulSet, init Job, services, manual PDB and local-store cleanup YAML have been
removed from the working tree; Git history retains their prior versions.

## Sources and verification

- [Current operator deployment guide](https://docs.cockroachlabs.com/docs/stable/deploy-cockroachdb-with-cockroachdb-operator)
- [Chart versioning](https://github.com/cockroachdb/helm-charts/blob/master/cockroachdb-parent/docs/VERSIONING.md)
- Operator chart README bundled in `charts/cockroachdb-operator-chart-1.1.0.tgz`:
  under-replicated-range safeguard and namespace-scoped deployment.
- [AKS disk CSI](https://learn.microsoft.com/en-us/azure/aks/create-volume-azure-disk)
- [AKS upgrade options](https://learn.microsoft.com/en-us/azure/aks/upgrade-options)
- [Kubernetes PDB semantics](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
- [CockroachDB licensing](https://www.cockroachlabs.com/docs/stable/licensing-faqs)

See [VERIFICATION.md](VERIFICATION.md) for observed results and test limits.
