import azure_pipelines.ap.steps
import lib.steps.azure

MAX_CONSECUTIVE_APISERVER_ERRORS = 20

RunClusterLoader2 = lambda serviceConnection: str, namespace: str, manifest: str -> steps.Step {
    script = """
set +eo pipefail
kubectl create namespace "${namespace}" || true
kubectl apply -f $(Pipeline.Workspace)/s/${manifest}
# Wait
consecutive_errors=0
while true; do
  # Under consistent API server errors, we would want to exit early instead of waiting for the entire timeout duration.
  phases="$(kubectl get pods --namespace="${namespace}" -o jsonpath='{range .items[*]}{.status.phase}{"\\n"}{end}' 2>/tmp/kubectl_err)"
  kubectl_exit_code=$?
  if [ $kubectl_exit_code -ne 0 ]; then
    consecutive_errors=$((consecutive_errors + 1))
    echo "kubectl get pods failed (exit_code=$kubectl_exit_code, consecutive=$consecutive_errors/${MAX_CONSECUTIVE_APISERVER_ERRORS}):"
    cat /tmp/kubectl_err
    if [ "$consecutive_errors" -ge "${MAX_CONSECUTIVE_APISERVER_ERRORS}" ]; then
      echo "API server unresponsive for $consecutive_errors consecutive polls; aborting."
      exit 1
    fi
    sleep 30
    continue
  fi
  consecutive_errors=0

  total=0
  terminal=0

  if [ -n "$phases" ]; then
    while IFS= read -r phase; do
      if [ -z "$phase" ]; then
        continue
      fi

      total=$((total + 1))
      if [ "$phase" = "Succeeded" ] || [ "$phase" = "Failed" ]; then
        terminal=$((terminal + 1))
      fi
    done <<< "$phases"
  fi

  if [ "$total" -gt 0 ] && [ "$terminal" -eq "$total" ]; then
    echo "All cl2 pods reached terminal state (Succeeded or Failed)"
    kubectl get pods --namespace="${namespace}" -l job-name=cl2 -o wide

    break
  fi

  sleep 30
done
"""
    azure.AzCli(serviceConnection, "Run cluster loader 2", script)
}
