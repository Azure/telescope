import azure_pipelines.ap.steps

# RecordCurrentTime emits a step that captures the current UTC time as
# the named pipeline variable, for use downstream (e.g. as the start of
# a dashboard time range or metrics query window).
RecordCurrentTime = lambda envName: str -> steps.Step {
    steps.Bash {
        bash = """
set -exo pipefail
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
echo "${envName}: $TIMESTAMP"
echo "##vso[task.setvariable variable=${envName}]$TIMESTAMP"
"""
        displayName = "Record current time as ${envName}"
    }
}
