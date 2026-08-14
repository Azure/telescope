#!/usr/bin/env bash
set -euo pipefail
shopt -s globstar nullglob

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=managed-prometheus-common.sh
source "$script_dir/managed-prometheus-common.sh"

: "${CL2_REPORT_DIR:?CL2_REPORT_DIR is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${BUILD_ID:?BUILD_ID is required}"
: "${SNAPSHOT_TIER:?SNAPSHOT_TIER is required}"

work_root=$(mktemp -d "${TMPDIR:-/tmp}/prom-snapshot-relabel-XXXXXX")
cleanup() {
  chmod -R u+w "$work_root" 2>/dev/null || true
  rm -rf "$work_root"
}
trap cleanup EXIT

snapshots=("$CL2_REPORT_DIR"/**/prom-snapshot-*.tar.gz)
if [ "${#snapshots[@]}" -eq 0 ]; then
  echo "No Prometheus TSDB snapshots found for block relabeling."
  echo "##vso[task.setvariable variable=CL2_PROM_SNAPSHOT_RELABEL_READY]true"
  exit 0
fi

if [ -n "${INDEX_RELABEL_BIN:-}" ]; then
  rewriter="$INDEX_RELABEL_BIN"
  if [ ! -x "$rewriter" ]; then
    echo "INDEX_RELABEL_BIN is not executable: $rewriter" >&2
    exit 1
  fi
else
  go_version="${GO_VERSION:-1.25.5}"
  go_sha256="${GO_SHA256:-9e9b755d63b36acf30c12a9a3fc379243714c1c6d3dd72861da637f336ebb35b}"
  go_bin=""
  if command -v go >/dev/null 2>&1; then
    installed_version=$(go env GOVERSION 2>/dev/null || true)
    if [[ "$installed_version" =~ ^go1\.(2[5-9]|[3-9][0-9])([.].*)?$ ]]; then
      go_bin=$(command -v go)
    fi
  fi
  if [ -z "$go_bin" ]; then
    if [ "$(uname -m)" != "x86_64" ]; then
      echo "Pinned Go fallback only supports linux-amd64 agents." >&2
      exit 1
    fi
    go_archive="$work_root/go${go_version}.linux-amd64.tar.gz"
    curl -fsSL \
      "https://go.dev/dl/go${go_version}.linux-amd64.tar.gz" \
      -o "$go_archive"
    echo "$go_sha256  $go_archive" | sha256sum -c -
    mkdir -p "$work_root/go-root"
    tar xzf "$go_archive" -C "$work_root/go-root"
    go_bin="$work_root/go-root/go/bin/go"
  fi

  rewriter="$work_root/tsdb-index-relabel"
  (
    cd "$script_dir/tsdb-index-relabel"
    GOTOOLCHAIN=local \
      GOCACHE="$work_root/go-build-cache" \
      GOMODCACHE="$work_root/go-module-cache" \
      CGO_ENABLED=0 \
      "$go_bin" build \
        -mod=readonly \
        -trimpath \
        -ldflags="-s -w" \
        -o "$rewriter" \
        .
  )
  chmod -R u+w \
    "$work_root/go-build-cache" \
    "$work_root/go-module-cache" \
    "$work_root/go-root" \
    2>/dev/null || true
  rm -rf \
    "$work_root/go-build-cache" \
    "$work_root/go-module-cache" \
    "$work_root/go-root"
  rm -f "$work_root"/go*.linux-amd64.tar.gz
fi

run_label=$(snapshot_label_value "$RUN_ID")
build_label=$(snapshot_label_value "$BUILD_ID")
tier_label=$(snapshot_label_value "$SNAPSHOT_TIER")
if [ -z "$run_label" ] || [ -z "$build_label" ] || [ -z "$tier_label" ]; then
  echo "Snapshot run/build/tier labels must not be empty." >&2
  exit 1
fi

list_blocks() {
  local data_root="$1"
  find "$data_root" \
    -mindepth 2 \
    -maxdepth 2 \
    -type f \
    -name meta.json \
    -printf '%h\n' \
    | sed 's#.*/##' \
    | grep -E '^[0-9A-Z]{26}$' \
    | sort
}

relabel_snapshot() {
  local snapshot="$1"
  local index="$2"
  local snapshot_work="$work_root/snapshot-$index"
  local extract_root="$snapshot_work/extract"
  local snapshot_cluster data_root relabeled block
  local -a roots blocks

  mkdir -p "$extract_root"
  tar xzf "$snapshot" -C "$extract_root"
  mapfile -t roots < <(
    find "$extract_root" -mindepth 1 -maxdepth 1 -type d | sort
  )
  if [ "${#roots[@]}" -ne 1 ]; then
    echo "$snapshot must contain exactly one snapshot directory." >&2
    return 1
  fi
  data_root="${roots[0]}"
  mapfile -t blocks < <(list_blocks "$data_root")
  if [ "${#blocks[@]}" -eq 0 ]; then
    echo "No TSDB blocks found in $snapshot." >&2
    return 1
  fi

  snapshot_cluster=$(snapshot_label_value "$(basename "$(dirname "$snapshot")")")
  if [ -z "$snapshot_cluster" ]; then
    echo "Unable to derive snapshot_cluster from $snapshot." >&2
    return 1
  fi

  for block in "${blocks[@]}"; do
    "$rewriter" \
      --block-dir "$data_root/$block" \
      --label "run=$run_label" \
      --label "build=$build_label" \
      --label "tier=$tier_label" \
      --label "snapshot_cluster=$snapshot_cluster"
  done

  if find "$data_root" -type f -name '.index-relabel-*' -print -quit \
      | grep -q .; then
    echo "Temporary index files remain in $snapshot." >&2
    return 1
  fi

  relabeled="${snapshot}.relabel.partial"
  rm -f "$relabeled"
  if tar czf "$relabeled" -C "$extract_root" "$(basename "$data_root")" &&
     gzip -t "$relabeled"; then
    mv "$relabeled" "$snapshot"
  else
    rm -f "$relabeled"
    return 1
  fi
  rm -rf "$snapshot_work"
  echo "Relabeled ${#blocks[@]} index file(s) in $snapshot"
}

for index in "${!snapshots[@]}"; do
  relabel_snapshot "${snapshots[$index]}" "$index"
done

echo "Relabeled ${#snapshots[@]} Prometheus snapshot tarball(s) with run/build/tier/snapshot_cluster."
echo "##vso[task.setvariable variable=CL2_PROM_SNAPSHOT_RELABEL_READY]true"
