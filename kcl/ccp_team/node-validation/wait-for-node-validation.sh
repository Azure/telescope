#!/usr/bin/env bash
set -euo pipefail

parse_expected_pools() {
    jq -cn --args '
        reduce $ARGS.positional[] as $pair ({};
            if ($pair | test("^[A-Za-z0-9]([A-Za-z0-9_.-]*[A-Za-z0-9])?:[1-9][0-9]*$")) then
                ($pair | split(":")) as $parts
                | if has($parts[0]) then
                    error("Duplicate pool name: \($parts[0])")
                  else .[$parts[0]] = ($parts[1] | tonumber)
                  end
            else error("Expected pool_name:positive_count, got: \($pair)")
            end)
    ' -- "$@"
}

fetch_node_summary() {
    local kubeconfig=$1 request_timeout=$2 expected_pools=$3
    local statuses
    if timeout "${request_timeout}s" kubectl --kubeconfig "$kubeconfig" \
        --request-timeout="${request_timeout}s" get nodes -o json \
        | jq -cse --argjson expected "$expected_pools" '
            def node_array:
                if length == 1 then .[0]
                else error("Expected one node-list response") end
                | if (.items | type) == "array" then .items
                  else error("Expected a node array") end;

            def pool_name:
                .metadata.labels
                | if . == null or type == "object" then .
                  else error("Node labels must be an object") end
                | (.agentpool // .["kubernetes.azure.com/agentpool"])
                | if . == null or type == "string" then .
                  else error("Node pool label must be a string") end;

            def node_taints:
                if (.spec | type) == "object" then .
                else error("Selected node spec must be an object") end
                | if (.spec.taints == null or (.spec.taints | type) == "array") and
                     all(.spec.taints[]?;
                         (.key | type) == "string" and
                         (.effect == "NoSchedule" or .effect == "PreferNoSchedule" or .effect == "NoExecute"))
                  then (.spec.taints // [])
                  else error("Malformed selected-node taints") end;

            def summarize_pool($nodes):
                . as $pool
                | [$nodes[] | select(.pool == $pool)] as $members
                | {
                    pool: $pool,
                    expected: $expected[$pool],
                    total: ($members | length),
                    noSchedule: ([$members[] |
                        select(.noScheduleTaints | length > 0)] | length),
                    taints: ([$members[].noScheduleTaints[]]
                        | group_by(.key)
                        | map({
                            key: .[0].key,
                            count: length
                        }))
                };

            node_array
            | [.[]
                | pool_name as $pool
                | select($pool != null)
                | select($expected | has($pool))
                | {
                    pool: $pool,
                    noScheduleTaints: (node_taints | map(select(.effect == "NoSchedule")))
                }] as $nodes
            | ($expected | keys)
            | map(summarize_pool($nodes))
            | {
                pools: .,
                passed: all(.[];
                    .total == .expected and .noSchedule == 0)
            }
        '; then
        return 0
    else
        statuses=("${PIPESTATUS[@]}")
    fi
    # Prioritize fetch errors, except SIGPIPE (141), which jq failure can cause.
    if (( statuses[0] != 0 && statuses[0] != 141 )); then
        return 1
    fi
    if (( statuses[1] != 0 )); then
        echo "##[error]Could not validate or summarize node-list response" >&2
        return 2
    fi
    return 1
}

finish_validation() {
    local exit_code=$?
    trap - EXIT
    echo "NODE_VALIDATION_END $(date -u +%Y-%m-%dT%H:%M:%SZ) exit_code=$exit_code"
    exit "$exit_code"
}

if [[ $# -lt 2 ]]; then
    echo "##[error]Usage: $0 <kubeconfig> <pool_name:expected_count> [pool_name:expected_count ...]" >&2
    exit 2
fi
kubeconfig=$1
shift
if ! expected_pools=$(parse_expected_pools "$@"); then
    echo "##[error]Invalid expected pool arguments" >&2
    exit 2
fi
if [[ ! -r "$kubeconfig" ]]; then
    echo "##[error]Kubeconfig is not readable: $kubeconfig" >&2
    exit 2
fi
timeout_seconds=300
poll_interval_seconds=60
request_timeout=30
final_check_window_seconds=5
deadline=$((SECONDS + timeout_seconds))
trap finish_validation EXIT
trap 'echo "##[error]Node validation interrupted" >&2; exit 130' INT
trap 'echo "##[error]Node validation terminated" >&2; exit 143' TERM
echo "NODE_VALIDATION_START $(date -u +%Y-%m-%dT%H:%M:%SZ)"

while (( SECONDS < deadline )); do
    final_check=$((deadline - SECONDS <= final_check_window_seconds))
    if summary=$(fetch_node_summary "$kubeconfig" "$request_timeout" "$expected_pools"); then
        jq -nc --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson summary "$summary" \
            '{time: $time, summary: $summary}'
        if jq -e '.passed == true' <<< "$summary" >/dev/null; then
            echo "Node validation passed: exact node counts confirmed and no NoSchedule taints"
            exit 0
        fi
    else
        if (( $? == 2 )); then
            exit 1
        fi
        echo "##[warning]Node-list request failed" >&2
        jq -nc --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            '{time: $time, error: "Node-list request failed"}'
    fi

    if (( final_check )); then
        break
    fi
    # Reserve the last five seconds to start a final, normally bounded request.
    remaining=$((deadline - SECONDS))
    sleep_interval=$((remaining - final_check_window_seconds))
    if (( sleep_interval > 0 )); then
        if (( sleep_interval > poll_interval_seconds )); then
            sleep_interval=$poll_interval_seconds
        fi
        sleep "$sleep_interval"
    fi
done
echo "##[error]Node validation failed: exact node counts and taint clearance were not confirmed during the $timeout_seconds-second polling window or its final in-flight request" >&2
exit 1
