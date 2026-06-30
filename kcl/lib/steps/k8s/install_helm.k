import azure_pipelines.ap.steps

# Install Helm v3 on the pipeline agent.
InstallHelm = lambda -> steps.Step {
    steps.Bash {
        bash = """\
set -euo pipefail
if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
helm version --short"""
        displayName = "Install Helm"
    }
}
