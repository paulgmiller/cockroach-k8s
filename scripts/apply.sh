#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export KUBECONFIG=${KUBECONFIG:-/home/pmiller/.kube/config}
context=${KUBE_CONTEXT:-zebu}
kubectl --context="$context" apply -k "$repo_dir/manifests"
helm upgrade --install cockroach-operator "$repo_dir/charts/cockroachdb-operator-chart-1.1.0.tgz" \
  --kube-context="$context" --namespace cockroach-operator-system --create-namespace \
  -f "$repo_dir/helm/operator-values.yaml" --wait --timeout 5m
helm upgrade --install cockroachdb "$repo_dir/charts/cockroachdb-chart-26.2.4.tgz" \
  --kube-context="$context" --namespace cockroach \
  -f "$repo_dir/helm/database-values.yaml" --wait --timeout 5m
kubectl --context="$context" -n cockroach wait --for=condition=Initialized \
  crdbcluster/cockroachdb --timeout=300s
kubectl --context="$context" -n cockroach wait --for=condition=Ready \
  pods -l app=cockroachdb --timeout=300s
kubectl --context="$context" -n cockroach get crdbclusters,crdbnodes,pods,pvc,pdb
