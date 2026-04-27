import azure_pipelines.ap.steps

Bootstrap = lambda defaultCluster: str -> steps.Step {
    steps.Bash {
        bash = """
set -exo pipefail

# Resolve RUN_ID
if [ -n "$PARAM_RUN_ID" ] && [ "$PARAM_RUN_ID" != "default" ]; then
  RUN_ID="$PARAM_RUN_ID"
  echo "Using provided Run ID: $RUN_ID"
else
  job_id="$(System.JobId)"
  RUN_ID=$(Build.BuildId)-\${job_id:0:8}
  echo "Generated Run ID: $RUN_ID"
fi

# Resolve CLUSTER
if [ -n "$PARAM_EXISTING_CLUSTER" ] && [ "$PARAM_EXISTING_CLUSTER" != "none" ]; then
  CLUSTER="$PARAM_EXISTING_CLUSTER"
  echo "Using existing cluster: $CLUSTER"
else
  CLUSTER="$DEFAULT_CLUSTER"
  echo "Using default cluster: $CLUSTER"
fi

# Resolve RESOURCE_GROUP
if [ -n "$PARAM_EXISTING_RG" ] && [ "$PARAM_EXISTING_RG" != "none" ]; then
  RESOURCE_GROUP="$PARAM_EXISTING_RG"
  echo "Using existing resource group: $RESOURCE_GROUP"
else
  RESOURCE_GROUP="$RUN_ID"
  echo "Using RUN_ID as resource group: $RESOURCE_GROUP"
fi

echo "##vso[task.setvariable variable=RUN_ID;isOutput=true]$RUN_ID"
echo "##vso[task.setvariable variable=CLUSTER;isOutput=true]$CLUSTER"
echo "##vso[task.setvariable variable=RESOURCE_GROUP;isOutput=true]$RESOURCE_GROUP"
"""
        name = "resolve"
        displayName = "Bootstrap - resolve RUN_ID, CLUSTER, RESOURCE_GROUP"
        env = {
            PARAM_RUN_ID = "\${{ parameters.run_id }}"
            PARAM_EXISTING_CLUSTER = "\${{ parameters.existing_cluster_name }}"
            PARAM_EXISTING_RG = "\${{ parameters.existing_cluster_resource_group }}"
            DEFAULT_CLUSTER = defaultCluster
        }
    }
}
