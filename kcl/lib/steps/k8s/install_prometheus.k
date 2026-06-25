import azure_pipelines.ap.steps
import lib.steps.azure

# Install kube-prometheus-stack via Helm. Caller must run azure.GetCredentials first and check in a values.yaml.
InstallKubePrometheusStack = lambda serviceConnection: str, valuesFile: str, namespace: str = "monitoring", releaseName: str = "prometheus", chartVersion: str = "", waitTimeout: str = "10m" -> steps.Step {
    script = """
set -euo pipefail

# Install Helm v3 if missing
if ! command -v helm >/dev/null 2>&1; then
  echo "==> helm not found; installing"
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
helm version --short

# Add / refresh prometheus-community repo (idempotent)
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

echo "==> kube-prometheus-stack release '${releaseName}' is ready in namespace '${namespace}'"
# Prometheus web service is svc/<releaseName>-kube-prometheus-prometheus on port 9090.
echo "==> Prometheus web service: svc/${releaseName}-kube-prometheus-prometheus in ${namespace} (port 9090)"
"""
    azure.AzCli(serviceConnection, "Install kube-prometheus-stack", script)
}
