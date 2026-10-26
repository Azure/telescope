#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || ! $2 =~ ^(250|500|1000)$ ]]; then
    echo "##[error]Usage: $0 <kubeconfig> <250|500|1000 nodes per worker pool>" >&2
    exit 2
fi
kubeconfig=$1
nodes_per_pool=$2
for dependency in kubectl jq timeout; do
    if ! command -v "$dependency" >/dev/null; then
        echo "##[error]Missing required command: $dependency" >&2
        exit 2
    fi
done
if [[ ! -r "$kubeconfig" ]]; then
    echo "##[error]Kubeconfig is not readable: $kubeconfig" >&2
    exit 2
fi
timeout_seconds=600
poll_interval_seconds=60
deadline=$((SECONDS + timeout_seconds))
nodes_file=$(mktemp)
trap 'rm -f "$nodes_file"' EXIT
trap 'echo "##[error]Node validation interrupted" >&2; exit 130' INT
trap 'echo "##[error]Node validation terminated" >&2; exit 143' TERM

while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    if (( remaining <= 0 )); then
        break
    fi
    request_timeout=$((remaining < 30 ? remaining : 30))
    if timeout "${request_timeout}s" kubectl --kubeconfig "$kubeconfig" \
        --request-timeout="${request_timeout}s" get nodes -o json \
        > "$nodes_file"; then
        if ! summary=$(jq -cse --argjson count "$nodes_per_pool" '
            if length == 1 then .[0] else error("Expected one node-list response") end
            | if (
            (.kind == "NodeList" or .kind == "List") and (.items | type == "array") and
            all(.items[];
              .kind == "Node" and
              (.metadata.name | type == "string") and
              (.status.conditions == null or (.status.conditions | type == "array")) and
              (.spec.taints == null or (.spec.taints | type == "array")) and
              all(.spec.taints[]?;
                (.key | type == "string") and
                (.effect == "NoSchedule" or .effect == "PreferNoSchedule" or .effect == "NoExecute")))
            ) then . else error("Malformed node-list response") end
            | [.items[] | {
              pool: (.metadata.labels.agentpool //
                     .metadata.labels["kubernetes.azure.com/agentpool"] // "unknown"),
              ready: any(.status.conditions[]?; .type == "Ready" and .status == "True"),
              taints: (.spec.taints // [])
            }] as $nodes
            | {systempool: 2, workerpool0: $count, workerpool1: $count} as $expected
            | [($expected | keys[]), $nodes[].pool] | unique
            | map(. as $pool | [$nodes[] | select(.pool == $pool)] as $members
              | {pool: $pool, expected: ($expected[$pool] // 0),
                 total: ($members | length),
                 ready: ([$members[] | select(.ready)] | length),
                 noSchedule: ([$members[] |
                   select(any(.taints[]; .effect == "NoSchedule"))] | length),
                 taints: ([$members[].taints[]] | group_by([.key, .value, .effect])
                   | map({key: .[0].key, value: (.[0].value // ""),
                          effect: .[0].effect, count: length}))})
            | {pools: ., passed: all(.[];
                .expected > 0 and .total == .expected and
                .ready == .expected and .noSchedule == 0)}
        ' "$nodes_file"); then
            echo "##[error]Could not validate or summarize node-list response" >&2
            exit 1
        fi
        jq -nc --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson summary "$summary" \
            '{time: $time, summary: $summary}'
        if jq -e '.passed == true' <<< "$summary" >/dev/null && (( SECONDS < deadline )); then
            echo "Node validation passed: all expected nodes are Ready and have no NoSchedule taints"
            exit 0
        fi
    else
        echo "##[warning]Node-list request failed; retrying within the verification deadline" >&2
        jq -nc --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            '{time: $time, error: "Node-list request failed"}'
    fi
    remaining=$((deadline - SECONDS))
    if (( remaining > 0 )); then
        sleep "$((remaining < poll_interval_seconds ? remaining : poll_interval_seconds))"
    fi
done
echo "##[error]Timed out after $timeout_seconds seconds without confirming exact node counts, readiness and taint clearance" >&2
exit 1
