# Overview

This guide covers how to manually run Terraform for AWS. All commands should be run from the root of the repository and in a bash shell (Linux or WSL).

## Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [AWS CLI - 2.15.19](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)
* Install [Kubectl - 1.31.0](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)
* Install [Helm - v3.16.1](https://helm.sh/docs/intro/install/)

#### Install Python Packages for Jupyter to use Interactive Notebooks
```bash
pip install jupyter notebook ipykernel bash_kernel
python -m bash_kernel.install
```
You can install Jupyter Extension from here in the VS code: https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter

## Interactive Notebooks
- **[AWS Notebook:](./aws.ipynb)** Interactive notebook for AWS telescope testing

### Quick Start with Notebooks

```bash
jupyter notebook aws.ipynb
```
Once you run the command go to this http://localhost:8888/tree to access the Jupyter Notebook UI.
On the top right corner, you will see a button called "


## Define Variables

Set environment variables for a specific test scenario. In this guide, we'll use `perf-eval/apiserver-vn10pod100` scenario as the example and set the following variables:

Run the following commands from the root of the repository:
```bash
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=nap-c4n10p100
RUN_ID=$(date +%s)
CLOUD=aws
REGION="us-east-2"
CREATION_TIME=$(date -uIseconds |  sed 's/+00:00/Z/')
TERRAFORM_MODULES_DIR=$(pwd)/modules/terraform/$CLOUD
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
TERRAFORM_USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/scripts/user_data
```

**Note**:

* `RUN_ID` should be a unique identifier since it is used to identify the resources based on tags as AWS has no concept of a resource group.
* `CREATION_TIME` is used to define the tags `creation_time` and `deletion_due_time`, which can be used to track provisioned resources in the AWS account. It must be within one hour of the time the terraform plan/apply commands are executed.
* These variables are not exhaustive and may vary depending on the scenario.

## Provision Resources

Create access key and secret key for AWS CLI following the instructions [here](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html#Using_CreateAccessKey) if you don't have one yet.

Login using the access key and secret key

```bash
aws configure set aws_access_key_id <access-key>
aws configure set aws_secret_access_key <secret-access-key>
aws configure set region <test-region>
```

**Note**: Make sure you configure the region to be the same as where you want to provision the resources. Otherwise, you might get an error.

Set `INPUT_JSON` variable. This variable is not exhaustive and may vary depending on the scenario. For a full list of what can be set, look for `json_input` in file [`modules/terraform/aws/variables.tf`](../../../modules/terraform/aws/variables.tf) as the list will keep changing as we add more features.

```bash
INPUT_JSON=$(jq -n \
      --arg run_id $RUN_ID \
      --arg region $REGION \
      --arg creation_time $CREATION_TIME \
      --arg user_data_path "$TERRAFORM_USER_DATA_PATH" \
      '{
      run_id: $run_id,
      region: $region,
      creation_time: $creation_time,
      user_data_path: $user_data_path,
      }' | jq 'with_entries(select(.value != null and .value != ""))')
```
**Note**: The `jq` command will remove any null or empty values from the JSON object. So any variable surrounded by double quotes means it is optional and can be removed if not needed.

### Provision resources using Terraform:
```bash
pushd $TERRAFORM_MODULES_DIR
terraform init
INPUT_JSON=$(echo $INPUT_JSON | jq -c '. + {creation_time: (now |  todateiso8601)}')
terraform plan -var json_input=$INPUT_JSON -var-file $TERRAFORM_INPUT_FILE
terraform apply -var json_input=$INPUT_JSON -var-file $TERRAFORM_INPUT_FILE
popd
```

### Cleanup Resources
Cleanup test resources using terraform
```bash 
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$INPUT_JSON -var-file $TERRAFORM_INPUT_FILE
popd
```

## References

* [Terraform AWS Provider](https://www.terraform.io/docs/providers/aws/index.html)
* [AWS CLI](https://docs.aws.amazon.com/cli/latest/)
* [AWS Console](https://aws.amazon.com/console/)
