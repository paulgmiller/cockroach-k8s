# Minimal CockroachDB on Kubernetes

Single-node development database in namespace `cockroach`, deployed to the
`zebu` context using `/home/pmiller/.kube/config`. Credentials are not in this repo.
The manifests are plain Kubernetes resources, assembled with built-in Kustomize.

## Deploy and verify

```bash
export KUBECONFIG=/home/pmiller/.kube/config
kubectl --context=zebu apply -k manifests
kubectl --context=zebu -n cockroach rollout status statefulset/cockroachdb --timeout=300s
kubectl --context=zebu -n cockroach get pods,pvc,services
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
| One StatefulSet replica, `start-single-node` | Few resources, automatic initialization | No replication or high availability. Pod restarts, upgrades, node failures, and disk reattachment cause downtime. Do not simply raise the replica count; a multi-node deployment needs `start`, join addresses, initialization, and replication planning. |
| Insecure mode | No certificates or credential bootstrap | No TLS or password authentication; reachable clients can act as root. Use only for trusted development data. Production requires TLS, proper SQL users, and managed secrets. |
| ClusterIP services and ingress NetworkPolicy | No public load balancer; ingress allowed only from pods in `cockroach` | Policy requires a supporting cluster network implementation and does not replace authentication. Node traffic and authorized Kubernetes port-forward access have separate access paths. Egress is unrestricted. Applications in other namespaces need an explicit policy change. |
| 10Gi `managed-csi` PVC | Data survives pod replacement; Azure Standard SSD rather than shared network files | AKS-specific storage class, single disk and single writer, no backup. Azure may round provisioned capacity to a billing tier. A zonal disk can constrain rescheduling. |
| StatefulSet default PVC retention | Deleting/scaling the StatefulSet keeps its PVC | Deleting the PVC or namespace destroys data: the storage class has reclaim policy `Delete`. PVC retention is not a backup. |
| 250m CPU / 512Mi memory requested; 1 CPU / 1Gi limited | Small scheduling footprint; bounded resource consumption | Development sizing only. CPU throttling and OOM restarts are possible under load. 128Mi cache and SQL memory budgets leave headroom but do not cap all memory. Temporary SQL disk use capped at 1Gi. |
| Version tag `v26.2.7` | Repeatable version selection, avoids `latest`; patch includes security fixes | Tag is not an immutable digest; updates require deliberate review. Record the running digest in deployment verification. |
| Direct manifests, no operator | Simple installation; no cluster-wide CRDs/RBAC | Manual upgrades, backups, monitoring, certificate management, and recovery. No disruption budget since this single node cannot provide continuous availability. |

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

Pause the database while retaining data (the disk can still incur charges):

```bash
kubectl --kubeconfig=/home/pmiller/.kube/config --context=zebu -n cockroach \
  scale statefulset/cockroachdb --replicas=0
```

Reapplying the manifests resumes the single replica. To remove the database
permanently, deleting the namespace also deletes its PVC and backing disk:

```bash
# DESTRUCTIVE: deletes all database data and all resources in this namespace.
kubectl --kubeconfig=/home/pmiller/.kube/config --context=zebu delete namespace cockroach
```

## Sources

- [Single-node command, limitations and insecure mode](https://www.cockroachlabs.com/docs/stable/cockroach-start-single-node)
- [v26.2 release notes and image tags](https://www.cockroachlabs.com/docs/releases/v26.2)
- [Licensing FAQ](https://www.cockroachlabs.com/docs/stable/licensing-faqs)

See [deployment verification](VERIFICATION.md) for results from the actual cluster.
