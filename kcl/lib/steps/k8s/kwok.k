import azure_pipelines.ap.steps

KWOK_SCRIPT = "kwok/kwok.py"

_runKwok = lambda action: str, displayName: str, nodeCount: int, extraArgs: str, logLevel: str, continueOnError: bool -> steps.Step {
    steps.Script {
        script = """
set -exo pipefail
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 ${KWOK_SCRIPT} \
  --action ${action} \
  --node-count ${nodeCount} \
  ${extraArgs}"""
        workingDirectory = "modules/python"
        displayName = displayName
        continueOnError = continueOnError
        env = {
            "LOG_LEVEL": logLevel
        }
    }
}

# Returns two pipeline steps: one to create KWOK nodes (optionally tolerant of
# transient errors via continueOnError), and one to validate them strictly so
# that a real validation failure always fails the pipeline.
CreateKwokNodes = lambda nodeCount: int, logLevel: str = "INFO", continueOnError: bool = False, params: {str:str} = {} -> [steps.Step] {
    extraArgs = " ".join(["--${k} ${v}" for k, v in params])
    assert "node-count" not in params, "node-count should be passed as a separate argument, not in params"
    [
        _runKwok("create", "Create KWOK Nodes", nodeCount, extraArgs, logLevel, continueOnError),
        _runKwok("validate", "Validate KWOK Nodes", nodeCount, extraArgs, logLevel, False),
    ]
}
