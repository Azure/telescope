import azure_pipelines.ap.steps
import lib.steps.azure

MAX_CONSECUTIVE_APISERVER_ERRORS = 20

RunClusterLoader2 = lambda serviceConnection: str, namespace: str, manifest: str -> steps.Step {
    script = """
set +eo pipefail
kubectl create namespace "${namespace}" || true
kubectl apply -f $(Pipeline.Workspace)/s/${manifest} || exit 1
# Wait
consecutive_errors=0
while true; do
  # Under consistent API server errors, we would want to exit early instead of waiting for the entire timeout duration.
  conditions="$(kubectl get job cl2 --namespace="${namespace}" -o jsonpath='{range .status.conditions[?(@.status=="True")]}{.type}{" "}{.reason}{" "}{.message}{"\\n"}{end}' 2>/tmp/kubectl_err)"
  kubectl_exit_code=$?
  if [ $kubectl_exit_code -ne 0 ]; then
    consecutive_errors=$((consecutive_errors + 1))
    echo "kubectl get job cl2 failed (exit_code=$kubectl_exit_code, consecutive=$consecutive_errors/${MAX_CONSECUTIVE_APISERVER_ERRORS}):"
    cat /tmp/kubectl_err
    if [ "$consecutive_errors" -ge "${MAX_CONSECUTIVE_APISERVER_ERRORS}" ]; then
      echo "Unable to read cl2 Job for $consecutive_errors consecutive polls; aborting."
      exit 1
    fi
    sleep 30
    continue
  fi
  consecutive_errors=0

  while read -r condition reason message; do
    case "$condition" in
      Failed)
        echo "cl2 Job failed: $reason $message"
        exit 1
        ;;
      Complete)
        echo "cl2 Job completed successfully"
        exit 0
        ;;
    esac
  done <<< "$conditions"

  kubectl get pods --namespace="${namespace}" -l job-name=cl2 -o wide || echo "Unable to list cl2 pods; retrying on the next poll."
  sleep 30
done
"""
    azure.AzCli(serviceConnection, "Run cluster loader 2", script)
}
