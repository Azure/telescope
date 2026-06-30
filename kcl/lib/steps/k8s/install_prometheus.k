import azure_pipelines.ap.steps
import lib.steps.azure

# Install kube-prometheus-stack via Helm. Caller must run InstallHelm and azure.GetCredentials first, and check in a values.yaml.
InstallPrometheus = lambda serviceConnection: str, valuesFile: str, namespace: str = "monitoring", releaseName: str = "prometheus", chartVersion: str = "", waitTimeout: str = "10m" -> steps.Step {
    script = """
set -euo pipefail

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update prometheus-community

VERSION_FLAG=""
if [ -n "${chartVersion}" ]; then
  VERSION_FLAG="--version ${chartVersion}"
fi

helm upgrade --install "${releaseName}" prometheus-community/kube-prometheus-stack \\
  --namespace "${namespace}" --create-namespace \\
  --values "$(Pipeline.Workspace)/s/${valuesFile}" \\
  --wait --atomic --timeout "${waitTimeout}" \\
  \${VERSION_FLAG}

echo "==> Prometheus release '${releaseName}' is ready in namespace '${namespace}'"
"""
    azure.AzCli(serviceConnection, "Install Prometheus", script)
}
