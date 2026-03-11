import azure_pipelines.ap.steps

AzCli = lambda serviceConnection: str, name: str, script: str, condition: str = Undefined -> steps.Step {
    steps.Task {
        task = "AzureCLI@2"
        inputs = {
            azureSubscription = serviceConnection,
            scriptType = "bash"
            scriptLocation = "inlineScript"
            inlineScript = script
        }
        displayName = name
        condition = condition
    }
}