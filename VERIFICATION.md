# Managed-CSI reset verification

Verified on 2026-10-04 (America/Los_Angeles), context `zebu`.

- Stopped the old database before removing its local store.
- Removed old PVCs `data-cockroachdb-0` and `local-data-cockroachdb-0`.
- Verified deletion of original Azure PV `pvc-20fdfaab-2d93-442f-8e4a-a82c23ad9c6f`.
- Cleanup Job logged `Discarded local CockroachDB store removed`; Job completed
  and was removed. Static local PV `cockroachdb-local` was deleted afterward.
- Removed the dedicated cockroach-storage namespace, local provisioner and its
  RBAC, plus StorageClasses cockroach-local and cockroach-local-auto.
- Recreated the StatefulSet with a data claim template using managed-csi and
  preferred anti-affinity. Replica count remains one; PDB maxUnavailable remains 1.
- New PVC `data-cockroachdb-0` is Bound, 10Gi, ReadWriteOnce, managed-csi.
- New PV is `pvc-7b9708f7-3d7e-43b0-a9bd-73f3140a3ea4`, CSI driver
  disk.csi.azure.com, StandardSSD_LRS, reclaim policy Delete.
- Fresh init Job completed with `Cluster successfully initialized`.
- Database pod is 1/1 Running with zero container restarts after deployment.
- SHOW DATABASES initially returned only defaultdb, postgres and system,
  confirming a fresh database rather than migrated data.
- Created temporary csi_smoke database/table, inserted a row and read it through
  service cockroachdb:26257. The test database was removed after validation.
- Fresh zone policies request three user-data replicas and five replicas for
  critical system ranges. One live node is under-replicated and has no HA.
- No CockroachDB operator CRDs are installed. Vendor guidance recommending the
  newer operator is recorded in README; an operator has not been deployed.
- Final manifest diff returned exit code 0 with no differences. The namespace
  has only the new managed-CSI PVC; both named old PVs are absent. YAML parsing,
  shell syntax validation and Git whitespace checks passed.

No worker upgrade, cross-worker disk reattachment, production load test,
backup/restore or managed-disk multi-node scale-out test was performed.
The previous local-volume version was tested with two database nodes, but that
is not evidence of managed-disk upgrade availability.
