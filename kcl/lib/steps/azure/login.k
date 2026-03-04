import azure_pipelines.ap.steps

Login = lambda serviceConnection: str, subscription: str, region: str -> steps.Step {
    script = """az account set --subscription "${subscription}"
az config set defaults.location="${region}"
az account show
"""
    AzCli(serviceConnection,"Login to Azure", script)
}
