import azure_pipelines.ap.steps

# Wait for a named Kubernetes Job to reach a terminal condition, then emit
# logs and diagnostics before returning.
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

deadline=$(( $(date +%s) + ${timeoutSeconds} ))
final=""
while [ $(date +%s) -lt $deadline ]; do
    conditions=$(kubectl -n "${namespace}" get job "${jobName}" -o jsonpath='C={.status.conditions[?(@.type=="Complete")].status} F={.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || true)
    case "$conditions" in
    *"C=True"*) final="complete"; break ;;
    *"F=True"*) final="failed"; break ;;
    esac
    job_json=$(kubectl -n "${namespace}" get job "${jobName}" -o json 2>/dev/null || true)
    if [ -n "$job_json" ]; then
        printf '%s' "$job_json" | jq -r '"Job status: active=\(.status.active // 0) succeeded=\(.status.succeeded // 0) failed=\(.status.failed // 0)"'
    fi
    sleep 60
done

kubectl -n "${namespace}" logs -l job-name="${jobName}" --all-containers --prefix --tail=-1 || true
if [ "$final" != "complete" ]; then
    kubectl -n "${namespace}" describe job "${jobName}" || true
    kubectl -n "${namespace}" describe pods -l job-name="${jobName}" || true
    exit 1
fi
"""
    }
}
