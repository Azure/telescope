import azure_pipelines.ap.steps

Bootstrap = lambda defaultCluster: str -> steps.Step {
    steps.Bash {
        bash = """
set -exo pipefail

# Resolve CLUSTER
if [ -n "$PARAM_EXISTING_CLUSTER" ] && [ "$PARAM_EXISTING_CLUSTER" != "none" ]; then
  CLUSTER="$PARAM_EXISTING_CLUSTER"
  echo "Using existing cluster: $CLUSTER"
else
  CLUSTER="$DEFAULT_CLUSTER_NAME"
  echo "Using default cluster: $CLUSTER"
fi

# Resolve RESOURCE_GROUP
if [ -n "$PARAM_EXISTING_RG" ] && [ "$PARAM_EXISTING_RG" != "none" ]; then
  RESOURCE_GROUP="$PARAM_EXISTING_RG"
  echo "Using existing resource group: $RESOURCE_GROUP"
else
  job_id="$(System.JobId)"
  RESOURCE_GROUP=$(Build.BuildId)-\${job_id:0:8}
  echo "Generated resource group: $RESOURCE_GROUP"
fi

echo "##vso[task.setvariable variable=CLUSTER;isOutput=true]$CLUSTER"
echo "##vso[task.setvariable variable=RESOURCE_GROUP;isOutput=true]$RESOURCE_GROUP"
"""
        name = "resolve"
        displayName = "Bootstrap - resolve CLUSTER, RESOURCE_GROUP"
        env = {
            PARAM_EXISTING_CLUSTER = "\${{ parameters.existing_cluster_name }}"
            PARAM_EXISTING_RG = "\${{ parameters.existing_cluster_resource_group }}"
            DEFAULT_CLUSTER_NAME = defaultCluster
        }
    }
}
