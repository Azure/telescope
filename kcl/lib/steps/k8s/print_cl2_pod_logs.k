import azure_pipelines.ap.steps
import lib.steps.azure

PrintCl2PodLogs = lambda serviceConnection: str, namespace: str -> steps.Step {
    script = """
for pod in $(kubectl get pods --namespace="${namespace}" -l job-name=cl2 -o jsonpath='{.items[*].metadata.name}'); do
  echo "===== Logs for pod: $pod ====="
  kubectl logs --namespace="${namespace}" "$pod" || true
done
"""
    azure.AzCli(serviceConnection, "Print cl2 pod logs", script)
}
