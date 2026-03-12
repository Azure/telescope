import azure_pipelines.ap.steps

KWOK_SCRIPT = "kwok/kwok.py"

CreateKwokNodes = lambda nodeCount: int, params: {str:str} = {} -> steps.Step {
    extraArgs = " ".join(["--${k} ${v}" for k, v in params])
    assert "node-count" not in params, "node-count should be passed as a separate argument, not in params"
    steps.Script {
        script = """
set -exo pipefail
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 ${KWOK_SCRIPT} \
  --action create \
  --node-count ${nodeCount} \
  ${extraArgs}
python3 ${KWOK_SCRIPT} \
  --action validate \
  --node-count ${nodeCount}"""
        workingDirectory = "modules/python"
        displayName = "Create and Validate KWOK Nodes"
    }
}
