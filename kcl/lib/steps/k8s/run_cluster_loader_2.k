import azure_pipelines.ap.steps
import lib.steps.azure

RunClusterLoader2 = lambda serviceConnection: str, namespace: str, manifest: str -> steps.Step {
    script = """
set +eo pipefail
kubectl create namespace "${namespace}" || true
kubectl apply -f $(Pipeline.Workspace)/s/${manifest}
# Wait
while true; do
  phases="$(kubectl get pods --namespace="${namespace}" -o jsonpath='{range .items[*]}{.status.phase}{"\\n"}{end}' 2>&1)"
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
