import azure_pipelines.ap.steps

RunClusterLoader2 = lambda serviceConnection: str, image: str, testConfig: str, namespace: str, nodePool: str, taintPrefix: str = "" -> steps.Step {
    script = """
kubectl create namespace "${namespace}" || true
kcl run $(Pipeline.Workspace)/s/kcl/lib/steps/azure/cluster_loader_2_job.k \\
  -D image="${image}" \\
  -D testConfig="${testConfig}" \\
  -D namespace="${namespace}" \\
  -D nodePool="${nodePool}" \\
  -D taintPrefix="${taintPrefix}" \\
  -S output \\
  -o cl2.yaml
cat cl2.yaml
kubectl apply -f cl2.yaml
kubectl wait job/cl2 \\
  --for=condition=complete \\
  --timeout=3600s \\
  --namespace="${namespace}" || \\
  (kubectl logs job/cl2 --namespace="${namespace}"; exit 1)
"""
    AzCli(serviceConnection, "Run cluster loader 2", script)
}
