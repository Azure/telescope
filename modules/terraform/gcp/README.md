# Overview

This guide covers how to manually run Terraform for GCP. All commands should be run from the root of the repository and in a bash shell (Linux or WSL).

## Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [Google Cloud SDK - 502.0.0](https://cloud.google.com/sdk/docs/install)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)
* Install [Kubectl - 1.31.0](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)
* Install [Helm - v3.16.1](https://helm.sh/docs/intro/install/)

## Define Variables

Set environment variables for a specific test scenario. In this guide, we'll use `perf-eval/apiserver-vn10pod100` scenario as the example and set the following variables:

Run the following commands from the root of the repository:
```bash
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=apiserver-vn10pod100
RUN_ID=$(date +%s)
CLOUD=gcp
REGION="us-east1"
CREATION_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
TERRAFORM_MODULES_DIR=$(pwd)/modules/terraform/$CLOUD
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
```

**Note**:
* `RUN_ID` should be a unique identifier since it is used to identify the resources based on tags as GCP has no concept of a resource group.
* `CREATION_TIME` is used to define the tags `creation_time` and `deletion_due_time`, which can be used to track provisioned resources in the GCP account. It must be within one hour of the time the terraform plan/apply commands are executed.
* These variables are not exhaustive and may vary depending on the scenario.

## Provision Resources

Create credentials.json for gcloud CLI following the instructions [here](https://cloud.google.com/sdk/gcloud/reference/auth/application-default) if you don't have one yet.

Login via web browser

```bash
gcloud auth application-default login --quiet --format=json
PROJECT_ID=$(gcloud config get-value project)
```

**Note**: Make sure you configure the region to be the same as where you want to provision the resources. Otherwise, you might get an error.

Set `INPUT_JSON` variable. This variable is not exhaustive and may vary depending on the scenario. For a full list of what can be set, look for `json_input` in file [`modules/terraform/gcp/variables.tf`](../../../modules/terraform/gcp/variables.tf) as the list will keep changing as we add more features.

```bash
INPUT_JSON=$(jq -n \
  --arg project_id "$PROJECT_ID" \
  --arg run_id "$RUN_ID" \
  --arg region "$REGION" \
  --arg creation_time "$CREATION_TIME" \
  '{
    project_id: $project_id,
    run_id: $run_id,
    region: $region,
    creation_time: $creation_time
  }' | jq 'with_entries(select(.value != null and .value != ""))')
```
**Note**: The `jq` command will remove any null or empty values from the JSON object. So any variable surrounded by double quotes means it is optional and can be removed if not needed.

### Provision resources using Terraform:
```bash
pushd $TERRAFORM_MODULES_DIR
terraform init
terraform plan -var 'json_input='"$INPUT_JSON" -var-file="$TERRAFORM_INPUT_FILE"
terraform apply -var 'json_input='"$INPUT_JSON" -var-file="$TERRAFORM_INPUT_FILE"
popd
```

### Cleanup Resources
Cleanup test resources using terraform
```bash
pushd $TERRAFORM_MODULES_DIR
terraform destroy  -var 'json_input='"$INPUT_JSON" -var-file="$TERRAFORM_INPUT_FILE"
popd
```

## References

* [Terraform Provider for Google Cloud](https://registry.terraform.io/providers/hashicorp/google/latest/docs)
* [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
* [Google Cloud Console](https://cloud.google.com/cloud-console)
