import azure_pipelines.ap.steps
import lib.steps.azure

# RunScaleCommand invokes the same deterministic CLI used by local runs.
RunScaleCommand = lambda serviceConnection: str, command: str, displayName: str, args: str, condition: str = Undefined, continueOnError: bool = Undefined -> steps.Step {
    azure.AzCli(
        serviceConnection,
        displayName,
        """
export PYTHONPATH="$(Build.SourcesDirectory)/modules/python"
python3 -m aks_flex_scale.cli ${command} \\
  --config "$(Build.SourcesDirectory)/kcl/aks_flex_scale/defaults.json" \\
  --state-dir "$(Pipeline.Workspace)/flex-scale" \\
  --output /tmp/run-result.json \\
  ${args}
""",
        condition = condition,
        continueOnError = continueOnError)
}
