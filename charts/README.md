# Pinned upstream Helm charts

Downloaded from the official Helm repository https://charts.cockroachdb.com/v2.

- cockroachdb-operator-chart 1.1.0: current operator v1.1.0.
- cockroachdb-chart 26.2.4: application chart; saved values override its
  default CockroachDB v26.2.5 with v26.2.7.

SHA256SUMS records local artifact hashes for reproducibility; these are not
publisher signatures. The operator chart archive includes CRD schemas, API
reference, manifests and its README describing lifecycle safeguards.

Update chart versions in the scripts and documentation together. Retain the
saved values when upgrading; render YAML for review before applying.
