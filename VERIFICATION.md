# License installation verification

Verified 2026-10-26, context `zebu`.

- Applied the supplied Enterprise Free license through certificate-authenticated
  SQL and verified exact setting readback without printing the key.
- Stored the accepted key in `cockroach/cockroachdb-license`, data key `license`,
  using server-side apply; the key is absent from Helm values and rendered YAML.
- Reapplied the saved Secret successfully through `scripts/apply-license.py`.
  Deployment now calls the helper after pod readiness, skipping it if no Secret
  exists. The operator's post-init SQL hook runs once and does not watch renewal.
- `diagnostics.reporting.enabled` is true. The expiry metric on node 6 reports
  approximately 31.54 million seconds (365 days) remaining. Successful ongoing
  telemetry delivery has not been independently verified by this check.
- No database restart was needed. Nine credential/license helper tests passed,
  including error redaction and refusal to save rejected license input. Shell
  syntax and `git diff --check` passed. No license key is written to repository
  files; the protected temporary input file was removed after installation.

---

# Memory tuning verification

Verified 2026-10-26, context `zebu`, after merging `origin/main` at `cc9cd43`.

- Helm release `cockroachdb-secure` upgraded to revision 13 with only two live
  value changes: database container memory limit 1Gi -> 2Gi, and explicit
  `--max-go-memory=768MiB`. Existing three-node count, ZRS storage, CPU resources,
  512Mi memory requests, 128MiB cache and 128MiB SQL budget were preserved.
- Helm lint and values comparison passed. The operator reconciled generation 12
  and rolled all three database pods. Each remains on a separate worker, with
  a 2Gi container limit. All database nodes are live and available, with zero
  unavailable or under-replicated ranges.
- Runtime logs on node 6 report `GoLimitBytes=805306368` (768MiB), replacing
  the old 301989888 (288MiB). Two consecutive runtime samples ten seconds apart
  had the same GC count (27), versus several GC cycles per second before tuning.
- Approximately 13–17 minutes after pod restarts, database CPU samples were
  78m, 58m and 62m (198m total), compared with earlier samples of 887m, 127m and
  870m (1884m total). Memory working sets were 750Mi, 745Mi and 858Mi.
  These are point-in-time observations, not a controlled benchmark or a guarantee
  of long-term behavior. Recheck after sustained uptime and application load.
- No authenticated CPU profile was collected. The runtime observations and early
  improvement support GC pressure as the cause of the earlier high CPU usage.
- A separate licensing check found no configured `enterprise.license`. The
  multi-node cluster is older than the documented seven-day unlicensed grace
  period and appears eligible for the five-concurrent-transaction restriction;
  no rejected transaction was observed during this check. Memory tuning does not
  resolve license enforcement. No license settings were changed.

The sections below record earlier migrations and deployments.

---

# ZRS volume migration

Verified 2026-10-23, context `zebu`, operator 1.1.0 and database v26.2.7.

- Migrated the three zonal StandardSSD_LRS stores to three new StandardSSD_ZRS
  stores. Capacity remains 10Gi per replica. The secure Helm release now uses
  `managed-csi-zrs`, with final replica count three, release revision 12 and
  CrdbCluster generation/observedGeneration 11. TLS, image and resource settings
  were preserved.
- Took full-cluster backup job 1221344425431957506, succeeded with 576 rows.
  `SHOW BACKUP LATEST ... WITH check_files` passed. Copied the backup into a private
  mode-0600 local archive at `/tmp/zebu-zrs-migration/backup.tar.gz` and onto the
  first ZRS store. File validation also passed at
  `nodelocal://5/zrs-migration-20261023T2235` after copying.
  The local archive contains 29 files, including 15 data SSTs; SHA256:
  `65aa384a8c9b0ec1289e03f940bbfac26a8052f7cd33b792bf4db8df3cd7b535`.
  A backup restore rehearsal was not performed.
- Protected all source PVs with Retain reclamation and ran three replacement
  cycles, each scaling 3 to 4 to 3. Before each decommission, all four database
  nodes were live/available with zero unavailable and under-replicated ranges,
  and Azure confirmed that the added disk was StandardSSD_ZRS and 10Gi.
- Retired `cockroachdb-secure-87bsx` (database node 3), then
  `cockroachdb-secure-rvw8l` (node 2), then `cockroachdb-secure-z5z5p` (node 4).
  The operator removed each old CrdbNode and PVC only after decommissioning;
  `node status --all --decommission` confirmed zero gossiped replicas on each
  retired node. The next cycle began only after three healthy replicas remained.
- The initial storage-template change caused the existing LRS pods to roll,
  retaining their PVCs as in the earlier experiment. During decommissioning a pod
  can show 1/2 Ready because the database container intentionally stops accepting
  clients while the certificate sidecar stays Ready. Health checks used another
  Ready node when a draining pod refused SQL connections.
- Final active database nodes and volumes:

| Node ID | CrdbNode | PV |
| --- | --- | --- |
| 5 | cockroachdb-secure-wcw8r | pvc-85271c09-5b4d-45f4-b865-00835babfeed |
| 6 | cockroachdb-secure-4s6vr | pvc-6d031d8f-b713-4419-8f06-9797fd160715 |
| 7 | cockroachdb-secure-c452k | pvc-1903a92e-764d-473a-82fa-a0b343e4510e |

All three pods are Ready with zero restarts. Each node holds 64 ranges, with
zero unavailable and under-replicated ranges. Azure reports three attached 10Gi
StandardSSD_ZRS disks. The new PVs use Retain reclamation and permit attachment
across zones. Nodes 6 and 7 share the zone-1 worker; node 5 runs in zone 2.

- All 24 database names matched before and after migration. Six sampled table
  counts also matched: aggrovites.events 36, aggrovites.rsvps 116,
  horsebets.bets 225, horsebets.horses 123, horsebets.races 9,
  lunch.lunch_requests 2. This was not a full index fingerprint comparison.
- Connection Jobs from lunch, horsebets and aggrovites passed using their current
  `roachkey` Secret references through the database service while the final LRS
  replica was draining.
- After data and connection checks, confirmed that all three old PVs were Released
  and their Azure disks were unattached. Removed the three retired LRS disks and
  their PVs. DragonQR and WireGuard storage were outside this cleanup.
- Helm lint, rendered-manifest semantic comparison and `git diff --check` passed.
  Migration state and resource snapshots are under `/tmp/zebu-zrs-migration/`.

ZRS improves cross-zone disk recovery but does not provide continuous quorum when
a failed worker hosts two of the three replicas. No recurring off-cluster backup
policy was configured as part of this migration.

---

# StorageClass change experiment

Verified 2026-10-23, operator 1.1.0, context `zebu`.

- Created `managed-csi-zrs` with provisioner disk.csi.azure.com,
  StandardSSD_ZRS, WaitForFirstConsumer, expansion enabled and Retain reclamation.
  Saved the original cluster, CrdbNode, PVC, pod and PV state under
  `/tmp/zebu-recovery/zrs-experiment/`. Temporarily set the three data PVs to
  Retain reclamation to protect disks if the operator replaced claims.
- Confirmed three live, available database nodes and zero unavailable or
  under-replicated ranges. Changed only the Helm volume template storage class;
  desired count stayed three and capacity stayed 10Gi. Helm revision 5 applied
  the change; CrdbCluster generation advanced from 3 to 4.
- The operator updated CrdbNode `cockroachdb-secure-87bsx` to generation 2 and
  storageClassName managed-csi-zrs, then evicted and recreated its pod. The
  original PVC remained Bound with its original UID, PV and managed-csi class.
  Operator log at nodectrl/pvc.go:72 explicitly said:
  `ignore conflicting data storage class name existing managed-csi, but got managed-csi-zrs`.
- Restored managed-csi through Helm revision 6 before the other CrdbNodes were
  changed. The first node returned to managed-csi at generation 3 and its pod
  restarted again. All three CrdbNode and PVC UIDs match the saved state; all
  pods are Ready. Database node IDs remain 2, 3 and 4, each with 64 ranges and
  zero unavailable or under-replicated ranges.
- Restored the original Delete reclaim policy on all three active data PVs.
  The unused ZRS StorageClass remains available and its manifest is included
  in Kustomize. No ZRS disks were created by this experiment.
- Helm lint, rendered-manifest semantic comparison and `git diff --check` passed.

This test demonstrates that changing storageClassName on operator 1.1.0 restarts
an existing pod while preserving its original PVC rather than migrating storage.
The experiment was stopped after observing the first node; a complete rollout of
the mismatched template was not exercised. Operator logs are saved locally at
`/tmp/zebu-recovery/zrs-experiment/operator.log`.

---

# Zonal worker recovery

Verified 2026-10-23, context `zebu`.

- The replacement `main` workers advertise zones `westus3-1` and `westus3-2`.
  The original CockroachDB PV required an empty Azure disk zone, and Azure
  confirmed its StandardSSD_LRS disk was nonzonal and unattached. The pod could
  not schedule on either replacement worker.
- Created one temporary nonzonal `recovery` worker, Standard_B2s_v2, matching
  the permanent workers. The original pod `cockroachdb-secure-j2m6z` recovered
  with its original disk; existing databases were readable. Cordoned this worker
  after the pod scheduled, so all new database volumes were provisioned on `main`.
- Scaled the secure Helm release to four replicas with `scripts/scale.sh 4`.
  Applied the helper's three-copy replication policies, including system ranges.
  Waited for all four nodes to report zero unavailable and under-replicated ranges.
- Annotated the original CrdbNode with
  `crdb.cockroachlabs.com/decommission=true`, saved three replicas in Helm values,
  and upgraded Helm release `cockroachdb-secure` to revision 4. The operator
  drained and decommissioned database node 1, then removed its pod and CrdbNode.
  `cockroach node status --all --decommission` confirmed node 1 was decommissioned
  with zero gossiped replicas.
- Database nodes 2, 3 and 4 are active, live and available, each holding 64 ranges
  with zero unavailable or under-replicated ranges. The CrdbCluster reports
  readyNodes 3, observedGeneration 3, reconciled true and AllReplicated.
  Nodes 2 and 3 share the zone-1 worker; node 4 runs on the zone-2 worker.
- Deleted the temporary recovery pool only after decommissioning completed.
  Azure now lists only `main`, two workers, Succeeded. Both workers are Ready,
  and all three database pods are Ready with zero restarts.
- Protected original PV `pvc-4866b789-7ae0-4f63-8d54-4c061bb199d1` by changing its
  reclaim policy to Retain before decommissioning. Despite PVC retention settings,
  the operator removed the original PVC during decommissioning. The PV is Released;
  Azure confirms the original disk still exists, Unattached. It includes local
  files from the retired store; do not restart it as a database node.
  Following the user's subsequent cleanup request, deleted that unattached Azure
  disk and its released PV. The original PVC, PV and disk are now removed.
- All 24 database names matched before and after decommissioning. Sampled application
  row counts also matched: aggrovites.events 36, aggrovites.rsvps 116,
  horsebets.races 9, horsebets.horses 123, horsebets.bets 225,
  lunch.lunch_requests 2. These checks do not constitute a full index fingerprint
  comparison or an off-cluster backup.
- Reset DragonQR storage with the user's authorization: scaled down its Deployment,
  deleted `dragon/dragonqr-data`, created an empty 1Gi default-class claim, and
  restarted the Deployment with `agentpool: main`. Its new PV is
  `pvc-b0c6f840-6bd3-498f-b81c-cc089f260d86`, zone westus3-2; the pod is Ready.
- Helm lint, semantic comparison of rendered manifests and `git diff --check`
  passed. Saved Helm configuration changes only the database replica count.

The repository password-check helper could not start because it assumes a Secret
named `cockroachdb-connection`; live applications now reference `roachkey`.
Separate short-lived Jobs using each application's current `roachkey` reference
successfully executed `SELECT 1` from lunch, horsebets and aggrovites after the
recovery pool was removed. No credentials were copied or printed.
The earlier migration records below describe their configuration at that time.

Three database replicas on two workers still cannot guarantee survival of a worker
failure: losing the worker hosting two replicas can remove quorum. Active disks
are zonal LRS, so future worker replacements must preserve compatible zone capacity.

---

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
