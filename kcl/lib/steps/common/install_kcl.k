import azure_pipelines.ap.steps

InstallKcl = lambda -> steps.Step {
    steps.Bash {
        bash = "wget -q https://kcl-lang.io/script/install-cli.sh -O - | /bin/bash"
        displayName = "Install KCL"
    }
}
