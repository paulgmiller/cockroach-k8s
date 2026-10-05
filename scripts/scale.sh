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
current=$(kubectl --context="$context" -n cockroach get statefulset cockroachdb -o jsonpath='{.spec.replicas}')
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
if (( workers < replicas )); then
  echo "Need at least $replicas Ready, schedulable Linux workers; found $workers." >&2
  exit 1
fi
# Persist desired replicas so future applies do not undo scale-out.
python3 - "$repo_dir/manifests/statefulset.yaml" "$replicas" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1])
s,count=re.subn(r'^  replicas: [0-9]+$', '  replicas: '+sys.argv[2], p.read_text(), flags=re.M)
if count != 1: raise SystemExit('Expected exactly one StatefulSet replicas setting')
p.write_text(s)
PY
kubectl --context="$context" apply -k "$repo_dir/manifests"
kubectl --context="$context" -n cockroach rollout status statefulset/cockroachdb --timeout=600s
kubectl --context="$context" -n cockroach exec cockroachdb-0 -- \
  /cockroach/cockroach node status --insecure --host=localhost:26257 --ranges
echo 'Check that all nodes are live and under-replicated/unavailable ranges settle to zero.'
