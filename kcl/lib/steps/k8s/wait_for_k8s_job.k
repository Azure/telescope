import azure_pipelines.ap.steps

# Wait for a named Kubernetes Job to reach a terminal condition, stream its
# container logs, and emit diagnostics before returning.
WaitForK8sJobFinished = lambda namespace: str, jobName: str, timeoutSeconds: int = 7200, continueOnError: bool = False -> steps.Bash {
    steps.Bash {
        displayName = "Wait for k8s job to finish: ${jobName}"
        continueOnError = continueOnError
        bash = """
set -euo pipefail

if ! kubectl -n "${namespace}" get job "${jobName}" >/dev/null; then
    echo "##[error]Kubernetes Job ${namespace}/${jobName} does not exist or cannot be read"
    exit 1
fi

log_cursor=""
fetch_logs() {
    poll_start=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    since_args=()
    if [ -n "$log_cursor" ]; then
        since_args=("--since-time=$log_cursor")
    fi
    if kubectl --request-timeout=15s -n "${namespace}" logs \
        -l job-name="${jobName}" --all-containers --timestamps --prefix --tail=-1 \
        "\${since_args[@]}"; then
        log_cursor="$poll_start"
    else
        echo "##[warning]Unable to read logs for Kubernetes Job ${namespace}/${jobName}; retaining the previous log cursor"
    fi
}

deadline=$(( $(date +%s) + ${timeoutSeconds} ))
final=""
while [ $(date +%s) -lt $deadline ]; do
    conditions=$(kubectl -n "${namespace}" get job "${jobName}" -o jsonpath='C={.status.conditions[?(@.type=="Complete")].status} F={.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || true)
    case "$conditions" in
    *"C=True"*) final="complete"; break ;;
    *"F=True"*) final="failed"; break ;;
    esac
    fetch_logs
    sleep 60
done

fetch_logs
if [ "$final" != "complete" ]; then
    kubectl -n "${namespace}" describe job "${jobName}" || true
    kubectl -n "${namespace}" describe pods -l job-name="${jobName}" || true
    exit 1
fi
"""
    }
}
