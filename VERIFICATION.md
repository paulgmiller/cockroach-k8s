# Deployment verification

Verified on 2026-10-04 (America/Los_Angeles) against context `zebu`, using
`/home/pmiller/.kube/config`. The Kubernetes cluster has two Ready workers.

## Final state

- StatefulSet `cockroachdb` has one desired database replica, `1/1 Running`,
  zero container restarts after the final rollout, using `cockroach start`.
- Replica 0 uses PVC `local-data-cockroachdb-0`, bound to static local PV
  `cockroachdb-local`, retaining `/var/lib/cockroachdb/cockroach` on
  `aks-main-11118102-vmss000001`.
- StorageClass `cockroach-local-auto` uses the dedicated automatic provisioner,
  local-type volumes, WaitForFirstConsumer binding, and Retain reclamation.
- Provisioner deployment in `cockroach-storage` is `1/1 Running`.
- Init Job completed and correctly recognized the existing initialized database.
- All 15 zone configurations previously set to one replica now specify three;
  they remained at three after a database pod replacement.
- Final node status reported one live/available node, zero unavailable ranges,
  and 56 under-replicated ranges. Under-replication is expected with only one
  running database node and a desired replication factor of three.
- Final `kubectl diff -k manifests` exited 0 with no differences.
- All YAML parsed, `bash -n scripts/scale.sh` passed, and Git whitespace checks passed.

## Scale-out test

1. Wrote `(1, 'scale-ready')` to a temporary table before the conversion.
2. Stopped the database, retained its PV and rebound it to the new ordinal-0
   claim. Recreated the StatefulSet because claim templates and pod management
   policy are immutable. The same initialized store restarted successfully.
3. Confirmed the original row remained available after conversion.
4. Temporarily scaled to two database replicas while replication policies still
   requested one copy, so the test could safely return to one node afterward.
5. The provisioner automatically created a separate local directory and PV on
   worker `aks-main-11118102-vmss000000` for `local-data-cockroachdb-1`.
6. Verified the generated PV had `spec.local`, no `spec.hostPath`, worker node
   affinity, and reclaim policy Retain.
7. Both CockroachDB nodes were live/available. A SQL query through replica 1
   returned the row written before conversion, confirming membership in the
   existing cluster rather than an independent database.
8. Fully decommissioned database node ID 2, waited for zero remaining replicas
   and successful draining, then scaled back to one database replica.
9. Deleted only the decommissioned test claim/store, using Delete reclamation
   for that disposable PV; verified the test PV was removed. Replica 0 was retained.
10. Applied `operations/enable-replication.sql`, rolled replica 0 once more,
    and verified both the test row and three-copy zone policies survived.
11. Dropped the temporary database `scale_ready_smoke` after verification.

The scale helper correctly rejected three replicas with only two Ready workers,
without modifying the desired manifest count. Its three-or-more execution path
cannot be exercised until additional workers exist. Three-node quorum behavior,
worker failure, backup/restore, and fresh-cluster initialization were not tested.
The existing-cluster init path and two-node join/provisioning path were tested.
NetworkPolicy is installed; cross-namespace enforcement was not tested.

## Historical migrations and retained resources

The initial Azure-disk deployment was migrated offline to the host directory.
A pre-migration test row survived the copy and a pod restart. The host directory
was then wrapped in a static local PV/PVC; another row survived that conversion
and a pod restart. The final scalable conversion reused the same data again.

The unused Azure PVC `data-cockroachdb-0` remains as an earlier rollback snapshot
and still incurs disk charges. It does not contain writes after the host migration.
The old static StorageClass `cockroach-local` remains unused. The old local PVC
`cockroachdb-local` was removed during rebinding; its data is now in replica 0's
retained store, with no data copy needed for this conversion.

Running database image digest:

```text
docker.io/cockroachdb/cockroach@sha256:9464ae30465b887295459b98d129a76d074caeaa4c86836d369c6d2fdddd1685
```
