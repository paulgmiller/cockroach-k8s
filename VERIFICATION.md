# Deployment verification

Verified on 2026-10-04 against context `zebu` with the kubeconfig at
`/home/pmiller/.kube/config`.

- Client-side dry run passed; manifests applied successfully.
- Namespace `cockroach` created.
- StatefulSet `cockroachdb` rolled out successfully: pod `cockroachdb-0` is
  `1/1 Running`, with zero container restarts after the final pod replacement.
- PVC `data-cockroachdb-0` is `Bound`, 10Gi, ReadWriteOnce, `managed-csi`.
- Client service is ClusterIP on SQL 26257 and HTTP 8080; no external IP.
- SQL connection using service hostname `cockroachdb:26257` succeeded.
- `SELECT version()` returned CockroachDB CCL v26.2.7, linux amd64.
- Created a temporary database/table and wrote `(1, 'persistent')`.
- Restarted the StatefulSet and waited for readiness; the same row was read
  successfully afterward, verifying persistence across pod replacement.
- Dropped the temporary database `deployment_smoke` after verification.
- `kubectl diff -k manifests` returned exit code 0, with no differences.

Running image digest reported by Kubernetes:

```text
docker.io/cockroachdb/cockroach@sha256:9464ae30465b887295459b98d129a76d074caeaa4c86836d369c6d2fdddd1685
```

Ingress NetworkPolicy is installed. Its cross-namespace enforcement was not
tested; it depends on the cluster's network policy implementation. SQL service
resolution, readiness probes and storage persistence were tested. No load test,
node failure test, backup/restore test or production suitability claim is made.
