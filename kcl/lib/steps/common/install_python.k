import azure_pipelines.ap.steps

InstallPythonDependencies = lambda -> steps.Step {
    steps.Bash {
        bash = """\
set -exo pipefail
pip3 install --upgrade "pip<24"
pip3 install -r $(Pipeline.Workspace)/s/modules/python/requirements.txt"""
        displayName = "Install Python dependencies"
    }
}
