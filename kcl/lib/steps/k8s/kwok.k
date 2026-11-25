import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

KWOK_SCRIPT = "kwok/kwok.py"

_runKwok = lambda serviceConnection: str, action: str, displayName: str, nodeCount: int, extraArgs: str, continueOnError: bool = Undefined -> steps.Step {
    script = """
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 ${KWOK_SCRIPT} \
  --action ${action} \
  --node-count ${nodeCount} \
  ${extraArgs}"""
    azure.AzCli(
        serviceConnection,
        displayName,
        "cd modules/python\n" + script,
        continueOnError = continueOnError
    )
}

# Returns two pipeline steps: one to create KWOK nodes (optionally tolerant of
# transient errors via continueOnError), and one to validate them strictly so
# that a real validation failure always fails the pipeline.
CreateKwokNodes = lambda serviceConnection: str, nodeCount: int, continueOnError: bool = Undefined, params: {str:str} = {} -> [steps.Step] {
    extraArgs = " ".join(["--${k} ${v}" for k, v in params])
    assert "node-count" not in params, "node-count should be passed as a separate argument, not in params"
    [
        _runKwok(
            serviceConnection,
            "create",
            "Create KWOK Nodes",
            nodeCount,
            extraArgs,
            continueOnError),
        _runKwok(
            serviceConnection,
            "validate",
            "Validate KWOK Nodes",
            nodeCount,
            extraArgs),
    ]
}

DeleteKwokNodes = lambda nodeCount: int, serviceConnection: str = const.DEFAULT_SERVICE_CONNECTION -> steps.Step {
    _runKwok(
        serviceConnection,
        "tear_down",
        "Delete KWOK Nodes and controllers",
        nodeCount,
        ""
    )
}
