# Overview

This guide covers how to manually run Terraform for AWS. All commands should be run from the root of the repository and in a bash shell (Linux or WSL).

## Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [AWS CLI - 2.15.19](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)

## Generate SSH public and Private key using SSH-Keygen

```bash
CLOUD=aws
ssh_key_path=$(pwd)/modules/terraform/$CLOUD/private_key.pem
ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N ""
SSH_PUBLIC_KEY_PATH="${ssh_key_path}.pub"
```

## Define Variables

Set environment variables for a specific test scenario. In this guide, we'll use `perf-eval/vm-same-zone-iperf` scenario as the example and set the following variables:

```bash
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=vm-same-zone-iperf
RUN_ID=123456789
OWNER=$(whoami)
CLOUD=aws
REGIONS='["us-east-2"]' 
MACHINE_TYPE=m5.4xlarge
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TERRAFORM_USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
VM_COUNT_OVERRIDE=1
```

**Note**:

* `RUN_ID` should be a unique identifier since it is used to identify the resources based on tags as AWS has no concept of a resource group.
* These variables are not exhaustive and may vary depending on the scenario.
* `REGIONS` contains list of regions
* `VM_COUNT_OVERRIDE` optional, will create this number copies of all the vms in vm_config_list

## Set Input File

```bash
regional_config=$(jq -n '{}')
multi_region=$(echo "$REGIONS" | jq -r 'if length > 1 then "true" else "false" end')
for region in $(echo "$REGIONS" | jq -r '.[]'); do
  if [ $multi_region = "false" ]; then
    terraform_input_file=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
  else
    terraform_input_file=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}-${region}.tfvars
  fi
  regional_config=$(echo $regional_config | jq --arg region $region --arg file_path $terraform_input_file '. + {($region): {"TERRAFORM_INPUT_FILE" : $file_path}}')
done
regional_config_str=$(echo $regional_config | jq -c .)
```

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
for REGION in $(echo "$REGIONS" | jq -r '.[]'); do
  echo "Set input variables for region $REGION"
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
        --arg data_disk_count "$DATA_DISK_COUNT" \
        --arg vm_count_override "$VM_COUNT_OVERRIDE"  \
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
        data_disk_count: $data_disk_count,
        vm_count_override: $vm_count_override,
        ultra_ssd_enabled: $ultra_ssd_enabled,
        user_data_path: $user_data_path,
        efs_performance_mode: $efs_performance_mode,
        efs_throughput_mode: $efs_throughput_mode,
        efs_provisioned_throughput_in_mibps: $efs_provisioned_throughput_in_mibps
        }' | jq 'with_entries(select(.value != null and .value != ""))')
  input_json_str=$(echo $INPUT_JSON | jq -c .)
  regional_config=$(echo "$regional_config" | jq --arg region "$REGION" --arg input_variable "$input_json_str" \
    '.[$region].TERRAFORM_INPUT_VARIABLES += $input_variable')
  INPUT_JSON=""
done
```

**Note**: The `jq` command will remove any null or empty values from the JSON object. So any variable surrounded by double quotes means it is optional and can be removed if not needed.

Provision resources using Terraform:

```bash
pushd $TERRAFORM_MODULES_DIR
terraform init
for region in $(echo "$REGIONS" | jq -r '.[]'); do
  if terraform workspace list | grep -q "$region"; then
    terraform workspace select $region
  else
    terraform workspace new $region
    terraform workspace select $region
  fi
  terraform_input_file=$(echo $regional_config | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_FILE')
  terraform_input_variables=$(echo $regional_config | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_VARIABLES')
  terraform plan -var-file $terraform_input_file -var json_input=$terraform_input_variables
  
  # Check if the plan was successful
  if [ $? -ne 0 ]; then
    echo "Terraform plan failed for $region. Skipping apply."
    continue
  fi
  
  terraform apply -var-file $terraform_input_file -var json_input=$terraform_input_variables --auto-approve
done
popd
```

Once resources are provisioned, make sure to go to AWS console to verify the resources are created as expected.

### Cleanup Resources

Once your test is done, you can destroy the resources using Terraform.

```bash
pushd $TERRAFORM_MODULES_DIR
for region in $(echo "$REGIONS" | jq -r '.[]'); do
  if terraform workspace list | grep -q "$region"; then
    terraform workspace select $region
  else
    terraform workspace new $region
    terraform workspace select $region
  fi
  terraform_input_file=$(echo $regional_config | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_FILE')
  terraform_input_variables=$(echo $regional_config | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_VARIABLES')
  terraform destroy -var-file $terraform_input_file -var json_input=$terraform_input_variables --auto-approve
done
popd
```

## References

* [Terraform AWS Provider](https://www.terraform.io/docs/providers/aws/index.html)
* [AWS CLI](https://docs.aws.amazon.com/cli/latest/)
* [AWS Console](https://aws.amazon.com/console/)
