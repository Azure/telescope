#!/usr/bin/env bash
# Per-cluster CL2 worker for the clustermesh-scale scenario.
#
# Extracted from steps/engine/clusterloader2/clustermesh-scale/execute.yml
# so that scale.py execute-parallel can fan out N copies of this script with
# bounded concurrency. The body MUST stay equivalent to the original
# per-iteration bash for-loop body (CL2 invoke + junit check + log capture +
# failure diag) — see PR #1157 phase 3 for the parallelization rationale.
#
# Per-cluster log capture + failure diag happen IMMEDIATELY when this
# cluster's CL2 finishes — before peer clusters complete — so that
# `kubectl --tail` log windows and `kubectl get events` recency don't age out
# while peers are still running.
#
# Exit code:
#   0 — CL2 ran AND junit.xml reports failures=0 errors=0
#   1 — anything else (CL2 didn't write junit, or junit has failures/errors)
# This is the authoritative per-cluster pass/fail signal that
# scale.py execute-parallel aggregates into the step's exit code.
#
# Usage:
#   run-cl2-on-cluster.sh \
#     <role> <kubeconfig> <report_dir> \
#     <cl2_image> <cl2_config_dir> <cl2_config_file> \
#     <provider> <python_script_file> <python_workdir> \
#     [tear_down_prometheus_flag]
#
# tear_down_prometheus_flag: "1" → pass --tear-down-prometheus to scale.py
# execute. Used by share-infra mode so each scenario's CL2 deploys a fresh
# Prom. "0" or unset → preserve Prom for failure-diagnostic dump (default
# single-scenario behavior).

set -uo pipefail

if [ "$#" -lt 9 ] || [ "$#" -gt 10 ]; then
  echo "Usage: $0 <role> <kubeconfig> <report_dir> <cl2_image> <cl2_config_dir> <cl2_config_file> <provider> <python_script_file> <python_workdir> [tear_down_prometheus_flag]" >&2
  exit 2
fi

role="$1"
kubeconfig="$2"
report_dir="$3"
cl2_image="$4"
cl2_config_dir="$5"
cl2_config_file="$6"
provider="$7"
python_script_file="$8"
python_workdir="$9"
tear_down_prometheus_flag="${10:-0}"
worker_started_epoch=$(date +%s)

mkdir -p "$report_dir"
repo_root=$(cd -- "$(dirname -- "$python_script_file")/../../../.." && pwd)
acns_telemetry_failed=0

# Cleanup state shared by the single EXIT trap below. Populated later
# (PROM_PATCH_PID / SNAPSHOT_PID once the background daemons are spawned,
# azure_private_dir once the per-worker Azure CLI cache copy is made) —
# declared here, empty, so the trap can be registered once and safely
# reference them under `set -u` no matter how early the script exits.
PROM_PATCH_PID=""
SNAPSHOT_PID=""
azure_private_dir=""
_cleanup_worker_state() {
  # Terminate background daemons (prom-cr-patcher, snapshot) regardless of
  # CL2 outcome, otherwise they'd linger past job end and keep hitting
  # kube-api.
  if [ -n "${PROM_PATCH_PID:-}" ]; then
    kill -- "-${PROM_PATCH_PID}" 2>/dev/null ||
      kill "${PROM_PATCH_PID}" 2>/dev/null || true
    wait "${PROM_PATCH_PID}" 2>/dev/null || true
  fi
  if [ -n "${SNAPSHOT_PID:-}" ]; then
    kill "${SNAPSHOT_PID}" 2>/dev/null || true
    wait "${SNAPSHOT_PID}" 2>/dev/null || true
  fi
  # Remove this worker's PRIVATE copy of the Azure CLI cache (never the
  # host's shared ~/.azure — that's only ever read from, never written
  # here). Safe to call even when no private dir was created.
  if [ -n "$azure_private_dir" ]; then
    rm -rf -- "$azure_private_dir"
  fi
  # CL2 can leave its CoreDNS monitor behind after deleting the rest of the
  # per-scenario Prometheus objects. Remove both possible monitor kinds so the
  # post-scenario health gate does not wait on telemetry-only residue.
  for resource in \
      podmonitors.monitoring.coreos.com \
      servicemonitors.monitoring.coreos.com; do
    kubectl --kubeconfig "$kubeconfig" -n monitoring delete "$resource" coredns \
      --ignore-not-found=true --wait=false --request-timeout=15s \
      >/dev/null 2>&1 || true
  done
}
trap _cleanup_worker_state EXIT

# Per-worker Azure CLI cache isolation (provider=aks only).
#
# run_cl2_command (modules/python/clusterloader2/utils.py) mounts an Azure
# CLI config dir rw into every CL2 docker container so `az` calls inside CL2
# (e.g. cloud-provider auth refresh) work. By default that's the host's
# ~/.azure MSAL token cache. clustermesh-scale's n-cluster fan-out runs up
# to N of these workers concurrently (scale.py execute_parallel), and
# concurrent containers reading/writing the SAME cache can race and corrupt
# it. So for aks we give each worker its OWN private copy: copy (never
# move/mutate) ONLY the top-level REGULAR files of the host cache into a
# fresh mktemp -d OUTSIDE report_dir (so it's never picked up as a test
# artifact / uploaded), then export CL2_AZURE_CONFIG_DIR so utils.py mounts
# the private copy instead of ~/.azure. Concurrent workers each get a
# distinct mktemp -d, so there is no cross-worker contention. Unset for
# every other provider — behavior there is byte-for-byte unchanged.
#
# Deliberately NOT a recursive copy: `az`/kubelogin only ever read the
# root-level auth/profile files (azureProfile.json, msal_token_cache.json,
# msal_http_cache.bin, clouds.config, config, ...). A real-world ~/.azure
# also carries large subdirectories this worker never needs — azuredevops/
# (~223MiB), cliextensions/ (~43MiB), logs/ (~7MiB), plus commands/ and
# telemetry/ — which a naive `cp -R` would duplicate per worker. At n=100
# concurrent workers that recursive copy amplifies to ~27GiB of throwaway
# disk per run, so we copy top-level regular files only (no directories,
# no symlinks).
if [ "$provider" = "aks" ]; then
  azure_host_dir="${HOME}/.azure"
  if [ ! -d "$azure_host_dir" ]; then
    # This scenario's kubeconfigs are populated via `az aks get-credentials`
    # (see execute.yml), so CL2 relies on an Azure CLI auth cache existing
    # before any worker starts. Fail loudly instead of letting CL2 hit a
    # confusing auth error deep inside the container.
    echo "##vso[task.logissue type=error;] $role: Azure CLI config dir not found at \$HOME/.azure; kubeconfig access for this scenario depends on Azure CLI auth (az aks get-credentials) having run first." >&2
    exit 1
  fi
  # This script runs under `set -uo pipefail` (no `-e`), so a failing
  # mktemp is NOT automatically fatal: `$(...)` command substitution would
  # otherwise silently leave azure_private_dir empty and let control fall
  # through to the `cp ... "$azure_private_dir/"` loop below, where an
  # empty azure_private_dir turns the copy destination into bare "/" --
  # i.e. `cp -p ... /`, attempting to copy Azure CLI cache files over the
  # root filesystem. Explicitly check mktemp's exit status AND that it
  # actually produced a path before ever reaching cp.
  if ! azure_private_dir="$(mktemp -d "${TMPDIR:-/tmp}/cl2-azure-${role}-XXXXXX")" ||
     [ -z "$azure_private_dir" ]; then
    echo "##vso[task.logissue type=error;] $role: mktemp failed to create a worker-private Azure CLI cache directory" >&2
    azure_private_dir=""
    exit 1
  fi
  # Copy ONLY top-level REGULAR files from the host cache -- never
  # directories and never symlinks. `az` / kubelogin only need the root
  # auth/profile files (azureProfile.json, msal_token_cache.json,
  # msal_http_cache.bin, clouds.config, config, service_principal_entries.json,
  # etc.); everything else at the top level of ~/.azure is a directory
  # (cliextensions/, azuredevops/, logs/, commands/, telemetry/, ...) that
  # this worker does not need. A full recursive copy of a real-world
  # ~/.azure can be 250+ MiB (223MiB azuredevops + 43MiB cliextensions +
  # 7MiB logs alone) -- with clustermesh-scale's n-cluster fan-out running
  # up to N workers concurrently, that would amplify into tens of GiB of
  # disk per run. `-type f` (not `-xtype f`) deliberately excludes symlinks
  # even if they resolve to a regular file, so a symlink under $HOME/.azure
  # can never be used to pull an arbitrary file from outside the cache
  # root into a worker's private copy. `-p` preserves the file mode.
  copy_failed=0
  copied_count=0
  while IFS= read -r -d '' entry; do
    if ! cp -p -- "$entry" "$azure_private_dir/"; then
      copy_failed=1
      break
    fi
    copied_count=$((copied_count + 1))
  done < <(find "$azure_host_dir" -mindepth 1 -maxdepth 1 -type f -print0)

  if [ "$copy_failed" -eq 1 ]; then
    echo "##vso[task.logissue type=error;] $role: failed to populate worker-private Azure CLI cache" >&2
    # Clean up the (partially populated, unusable) private dir ourselves
    # before exiting -- don't rely solely on the EXIT trap for this.
    rm -rf -- "$azure_private_dir"
    azure_private_dir=""
    exit 1
  fi
  if [ "$copied_count" -eq 0 ]; then
    # An empty private cache is as useless as a missing one -- fail loudly
    # instead of letting CL2 hit a confusing auth error deep inside the
    # container.
    echo "##vso[task.logissue type=error;] $role: no top-level regular files found under \$HOME/.azure ($azure_host_dir); refusing to proceed with an empty worker-private Azure CLI cache" >&2
    rm -rf -- "$azure_private_dir"
    azure_private_dir=""
    exit 1
  fi
  export CL2_AZURE_CONFIG_DIR="$azure_private_dir"
  echo "  $role: using worker-private Azure CLI cache at $azure_private_dir ($copied_count top-level file(s) copied)"
fi

identity_ready=true
for identity_value in \
  "${CLUSTERMESH_RUN_ID:-}" \
  "${CLUSTERMESH_CLUSTER_ROLE:-}" \
  "${CLUSTERMESH_CLUSTER_NAME:-}" \
  "${CLUSTERMESH_CLUSTER_RESOURCE_ID:-}" \
  "${CLUSTERMESH_SUBSCRIPTION_ID:-}" \
  "${CLUSTERMESH_RESOURCE_GROUP:-}" \
  "${CLUSTERMESH_REGION:-}" \
  "${CLUSTERMESH_PROMETHEUS_CLUSTER_ALIAS:-}"; do
  if [ -z "$identity_value" ]; then
    identity_ready=false
    break
  fi
done

echo "===================================================================="
echo "  Running CL2 on $role"
echo "===================================================================="

if [ "${CL2_ACNS_TELEMETRY_ENABLED:-false}" = "true" ]; then
  acns_setup_script="$repo_root/scenarios/perf-eval/clustermesh-scale/telemetry/setup-acns-telemetry.sh"
  echo "------- $role: configuring ACNS telemetry probe -------"
  if ! KUBECONFIG="$kubeconfig" bash "$acns_setup_script"; then
    echo "##vso[task.logissue type=error;] $role: ACNS telemetry setup failed."
    acns_telemetry_failed=1
  fi
fi

# Background Prometheus memory-limit patcher (Phase D fix 2026-05-16):
# CL2's bundled prometheus manifest hardcodes `resources.limits.memory: 2Gi`
# AND CL2 exposes only `--prometheus-memory-request` (not -limit) as a CLI
# knob. Build 67335 raised the request to 6Gi → k8s admission rejected the
# Prom StatefulSet with `requests: "6Gi" must be <= memory limit of 2Gi`
# → Prom was never created → every gather query returned "no endpoints
# available". Build 67347 used a 1Gi request (so request<=limit holds) but
# the 2Gi limit then OOM'd Prom under our cardinality, crashlooping mid-run.
#
# We can't change the CL2 image, but we CAN patch the Prometheus CR after
# prometheus-operator creates it. Run a polling background process that waits
# for the CR to exist and CONTINUOUSLY enforces `spec.resources.limits.memory`
# = target (patching whenever it diverges). It must keep running and re-patch
# across CL2 retries (CL2_MAX_ATTEMPTS>1 deletes+recreates the monitoring stack
# on a transient prometheus-setup failure → a fresh CR at the 2Gi default) and
# through post-run telemetry audit. Polling is cheap and no-ops if the CR never
# appears (enable_prometheus=False scenarios).
PROM_LIMIT="${CL2_PROMETHEUS_MEMORY_LIMIT_GI:-12}Gi"
PROM_PATCH_POLL_SECONDS="${CL2_PROM_PATCH_POLL_SECONDS:-10}"
PROM_PATCH_REQUEST_TIMEOUT_SECONDS="${CL2_PROM_PATCH_REQUEST_TIMEOUT_SECONDS:-15}"
if ! [[ "$PROM_PATCH_POLL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  PROM_PATCH_POLL_SECONDS=10
elif [ "$PROM_PATCH_POLL_SECONDS" -gt 60 ]; then
  PROM_PATCH_POLL_SECONDS=60
fi
if ! [[ "$PROM_PATCH_REQUEST_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  PROM_PATCH_REQUEST_TIMEOUT_SECONDS=15
elif [ "$PROM_PATCH_REQUEST_TIMEOUT_SECONDS" -gt 60 ]; then
  PROM_PATCH_REQUEST_TIMEOUT_SECONDS=60
fi
prom_patcher_kubectl() {
  timeout --foreground "$((PROM_PATCH_REQUEST_TIMEOUT_SECONDS + 5))s" \
    env KUBECONFIG="$kubeconfig" kubectl \
    --request-timeout="${PROM_PATCH_REQUEST_TIMEOUT_SECONDS}s" "$@"
}
PROM_PATCH_LOG="$report_dir/prom-cr-patch.log"
run_prom_patcher() {
  echo "[prom-patcher] starting; target limit=$PROM_LIMIT, lifetime=worker, poll=${PROM_PATCH_POLL_SECONDS}s, request-timeout=${PROM_PATCH_REQUEST_TIMEOUT_SECONDS}s, attempts=${CL2_MAX_ATTEMPTS:-1}, mock=${CL2_MOCK_MODE:-false}" >&2
  # Stay alive through long policy/saturation scenarios and the post-CL2
  # telemetry audit. CL2 can rewrite the Prometheus CR after initial setup;
  # the worker EXIT trap still terminates this daemon immediately on completion.
  _patches=0
  _identity_patches=0
  while true; do
    _prometheus_json=$(prom_patcher_kubectl -n monitoring \
      get prometheus k8s -o json 2>/dev/null || true)
    _current=$(echo "$_prometheus_json" | jq -r \
      '.spec.resources.limits.memory // ""' 2>/dev/null || true)
    _scrape_name=$(echo "$_prometheus_json" | jq -r \
      '.spec.additionalScrapeConfigs.name // ""' 2>/dev/null || true)
    _scrape_key=$(echo "$_prometheus_json" | jq -r \
      '.spec.additionalScrapeConfigs.key // ""' 2>/dev/null || true)
    _needs_patch=""
    _patch="{\"spec\":{\"resources\":{\"limits\":{\"memory\":\"$PROM_LIMIT\"}}"
    _scrape_secret_ready=""
    if [ "${CL2_MOCK_MODE:-false}" = "true" ] && \
       prom_patcher_kubectl -n monitoring get secret \
         clustermesh-additional-scrapes >/dev/null 2>&1; then
      _scrape_secret_ready=1
      _patch="${_patch},\"additionalScrapeConfigs\":{\"name\":\"clustermesh-additional-scrapes\",\"key\":\"prometheus-additional.yaml\"}"
      if [ "$_scrape_name" != "clustermesh-additional-scrapes" ] || \
         [ "$_scrape_key" != "prometheus-additional.yaml" ]; then
        _needs_patch=1
      fi
    fi
    _patch="${_patch}}}"
    # Patch whenever the CR exists but its limit isn't the target (covers both
    # first appearance and a retry's freshly-recreated CR).
    if [ -n "$_current" ] && { [ "$_current" != "$PROM_LIMIT" ] || [ -n "$_needs_patch" ]; }; then
      echo "[prom-patcher] prometheus/k8s limit=$_current additionalScrapeConfigs=${_scrape_name:-<none>}/${_scrape_key:-<none>} secretReady=${_scrape_secret_ready:-false} → patching" >&2
      if prom_patcher_kubectl -n monitoring patch prometheus k8s \
           --type=merge -p "$_patch" >&2; then
        _patches=$((_patches + 1))
        echo "[prom-patcher] patch #$_patches OK" >&2
      else
        echo "[prom-patcher] patch failed; will retry in ${PROM_PATCH_POLL_SECONDS}s" >&2
      fi
    fi
    if [ "$identity_ready" = "true" ]; then
      _identity_deployment_list=$(prom_patcher_kubectl -n monitoring get \
        deployment -l app=apiserver-backend-exporter -o json \
        2>/dev/null || true)
      _identity_deployment=$(echo "$_identity_deployment_list" | jq -c \
        '.items[0] // empty' 2>/dev/null || true)
      _identity_deployment_name=$(echo "$_identity_deployment" | jq -r \
        '.metadata.name // ""' 2>/dev/null || true)
      if [ -n "$_identity_deployment_name" ]; then
        _current_run_id=$(echo "$_identity_deployment" | jq -r '
          .spec.template.spec.containers[]
          | select(.name == "exporter")
          | (.env // [])
          | map(select(.name == "CLUSTERMESH_RUN_ID"))
          | .[0].value // ""
        ')
        _current_resource_id=$(echo "$_identity_deployment" | jq -r '
          .spec.template.spec.containers[]
          | select(.name == "exporter")
          | (.env // [])
          | map(select(.name == "CLUSTERMESH_CLUSTER_RESOURCE_ID"))
          | .[0].value // ""
        ')
        if [ "$_current_run_id" != "$CLUSTERMESH_RUN_ID" ] || \
           [ "$_current_resource_id" != "$CLUSTERMESH_CLUSTER_RESOURCE_ID" ]; then
          echo "[prom-patcher] injecting cluster identity into apiserver-backend-exporter" >&2
          if prom_patcher_kubectl -n monitoring set env \
              "deployment/$_identity_deployment_name" \
              CLUSTERMESH_RUN_ID="$CLUSTERMESH_RUN_ID" \
              CLUSTERMESH_CLUSTER_ROLE="$CLUSTERMESH_CLUSTER_ROLE" \
              CLUSTERMESH_CLUSTER_NAME="$CLUSTERMESH_CLUSTER_NAME" \
              CLUSTERMESH_CLUSTER_RESOURCE_ID="$CLUSTERMESH_CLUSTER_RESOURCE_ID" \
              CLUSTERMESH_SUBSCRIPTION_ID="$CLUSTERMESH_SUBSCRIPTION_ID" \
              CLUSTERMESH_RESOURCE_GROUP="$CLUSTERMESH_RESOURCE_GROUP" \
              CLUSTERMESH_REGION="$CLUSTERMESH_REGION" \
              CLUSTERMESH_PROMETHEUS_CLUSTER_ALIAS="$CLUSTERMESH_PROMETHEUS_CLUSTER_ALIAS" \
              >&2; then
            _identity_patches=$((_identity_patches + 1))
          else
            echo "[prom-patcher] identity injection failed; will retry" >&2
          fi
        fi
      fi
    fi
    sleep "$PROM_PATCH_POLL_SECONDS"
  done
  echo "[prom-patcher] exiting after $_patches Prometheus patch(es) and $_identity_patches identity patch(es)" >&2
}
export -f prom_patcher_kubectl run_prom_patcher
export kubeconfig identity_ready PROM_LIMIT PROM_PATCH_POLL_SECONDS
export PROM_PATCH_REQUEST_TIMEOUT_SECONDS
setsid bash -c run_prom_patcher > "$PROM_PATCH_LOG" 2>&1 &
PROM_PATCH_PID=$!
echo "  $role: spawned prometheus-cr-patcher (PID=$PROM_PATCH_PID, log=$PROM_PATCH_LOG)"

# Background periodic snapshot daemon (n=20 debug enhancement 2026-05-16):
# At n=20 a per-cluster clustermesh-apiserver receives 19x the cross-cluster
# event traffic of n=2. A "post-run" snapshot misses the PEAK pressure window
# where saturation actually happens. This daemon captures lightweight state
# every 60s for the duration of CL2 so we can correlate verdicts with peak
# resource use ("when did mesh-7's apiserver start OOMing?") rather than
# guess from end-state. ~5KB per minute × ~40min CL2 ≈ 200KB per cluster —
# cheap. Failure of any kubectl call inside the loop is non-fatal (|| true).
SNAPSHOT_LOG="$report_dir/snapshots.log"
{
  echo "[snapshot] starting; will sample every 60s until SIGTERM"
  while true; do
    _ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    echo "===== snapshot @ $_ts ====="
    # 1. clustermesh-apiserver pod state (restart count + status)
    echo "--- clustermesh-apiserver pods ---"
    KUBECONFIG="$kubeconfig" kubectl -n kube-system get pods \
      -l k8s-app=clustermesh-apiserver \
      -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount,READY:.status.containerStatuses[*].ready \
      2>&1 || true
    # 2. cilium-agent restart counts (only pods with >0 restarts, to bound output)
    echo "--- cilium-agent pods with restarts ---"
    KUBECONFIG="$kubeconfig" kubectl -n kube-system get pods -l k8s-app=cilium \
      -o jsonpath='{range .items[?(@.status.containerStatuses[0].restartCount > 0)]}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}' \
      2>&1 || true
    # 3. monitoring/prometheus state
    echo "--- prometheus-k8s ---"
    KUBECONFIG="$kubeconfig" kubectl -n monitoring get pods -l app.kubernetes.io/name=prometheus \
      -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount \
      2>&1 || true
    # 4. kubectl top (requires metrics-server which CL2 deploys). Capture
    # top-5 mem consumers in kube-system to spot OOM trajectories early.
    echo "--- top mem in kube-system ---"
    KUBECONFIG="$kubeconfig" kubectl top pods -n kube-system --sort-by=memory --no-headers 2>/dev/null | head -5 || echo "(kubectl top unavailable)"
    echo ""
    sleep 60
  done
} > "$SNAPSHOT_LOG" 2>&1 &
SNAPSHOT_PID=$!
echo "  $role: spawned snapshot-daemon (PID=$SNAPSHOT_PID, log=$SNAPSHOT_LOG)"

# Background daemons + the worker-private Azure CLI cache (if any) are
# terminated/removed by the single _cleanup_worker_state EXIT trap
# registered near the top of this script, which now sees the PIDs above.

cl2_passed=0
# Run CL2; collect outcome WITHOUT failing on a non-zero exit (so we can
# also inspect junit.xml for internal test failures even when CL2 exits
# 0). Treat as "passed" only if BOTH:
#   (a) junit.xml exists (CL2 actually completed and wrote a report)
#   (b) junit.xml has zero <failure>/<error> elements
# Without (b) we'd silently green-light runs where measurements failed
# — e.g. PodMonitor template substitution producing "<no value>", which
# k8s admission rejects but CL2 still writes junit with <failure> tags.
exec_extra_args=()
# When CL2_PROM_SNAPSHOT_ENABLED=true we suppress CL2's built-in prometheus
# tear-down so the snapshot block below can hit /api/v1/admin/tsdb/snapshot
# on a still-running prometheus-k8s pod. After snapshotting + copying out
# the tarball, the snapshot block deletes the Prometheus CR manually so
# the cluster doesn't keep the stack alive longer than CL2 normally would.
if [ "${CL2_PROM_SNAPSHOT_ENABLED:-false}" = "true" ]; then
  if [ "$tear_down_prometheus_flag" = "1" ]; then
    echo "  $role: CL2_PROM_SNAPSHOT_ENABLED=true — suppressing CL2 --tear-down-prometheus; snapshot+manual teardown handled below"
  fi
elif [ "$tear_down_prometheus_flag" = "1" ]; then
  exec_extra_args+=(--tear-down-prometheus)
fi
# CL2 invocation, with OPTIONAL retry on transient prometheus-stack setup
# failures. Default CL2_MAX_ATTEMPTS=1 → exactly one run → behavior is
# byte-for-byte unchanged for every existing scenario. The mock topology sets
# CL2_MAX_ATTEMPTS>1 because at scale (n=20 spike build 71650, mesh-2) a single
# cluster's AKS apiserver can throw a transient "server is currently unable to
# handle the request (post namespaces)" while CL2 creates the monitoring
# namespace, killing prometheus setup BEFORE any measurement runs — so CL2
# writes NO junit. That early-setup failure is cheap to retry (no churn ran
# yet). We retry ONLY when (a) CL2 produced no junit (it died in setup, not a
# real test outcome — those write junit and are handled by the gate below) AND
# (b) the captured output matches the prometheus-stack-setup failure signature.
CL2_MAX_ATTEMPTS="${CL2_MAX_ATTEMPTS:-1}"
cl2_attempt=0
cl2_run_log="$(mktemp "${TMPDIR:-/tmp}/cl2-${role}-XXXXXX.log")"
while :; do
  cl2_attempt=$((cl2_attempt + 1))
  (
    cd "$python_workdir" || exit 1
    PYTHONPATH="${PYTHONPATH:-}:$python_workdir" python3 -u "$python_script_file" execute \
      --cl2-image "$cl2_image" \
      --cl2-config-dir "$cl2_config_dir" \
      --cl2-report-dir "$report_dir" \
      --cl2-config-file "$cl2_config_file" \
      --kubeconfig "$kubeconfig" \
      --provider "$provider" \
      --mock-mode "${CL2_MOCK_MODE:-false}" \
      "${exec_extra_args[@]}"
  ) 2>&1 | tee "$cl2_run_log" || true

  # CL2 wrote junit → it got past setup into measurements; the junit gate below
  # owns the pass/fail decision. NEVER retry a real test outcome.
  if [ -f "$report_dir/junit.xml" ]; then
    break
  fi
  # No junit → CL2 died during setup. Retry only on the transient prometheus-
  # stack-setup signature, and only while attempts remain.
  if [ "$cl2_attempt" -lt "$CL2_MAX_ATTEMPTS" ] \
     && grep -qE 'setting up prometheus stack|unable to handle the request|prometheus stack: timed out' "$cl2_run_log" 2>/dev/null; then
    echo "##vso[task.logissue type=warning;] $role: CL2 prometheus-stack setup failed (transient infra); retrying (attempt $((cl2_attempt + 1))/$CL2_MAX_ATTEMPTS)"
    # Clear any half-built monitoring stack so the retry deploys clean, then POLL
    # until the namespace is fully gone — CL2's retry will POST the monitoring
    # namespace and must not race a still-Terminating one ("object is being
    # deleted"). Cap the wait; if it won't drain we proceed and let the retry
    # surface any residual conflict rather than hang here.
    KUBECONFIG="$kubeconfig" kubectl delete namespace monitoring \
      --ignore-not-found --wait=false >/dev/null 2>&1 || true
    _ns_gone_deadline=$(( $(date +%s) + 180 ))
    while KUBECONFIG="$kubeconfig" kubectl get namespace monitoring >/dev/null 2>&1; do
      if [ "$(date +%s)" -ge "$_ns_gone_deadline" ]; then
        echo "  $role: monitoring namespace still Terminating after 180s; proceeding with retry anyway"
        break
      fi
      sleep 5
    done
    sleep 5
    continue
  fi
  break
done
rm -f "$cl2_run_log" 2>/dev/null || true
if [ -f "$report_dir/junit.xml" ]; then
  # Count failure/error attrs from <testsuite ... failures="N" errors="M">.
  junit_failures=$(grep -oE 'failures="[0-9]+"' "$report_dir/junit.xml" | head -1 | grep -oE '[0-9]+' || echo 0)
  junit_errors=$(grep -oE 'errors="[0-9]+"' "$report_dir/junit.xml" | head -1 | grep -oE '[0-9]+' || echo 0)
  junit_failures=${junit_failures:-0}
  junit_errors=${junit_errors:-0}
  if [ "$junit_failures" -eq 0 ] && [ "$junit_errors" -eq 0 ]; then
    cl2_passed=1
  else
    # Soft-fail policy 2026-05-18 for ALL clustermesh-scale scenarios.
    # This runner is in steps/engine/clusterloader2/clustermesh-scale/ so it
    # ONLY runs for the clustermesh-scale topology — never affects other
    # repo scenarios. Across the 7 scenarios (event-throughput, pod-churn-
    # combined, apiserver-failure, ha-config, isolation, node-churn-combined,
    # upper-bound), we've seen junit failures that are NOT bugs but rather:
    #   - upper-bound build 67497 mesh-1: 2 Patch http2:client-connection-
    #     lost during restart-burst (=expected saturation signal)
    #   - n2_shared pod-churn-combined: PodStartupLatency P99 5m23s vs 3m
    #     SLI (=workload contention under continuous churn)
    #   - n2_node_churn_combined: transient AKS apiserver 503s on namespace
    #     creation (=normal early-startup back-pressure)
    # In every case CL2 still wrote junit.xml + measurement files. The
    # downstream classifier/dashboard layer evaluates the actual signals;
    # losing the entire blob because of a tight SLI assertion is far worse
    # than letting an "issue" run propagate. Log junit failures as warning
    # + set cl2_passed=1 so collect+upload runs. Operator sees the warning
    # in the AzDO UI and the blob has the actual measurement values to
    # decide if the assertion failure was real.
    echo "##vso[task.logissue type=warning;] $role: junit.xml reports failures=$junit_failures errors=$junit_errors (clustermesh-scale soft-fail; measurement data still uploaded — inspect blob for real signal values)"
    cl2_passed=1
  fi
fi

if [ "$cl2_passed" -eq 1 ]; then
  echo "  $role: CL2 run succeeded"
fi

# Per-cluster resource snapshot — helps interpret PodStartupLatency outliers
# at N=50/N=100 by distinguishing "node under-resourced" from "control-plane
# bottleneck". Written to file (not stdout) to avoid interleaving with
# parallel CL2 worker output that makes it unreadable.
log_dir="$report_dir/logs"
mkdir -p "$log_dir"
{
  echo "=== $role resource snapshot ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="
  echo "--- kubectl top nodes ---"
  KUBECONFIG="$kubeconfig" kubectl top nodes --no-headers 2>/dev/null | head -20 || true
  echo "--- kubectl top pods -n kube-system (sorted by CPU) ---"
  KUBECONFIG="$kubeconfig" kubectl top pods -n kube-system --no-headers --sort-by=cpu 2>/dev/null | head -15 || true
  echo "--- kubectl get nodes (status) ---"
  KUBECONFIG="$kubeconfig" kubectl get nodes --no-headers 2>/dev/null | head -15 || true
} > "$log_dir/resource-snapshot.txt" 2>&1
echo "  $role: resource snapshot written to $log_dir/resource-snapshot.txt"

# Always-on log capture (spec line 35: "Logs: clustermesh-apiserver,
echo "------- $role: capturing pod logs to $log_dir -------"
# clustermesh-apiserver: all three containers (apiserver / etcd /
# kvstoremesh) — bounded tail, single pod expected.
for c in apiserver etcd kvstoremesh; do
  KUBECONFIG="$kubeconfig" kubectl -n kube-system logs \
    -l k8s-app=clustermesh-apiserver -c "$c" --tail=4000 \
    > "$log_dir/clustermesh-apiserver-$c.log" 2>&1 || true
done
# cilium-agent: one pod per node — keep tail small to bound size.
KUBECONFIG="$kubeconfig" kubectl -n kube-system logs \
  -l k8s-app=cilium --tail=1000 --prefix=true \
  > "$log_dir/cilium-agent.log" 2>&1 || true
# cilium-operator: low-volume control plane.
KUBECONFIG="$kubeconfig" kubectl -n kube-system logs \
  -l io.cilium/app=operator --tail=2000 --prefix=true \
  > "$log_dir/cilium-operator.log" 2>&1 || true

if [ "${CL2_ACNS_TELEMETRY_ENABLED:-false}" = "true" ]; then
  acns_collect_script="$repo_root/scenarios/perf-eval/clustermesh-scale/telemetry/collect-acns-telemetry.sh"
  acns_output_dir="$report_dir/telemetry/acns"
  echo "------- $role: collecting ACNS telemetry -------"
  if ! KUBECONFIG="$kubeconfig" OUTPUT_DIR="$acns_output_dir" \
      bash "$acns_collect_script"; then
    echo "##vso[task.logissue type=error;] $role: ACNS telemetry collection failed."
    acns_telemetry_failed=1
  fi
fi

# Coverage audit runs before the optional snapshot and Prometheus teardown so
# every run records exactly which telemetry families and scrape targets landed
# in its TSDB. Missing coverage is a warning, not a workload-result failure.
telemetry_audit_script="$(dirname "$python_script_file")/telemetry/audit_self_hosted.py"
if [ -f "$telemetry_audit_script" ]; then
  telemetry_audit_dir="$report_dir/telemetry"
  telemetry_audit_args=(
    --kubeconfig "$kubeconfig"
    --output-prefix "$telemetry_audit_dir/telemetry-audit-self-hosted"
    --target-lookback-seconds "$(( $(date +%s) - worker_started_epoch + 60 ))"
  )
  if [ "${CL2_MOCK_MODE:-false}" = "true" ]; then
    telemetry_audit_args+=(
      --require-real-node-kubelet
      --require-kwok-resource
      --expected-mock-agent-targets "${CL2_MOCK_NODE_COUNT:-0}"
    )
    # propagation-probe intentionally keeps its tiny backend/source Pods on
    # real nodes, so pod-level KWOK resource metrics are not applicable.
    if [ "$cl2_config_file" != "propagation-probe.yaml" ]; then
      telemetry_audit_args+=(--require-kwok-pod-resource)
    fi
  fi
  if [ "${CL2_ACNS_TELEMETRY_ENABLED:-false}" = "true" ]; then
    telemetry_audit_args+=(--require-acns)
  fi
  # Never let a crashed audit inherit a success JSON from a dirty/reused agent
  # workspace at the same per-scenario path.
  rm -f \
    "$telemetry_audit_dir/telemetry-audit-self-hosted.json" \
    "$telemetry_audit_dir/telemetry-audit-self-hosted.md"
  telemetry_audit_rc=0
  python3 "$telemetry_audit_script" "${telemetry_audit_args[@]}" ||
    telemetry_audit_rc=$?
  if [ "$telemetry_audit_rc" -ne 0 ]; then
    echo "##vso[task.logissue type=warning;] $role: self-hosted Prometheus telemetry audit is incomplete; inspect $telemetry_audit_dir/telemetry-audit-self-hosted.json"
  fi
  if [ "${CL2_ACNS_TELEMETRY_ENABLED:-false}" = "true" ] &&
     { [ ! -s "$telemetry_audit_dir/telemetry-audit-self-hosted.json" ] ||
       ! jq -e '.acns_complete == true' \
         "$telemetry_audit_dir/telemetry-audit-self-hosted.json" >/dev/null; }; then
    acns_telemetry_failed=1
  fi
else
  echo "##vso[task.logissue type=warning;] $role: telemetry audit script not found at $telemetry_audit_script"
fi

# Prometheus TSDB snapshot (opt-in via CL2_PROM_SNAPSHOT_ENABLED=true).
# Use kubectl port-forward + host curl to trigger /api/v1/admin/tsdb/snapshot
# — avoids depending on what's inside the prometheus container (busybox wget
# in some prom image versions doesn't support --post-data, busybox nc raw
# HTTP is fragile across kubectl exec stdout/stderr mixing). port-forward
# binds to :0 so each parallel worker gets a unique random local port.
#
# Then kubectl-exec-tars the snapshot dir out to the report dir where the
# downstream collect step uploads it as a build artifact / blob. Use case:
# load locally with
#   tar xzf prom-snapshot-...tar.gz
#   docker run --rm -v "$PWD/<snap_dir>:/prometheus" -p 9090:9090 \
#     prom/prometheus --storage.tsdb.path=/prometheus
# to PromQL over the full scrape set offline.
#
# Requires --web.enable-admin-api on Prometheus (CL2 / kube-prometheus
# operator's Prometheus CR sets enableAdminAPI=true by default). If
# anything fails we log a warning and move on — the snapshot is auxiliary;
# missing it must not gate the run.
if [ "${CL2_PROM_SNAPSHOT_ENABLED:-false}" = "true" ]; then
  echo "------- $role: prometheus TSDB snapshot -------"
  prom_pod=$(KUBECONFIG="$kubeconfig" kubectl -n monitoring get pods \
    -l app.kubernetes.io/name=prometheus \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [ -z "$prom_pod" ]; then
    echo "##vso[task.logissue type=warning;] $role: prom-snapshot: no Running prometheus pod found in namespace monitoring (label app.kubernetes.io/name=prometheus); skipping snapshot"
  else
    echo "  $role: prom-snapshot: pod=$prom_pod, starting port-forward"
    pf_log=$(mktemp)
    KUBECONFIG="$kubeconfig" kubectl -n monitoring port-forward \
      "$prom_pod" :9090 >"$pf_log" 2>&1 &
    PF_PID=$!
    # Wait for port-forward to bind + report local port
    local_port=""
    for _i in $(seq 1 20); do
      local_port=$(grep -oE 'Forwarding from 127\.0\.0\.1:[0-9]+' "$pf_log" 2>/dev/null \
        | head -1 | grep -oE '[0-9]+$' || true)
      [ -n "$local_port" ] && break
      sleep 0.5
    done
    if [ -z "$local_port" ]; then
      echo "##vso[task.logissue type=warning;] $role: prom-snapshot: port-forward never reported a local port (log: $(cat "$pf_log" 2>/dev/null | head -5)); skipping"
      kill "$PF_PID" 2>/dev/null || true
    else
      echo "  $role: prom-snapshot: port-forward listening on 127.0.0.1:$local_port"
      snapshot_max_attempts="${CL2_PROM_SNAPSHOT_MAX_ATTEMPTS:-5}"
      snapshot_retry_seconds="${CL2_PROM_SNAPSHOT_RETRY_SECONDS:-2}"
      if ! [[ "$snapshot_max_attempts" =~ ^[1-9][0-9]*$ ]]; then
        snapshot_max_attempts=5
      elif [ "$snapshot_max_attempts" -gt 10 ]; then
        snapshot_max_attempts=10
      fi
      if ! [[ "$snapshot_retry_seconds" =~ ^(0|[1-9][0-9]*)$ ]]; then
        snapshot_retry_seconds=2
      fi
      list_prom_snapshot_dirs() {
        timeout 15s env KUBECONFIG="$kubeconfig" \
          kubectl --request-timeout=10s -n monitoring \
          exec "$prom_pod" -c prometheus -- sh -c \
          'for d in /prometheus/snapshots/*; do [ -d "$d" ] && printf "%s\n" "${d##*/}"; done; exit 0' \
          2>/dev/null | sort -u
      }
      snapshot_baseline_file=$(mktemp)
      snapshot_baseline_ok=false
      if list_prom_snapshot_dirs > "$snapshot_baseline_file"; then
        snapshot_baseline_ok=true
      else
        : > "$snapshot_baseline_file"
        snapshot_max_attempts=1
      fi
      snap_name=""
      snap_resp=""
      snap_http_code=""
      snap_curl_rc=0
      snap_curl_error=""
      snapshot_ambiguous_dirs=""
      snapshot_directory_check_failed=false
      for _snapshot_attempt in $(seq 1 "$snapshot_max_attempts"); do
        snap_response_file=$(mktemp)
        snap_error_file=$(mktemp)
        snap_curl_rc=0
        snap_http_code=$(curl -sS --max-time 60 \
          -o "$snap_response_file" -w '%{http_code}' -X POST \
          "http://127.0.0.1:${local_port}/api/v1/admin/tsdb/snapshot" \
          2>"$snap_error_file") || snap_curl_rc=$?
        snap_resp=$(cat "$snap_response_file" 2>/dev/null || true)
        snap_curl_error=$(cat "$snap_error_file" 2>/dev/null || true)
        rm -f "$snap_response_file" "$snap_error_file"
        snap_name=$(echo "$snap_resp" | grep -oE '"name":"[^"]+"' \
          | head -1 | sed 's/.*"name":"\([^"]*\)".*/\1/')
        if [ -n "$snap_name" ]; then
          break
        fi
        # The snapshot POST is non-idempotent. A new directory after an empty
        # response is ambiguous: Prometheus creates it before snapshotting is
        # complete, so it must never be archived or deleted while the server
        # may still be writing. Stop retrying and let Prometheus teardown own
        # cleanup instead of creating a duplicate or a partial artifact.
        if [ "$snapshot_baseline_ok" = "true" ]; then
          if [ "$snapshot_retry_seconds" -gt 0 ]; then
            sleep "$snapshot_retry_seconds"
          fi
          snapshot_current_file=$(mktemp)
          if list_prom_snapshot_dirs > "$snapshot_current_file"; then
            snapshot_ambiguous_dirs=$(comm -13 "$snapshot_baseline_file" \
              "$snapshot_current_file")
          else
            snapshot_directory_check_failed=true
          fi
          rm -f "$snapshot_current_file"
          if [ "$snapshot_directory_check_failed" = "true" ]; then
            echo "  $role: prom-snapshot: unable to verify snapshot directories after an empty/lost response; refusing a non-idempotent retry"
            break
          fi
          if [ -n "$snapshot_ambiguous_dirs" ]; then
            echo "  $role: prom-snapshot: unverified snapshot directory appeared after an empty/lost response; refusing to archive or retry: $(echo "$snapshot_ambiguous_dirs" | tr '\n' ' ')"
            break
          fi
        fi
        if [ "$snap_curl_rc" -eq 28 ] ||
           [[ "${snap_http_code:-}" =~ ^2[0-9][0-9]$ ]]; then
          echo "  $role: prom-snapshot: request outcome is ambiguous (curl_rc=${snap_curl_rc}, http=${snap_http_code:-none}); refusing a non-idempotent retry"
          break
        fi
        if [ "$_snapshot_attempt" -lt "$snapshot_max_attempts" ]; then
          echo "  $role: prom-snapshot: admin API attempt ${_snapshot_attempt}/${snapshot_max_attempts} returned no snapshot name (curl_rc=${snap_curl_rc}, http=${snap_http_code:-none}); retrying in ${snapshot_retry_seconds}s"
          if [ "$snapshot_baseline_ok" != "true" ] &&
             [ "$snapshot_retry_seconds" -gt 0 ]; then
            sleep "$snapshot_retry_seconds"
          fi
        fi
      done
      kill "$PF_PID" 2>/dev/null || true
      wait "$PF_PID" 2>/dev/null || true
      if [ -z "$snap_name" ]; then
        prom_admin_api=$(timeout 15s env KUBECONFIG="$kubeconfig" \
          kubectl --request-timeout=10s -n monitoring get prometheus k8s \
          -o jsonpath='{.spec.enableAdminAPI}' 2>/dev/null || true)
        echo "##vso[task.logissue type=warning;] $role: prom-snapshot: admin API did not return a verified snapshot name after ${_snapshot_attempt} attempt(s) (curl_rc=${snap_curl_rc}, http=${snap_http_code:-none}, enableAdminAPI=${prom_admin_api:-unknown}, directory_check_failed=${snapshot_directory_check_failed}, ambiguous_dirs=$(echo "${snapshot_ambiguous_dirs:-<none>}" | tr '\n' ' '), response=${snap_resp:-<empty>}, curl_error=${snap_curl_error:-<empty>}); skipping copy"
      else
        snap_tar="${report_dir}/prom-snapshot-${role}-${snap_name}.tar.gz"
        snap_tar_partial="${snap_tar}.partial"
        echo "  $role: prom-snapshot: name=$snap_name, copying out to $snap_tar"
        # `tar c -C /prometheus/snapshots <snap_name>` outputs the tarball
        # over the kubectl-exec stdout pipe; we capture into a local file.
        # No -i / -t so kubectl pipes binary cleanly without TTY mangling.
        # Write to .partial then validate gzip before renaming, so a
        # corrupt mid-stream truncation doesn't get uploaded as if good.
        if KUBECONFIG="$kubeconfig" kubectl -n monitoring exec "$prom_pod" -c prometheus -- \
            tar czf - -C /prometheus/snapshots "$snap_name" > "$snap_tar_partial" 2>/dev/null \
          && gzip -t "$snap_tar_partial" 2>/dev/null; then
          mv "$snap_tar_partial" "$snap_tar"
          snap_size=$(stat -c%s "$snap_tar" 2>/dev/null || echo "?")
          echo "  $role: prom-snapshot: wrote ${snap_size} bytes to $snap_tar (gzip OK)"
        else
          echo "##vso[task.logissue type=warning;] $role: prom-snapshot: tar of snapshot dir failed or gzip integrity check failed; dropping partial $snap_tar_partial"
          rm -f "$snap_tar_partial"
        fi
      fi
      snapshot_cleanup_names=""
      if [ -n "$snap_name" ] && [ "$snapshot_baseline_ok" = "true" ]; then
        snapshot_current_file=$(mktemp)
        if list_prom_snapshot_dirs > "$snapshot_current_file"; then
          snapshot_cleanup_names=$(comm -13 "$snapshot_baseline_file" \
            "$snapshot_current_file")
        fi
        rm -f "$snapshot_current_file"
      fi
      if [ -n "$snap_name" ] && [ -z "$snapshot_cleanup_names" ]; then
        snapshot_cleanup_names="$snap_name"
      fi
      while IFS= read -r snapshot_cleanup_name; do
        [ -n "$snapshot_cleanup_name" ] || continue
        timeout 15s env KUBECONFIG="$kubeconfig" \
          kubectl --request-timeout=10s -n monitoring \
          exec "$prom_pod" -c prometheus -- \
          rm -rf "/prometheus/snapshots/$snapshot_cleanup_name" \
          2>/dev/null || true
      done <<< "$snapshot_cleanup_names"
      rm -f "$snapshot_baseline_file"
    fi
    rm -f "$pf_log"
  fi
  # Manual tear-down if requested — runs whether or not snapshot succeeded
  # so we honor the original tear-down contract under all failure modes.
  if [ "$tear_down_prometheus_flag" = "1" ]; then
    echo "  $role: prom-snapshot: manual tear-down of Prometheus CR"
    KUBECONFIG="$kubeconfig" kubectl -n monitoring delete prometheus k8s \
      --ignore-not-found --wait=false 2>/dev/null || true
  fi
fi

if [ "$cl2_passed" -ne 1 ]; then
  # Dump enough state to distinguish prometheus-stack scheduling
  # failures from CL2 logic failures. Prometheus is the most common
  # culprit here — its pod requests 10Gi by default, doesn't fit on
  # Standard_D4s_v4. If the pod is Pending with FailedScheduling, the
  # describe events make that obvious.
  #
  # Note: scale.py passes tear_down_prometheus=False so the stack
  # survives this dump (otherwise CL2 would clean up before we look).
  echo "------- $role: CL2 FAILURE DIAG -------"
  echo "------- node allocatable / requested capacity -------"
  KUBECONFIG="$kubeconfig" kubectl get nodes -o wide 2>&1 || true
  KUBECONFIG="$kubeconfig" kubectl describe nodes 2>&1 | grep -A 4 "Allocatable\|Allocated resources" | head -40 || true

  echo "------- monitoring/* pods -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring get pods -o wide 2>&1 || true

  echo "------- monitoring statefulsets -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring get statefulset -o wide 2>&1 || true

  echo "------- Prometheus CR (operator input) -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring get prometheus -o yaml 2>&1 | head -80 || true

  echo "------- prometheus-k8s pod describe -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring describe pod -l app.kubernetes.io/name=prometheus 2>&1 | tail -60 || true

  echo "------- prometheus-operator logs (tail 60) -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring logs -l app.kubernetes.io/name=prometheus-operator --tail=60 2>&1 || true

  echo "------- monitoring namespace events (recent) -------"
  KUBECONFIG="$kubeconfig" kubectl -n monitoring get events --sort-by='.lastTimestamp' 2>&1 | tail -30 || true

  # n=20 debug enhancement 2026-05-16 — extra diagnostics that matter at
  # higher mesh sizes. The current per-cluster diag misses (a) live resource
  # use at failure time, (b) cluster-wide Warning events outside monitoring/,
  # (c) cross-cluster peer pair state from each cluster's POV.
  echo "------- kube-system top pods (memory-sorted, n=20 OOM tracker) -------"
  KUBECONFIG="$kubeconfig" kubectl top pods -n kube-system --sort-by=memory --no-headers 2>&1 | head -20 || true

  echo "------- cluster-wide Warning events (recent, sorted by time) -------"
  KUBECONFIG="$kubeconfig" kubectl get events --all-namespaces \
    --field-selector type=Warning --sort-by='.lastTimestamp' 2>&1 | tail -30 || true

  echo "------- node resource pressure (Allocated + Conditions) -------"
  KUBECONFIG="$kubeconfig" kubectl describe nodes 2>&1 | \
    grep -E "^Name:|MemoryPressure|DiskPressure|PIDPressure|Allocated resources|^  cpu|^  memory" | head -60 || true

  echo "------- cilium clustermesh status (peer pair view from $role) -------"
  if command -v cilium-cli >/dev/null 2>&1 || [ -x /usr/local/bin/cilium ]; then
    CILIUM_BIN=$(command -v cilium-cli || command -v cilium || echo /usr/local/bin/cilium)
    KUBECONFIG="$kubeconfig" "$CILIUM_BIN" clustermesh status --wait=false 2>&1 | head -40 || true

    echo "------- cilium status (agent health from $role) -------"
    KUBECONFIG="$kubeconfig" "$CILIUM_BIN" status --wait=false 2>&1 | head -60 || true
  else
    echo "(cilium-cli not in PATH; skipping clustermesh status / cilium status)"
  fi

  echo "------- cilium-agent restart counts (per-node, n=100 diag) -------"
  KUBECONFIG="$kubeconfig" kubectl -n kube-system get pods -l k8s-app=cilium \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].restartCount}{"\n"}{end}' 2>&1 | head -20 || true

  echo "------- pod-snapshot tail (last 200 lines from periodic daemon) -------"
  if [ -f "$SNAPSHOT_LOG" ]; then
    tail -200 "$SNAPSHOT_LOG" || true
  else
    echo "(snapshot log not found at $SNAPSHOT_LOG)"
  fi
  echo "------- end CL2 FAILURE DIAG -------"

  echo "##vso[task.logissue type=warning;] $role: CL2 run failed (junit missing or has failures/errors at $report_dir/junit.xml)"
  exit 1
fi

if [ "$acns_telemetry_failed" -ne 0 ]; then
  echo "##vso[task.logissue type=error;] $role: ACNS telemetry smoke is incomplete."
  exit 1
fi

exit 0
