#!/bin/bash
# =============================================================================
# Common library functions for swiftv2 scripts
# Source this file in your scripts: source "$(dirname "$0")/lib/common.sh"
# =============================================================================

# =============================================================================
# CANCELLATION HANDLING
# =============================================================================
CANCELLED=false

handle_cancellation() {
    echo "WARNING: Received cancellation signal (SIGTERM/SIGINT)"
    CANCELLED=true
    sleep 2
    echo "ERROR: Script cancelled. Some resources may remain."
    exit 143
}

check_cancellation() {
    if [ "$CANCELLED" = true ]; then
        echo "WARNING: Cancellation detected, stopping current operation..."
        return 1
    fi
    if [ -f "/tmp/pipeline_cancelled" ]; then
        echo "WARNING: Pipeline cancellation marker detected"
        CANCELLED=true
        return 1
    fi
    return 0
}

# =============================================================================
# RETRY LOGIC
# =============================================================================

# Retry a command with exponential backoff
# Usage: retry_command [max_attempts] [initial_delay] command...
# Example: retry_command 5 30 az aks delete -g $RG -n $cluster --yes
retry_command() {
    local max_attempts=${1:-5}
    local delay=${2:-30}
    shift 2
    local command="$@"
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        echo "Attempt $attempt/$max_attempts: $command"
        if eval "$command"; then
            echo "Command succeeded on attempt $attempt"
            return 0
        else
            echo "Command failed on attempt $attempt"
            if [ $attempt -lt $max_attempts ]; then
                echo "Waiting $delay seconds before retry..."
                sleep $delay
                delay=$((delay * 2))  # Exponential backoff
            fi
            attempt=$((attempt + 1))
        fi
    done

    echo "Command failed after $max_attempts attempts: $command"
    return 1
}

# =============================================================================
# NODEPOOL HELPERS
# =============================================================================

# Wait for a nodepool to be deleted
# Usage: wait_for_nodepool_deletion cluster pool_name rg [timeout]
wait_for_nodepool_deletion() {
    local cluster=$1
    local pool_name=$2
    local rg=$3
    local timeout=${4:-600}
    local interval=15
    local elapsed=0

    echo "Waiting for nodepool $pool_name to be deleted..."
    while [ $elapsed -lt $timeout ]; do
        if ! check_cancellation; then
            return 1
        fi

        if ! az aks nodepool show --cluster-name "$cluster" --name "$pool_name" -g "$rg" &>/dev/null; then
            echo "Nodepool $pool_name has been deleted"
            return 0
        fi

        echo "Nodepool $pool_name still deleting... (elapsed: ${elapsed}s)"
        sleep $interval
        elapsed=$((elapsed + interval))
    done

    echo "ERROR: Timeout waiting for nodepool $pool_name deletion"
    return 1
}

# Wait for a nodepool to reach a specific provisioning state
# Usage: wait_for_nodepool_state cluster pool_name rg target_state [timeout]
wait_for_nodepool_state() {
    local cluster=$1
    local pool_name=$2
    local rg=$3
    local target_state=$4
    local timeout=${5:-600}
    local interval=15
    local elapsed=0

    echo "Waiting for nodepool $pool_name to reach state: $target_state..."
    while [ $elapsed -lt $timeout ]; do
        if ! check_cancellation; then
            return 1
        fi

        local state
        state=$(az aks nodepool show --cluster-name "$cluster" --name "$pool_name" -g "$rg" --query "provisioningState" -o tsv 2>/dev/null || echo "Unknown")

        if [[ "$state" == "$target_state" ]]; then
            echo "Nodepool $pool_name reached state: $target_state"
            return 0
        fi

        echo "Nodepool $pool_name state: $state (waiting for $target_state, elapsed: ${elapsed}s)"
        sleep $interval
        elapsed=$((elapsed + interval))
    done

    echo "ERROR: Timeout waiting for nodepool $pool_name to reach state $target_state"
    return 1
}

# =============================================================================
# CLUSTER HELPERS
# =============================================================================

# Wait for AKS cluster deletion
# Usage: wait_for_cluster_deletion cluster rg [timeout]
wait_for_cluster_deletion() {
    local cluster=$1
    local rg=$2
    local timeout=${3:-3600}
    local interval=30
    local elapsed=0

    echo "Waiting for cluster $cluster deletion to complete..."
    while [ $elapsed -lt $timeout ]; do
        if ! az aks show -g "$rg" -n "$cluster" &>/dev/null; then
            echo "Cluster $cluster has been deleted"
            return 0
        fi
        echo "  Cluster $cluster still deleting... (elapsed: ${elapsed}s, ~$((elapsed/60)) minutes)"
        sleep $interval
        elapsed=$((elapsed + interval))
    done

    echo "ERROR: Timeout waiting for cluster $cluster deletion"
    return 1
}
