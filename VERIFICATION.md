# Secure migration verification

Verified 2026-10-14, context `zebu`.

## Application database rename

After migration and old-database teardown, renamed `vitesdb` to `aggrovites` so
all three application databases match their namespaces: `horsebets`, `aggrovites`
and `lunch`. The existing names `horsebets` and `lunch` did not require
SQL renames.

- Stopped aggrovites before renaming. Its events/rsvps row counts and all index
  fingerprints matched immediately before and after the rename.
- Updated namespace-local connection Secrets to the matching database names,
  preserving existing usernames, passwords, service hostnames and
  `sslmode=require`. Rolled all three applications.
- Aggrovites's first startup migration failed when metadata queries reported the
  old database name. Fresh SQL and pgx queries worked; restarting the database
  pod and then aggrovites resolved the failure. The database retained PVC
  `cockroachdb-secure-j2m6z` and PV
  `pvc-4866b789-7ae0-4f63-8d54-4c061bb199d1`.
- All three HTTP checks returned 200. Password checks passed in all three
  namespaces, including rejection of incorrect and missing passwords.
- Final SQL inventory: aggrovites, horsebets, lunch, postgres, system. The old
  `vitesdb` name is absent. Updated this repo's README and aggrovites's README.

The following records the earlier secure migration before the application rename.

- Default Helm release and CrdbCluster: `cockroachdb-secure`; chart 26.2.4,
  database v26.2.7, operator 1.1.0. TLS and the built-in certificate self-signer
  are enabled; cert-manager is disabled.
- Secure node `cockroachdb-secure-j2m6z` Ready, with database and certificate
  reloader containers. Its new 10Gi managed-csi PVC is Bound, PV
  `pvc-4866b789-7ae0-4f63-8d54-4c061bb199d1`.
- Root password generated once with Python's `secrets.token_urlsafe(48)` and saved
  in Secret `cockroach/cockroachdb-root`. Post-init SQL succeeded. A second
  deployment reused this Secret and left the database Ready.
- Stopped the three application Deployments and took a full-cluster backup,
  `nodelocal://1/tls-migration-20261014T182439Z`. Backup and restore jobs succeeded
  (535 rows reported, including system data). Backup copied to both database
  PVCs and a mode-0600 local archive:
  `/tmp/tls-migration-20261014T182439Z-o2gzfxg2.tar`.
- Restored all five database names: `horsebets`, `lunch`, `postgres`, `system`,
  `vitesdb`. Source and destination row counts and every index fingerprint matched
  for all six application tables before cutover:
  lunch_requests=0, races=9, horses=123, bets=225, events=34, rsvps=115.
- Reapplied root's saved password after full restore, which includes users.
- All three Deployments read DATABASE_URL from their own namespace's
  `cockroachdb-connection` Secret. URLs use root, the original application database
  name, the secure service, and `sslmode=require`. Existing MSSQL Secrets preserved.
- Temporary Jobs in lunch, horsebets and aggrovites successfully connected without
  certificate mounts, and verified wrong and missing passwords fail. Repeated
  after the final NetworkPolicy and deployment changes: all three passed.
- Original application environment settings were restored after a faulty initial
  patch removed them. The corrected patch explicitly removed only the alternate
  DATABASE_URL value/valueFrom form, and server-side dry-runs verified that other
  environment entries were preserved.
- Lunch's startup AutoMigrate exposed a GORM/CockroachDB unique-index compatibility
  issue. Changed its SelectedDate model tag from `uniqueIndex` to `unique`, retaining
  database uniqueness. Unit tests passed and the fixed binary started twice against
  the secure database with HTTP 200. Built and deployed image
  `paulgmiller/letsgetlunch:cockroach-tls-20261014`, digest
  `sha256:908e320410259297628b7f60721a560582eb8a4e6ae8d6f0a2897d73954ef123`.
  Saved that model fix and all three application Secret references in their source
  repositories, preserving unrelated existing edits.
- All three application pods Running, Ready, with zero restarts after final fixes.
  HTTP checks returned 200 for all three applications. A temporary Job confirmed
  that a connection from lunch to the legacy insecure SQL service is blocked.
  Server-side dry-runs confirmed the corrected environment patch preserves all
  existing application environment entries.
- Following the user's teardown request, uninstalled the original `cockroachdb`
  Helm release. Its CrdbCluster, CrdbNode, pod and services were removed. Deleted
  retained PVC `cockroachdb-7g8tr` and confirmed PV
  `pvc-12826758-a804-45ca-8e58-c30073e9cb44` was deleted through its CSI finalizer
  with Delete reclamation. Removed both obsolete legacy NetworkPolicies and the
  legacy-isolation manifest. Only the secure database remains. Migration backups
  remain on its PVC and in the protected local archive; the rollback Secret now
  records historical settings rather than a live rollback path.
- Credential lifecycle tests: 5 passed. Helm lint, shell syntax checks and
  `git diff --check` passed. The scale script now uses the secure release and
  certificate-authenticated operator-side SQL; live scale-out was not run.

The one-time migration helper was removed after the secure installation and
old-database teardown were complete. The bootstrap and password verification
helpers remain part of the secure deployment workflow.

The machine-readable cutover report is in ConfigMap
`cockroach/cockroachdb-tls-migration`; original connection settings and replica
counts are in Secret `cockroach/cockroachdb-tls-migration-rollback`.

`sslmode=require` encrypts SQL but skips server identity verification. One replica
still has no HA. These migration archives do not establish an off-cluster backup
policy.

---

The following is the historical verification of the original insecure deployment.

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
