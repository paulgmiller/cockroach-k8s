#!/usr/bin/env bash
set -euo pipefail

replicas=${1:-}
if [[ ! "$replicas" =~ ^[1-9][0-9]*$ ]] || (( replicas < 3 )); then
  echo 'Usage: scripts/scale.sh REPLICAS (3 or more); see README for safe scale-down.' >&2
  exit 2
fi
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export KUBECONFIG=${KUBECONFIG:-/home/pmiller/.kube/config}
context=${KUBE_CONTEXT:-zebu}
current=$(kubectl --context="$context" -n cockroach get crdbcluster cockroachdb -o jsonpath='{.spec.regions[0].nodes}')
if (( replicas < current )); then
  echo 'This script only scales up. Decommission database nodes before scaling down.' >&2
  exit 2
fi
workers=$(kubectl --context="$context" get nodes -o json | python3 -c '
import json,sys
nodes=json.load(sys.stdin)["items"]
print(sum(not n.get("spec",{}).get("unschedulable",False)
          and n["metadata"].get("labels",{}).get("kubernetes.io/os")=="linux"
          and any(c["type"]=="Ready" and c["status"]=="True" for c in n["status"]["conditions"])
          for n in nodes))')
if (( workers < 2 )); then
  echo "Need at least two Ready, schedulable Linux workers; found $workers." >&2
  exit 1
fi
# Helm values are the source of truth, including for subsequent upgrades.
python3 - "$repo_dir/helm/database-values.yaml" "$replicas" <<'PYVALUES'
from pathlib import Path
import sys,yaml
p=Path(sys.argv[1])
v=yaml.safe_load(p.read_text())
v['cockroachdb']['crdbCluster']['regions'][0]['nodes']=int(sys.argv[2])
p.write_text(yaml.safe_dump(v,sort_keys=False))
PYVALUES
"$repo_dir/scripts/render.sh"
helm upgrade --install cockroachdb "$repo_dir/charts/cockroachdb-chart-26.2.4.tgz" \
  --kube-context="$context" --namespace cockroach -f "$repo_dir/helm/database-values.yaml" \
  --wait --timeout 5m
# Helm does not wait for custom-resource readiness. Wait for the operator too.
deadline=$((SECONDS + 600))
while ! kubectl --context="$context" -n cockroach get crdbcluster cockroachdb -o json |
  python3 -c 'import json,sys; c=json.load(sys.stdin); s=c.get("status",{}); sys.exit(0 if s.get("readyNodes",0)>=int(sys.argv[1]) and s.get("observedGeneration",0)>=c["metadata"]["generation"] and s.get("reconciled",False) else 1)' "$replicas"; do
  if (( SECONDS >= deadline )); then
    echo 'Timed out waiting for operator reconciliation. Desired count is saved; inspect events and CrdbCluster status.' >&2
    exit 1
  fi
  sleep 5
done
pod=$(kubectl --context="$context" -n cockroach get pods -l app=cockroachdb -o jsonpath='{.items[0].metadata.name}')
# Match system-range policies to this small three-copy deployment, so the
# operator's under-replication safeguard does not require five database nodes.
kubectl --context="$context" -n cockroach exec -i "$pod" -c cockroachdb -- \
  /cockroach/cockroach sql --insecure --host=localhost:26257 < "$repo_dir/sql/replication-three.sql"
deadline=$((SECONDS + 600))
while true; do
  if report=$(kubectl --context="$context" -n cockroach exec "$pod" -c cockroachdb -- \
    /cockroach/cockroach node status --insecure --host=localhost:26257 --ranges --format=csv --timeout=30s); then
    if python3 -c 'import csv,io,sys; rows=list(csv.DictReader(io.StringIO(sys.argv[1]))); sys.exit(0 if len(rows)>=int(sys.argv[2]) and all(r["is_live"]=="true" and r["is_available"]=="true" and int(r["ranges_unavailable"])==0 and int(r["ranges_underreplicated"])==0 for r in rows) else 1)' "$report" "$replicas"; then
      printf '%s\n' "$report"
      break
    fi
  fi
  if (( SECONDS >= deadline )); then
    echo 'Database nodes joined, but ranges have not converged. Inspect zone overrides and node status before maintenance.' >&2
    exit 1
  fi
  sleep 10
done
echo 'Scale-out complete. Commit the updated Helm values and rendered YAML.'
