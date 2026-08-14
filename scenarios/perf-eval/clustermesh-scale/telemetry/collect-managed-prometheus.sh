#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

for phase_script in \
  wait-managed-prometheus.sh \
  audit-managed-prometheus.sh \
  reconstruct-managed-prometheus.sh \
  upload-managed-prometheus.sh; do
  bash "$script_dir/$phase_script"
done
