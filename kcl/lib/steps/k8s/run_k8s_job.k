import azure_pipelines.ap.steps

# Apply a manifest containing a named Kubernetes Job, wait for it to reach a
# terminal condition, and emit logs and diagnostics before returning.
RunAndWaitK8sJob = lambda namespace: str, jobName: str, manifestYaml: str, timeoutSeconds: int = 7200 -> steps.Bash {
    steps.Bash {
        displayName = "Run Kubernetes Job: ${jobName}"
        bash = """
set -euo pipefail

NAMESPACE="${namespace}"
JOB_NAME="${jobName}"
MANIFEST_YAML="${manifestYaml}"

namespace_resource=$(kubectl get namespace "$NAMESPACE" --ignore-not-found -o name)
if [ -n "$namespace_resource" ]; then
    kubectl -n "$NAMESPACE" delete job "$JOB_NAME" --ignore-not-found --wait=true
fi

kubectl apply -f "$MANIFEST_YAML"
if ! kubectl -n "$NAMESPACE" get job "$JOB_NAME" >/dev/null; then
    echo "##[error]Manifest did not create expected Job $NAMESPACE/$JOB_NAME"
    exit 1
fi

deadline=$(( $(date +%s) + ${timeoutSeconds} ))
final=""
while [ $(date +%s) -lt $deadline ]; do
    conditions=$(kubectl -n "$NAMESPACE" get job "$JOB_NAME" -o jsonpath='C={.status.conditions[?(@.type=="Complete")].status} F={.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || true)
    case "$conditions" in
    *"C=True"*) final="complete"; break ;;
    *"F=True"*) final="failed"; break ;;
    esac
    job_json=$(kubectl -n "$NAMESPACE" get job "$JOB_NAME" -o json 2>/dev/null || true)
    if [ -n "$job_json" ]; then
        printf '%s' "$job_json" | jq -r '"Job status: active=\(.status.active // 0) succeeded=\(.status.succeeded // 0) failed=\(.status.failed // 0)"'
    fi
    sleep 30
done

kubectl -n "$NAMESPACE" logs -l job-name="$JOB_NAME" --all-containers --prefix --tail=-1 || true
if [ "$final" != "complete" ]; then
    kubectl -n "$NAMESPACE" describe job "$JOB_NAME" || true
    kubectl -n "$NAMESPACE" describe pods -l job-name="$JOB_NAME" || true
    exit 1
fi
"""
    }
}
