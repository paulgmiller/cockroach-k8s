# Minimal CockroachDB on Kubernetes

Single-node development database in namespace `cockroach`, deployed to the
`zebu` context using `/home/pmiller/.kube/config`. Credentials are not in this repo.
The manifests are plain Kubernetes resources, assembled with built-in Kustomize.
Storage is a static local PersistentVolume and PVC reusing the existing directory
`/var/lib/cockroachdb/cockroach` on `aks-main-11118102-vmss000001`.

## Deploy and verify

The local directory must already exist on the worker and be writable by the
container. It exists on this cluster from the previous hostPath deployment. A
fresh installation requires an administrator to prepare the directory or a
dedicated mounted disk on the chosen worker, and update the PV node affinity.
The local volume plugin does not create directories or provision disks. Applying
the manifests requires permissions for cluster-scoped PV and StorageClass objects.


```bash
export KUBECONFIG=/home/pmiller/.kube/config
kubectl --context=zebu apply -k manifests
kubectl --context=zebu -n cockroach rollout status statefulset/cockroachdb --timeout=300s
kubectl --context=zebu -n cockroach get pods,pvc,services
kubectl --context=zebu get pv cockroachdb-local
kubectl --context=zebu -n cockroach exec cockroachdb-0 -- \
  /cockroach/cockroach sql --insecure --host=localhost:26257 \
  --execute='SELECT version(); SELECT 1;'
```

`start-single-node` initializes the database automatically; no init Job is needed.
The container command invokes `/cockroach/cockroach` directly because the image's
shell entrypoint rejects a non-localhost listen address in single-node mode.

## Connect

SQL endpoint for applications in this namespace:
`postgresql://root@cockroachdb.cockroach.svc.cluster.local:26257/defaultdb?sslmode=disable`.

For local access, keep this command running:

```bash
kubectl --kubeconfig=/home/pmiller/.kube/config --context=zebu -n cockroach \
  port-forward --address=127.0.0.1 service/cockroachdb 26257:26257 8080:8080
```

Then connect to `postgresql://root@localhost:26257/defaultdb?sslmode=disable`,
or open the DB Console at <http://localhost:8080>.

## Tradeoffs

| Choice | Benefit | Cost or limitation |
| --- | --- | --- |
| One StatefulSet replica, `start-single-node` | Few resources, automatic initialization | No replication or high availability. Pod restarts, upgrades, node failures, and storage migration cause downtime. Do not simply raise the replica count; a multi-node deployment needs `start`, join addresses, initialization, and replication planning. |
| Insecure mode | No certificates or credential bootstrap | No TLS or password authentication; reachable clients can act as root. Use only for trusted development data. Production requires TLS, proper SQL users, and managed secrets. |
| ClusterIP services and ingress NetworkPolicy | No public load balancer; ingress allowed only from pods in `cockroach` | Policy requires a supporting cluster network implementation and does not replace authentication. Node traffic and authorized Kubernetes port-forward access have separate access paths. Egress is unrestricted. Applications in other namespaces need an explicit policy change. |
| Static local PV and PVC, declared 10Gi | Kubernetes tracks the claim and volume; no new managed disk; reuses existing data | The directory shares the worker filesystem. Declared capacity is a binding value, not an enforced quota or reserved disk space. Monitor actual disk space and use a dedicated filesystem for isolation. Node deletion, replacement or reimaging can lose all data. |
| PV node affinity for `aks-main-11118102-vmss000001` | Scheduler places the pod on the worker containing its data; no pod node selector needed | Cannot fail over to another worker. If that worker is unavailable the pod stays Pending. Moving to another worker requires offline migration or restore and a replacement PV. |
| `cockroach-local` StorageClass, `WaitForFirstConsumer` | Binding considers pod scheduling; no external provisioner | Static provisioning and directory preparation are manual. PV claim reservation and PVC selector limit binding to this database. |
| PV reclaim policy `Retain` | PVC or namespace deletion preserves the PV and local data | Released PVs require manual reclamation before reuse. Retention provides no backup, replication, or protection from loss of the underlying worker disk. |
| 250m CPU / 512Mi memory requested; 1 CPU / 1Gi limited | Small scheduling footprint; bounded resource consumption | Development sizing only. CPU throttling and OOM restarts are possible under load. 128Mi cache and SQL memory budgets leave headroom but do not cap all memory. Temporary SQL disk use capped at 1Gi. |
| Version tag `v26.2.7` | Repeatable version selection, avoids `latest`; patch includes security fixes | Tag is not an immutable digest; updates require deliberate review. Record the running digest in deployment verification. |
| Direct manifests, no operator | Simple installation; no operator or CRDs | Manual upgrades, backups, monitoring, certificate management, and recovery. No disruption budget since this single node cannot provide continuous availability. |

This is a development deployment, not a production or performance-testing setup.
For production, use at least three database nodes on suitable failure domains,
TLS/authentication, workload-sized resources and disks, automated off-cluster
backups with restore tests, monitoring, and a supported upgrade process.
The inspected Kubernetes cluster has two worker nodes, so additional capacity
would be needed to place three database replicas on distinct workers.

CockroachDB licensing must be reviewed before changing use or topology.
The official FAQ says single-node internal development clusters generally do not
require a license key and are not throttled; production/multi-node use has other requirements.

## Stop or remove

Pause the database while retaining the host directory:

```bash
kubectl --kubeconfig=/home/pmiller/.kube/config --context=zebu -n cockroach \
  scale statefulset/cockroachdb --replicas=0
```

Reapplying the manifests resumes the single replica using the bound PVC.
Deleting the namespace removes the local PVC and the retained Azure migration
source PVC/disk. The local PV becomes `Released` and its directory remains; the
cluster-scoped StorageClass also remains. Host data must be removed separately
on that worker after the database is stopped:

```bash
# DESTRUCTIVE: removes namespace resources and the retained source disk.
# Local host data remains on the worker.
kubectl --kubeconfig=/home/pmiller/.kube/config --context=zebu delete namespace cockroach
```

## Local PV conversion and recovery

The conversion replaced the pod hostPath mount with PVC `cockroachdb-local`.
PV `cockroachdb-local` points to the same existing directory and worker, so no
copy or database reinitialization was needed. The StatefulSet rolled its pod to
use the PVC. A row written before conversion survived conversion and a subsequent
pod restart. The one-replica rollout causes brief database downtime.

If the PVC is deleted, the PV remains `Released` with the old claim UID. Simply
reapplying manifests does not reclaim it. After confirming that no database pod
is running, the retained directory is correct, and the replacement PVC is
intended to own this data, an administrator can remove the stale PV `claimRef`:

```bash
kubectl --kubeconfig=/home/pmiller/.kube/config --context=zebu patch pv cockroachdb-local \
  --type=json -p='[ {"op": "remove", "path": "/spec/claimRef"} ]'
kubectl --kubeconfig=/home/pmiller/.kube/config --context=zebu apply -k manifests
```

The manifest reserves the PV for `cockroach/cockroachdb-local`; the PVC selector
identifies this specific local PV. Verify binding before accepting traffic.
Do not bind another database to the same directory. If the worker or disk is lost,
restore an off-node backup to a prepared directory on a replacement worker and
create a replacement PV with the appropriate node affinity. `Retain` cannot
recover a lost directory.

## Historical disk migration and rollback

The original database was stopped and its complete store copied offline with
[operations/migrate-to-host.yaml](operations/migrate-to-host.yaml). This one-time
Job is excluded from Kustomize and refuses a non-empty destination. The
StatefulSet was recreated because removing `volumeClaimTemplates` is immutable.
The source PVC `data-cockroachdb-0` remains as a rollback copy and still incurs
Azure disk charges; it is not used by the running database. It is a point-in-time
copy and does not contain changes made after migration.

To roll back to that point, stop the current database, restore the original
StatefulSet manifest from Git commit `957fc8f`, delete the stopped StatefulSet,
and apply the restored manifest. It will reuse the retained PVC. Do not run both
versions concurrently. To preserve newer writes, first perform an offline reverse
copy or a database backup/restore. Never change the storage node without moving
the data.

For migration replay: scale the old StatefulSet to zero, wait for its pod deletion,
apply the migration Job and wait for completion, inspect its logs, delete the Job,
then delete the stopped StatefulSet and apply `manifests`. Current manifests
create the local PV/PVC for that copied directory. Never rerun the copy
against an active database. The Job must be absent before the host store starts.

## Sources

- [Kubernetes local volumes and node affinity](https://kubernetes.io/docs/concepts/storage/volumes/#local)
- [Local StorageClass and delayed binding](https://kubernetes.io/docs/concepts/storage/storage-classes/#local)
- [Single-node command, limitations and insecure mode](https://www.cockroachlabs.com/docs/stable/cockroach-start-single-node)
- [v26.2 release notes and image tags](https://www.cockroachlabs.com/docs/releases/v26.2)
- [Licensing FAQ](https://www.cockroachlabs.com/docs/stable/licensing-faqs)

See [deployment verification](VERIFICATION.md) for results from the actual cluster.
