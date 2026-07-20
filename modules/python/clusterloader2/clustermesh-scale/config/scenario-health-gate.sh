#!/usr/bin/env bash
set -uo pipefail

usage() {
  cat <<'EOF'
Usage: scenario-health-gate.sh [options]

Options override the corresponding environment variables:
  --clusters FILE              CLUSTERMESH_CLUSTERS_JSON
  --scenario NAME              SCENARIO_NAME
  --expected-mock-count N      EXPECTED_MOCK_COUNT (0 disables mock checks)
  --expected-remote-count N    EXPECTED_REMOTE_COUNT
  --timeout-seconds N          HEALTH_GATE_TIMEOUT_SECONDS
  --cycle-timeout-seconds N    HEALTH_GATE_CYCLE_TIMEOUT_SECONDS
  --quiet-window-seconds N     HEALTH_GATE_QUIET_WINDOW_SECONDS
  --poll-interval-seconds N    HEALTH_GATE_POLL_INTERVAL_SECONDS
  --concurrency N              HEALTH_GATE_CONCURRENCY
  --summary-file FILE          HEALTH_GATE_SUMMARY_FILE
EOF
}

clusters_json="${CLUSTERMESH_CLUSTERS_JSON:-}"
scenario="${SCENARIO_NAME:-}"
expected_mock_count="${EXPECTED_MOCK_COUNT:-0}"
expected_remote_count="${EXPECTED_REMOTE_COUNT:-}"
timeout_seconds="${HEALTH_GATE_TIMEOUT_SECONDS:-600}"
cycle_timeout_seconds="${HEALTH_GATE_CYCLE_TIMEOUT_SECONDS:-180}"
quiet_window_seconds="${HEALTH_GATE_QUIET_WINDOW_SECONDS:-60}"
poll_interval_seconds="${HEALTH_GATE_POLL_INTERVAL_SECONDS:-10}"
concurrency="${HEALTH_GATE_CONCURRENCY:-8}"
kubectl_request_timeout_seconds="${HEALTH_GATE_KUBECTL_REQUEST_TIMEOUT_SECONDS:-15}"
summary_file="${HEALTH_GATE_SUMMARY_FILE:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --clusters) clusters_json="${2:?missing value for --clusters}"; shift 2 ;;
    --scenario) scenario="${2:?missing value for --scenario}"; shift 2 ;;
    --expected-mock-count)
      expected_mock_count="${2:?missing value for --expected-mock-count}"
      shift 2
      ;;
    --expected-remote-count)
      expected_remote_count="${2:?missing value for --expected-remote-count}"
      shift 2
      ;;
    --timeout-seconds)
      timeout_seconds="${2:?missing value for --timeout-seconds}"
      shift 2
      ;;
    --cycle-timeout-seconds)
      cycle_timeout_seconds="${2:?missing value for --cycle-timeout-seconds}"
      shift 2
      ;;
    --quiet-window-seconds)
      quiet_window_seconds="${2:?missing value for --quiet-window-seconds}"
      shift 2
      ;;
    --poll-interval-seconds)
      poll_interval_seconds="${2:?missing value for --poll-interval-seconds}"
      shift 2
      ;;
    --concurrency)
      concurrency="${2:?missing value for --concurrency}"
      shift 2
      ;;
    --summary-file)
      summary_file="${2:?missing value for --summary-file}"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$clusters_json" ] || [ ! -s "$clusters_json" ]; then
  echo "Cluster inventory JSON is required and must be nonempty: ${clusters_json:-unset}" >&2
  exit 2
fi
if [ -z "$scenario" ]; then
  echo "Scenario name is required." >&2
  exit 2
fi
if ! jq -e '
    type == "array" and length > 0 and
    all(.[]; (.role | type == "string" and length > 0) and
             (.name | type == "string" and length > 0) and
             (.kubeconfig | type == "string" and length > 0))
  ' "$clusters_json" >/dev/null 2>&1; then
  echo "Cluster inventory must be a nonempty array with role, name, and kubeconfig." >&2
  exit 2
fi

cluster_count=$(jq 'length' "$clusters_json")
if [ -z "$expected_remote_count" ]; then
  expected_remote_count=$((cluster_count - 1))
fi
for value_name in \
  expected_mock_count expected_remote_count timeout_seconds cycle_timeout_seconds \
  quiet_window_seconds poll_interval_seconds concurrency \
  kubectl_request_timeout_seconds; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "$value_name must be a nonnegative integer, got '$value'." >&2
    exit 2
  fi
done
if [ "$timeout_seconds" -eq 0 ] ||
   [ "$cycle_timeout_seconds" -eq 0 ] ||
   [ "$poll_interval_seconds" -eq 0 ] ||
   [ "$concurrency" -eq 0 ] ||
   [ "$kubectl_request_timeout_seconds" -eq 0 ]; then
  echo "timeout_seconds, cycle_timeout_seconds, poll_interval_seconds, concurrency, and kubectl_request_timeout_seconds must be greater than zero." >&2
  exit 2
fi
if ! command -v timeout >/dev/null 2>&1; then
  echo "coreutils timeout is required for bounded kubectl observations." >&2
  exit 2
fi

if [ -z "$summary_file" ]; then
  safe_scenario=$(printf '%s' "$scenario" | sed -E 's/[^a-zA-Z0-9_.-]+/_/g')
  summary_file="scenario-health-gate-${safe_scenario}.json"
fi
mkdir -p "$(dirname "$summary_file")"
state_dir="${summary_file}.state.$$"
mkdir -p "$state_dir"
trap 'rm -rf "$state_dir"' EXIT

K_OUT=""
K_ERROR=""
active_cycle_deadline=0
kube() {
  local kubeconfig="$1"
  local context="$2"
  shift 2
  local output rc now remaining request_timeout
  now=$(date +%s)
  remaining=$((active_cycle_deadline - now))
  if [ "$remaining" -le 0 ]; then
    K_OUT=""
    K_ERROR="observation cycle deadline exhausted before kubectl invocation"
    return 1
  fi
  request_timeout="$kubectl_request_timeout_seconds"
  if [ "$request_timeout" -gt "$remaining" ]; then
    request_timeout="$remaining"
  fi

  if output=$(KUBECONFIG="$kubeconfig" timeout --signal=KILL "${remaining}s" \
      kubectl --context "$context" --request-timeout="${request_timeout}s" \
      "$@" 2>&1); then
    K_OUT="$output"
    K_ERROR=""
    return 0
  else
    rc=$?
  fi
  K_OUT=""
  output=$(printf '%s' "$output" | tr '\n' ' ' | cut -c1-500)
  if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
    K_ERROR="kubectl timed out after ${remaining}s at the observation cycle deadline${output:+: $output}"
  else
    K_ERROR="$output"
  fi
  return 1
}

is_absent_resource_error() {
  grep -qiE \
    '(the server (could not find|doesn.t have) (the requested resource|a resource type)|not found)' \
    <<<"$1"
}

append_failure() {
  jq -c --arg failure "$2" '. + [$failure]' <<<"$1"
}

line_count() {
  awk 'NF {count++} END {print count + 0}'
}

observe_cluster() {
  local cluster="$1"
  local role name kubeconfig context observed_at
  role=$(jq -r '.role' <<<"$cluster")
  name=$(jq -r '.name' <<<"$cluster")
  kubeconfig=$(jq -r '.kubeconfig' <<<"$cluster")
  context=$(jq -r '.context // .name' <<<"$cluster")
  observed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  local failures='[]'
  local namespace_names='[]' namespace_count=0
  local cnl_count=0 cnm_count=0
  local cep_total=0 stale_cep_count=0
  local prometheus_k8s_count=0 monitoring_resource_count=0
  local monitoring_resources='[]'
  local cilium_desired=-1 cilium_ready=-1
  local mock_node_count=0 mock_ready_node_count=0
  local mock_agent_count=0 mock_running_agent_count=0
  local remote_ready=-1 remote_total=-1
  local identity_count=0 global_service_count=0
  local endpoint_namespaces=""

  if kube "$kubeconfig" "$context" get namespaces -o name; then
    namespace_names=$(sed -n 's#^namespace/##p' <<<"$K_OUT" \
      | awk '/^clustermesh-/ {print}' \
      | jq -Rsc 'split("\n") | map(select(length > 0))')
    namespace_count=$(jq 'length' <<<"$namespace_names")
    if [ "$namespace_count" -gt 0 ]; then
      failures=$(append_failure "$failures" \
        "scenario namespaces remain: $(jq -r 'join(",")' <<<"$namespace_names")")
    fi
  else
    failures=$(append_failure "$failures" "get namespaces failed: $K_ERROR")
  fi

  if kube "$kubeconfig" "$context" \
      get containernetworklogs.acn.azure.com -o name; then
    cnl_count=$(awk '
      /^containernetworklog(\.acn\.azure\.com)?\// {count++}
      END {print count + 0}
    ' <<<"$K_OUT")
    if [ "$cnl_count" -gt 0 ]; then
      failures=$(append_failure "$failures" \
        "$cnl_count ContainerNetworkLog resource(s) remain")
    fi
  elif ! is_absent_resource_error "$K_ERROR"; then
    failures=$(append_failure "$failures" \
      "get ContainerNetworkLogs failed: $K_ERROR")
  fi

  if kube "$kubeconfig" "$context" \
      get containernetworkmetrics.acn.azure.com -o name; then
    cnm_count=$(awk '
      /^containernetworkmetric(\.acn\.azure\.com)?\// {count++}
      END {print count + 0}
    ' <<<"$K_OUT")
    if [ "$cnm_count" -gt 0 ]; then
      failures=$(append_failure "$failures" \
        "$cnm_count ContainerNetworkMetric resource(s) remain")
    fi
  elif ! is_absent_resource_error "$K_ERROR"; then
    failures=$(append_failure "$failures" \
      "get ContainerNetworkMetrics failed: $K_ERROR")
  fi

  if kube "$kubeconfig" "$context" get ciliumendpoints.cilium.io -A \
      -o custom-columns=NAMESPACE:.metadata.namespace --no-headers; then
    endpoint_namespaces=$(awk \
      '/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/ {print}' <<<"$K_OUT")
    cep_total=$(line_count <<<"$endpoint_namespaces")
    stale_cep_count=$(awk '/^clustermesh-/ {count++} END {print count + 0}' \
      <<<"$endpoint_namespaces")
    if [ "$stale_cep_count" -gt 0 ]; then
      failures=$(append_failure "$failures" \
        "$stale_cep_count CiliumEndpoint resource(s) remain in clustermesh-* namespaces")
    fi
  else
    failures=$(append_failure "$failures" "get CiliumEndpoints failed: $K_ERROR")
  fi

  local monitoring_types="" resource_arg
  resource_arg="all,configmaps,secrets,serviceaccounts,persistentvolumeclaims,roles.rbac.authorization.k8s.io,rolebindings.rbac.authorization.k8s.io"
  if kube "$kubeconfig" "$context" api-resources \
      --api-group=monitoring.coreos.com --verbs=list --namespaced=true -o name; then
    monitoring_types=$(awk 'NF' <<<"$K_OUT")
    while IFS= read -r resource_type; do
      [ -n "$resource_type" ] && resource_arg="${resource_arg},${resource_type}"
    done <<<"$monitoring_types"
    if kube "$kubeconfig" "$context" -n monitoring get "$resource_arg" -o json; then
      if jq -e '.items | type == "array"' <<<"$K_OUT" >/dev/null 2>&1; then
        monitoring_resources=$(jq -c '
          [
            "clustermesh-apiserver",
            "hubble-metrics",
            "coredns",
            "kvstoremesh-standalone",
            "mock-cilium-agent",
            "apiserver-backend-exporter"
          ] as $prefixes
          | [.items[]
           | .metadata.name as $name
           | select(any($prefixes[];
               . as $prefix | $name | startswith($prefix)))
           | "\(.kind)/\(.metadata.name)"] | sort
        ' <<<"$K_OUT")
        prometheus_k8s_count=$(jq '
          [.items[]
           | select(.kind == "Prometheus" and .metadata.name == "k8s")]
          | length
        ' <<<"$K_OUT")
      else
        failures=$(append_failure "$failures" \
          "monitoring resource response was not a Kubernetes List")
      fi
    elif ! is_absent_resource_error "$K_ERROR"; then
      failures=$(append_failure "$failures" \
        "get monitoring resources failed: $K_ERROR")
    fi
  else
    failures=$(append_failure "$failures" \
      "discover monitoring resources failed: $K_ERROR")
  fi

  if kube "$kubeconfig" "$context" get \
      clusterroles.rbac.authorization.k8s.io,clusterrolebindings.rbac.authorization.k8s.io \
      -o json; then
    if jq -e '.items | type == "array"' <<<"$K_OUT" >/dev/null 2>&1; then
      exporter_rbac=$(jq -c '
        [.items[]
         | select(.metadata.name | startswith("apiserver-backend-exporter"))
         | "\(.kind)/\(.metadata.name)"] | sort
      ' <<<"$K_OUT")
      monitoring_resources=$(jq -cn \
        --argjson namespaced "$monitoring_resources" \
        --argjson cluster_rbac "$exporter_rbac" \
        '$namespaced + $cluster_rbac | unique | sort')
    else
      failures=$(append_failure "$failures" \
        "exporter RBAC response was not a Kubernetes List")
    fi
  else
    failures=$(append_failure "$failures" \
      "get exporter ClusterRole/ClusterRoleBinding resources failed: $K_ERROR")
  fi

  monitoring_resource_count=$(jq 'length' <<<"$monitoring_resources")
  if [ "$prometheus_k8s_count" -gt 0 ]; then
    failures=$(append_failure "$failures" \
      "$prometheus_k8s_count Prometheus/k8s resource(s) remain")
  fi
  if [ "$monitoring_resource_count" -gt 0 ]; then
    failures=$(append_failure "$failures" \
      "scenario-owned monitoring resources remain: $(jq -r '.[0:20] | join(",")' <<<"$monitoring_resources")")
  fi

  if kube "$kubeconfig" "$context" -n kube-system get daemonset cilium -o json; then
    if jq -e 'type == "object"' <<<"$K_OUT" >/dev/null 2>&1; then
      cilium_desired=$(jq -r '.status.desiredNumberScheduled // -1' <<<"$K_OUT")
      cilium_ready=$(jq -r '.status.numberReady // 0' <<<"$K_OUT")
      if [ "$cilium_desired" -le 0 ] ||
         [ "$cilium_desired" -ne "$cilium_ready" ]; then
        failures=$(append_failure "$failures" \
          "Cilium DaemonSet desired/ready is ${cilium_desired}/${cilium_ready}")
      fi
    else
      failures=$(append_failure "$failures" \
        "Cilium DaemonSet response was not a Kubernetes object")
    fi
  else
    failures=$(append_failure "$failures" "get Cilium DaemonSet failed: $K_ERROR")
  fi

  if [ "$expected_mock_count" -gt 0 ]; then
    if kube "$kubeconfig" "$context" get nodes -l type=kwok -o json; then
      if jq -e '.items | type == "array"' <<<"$K_OUT" >/dev/null 2>&1; then
        mock_node_count=$(jq '.items | length' <<<"$K_OUT")
        mock_ready_node_count=$(jq '
          [.items[]
           | select(any(.status.conditions[]?;
               .type == "Ready" and .status == "True"))]
          | length
        ' <<<"$K_OUT")
        if [ "$mock_node_count" -ne "$expected_mock_count" ] ||
           [ "$mock_ready_node_count" -ne "$expected_mock_count" ]; then
          failures=$(append_failure "$failures" \
            "KWOK nodes expected/present/Ready=${expected_mock_count}/${mock_node_count}/${mock_ready_node_count}")
        fi
      else
        failures=$(append_failure "$failures" \
          "KWOK node response was not a Kubernetes List")
      fi
    else
      failures=$(append_failure "$failures" "get KWOK nodes failed: $K_ERROR")
    fi

    if kube "$kubeconfig" "$context" -n mock-clustermesh get pods \
        -l app=mock-cilium-agent -o json; then
      if jq -e '.items | type == "array"' <<<"$K_OUT" >/dev/null 2>&1; then
        mock_agent_count=$(jq '.items | length' <<<"$K_OUT")
        mock_running_agent_count=$(jq \
          '[.items[] | select(.status.phase == "Running")] | length' <<<"$K_OUT")
        if [ "$mock_agent_count" -ne "$expected_mock_count" ] ||
           [ "$mock_running_agent_count" -ne "$expected_mock_count" ]; then
          failures=$(append_failure "$failures" \
            "mock Cilium agents expected/present/Running=${expected_mock_count}/${mock_agent_count}/${mock_running_agent_count}")
        fi
      else
        failures=$(append_failure "$failures" \
          "mock Cilium agent response was not a Kubernetes List")
      fi
    else
      failures=$(append_failure "$failures" \
        "get mock Cilium agents failed: $K_ERROR")
    fi
  fi

  if kube "$kubeconfig" "$context" -n kube-system exec ds/cilium \
      -c cilium-agent -- cilium-dbg status; then
    remote_status=$(sed -nE \
      's/.*ClusterMesh:[[:space:]]+([0-9]+)\/([0-9]+) remote clusters ready.*/\1 \2/p' \
      <<<"$K_OUT" | head -1)
    if read -r remote_ready remote_total <<<"$remote_status" &&
       [[ "$remote_ready" =~ ^[0-9]+$ ]] &&
       [[ "$remote_total" =~ ^[0-9]+$ ]]; then
      if [ "$remote_ready" -ne "$expected_remote_count" ] ||
         [ "$remote_total" -ne "$expected_remote_count" ]; then
        failures=$(append_failure "$failures" \
          "ClusterMesh remote ready/total expected=${expected_remote_count}, observed=${remote_ready}/${remote_total}")
      fi
    else
      remote_ready=-1
      remote_total=-1
      failures=$(append_failure "$failures" \
        "cilium-dbg status did not report ClusterMesh remote readiness")
    fi
  else
    failures=$(append_failure "$failures" "cilium-dbg status failed: $K_ERROR")
  fi

  if kube "$kubeconfig" "$context" get ciliumidentities.cilium.io -o name; then
    identity_count=$(awk '
      /^ciliumidentit(y|ies)(\.cilium\.io)?\// {count++}
      END {print count + 0}
    ' <<<"$K_OUT")
  else
    failures=$(append_failure "$failures" "get CiliumIdentities failed: $K_ERROR")
  fi

  if kube "$kubeconfig" "$context" get services -A -o json; then
    if jq -e '.items | type == "array"' <<<"$K_OUT" >/dev/null 2>&1; then
      global_service_count=$(jq '
        [.items[]
         | select(
             (.metadata.annotations["service.cilium.io/global"] // "") == "true" or
             (.metadata.annotations["io.cilium/global-service"] // "") == "true" or
             (.metadata.labels["service.cilium.io/global"] // "") == "true" or
             (.metadata.labels["io.cilium/global-service"] // "") == "true"
           )]
        | length
      ' <<<"$K_OUT")
    else
      failures=$(append_failure "$failures" \
        "Service response was not a Kubernetes List")
    fi
  else
    failures=$(append_failure "$failures" "get Services failed: $K_ERROR")
  fi

  local healthy fingerprint
  healthy=$(jq -n --argjson failures "$failures" '$failures | length == 0')
  fingerprint="cep=${cep_total};identity=${identity_count};global_service=${global_service_count}"

  jq -cn \
    --arg role "$role" \
    --arg name "$name" \
    --arg context "$context" \
    --arg observed_at "$observed_at" \
    --arg fingerprint "$fingerprint" \
    --argjson healthy "$healthy" \
    --argjson failures "$failures" \
    --argjson namespace_names "$namespace_names" \
    --argjson namespace_count "$namespace_count" \
    --argjson cnl_count "$cnl_count" \
    --argjson cnm_count "$cnm_count" \
    --argjson cep_total "$cep_total" \
    --argjson stale_cep_count "$stale_cep_count" \
    --argjson prometheus_k8s_count "$prometheus_k8s_count" \
    --argjson monitoring_resource_count "$monitoring_resource_count" \
    --argjson monitoring_resources "$monitoring_resources" \
    --argjson cilium_desired "$cilium_desired" \
    --argjson cilium_ready "$cilium_ready" \
    --argjson mock_enabled "$([ "$expected_mock_count" -gt 0 ] && echo true || echo false)" \
    --argjson mock_expected "$expected_mock_count" \
    --argjson mock_node_count "$mock_node_count" \
    --argjson mock_ready_node_count "$mock_ready_node_count" \
    --argjson mock_agent_count "$mock_agent_count" \
    --argjson mock_running_agent_count "$mock_running_agent_count" \
    --argjson remote_expected "$expected_remote_count" \
    --argjson remote_ready "$remote_ready" \
    --argjson remote_total "$remote_total" \
    --argjson identity_count "$identity_count" \
    --argjson global_service_count "$global_service_count" \
    '{
      role: $role,
      name: $name,
      context: $context,
      observed_at: $observed_at,
      healthy: $healthy,
      failures: $failures,
      cleanup: {
        scenario_namespaces: $namespace_names,
        scenario_namespace_count: $namespace_count,
        container_network_log_count: $cnl_count,
        container_network_metric_count: $cnm_count,
        cilium_endpoint_total: $cep_total,
        stale_cilium_endpoint_count: $stale_cep_count,
        prometheus_k8s_count: $prometheus_k8s_count,
        monitoring_resource_count: $monitoring_resource_count,
        monitoring_resources: $monitoring_resources,
        scenario_monitoring_resource_count: $monitoring_resource_count,
        scenario_monitoring_resources: $monitoring_resources
      },
      cilium_daemonset: {
        desired: $cilium_desired,
        ready: $cilium_ready
      },
      mock: {
        enabled: $mock_enabled,
        expected: $mock_expected,
        nodes: $mock_node_count,
        ready_nodes: $mock_ready_node_count,
        agents: $mock_agent_count,
        running_agents: $mock_running_agent_count
      },
      clustermesh: {
        expected_remote: $remote_expected,
        ready_remote: $remote_ready,
        total_remote: $remote_total
      },
      fingerprint: {
        value: $fingerprint,
        cilium_endpoints: $cep_total,
        cilium_identities: $identity_count,
        global_services: $global_service_count
      }
    }'
}

write_failed_observation() {
  local cluster="$1"
  local output_file="$2"
  local failure="$3"
  jq -cn \
    --arg role "$(jq -r '.role' <<<"$cluster")" \
    --arg name "$(jq -r '.name' <<<"$cluster")" \
    --arg observed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg failure "$failure" \
    '{
      role: $role,
      name: $name,
      observed_at: $observed_at,
      healthy: false,
      failures: [$failure],
      fingerprint: {value: "observation-failed"}
    }' > "$output_file"
}

collect_observations() {
  local index=0 cluster output_file pid
  local -a pids=()
  rm -f "$state_dir"/observation-*.json

  while IFS= read -r cluster; do
    output_file=$(printf '%s/observation-%06d.json' "$state_dir" "$index")
    if [ "$(date +%s)" -ge "$active_cycle_deadline" ]; then
      write_failed_observation "$cluster" "$output_file" \
        "observation cycle deadline exhausted before cluster collection"
      index=$((index + 1))
      continue
    fi
    (
      if ! observe_cluster "$cluster" > "$output_file"; then
        write_failed_observation "$cluster" "$output_file" \
          "health observation process failed"
      fi
    ) &
    pids+=("$!")
    index=$((index + 1))

    if [ "${#pids[@]}" -ge "$concurrency" ]; then
      wait "${pids[0]}" || true
      pids=("${pids[@]:1}")
    fi
  done < <(jq -c '.[]' "$clusters_json")

  for pid in "${pids[@]}"; do
    wait "$pid" || true
  done

  jq -sc '.' "$state_dir"/observation-*.json
}

started_epoch=$(date +%s)
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
deadline=$((started_epoch + timeout_seconds))
stable_since=""
stable_fingerprints='{}'
last_observations='[]'

write_summary() {
  local success="$1"
  local completed_epoch completed_at stable_seconds partial
  completed_epoch=$(date +%s)
  completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  stable_seconds=0
  if [ -n "$stable_since" ]; then
    stable_seconds=$((completed_epoch - stable_since))
  fi
  partial="${summary_file}.partial"
  jq -n \
    --argjson success "$success" \
    --arg started_at "$started_at" \
    --arg completed_at "$completed_at" \
    --arg scenario "$scenario" \
    --argjson timeout_seconds "$timeout_seconds" \
    --argjson cycle_timeout_seconds "$cycle_timeout_seconds" \
    --argjson quiet_window_seconds "$quiet_window_seconds" \
    --argjson poll_interval_seconds "$poll_interval_seconds" \
    --argjson concurrency "$concurrency" \
    --argjson kubectl_request_timeout_seconds "$kubectl_request_timeout_seconds" \
    --argjson expected_mock_count "$expected_mock_count" \
    --argjson expected_remote_count "$expected_remote_count" \
    --argjson stable_seconds "$stable_seconds" \
    --argjson clusters "$last_observations" \
    '{
      schema_version: 1,
      success: $success,
      started_at: $started_at,
      completed_at: $completed_at,
      scenario: $scenario,
      timeout_seconds: $timeout_seconds,
      cycle_timeout_seconds: $cycle_timeout_seconds,
      quiet_window_seconds: $quiet_window_seconds,
      poll_interval_seconds: $poll_interval_seconds,
      concurrency: $concurrency,
      kubectl_request_timeout_seconds: $kubectl_request_timeout_seconds,
      expected_mock_count: $expected_mock_count,
      expected_remote_count: $expected_remote_count,
      stable_seconds: $stable_seconds,
      clusters: $clusters
    }' > "$partial" &&
    mv "$partial" "$summary_file"
}

echo "Waiting for post-${scenario} ClusterMesh health across ${cluster_count} cluster(s): timeout=${timeout_seconds}s cycle=${cycle_timeout_seconds}s quiet=${quiet_window_seconds}s poll=${poll_interval_seconds}s concurrency=${concurrency}"
while true; do
  now=$(date +%s)
  if [ "$now" -ge "$deadline" ]; then
    write_summary false
    echo "ClusterMesh scenario health gate timed out after ${timeout_seconds}s before starting another observation cycle; summary: $summary_file" >&2
    exit 1
  fi
  remaining=$((deadline - now))
  cycle_budget="$cycle_timeout_seconds"
  if [ "$cycle_budget" -gt "$remaining" ]; then
    cycle_budget="$remaining"
  fi
  active_cycle_deadline=$((now + cycle_budget))
  observations=$(collect_observations)
  last_observations="$observations"

  unhealthy_count=$(jq '[.[] | select(.healthy | not)] | length' \
    <<<"$observations")
  fingerprints=$(jq -c \
    'map({key: .role, value: .fingerprint.value}) | from_entries' \
    <<<"$observations")

  if [ "$unhealthy_count" -eq 0 ]; then
    if [ -z "$stable_since" ] ||
       [ "$fingerprints" != "$stable_fingerprints" ]; then
      if [ -n "$stable_since" ]; then
        echo "Health fingerprint changed; resetting quiet window: ${stable_fingerprints} -> ${fingerprints}" >&2
      else
        echo "All clusters healthy; starting ${quiet_window_seconds}s quiet window."
      fi
      stable_since="$now"
      stable_fingerprints="$fingerprints"
    fi
    stable_seconds=$((now - stable_since))
    if [ "$stable_seconds" -ge "$quiet_window_seconds" ]; then
      write_summary true
      echo "ClusterMesh scenario health gate passed after ${stable_seconds}s stable: $summary_file"
      exit 0
    fi
    echo "All clusters healthy and stable for ${stable_seconds}/${quiet_window_seconds}s."
  else
    stable_since=""
    stable_fingerprints='{}'
    jq -r '
      .[] | select(.healthy | not)
      | "\(.role) (\(.name)): \(.failures | join("; "))"
    ' <<<"$observations" >&2
  fi

  now=$(date +%s)
  if [ "$now" -ge "$deadline" ]; then
    write_summary false
    echo "ClusterMesh scenario health gate timed out after ${timeout_seconds}s; summary: $summary_file" >&2
    exit 1
  fi
  sleep "$poll_interval_seconds"
done
