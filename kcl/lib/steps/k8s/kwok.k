import azure_pipelines.ap.steps
import lib.steps.azure

KWOK_SCRIPT = "kwok/kwok.py"

_runKwok = lambda action: str, displayName: str, nodeCount: int, extraArgs: str, continueOnError: bool = Undefined, serviceConnection: str = Undefined -> steps.Step {
    script = """
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 ${KWOK_SCRIPT} \
  --action ${action} \
  --node-count ${nodeCount} \
  ${extraArgs}"""
    # Entra-only clusters need an Azure CLI login for kubelogin.
    azure.AzCli(
        serviceConnection,
        displayName,
        "cd modules/python\n" + script,
        continueOnError = continueOnError
    ) if serviceConnection != Undefined else steps.Script {
        script = "set -exo pipefail\n" + script
        workingDirectory = "modules/python"
        displayName = displayName
        continueOnError = continueOnError
    }
}

# Returns two pipeline steps: one to create KWOK nodes (optionally tolerant of
# transient errors via continueOnError), and one to validate them strictly so
# that a real validation failure always fails the pipeline.
CreateKwokNodes = lambda nodeCount: int, continueOnError: bool = Undefined, serviceConnection: str = Undefined, params: {str:str} = {} -> [steps.Step] {
    extraArgs = " ".join(["--${k} ${v}" for k, v in params])
    assert "node-count" not in params, "node-count should be passed as a separate argument, not in params"
    [
        _runKwok(
            "create",
            "Create KWOK Nodes",
            nodeCount,
            extraArgs,
            continueOnError,
            serviceConnection),
        _runKwok(
            "validate",
            "Validate KWOK Nodes",
            nodeCount,
            extraArgs,
            serviceConnection = serviceConnection),
    ]
}
