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

fetch_nodes() {
    local kubeconfig=$1 nodes_file=$2 request_timeout=$3 expected_pools=$4
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

            node_array
            | [.[]
                | pool_name as $pool
                | select($pool != null)
                | select($expected | has($pool))
                | {pool: $pool, taints: node_taints}]
        ' > "$nodes_file"; then
        return 0
    else
        statuses=("${PIPESTATUS[@]}")
    fi
    # A projection failure can also cause kubectl to exit with SIGPIPE (141).
    # Other fetch failures take precedence over the parser seeing incomplete input.
    if (( statuses[0] != 0 && statuses[0] != 141 )); then
        return 1
    fi
    if (( statuses[1] != 0 )); then
        echo "##[error]Could not validate or project node-list response" >&2
        return 2
    fi
    return 1
}

summarize_nodes() {
    local nodes_file=$1 expected_pools=$2
    jq -ce --argjson expected "$expected_pools" '
        def summarize_pool($nodes; $expected):
            . as $pool
            | [$nodes[] | select(.pool == $pool)] as $members
            | {
                pool: $pool,
                expected: $expected[$pool],
                total: ($members | length),
                noSchedule: ([$members[] |
                    select(any(.taints[]; .effect == "NoSchedule"))] | length),
                taints: ([$members[].taints[]]
                    | group_by([.key, .value, .effect])
                    | map({
                        key: .[0].key,
                        value: (.[0].value // ""),
                        effect: .[0].effect,
                        count: length
                    }))
            };

        . as $nodes
        | ($expected | keys)
        | map(summarize_pool($nodes; $expected))
        | {
            pools: .,
            passed: all(.[];
                .expected > 0 and .total == .expected and
                .noSchedule == 0)
        }
    ' "$nodes_file"
}

wait_for_next_poll() {
    local deadline=$1 poll_interval_seconds=$2
    local remaining=$((deadline - SECONDS))
    if (( remaining > 0 )); then
        sleep "$((remaining < poll_interval_seconds ? remaining : poll_interval_seconds))"
    fi
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
    if fetch_nodes "$kubeconfig" "$nodes_file" "$request_timeout" "$expected_pools"; then
        if ! summary=$(summarize_nodes "$nodes_file" "$expected_pools"); then
            echo "##[error]Could not validate or summarize node-list response" >&2
            exit 1
        fi
        jq -nc --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson summary "$summary" \
            '{time: $time, summary: $summary}'
        if jq -e '.passed == true' <<< "$summary" >/dev/null && (( SECONDS < deadline )); then
            echo "Node validation passed: exact node counts confirmed and no NoSchedule taints"
            exit 0
        fi
    else
        if (( $? == 2 )); then
            exit 1
        fi
        echo "##[warning]Node-list request failed; retrying within the verification deadline" >&2
        jq -nc --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            '{time: $time, error: "Node-list request failed"}'
    fi
    wait_for_next_poll "$deadline" "$poll_interval_seconds"
done
echo "##[error]Timed out after $timeout_seconds seconds without confirming exact node counts and taint clearance" >&2
exit 1
