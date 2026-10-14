# CockroachDB Operator on AKS

Namespace `cockroach`; Kubernetes context `zebu`. The kubeconfig at
`/home/pmiller/.kube/config` is never committed.

This deployment uses the **current CockroachDB Operator**, one CockroachDB
v26.2.7 replica, and one 10Gi `managed-csi` Azure disk. One operator controller
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
- `manifests/`: namespace and NetworkPolicies.
- `sql/replication-three.sql`: future three-copy replication policy,
  used by the scale helper.

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
managed-csi disk. Any count of three or more is accepted for scale-up.

The helper requires at least two Ready, schedulable Linux workers. It does not
validate taints, spare CPU/memory, disk-attachment slots or Azure quotas. Preferred
anti-affinity allows three database pods on two sufficiently provisioned workers.
That saves worker cost but cannot guarantee survival of a worker failure: losing
the worker holding two pods can remove quorum. Three workers and suitable
placement are needed for three-copy worker-failure tolerance.

The fresh single-node cluster retains vendor defaults: three copies for ordinary
ranges and five for critical system ranges. It is under-replicated and has no HA.
On scale-up, the helper deliberately changes default, system, meta and liveness
policies to **three copies**, including critical system ranges. This supports the
planned three-node database and its upgrade checks, at the cost of reducing those
critical ranges' five-copy redundancy. Additional application zone overrides are
not rewritten. Adding five database nodes later does not automatically change
this policy to five copies; review zone policies separately.

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
fails. The current one-node defaults cannot satisfy that check. Worker eviction
and pod recovery can still happen, but database rolling upgrades may be held
until replication policies and live node counts agree. The documented
`skip-under-replicated-ranges-check` feature is a recovery override, not enabled
here. Scale to three and let replication converge before expecting protected
rolling database upgrades. Upgrade the operator chart before the database chart
when updating versions, and keep saved values and rendered YAML in sync.

The scale helper refuses scale-down. The operator supports decommissioning, but
reducing node count must be planned around replication policies, sufficient live
nodes, and its health checks. Do not manually delete a CrdbNode or reuse a
previously decommissioned store to shrink the cluster.

## Tradeoffs and data lifecycle

| Choice | Benefit | Cost or limitation |
| --- | --- | --- |
| Operator | Node creation, disk provisioning, initialization and lifecycle reconciliation | One extra controller; chart requests 500m CPU and 1000Mi RAM, limits 2 CPU/4000Mi. A single controller is not redundant, although its outage does not stop existing database pods. |
| One database replica | Lowest current database footprint | No HA; regular worker maintenance causes downtime. |
| managed-csi per-node disks | Provision automatically and can reattach across eligible workers | Disk charges, attachment delays and topology/attachment limits. StorageClass uses StandardSSD_LRS; billing tiers may exceed requested 10Gi. |
| Preferred anti-affinity | Supports three database pods on two workers | Correlated worker failure can lose quorum. |
| Operator-managed disruption budget 1 | Adjusts when the desired node count grows | Cannot make one replica highly available or protect against unexpected failures. |
| PVC retention `whenDeleted: Retain` | Deleting a CrdbNode keeps its disk claim | Retained disks continue costing money. Explicit PVC/namespace deletion destroys data because managed-csi reclaims with Delete. |
| Small database limits | Requests 250m CPU/512Mi RAM; limits 1 CPU/1Gi | Development sizing, below vendor guidance. Load can throttle or OOM. Cache/SQL budgets are 128Mi each; temporary disk cap is 1Gi. |
| Secure SQL, password authentication and internal-only service | Encrypted access with a single connection string | `sslmode=require` skips server identity verification; application URLs currently use root. |

No off-cluster backups are configured. Operator management does not provide a
backup policy by itself. Review CockroachDB licensing for your intended use.

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
