# Operator deployment verification

Verified 2026-10-04 America/Los_Angeles (2026-10-05 UTC), context `zebu`.

## Deployed state

- Official current operator chart **1.1.0**, controller image
  `cockroachdb/cockroachdb-operator-v2:v1.1.0`.
- One controller Ready in `cockroach-operator-system`, region westus3,
  watching namespace cockroach. Its chart requests 500m CPU/1000Mi memory.
  An observed metrics sample was 6m CPU/31Mi memory; this is not a sizing guarantee.
- Database chart **26.2.4**, image override **cockroachdb/cockroach:v26.2.7**.
- CrdbCluster `cockroachdb` initialized, reconciled, observed generation 1,
  readyNodes 1, database version v26.2.7.
- CrdbNode/pod `cockroachdb-7g8tr`, database container Running and Ready.
  Node locality: region=azure-westus3, zone=azure-0.
- One Bound 10Gi ReadWriteOnce PVC `cockroachdb-7g8tr`, managed-csi,
  PV `pvc-12826758-a804-45ca-8e58-c30073e9cb44`.
- Previous manual PVC `data-cockroachdb-0` and its PV
  `pvc-7b9708f7-3d7e-43b0-a9bd-73f3140a3ea4` deleted; no leftover claims
  in cockroach. The earlier local provisioner/volumes were already removed.
- Operator-owned PDB `cockroachdb-pdb`: minAvailable 0 at one desired node,
  one disruption allowed. CrdbCluster default disruptionBudget is 1.
- SQL uses `cockroachdb-public:26257`; RPC is 26258. Services are internal only.
- TLS disabled, password authentication absent. NetworkPolicy includes
  same-namespace SQL/RPC/HTTP, SQL (TCP 26257) from `aggrovites` and `horsebets`,
  and controller namespace traffic. The application-namespace rule was applied
  and read back from the cluster; both namespaces have the matching standard
  `kubernetes.io/metadata.name` label. Cross-namespace client connections were
  not exercised.

## Checks performed

1. Queried old deployment before replacement: only default databases were present.
   Started a fresh operator deployment under the user's existing data-reset authorization.
2. Connected through the new public ClusterIP service, created a test database/table,
   inserted and read a row.
3. Deleted the database pod; operator recreated it with a new pod UID, the same
   CrdbNode name and the **same PVC/PV**. Pod became Ready again.
4. Read the original row through the service after recreation, then removed the
   test database. This verified durable storage and controller pod recovery.
5. Re-ran `scripts/apply.sh`: both Helm releases upgraded to revision 2,
   existing database pod/PVC remained, initialization and readiness checks passed.
6. Both pinned charts passed `helm lint` with saved values. All shell scripts
   passed `bash -n`. A temporary three-node values file rendered a CrdbCluster
   with nodes=3 and managed-csi storage; saved count remains one. Rendered YAML
   contains no Secrets. The saved CrdbCluster also passed server-side dry-run
   validation against the live operator API.
7. Queried node/range status: one live/available node, no unavailable ranges;
   ranges under-replicated as expected with one node and vendor defaults.
   No replication reduction SQL was applied to the current one-node database.

## Limits

Live scale-out, live decommissioning, cross-worker disk reattachment, AKS drains,
controller failover and database-version upgrades were not exercised. No worker
surge settings were changed. There is no HA with one database replica. The future
scale helper intentionally applies three-copy policies including critical system
ranges; review README before using it. Its range-convergence logic was syntax
checked and its desired three-node resource rendered, but the full scale-up path
was not run against this cluster. Existing user zone overrides are not rewritten.
