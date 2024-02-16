## Overview

This guide covers how to manually run Terraform for AWS. All commands should be run from the root of the repository and in a bash shell (Linux or WSL).

### Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [AWS CLI - 2.15.19](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)

### Define Variables

Set environment variables for a specific test scenario. In this guide, we'll use `perf-eval/vm-same-zone-iperf` scenario as the example and set the following variables:

```
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=vm-same-zone-iperf
RUN_ID=123456789
OWNER=$(whoami)
CLOUD=aws
REGION=us-east-2
ZONE=us-east-2b
MACHINE_TYPE=m5.4xlarge
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
```

**Note**:
* `RUN_ID` should be a unique identifier since it is used to identify the resources based on tags as AWS has no concept of a resource group.
* These variables are not exhaustive and may vary depending on the scenario.

### Provision Resources

Create access key and secret key for AWS CLI following the instructions [here](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html#Using_CreateAccessKey) if you don't have one yet.

Login using the access key and secret key
```
aws configure set aws_access_key_id <access-key>
aws configure set aws_secret_access_key <secret-access-key>
aws configure set region <test-region>
```

**Note**: Make sure you configure the region to be the same as where you want to provision the resources. Otherwise, you might get an error.

Provision resources using Terraform. Again, this `INPUT_JSON` is not exhaustive and may vary depending on the scenario. For a full list of what can be set, look for `json_input` in file `modules/terraform/aws/variables.tf`

```
INPUT_JSON=$(jq -n \
--arg owner $OWNER \
--arg run_id $RUN_ID \
--arg region $REGION \
--arg zone $ZONE \
--arg machine_type $MACHINE_TYPE \
--arg user_data_path $USER_DATA_PATH \
'{owner: $owner, run_id: $run_id, region: $region, zone: $zone, machine_type: $machine_type, user_data_path:$user_data_path}')

pushd $TERRAFORM_MODULES_DIR
terraform init
terraform plan -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE --auto-approve
popd
```

Once resources are provisioned, make sure to go to AWS console to verify the resources are created as expected.

### Cleanup Resources

Once your test is done, you can destroy the resources using Terraform.
```
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```

### References
- [Terraform AWS Provider](https://www.terraform.io/docs/providers/aws/index.html)
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/)
- [AWS Console](https://aws.amazon.com/console/)
