# Deployment verification

Verified on 2026-10-04 against context `zebu` with the kubeconfig at
`/home/pmiller/.kube/config`.

- Client-side dry run passed; manifests applied successfully.
- Namespace `cockroach` created.
- StatefulSet `cockroachdb` rolled out successfully: pod `cockroachdb-0` is
  `1/1 Running`, with zero container restarts after the final pod replacement.
- Active data volume is PVC `cockroachdb-local`, bound to local PV
  `cockroachdb-local` at `/var/lib/cockroachdb/cockroach` on worker
  `aks-main-11118102-vmss000001`, with reclaim policy `Retain`.
- Original PVC `data-cockroachdb-0` is retained only as an offline rollback copy;
  the running pod mounts only the new local PVC.
- Client service is ClusterIP on SQL 26257 and HTTP 8080; no external IP.
- SQL connection using service hostname `cockroachdb:26257` succeeded.
- `SELECT version()` returned CockroachDB CCL v26.2.7, linux amd64.
- Created a temporary database/table and wrote `(1, 'persistent')`.
- Restarted the StatefulSet and waited for readiness; the same row was read
  successfully afterward, verifying persistence across pod replacement.
- Dropped the temporary database `deployment_smoke` after verification.
- `kubectl diff -k manifests` returned exit code 0, with no differences.

## Host volume migration

Historical verification of the preceding hostPath deployment:

- Wrote `(1, 'migrated')` to `host_volume_smoke.checks` before stopping the
  original PVC-backed database.
- Scaled the StatefulSet to zero and waited for pod deletion.
- Copied the stopped store to the host directory using the one-time migration
  Job. Logs confirmed `Offline store copied successfully`; Job completed 1/1.
- Removed the migration Job and recreated the StatefulSet with no claim template,
  a hostPath volume, and the matching worker selector.
- Successfully read the pre-migration row through `cockroachdb:26257`.
- Restarted the host-volume StatefulSet and successfully read the same row again.
- Dropped the test database after verification. The retained source disk is frozen
  at the pre-migration state and still includes that temporary test database.
- Confirmed live pod volumes contain only the hostPath data volume, pod is
  `1/1 Running` with zero container restarts, and manifest diff is empty.

## Local PersistentVolume conversion

- Server-side dry run passed for all resources.
- Created StorageClass `cockroach-local` with `kubernetes.io/no-provisioner`,
  `WaitForFirstConsumer`, and reclaim policy `Retain`.
- Created static local PV `cockroachdb-local` with 10Gi declared capacity,
  ReadWriteOnce, node affinity, and reservation for the matching namespace/PVC.
- Created PVC `cockroach/cockroachdb-local`; verified both PVC and PV are Bound.
- Replaced the StatefulSet hostPath with a PVC mount and removed its node selector.
- No file copy was needed; the local PV reused the existing directory.
- A row `(1, 'local-pv-preserved')` written to `local_pv_smoke.checks` before
  conversion was read successfully through the SQL service after conversion.
- Restarted the StatefulSet; the same row was read successfully afterward.
- Dropped the temporary database after verification.
- Confirmed the final pod uses the local PVC, runs on the PV's worker, and is
  `1/1 Running` with zero container restarts.
- Final `kubectl diff -k manifests` returned exit code 0 with no differences.
- Retain reclamation and node-loss recovery are documented but were not tested
  destructively. Declared PV capacity does not enforce a directory quota.

Running image digest reported by Kubernetes:

```text
docker.io/cockroachdb/cockroach@sha256:9464ae30465b887295459b98d129a76d074caeaa4c86836d369c6d2fdddd1685
```

Ingress NetworkPolicy is installed. Its cross-namespace enforcement was not
tested; it depends on the cluster's network policy implementation. SQL service
resolution, readiness probes and storage persistence were tested. No load test,
node failure test, backup/restore test or production suitability claim is made.
