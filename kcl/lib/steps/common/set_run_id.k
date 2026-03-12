import azure_pipelines.ap.steps

SetRunId = lambda -> steps.Step {
    steps.Bash {
        bash = """
set -exo pipefail
job_id="$(System.JobId)"
RUN_ID=$(Build.BuildId)-\${job_id:0:8}
echo "Run ID: $RUN_ID"
echo "##vso[task.setvariable variable=RUN_ID]$RUN_ID"
"""
        displayName = "Set Run ID"
    }
}
