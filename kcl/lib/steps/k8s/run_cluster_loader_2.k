import azure_pipelines.ap.steps
import lib.steps.azure

RunClusterLoader2 = lambda serviceConnection: str, namespace: str, manifest: str -> steps.Step {
    script = """
kubectl create namespace "${namespace}" || true
kubectl apply -f $(Pipeline.Workspace)/s/${manifest}
kubectl wait job/cl2 \\
  --for=condition=complete \\
  --timeout=24h \\
  --namespace="${namespace}" || \\
  (kubectl logs job/cl2 --namespace="${namespace}"; exit 1)
"""
    azure.AzCli(serviceConnection, "Run cluster loader 2", script)
}
