# Azure disk choices, pricing and operational lessons

Recorded 2026-10-23 after the Zebu worker recovery and ZRS migration.
The current deployment has three 10Gi StandardSSD_ZRS disks, provisioned by
[`managed-csi-zrs`](manifests/storageclass-zrs.yaml). Helm's volume template is in
[`helm/database-values.yaml`](helm/database-values.yaml). Detailed migration
evidence and backup locations are in [VERIFICATION.md](VERIFICATION.md).

## What ZRS buys us

| Disk configuration | Placement and recovery |
| --- | --- |
| Zonal LRS | The disk belongs to one zone; replacement workers must be compatible with that zone. |
| Nonzonal LRS | In our original deployment, the PV required an empty zone label. New zonal workers could not satisfy it. Nonzonal does not mean zone-redundant. |
| ZRS | Storage is replicated across zones, and the disk can reattach to a worker in another zone within the region. Detach, attach and database startup still take time. |

ZRS has higher write latency than LRS because its storage replication crosses
zones. Benchmark the workload if latency becomes important. See Azure's
[redundancy comparison](https://learn.microsoft.com/en-us/azure/virtual-machines/disks-redundancy).

ZRS disk replication and CockroachDB replica placement solve different problems.
We still run three database replicas on two workers. Losing the worker hosting
two replicas can remove quorum even though the ZRS disks survive. Recovery can
restart the original database replicas with their existing disks on compatible
workers. Adding empty database replicas cannot by itself restore lost quorum.
For worker-failure tolerance, use three workers and suitable placement; for zone
failure tolerance, distribute replicas across three zones. See Cockroach Labs'
[topology guidance](https://docs.cockroachlabs.com/docs/stable/recommended-production-settings#topology).

### Write latency tradeoff and follow-up

We use synchronous replication at two layers: CockroachDB replicates writes
between database replicas, and each replica's ZRS disk synchronously replicates
across three Azure zones. This adds storage replication work to the database's
durable write path. CockroachDB sends Raft proposals to replicas in parallel and
needs a majority to acknowledge, so counting copies or zone crossings does not
directly predict transaction latency. See Cockroach Labs' explanation of
[consensus and storage latency](https://www.cockroachlabs.com/blog/transaction-pipelining/).

Azure targets approximately less than 2ms inter-zone network round-trip latency;
this is a network-link target, not a guarantee for pod traffic, disk writes or
transactions. Azure documents higher write latency for ZRS than LRS without a
fixed millisecond penalty. We have not measured Zebu's actual latency or the
increment attributable to ZRS. See
[Azure inter-zone networking](https://learn.microsoft.com/en-us/azure/reliability/availability-zones-overview#inter-zone-networking).

With three workers across three zones and appropriate replica placement, zonal
LRS could rely on CockroachDB for zone replication and avoid the additional ZRS
write latency and cost. For our current two-worker deployment, we retain ZRS for
cross-zone recovery of existing disks, accepting the unmeasured latency cost.

- [ ] TODO: Measure Zebu latency under representative write traffic. Capture
  per-store `storage.wal.fsync.latency` p50/p95/p99, inter-node RTT by zone pair,
  and `sql.service.latency` / `sql.txn.latency`. Use SQL Activity statement
  fingerprints to distinguish INSERT/UPDATE/DELETE from reads. Record workload,
  throughput, CPU and disk throttling alongside latency. Fsync measures the
  total storage path and cannot isolate ZRS overhead; quantify that overhead
  with a controlled LRS/ZRS comparison if needed before revisiting the choice.
  Metric names and units are in the
  [CockroachDB metric reference](https://docs.cockroachlabs.com/docs/stable/metrics).

## Standard SSD pricing snapshot

Public USD consumption rates for **West US 3**, checked 2026-10-23. These are
capacity charges for three disks, excluding I/O, snapshots, taxes and account
discounts. Rates can change; this is a dated comparison, not an invoice forecast.

| Requested capacity per replica | LRS, three disks/month | ZRS, three disks/month | ZRS premium/month |
| --- | ---: | ---: | ---: |
| 8Gi, billed as E2 | $1.80 | $2.70 | $0.90 |
| 10Gi or 16Gi, billed as E3 | $3.60 | $5.40 | $1.80 |

The underlying per-disk rates were E2 LRS $0.60, E2 ZRS $0.90, E3 LRS $1.20,
and E3 ZRS $1.80 per month. ZRS capacity is 50% more expensive in this snapshot.
Our current three 10Gi ZRS disks therefore have a $5.40/month capacity charge.

Small Standard SSD transaction meters were $0.002 per 10,000 operations for LRS
and $0.003 for ZRS. Hourly transaction billing caps apply and differ between
redundancy options, so the total bill does not have a fixed $1.80 difference.
Retained, unattached disks also continue incurring capacity charges.

Source: [Azure Retail Prices API, filtered to West US 3 Standard SSD](https://prices.azure.com/api/retail/prices?%24filter=serviceName%20eq%20%27Storage%27%20and%20armRegionName%20eq%20%27westus3%27%20and%20priceType%20eq%20%27Consumption%27%20and%20contains(productName,%27Standard%20SSD%27)),
with billing details on [Azure managed disk pricing](https://azure.microsoft.com/en-us/pricing/details/managed-disks/).
Use the E2/E3 `Disk` capacity meters and the `Disk Transactions LRS/ZRS Disk
Operations` meters for this comparison. Additional shared-disk `Disk Mount`
meters are not part of this deployment.

### Size requests to match billing tiers

Standard SSD capacity rounds up to an offered size tier. A 10Gi disk already
bills at 16Gi, so expanding it to 16Gi would provide more headroom for the same
capacity charge. It would not reduce the bill. An 8Gi disk falls into the cheaper
E2 tier. These tier rules are specific to the disk product; do not assume every
Azure storage product uses power-of-two billing. See
[disk sizes and billing](https://learn.microsoft.com/en-us/azure/virtual-machines/disks-types#managed-disk-size).

Azure cannot shrink an existing managed disk. Moving from 10Gi to 8Gi requires
replacement stores and data migration, with enough room for growth, compaction,
logs and temporary data. Capacity remains 10Gi after our ZRS migration. See the
[managed disk FAQ](https://learn.microsoft.com/en-us/azure/virtual-machines/faq-for-disks#can-i-shrink-or-downsize-my-managed-disks).

## Operator and migration lessons

### AKS defaults did not update Zebu's existing classes

[AKS documents ZRS defaults starting with 1.29 for clusters deployed across
availability zones](https://learn.microsoft.com/en-us/azure/aks/create-volume-azure-disk#built-in-storage-classes-for-dynamic-pvs-with-azure-disks).
However, our live check on 2026-10-23 found that Zebu's `default` and
`managed-csi` classes still explicitly specify `skuname: StandardSSD_LRS`;
`managed-csi-premium` specifies `Premium_LRS`. All three were created on
2022-11-22 and carry `addonmanager.kubernetes.io/mode: EnsureExists`.

These observations are consistent with older class definitions surviving the
cluster upgrades and move to zonal workers. They establish the current behavior,
but do not prove which AKS lifecycle rule preserved those definitions. The
documented default does not describe Zebu's actual existing classes. Our new
`managed-csi-zrs` makes the requested SKU explicit and sets reclaim policy Retain,
while leaving other workloads' class selection alone. Changing a default would
also not migrate existing disks.

### Migration checks

- Check the actual StorageClass parameters. The name `managed-csi` alone does
  not prove whether a cluster uses LRS or ZRS. `WaitForFirstConsumer` selects a
  compatible initial placement; it does not make an LRS disk portable across zones.
- On operator 1.1.0, changing the volume template's storageClassName restarted an
  existing pod but preserved its original PVC. The operator logged
  `ignore conflicting data storage class name existing managed-csi, but got managed-csi-zrs`.
  A successful Helm upgrade and a changed CrdbNode template did not prove that
  the disk migrated. Tracked in [helm-charts#693](https://github.com/cockroachdb/helm-charts/issues/693).
- Azure cannot directly convert our zonal LRS disks to ZRS. Its disk-level path
  requires snapshots and new disks. We instead used CockroachDB replication:
  add a fourth replica with a new ZRS disk, verify its Azure SKU and healthy
  replication, decommission one LRS replica, return to three, and repeat.
  See [Azure migration options](https://learn.microsoft.com/en-us/azure/virtual-machines/disks-migrate-lrs-zrs).
- During decommissioning, `1/2 Running` was expected: the database container
  stopped accepting clients while the certificate sidecar stayed Ready. Pod age
  is not the duration of its unready condition. Query another Ready replica.
- Verify zero unavailable and under-replicated ranges between replacements.
  Confirm the retired node is fully decommissioned with zero replicas before
  deleting its storage. A decommissioned store must not be restarted as a live node.
- `whenDeleted: Retain` did not keep PVCs during our operator-managed
  decommissioning. PV reclaim policy `Retain` protected the underlying disks.
  The new ZRS class uses Retain; explicitly clean up released disks after checks
  to avoid ongoing charges. A retained disk and ZRS replication do not replace
  a regular backup policy.

Verify the provider's disk rather than relying only on the requested class or
optional CSI volume attributes:

```sh
# Set PV to the Bound volume named by the database PVC.
disk_id=$(kubectl --context=zebu get pv "$PV" -o jsonpath='{.spec.csi.volumeHandle}')
az disk show --ids "$disk_id" \
  --query '{sku:sku.name,sizeGiB:diskSizeGB,zones:zones,state:diskState}'
```

The expected SKU is `StandardSSD_ZRS`. For the current active stores, size is
10GiB and state is Attached. Backup and data checks from the completed migration
are recorded separately in [VERIFICATION.md](VERIFICATION.md).
