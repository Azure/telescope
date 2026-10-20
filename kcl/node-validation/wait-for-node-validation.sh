#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 || ! $2 =~ ^(250|500|1000)$ ]]; then
    echo "##[error]Usage: $0 <kubeconfig> <250|500|1000 nodes per worker pool> <output directory>" >&2
    exit 2
fi
kubeconfig=$1
nodes_per_pool=$2
output_directory=$3
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
mkdir -p "$output_directory"
start_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
start_seconds=$SECONDS
deadline=$((start_seconds + 3600))
result="failed"
reason="Verification did not complete"
snapshot_time=""
summary='null'
: > "$output_directory/progress.jsonl"

finish() {
    exit_code=$?
    trap - EXIT
    rm -f "$output_directory/nodes.pending.json"
    end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    echo "##vso[task.setvariable variable=NODE_VALIDATION_END]$end_time"
    if ! jq -n \
        --arg result "$result" \
        --arg reason "$reason" \
        --arg startTime "$start_time" \
        --arg endTime "$end_time" \
        --arg snapshotTime "$snapshot_time" \
        --argjson elapsed "$((SECONDS - start_seconds))" \
        --argjson nodesPerPool "$nodes_per_pool" \
        --argjson summary "$summary" \
        '{result: $result, reason: $reason, startTime: $startTime, endTime: $endTime,
          elapsedSeconds: $elapsed, timeoutSeconds: 3600,
          nodesPerPool: $nodesPerPool, snapshotTime: $snapshotTime, summary: $summary}' \
        > "$output_directory/result.json"; then
        echo "##[error]Could not write node validation result: $result ($reason)" >&2
        if (( exit_code == 0 )); then
            exit_code=1
        fi
    else
        echo "Node validation: $result ($reason)"
    fi
    exit "$exit_code"
}
trap finish EXIT
trap 'reason="Verification interrupted"; exit 130' INT
trap 'reason="Verification terminated"; exit 143' TERM
echo "##vso[task.setvariable variable=NODE_VALIDATION_START]$start_time"

while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    request_timeout=$((remaining < 30 ? remaining : 30))
    if timeout "${request_timeout}s" kubectl --kubeconfig "$kubeconfig" \
        --request-timeout="${request_timeout}s" get nodes -o json \
        > "$output_directory/nodes.pending.json"; then
        if ! jq -e '
            (.kind == "NodeList" or .kind == "List") and (.items | type == "array") and
            all(.items[];
              .kind == "Node" and
              (.metadata.name | type == "string") and
              (.status.conditions | type == "array") and
              ((.spec.taints // []) | type == "array") and
              all(.spec.taints[]?;
                (.key | type == "string") and
                (.effect == "NoSchedule" or .effect == "PreferNoSchedule" or .effect == "NoExecute")))
        ' "$output_directory/nodes.pending.json" >/dev/null; then
            reason="Malformed node-list response"
            echo "##[error]$reason" >&2
            exit 1
        fi
        if ! next_summary=$(jq -c --argjson count "$nodes_per_pool" '
            [.items[] | {
              pool: (.metadata.labels.agentpool //
                     .metadata.labels["kubernetes.azure.com/agentpool"] // "unknown"),
              ready: any(.status.conditions[]; .type == "Ready" and .status == "True"),
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
        ' "$output_directory/nodes.pending.json"); then
            reason="Could not summarize node-list response"
            echo "##[error]$reason" >&2
            exit 1
        fi
        mv "$output_directory/nodes.pending.json" "$output_directory/nodes.json"
        snapshot_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        summary=$next_summary
        jq -nc --arg time "$snapshot_time" --argjson summary "$summary" \
            '{time: $time, summary: $summary}' \
            | tee -a "$output_directory/progress.jsonl"
        if [[ $(jq -r '.passed' <<< "$summary") == true ]] && (( SECONDS < deadline )); then
            result="passed"
            reason="All expected nodes are Ready and have no NoSchedule taints"
            exit 0
        fi
    else
        echo "##[warning]Node-list request failed; retrying within the verification deadline" >&2
        jq -nc --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            '{time: $time, error: "Node-list request failed"}' \
            | tee -a "$output_directory/progress.jsonl"
    fi
    remaining=$((deadline - SECONDS))
    if (( remaining > 0 )); then
        sleep "$((remaining < 60 ? remaining : 60))"
    fi
done
reason="Timed out after 3600 seconds without confirming exact node counts, readiness and taint clearance"
echo "##[error]$reason" >&2
exit 1
