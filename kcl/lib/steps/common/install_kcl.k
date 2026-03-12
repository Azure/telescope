import azure_pipelines.ap.steps

InstallKcl = lambda -> steps.Step {
    steps.Bash {
        bash = """\
set -exo pipefail
wget -q https://kcl-lang.io/script/install-cli.sh -O - | /bin/bash"""
        displayName = "Install KCL"
    }
}
