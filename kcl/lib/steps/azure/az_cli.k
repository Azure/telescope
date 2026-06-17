import azure_pipelines.ap.steps

AzCli = lambda serviceConnection: str, displayName: str, script: str, condition: str = Undefined, continueOnError: bool = Undefined, stepName: str = Undefined -> steps.Step {
    steps.Task {
        task = "AzureCLI@2"
        inputs = {
            azureSubscription = serviceConnection,
            scriptType = "bash"
            scriptLocation = "inlineScript"
            inlineScript = "set -exo pipefail\n" + script
        }
        displayName = displayName
        condition = condition
        continueOnError = continueOnError
        name = stepName
    }
}