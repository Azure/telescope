## Overview

This guide covers how to manually run Terraform for AWS. All commands should be run from the root of the repository and in a bash shell (Linux or WSL).

### Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [AWS CLI - 2.15.19](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)

### Generate SSH public and Private key using SSH-Keygen
```
CLOUD=aws
ssh_key_path=$(pwd)/modules/terraform/$CLOUD/private_key.pem
ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N ""
SSH_PUBLIC_KEY_PATH="${ssh_key_path}.pub"
```

### Define Variables

Set environment variables for a specific test scenario. In this guide, we'll use `perf-eval/vm-same-zone-iperf` scenario as the example and set the following variables:

```
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=vm-same-zone-iperf
RUN_ID=123456789
OWNER=$(whoami)
CLOUD=aws
REGION=us-east-2
MACHINE_TYPE=m5.4xlarge
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TERRAFORM_USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
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

Set `INPUT_JSON` variable. This variable is not exhaustive and may vary depending on the scenario. For a full list of what can be set, look for `json_input` in file [`modules/terraform/aws/variables.tf`](../../../modules/terraform/aws/variables.tf) as the list will keep changing as we add more features.

```
INPUT_JSON=$(jq -n \
  --arg owner $OWNER \
  --arg run_id $RUN_ID \
  --arg region $REGION \
  --arg public_key_path $SSH_PUBLIC_KEY_PATH \
  --arg machine_type "$MACHINE_TYPE" \
  --arg data_disk_volume_type "$DATA_DISK_TYPE" \
  --arg data_disk_size_gb "$DATA_DISK_SIZE_GB" \
  --arg data_disk_tier "$DATA_DISK_TIER" \
  --arg data_disk_iops_read_write "$DATA_DISK_IOPS_READ_WRITE" \
  --arg data_disk_iops_read_only "$DATA_DISK_IOPS_READ_ONLY" \
  --arg data_disk_mbps_read_write "$DATA_DISK_MBPS_READ_WRITE" \
  --arg data_disk_mbps_read_only "$DATA_DISK_MBPS_READ_ONLY" \
  --arg ultra_ssd_enabled "$ULTRA_SSD_ENABLED" \
  --arg user_data_path $TERRAFORM_USER_DATA_PATH \
  --arg efs_performance_mode "$EFS_PERFORMANCE_MODE" \
  --arg efs_throughput_mode "$EFS_THROUGHPUT_MODE" \
  --arg efs_provisioned_throughput_in_mibps "$EFS_PROVISIONED_THROUGHPUT_IN_MIBPS" \
  '{
  owner: $owner, 
  run_id: $run_id, 
  region: $region, 
  public_key_path: $public_key_path,  
  machine_type: $machine_type, 
  data_disk_volume_type: $data_disk_volume_type, 
  data_disk_size_gb: $data_disk_size_gb,
  data_disk_tier: $data_disk_tier, 
  data_disk_iops_read_write: $data_disk_iops_read_write, 
  data_disk_iops_read_only: $data_disk_iops_read_only, 
  data_disk_mbps_read_write: $data_disk_mbps_read_write, 
  data_disk_mbps_read_only: $data_disk_mbps_read_only,
  ultra_ssd_enabled: $ultra_ssd_enabled,
  user_data_path: $user_data_path,
  efs_performance_mode: $efs_performance_mode,
  efs_throughput_mode: $efs_throughput_mode,
  efs_provisioned_throughput_in_mibps: $efs_provisioned_throughput_in_mibps
  }' | jq 'with_entries(select(.value != null and .value != ""))')
```

**Note**: The `jq` command will remove any null or empty values from the JSON object. So any variable surrounded by double quotes means it is optional and can be removed if not needed.

Provision resources using Terraform:
```
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
