import azure_pipelines.ap.steps

SetRunId = lambda -> steps.Step {
    steps.Bash {
        bash = """
set -exo pipefail
if [ -n "$RUN_ID" ] && [ "$RUN_ID" != "default" ]; then
  echo "Using provided Run ID: $RUN_ID"
else
  job_id="$(System.JobId)"
  RUN_ID=$(Build.BuildId)-\${job_id:0:8}
  echo "Run ID: $RUN_ID"
fi
echo "##vso[task.setvariable variable=RUN_ID]$RUN_ID"
"""
        displayName = "Set Run ID"
        env = {
            RUN_ID = "\${{ parameters.run_id }}"
        }
    }
}
