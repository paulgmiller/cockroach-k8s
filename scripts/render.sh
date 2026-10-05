#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
helm template cockroach-operator "$repo_dir/charts/cockroachdb-operator-chart-1.1.0.tgz" \
  --namespace cockroach-operator-system -f "$repo_dir/helm/operator-values.yaml" \
  > "$repo_dir/rendered/operator.yaml"
helm template cockroachdb "$repo_dir/charts/cockroachdb-chart-26.2.4.tgz" \
  --namespace cockroach -f "$repo_dir/helm/database-values.yaml" \
  > "$repo_dir/rendered/database.yaml"
python3 - "$repo_dir/rendered" <<'PY'
from pathlib import Path
import sys
for path in Path(sys.argv[1]).glob('*.yaml'):
    path.write_text(path.read_text().rstrip() + '\n')
PY
