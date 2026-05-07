import azure_pipelines.ap.steps

SetRunId = lambda -> steps.Step {
    steps.Bash {
# Can not use `set -x`.
# https://learn.microsoft.com/en-us/azure/devops/pipelines/scripts/logging-commands?view=azure-devops
        bash = """
set -eo pipefail

job_id="$(System.JobId)"
RUN_ID=$(Build.BuildId)-\${job_id:0:8}
echo "Run ID: $RUN_ID"

echo "##vso[task.setvariable variable=RUN_ID]$RUN_ID"
"""
        displayName = "Set Run ID"
    }
}
