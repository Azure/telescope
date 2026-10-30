#!/usr/bin/env bash
set -euo pipefail

wait_for_taint_clearance() {
    local kubeconfig=$1 pool=${2%:*} expected=${2##*:}
    local deadline=$((SECONDS + 300)) nodes
    while (( SECONDS < deadline )); do
        if nodes=$(kubectl --kubeconfig "$kubeconfig" get nodes -o json); then
            if jq -e --arg pool "$pool" --argjson expected "$expected" '
                .items
                | map(
                    select((.metadata.labels.agentpool // .metadata.labels["kubernetes.azure.com/agentpool"]) == $pool)
                    | if (.spec | type) == "object" then . else error("Selected node spec must be an object") end
                )
                | length == $expected and all(.[]; all(.spec.taints[]?; .effect != "NoSchedule"))' <<< "$nodes" >/dev/null; then
                echo "Node validation passed: pool $pool has $expected nodes and no NoSchedule taints"
                return 0
            fi
        else
            echo "##[warning]Node-list request failed; retrying while polling time remains" >&2
        fi

        sleep 10
    done
    echo "##[error]Pool $pool did not reach $expected nodes without NoSchedule taints during the 300-second polling window or an in-flight request" >&2
    return 1
}

trap 'echo "NODE_VALIDATION_END $(date -u +%Y-%m-%dT%H:%M:%SZ)"' EXIT
echo "NODE_VALIDATION_START $(date -u +%Y-%m-%dT%H:%M:%SZ)"
wait_for_taint_clearance "$@"
