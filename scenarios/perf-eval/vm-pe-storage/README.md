## Overview

This guide covers how to manually run vm -> pe -> storage account https test on Azure

### Prerequisite
* Install Terraform (https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install Azure CLI (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)

### Define Variables
Set environment variables for testing
```
CLOUD=azure
ssh_key_path=$(pwd)/modules/terraform/$CLOUD/private_key.pem
ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N ""
SSH_PUBLIC_KEY_PATH="${ssh_key_path}.pub"
export SCENARIO_TYPE=perf-eval
export SCENARIO_NAME=vm-pe-storage
export RUN_ID=0003
export OWNER=$(whoami)
export RESULT_PATH=/tmp/$RUN_ID
export TEMP_JMETER=/tmp/jmeter
export CLOUD=azure
export REGION=eastus
export MACHINE_TYPE=Standard_D2s_v5
export ACCERLATED_NETWORKING=true
export CLIENT_ROLE=client
export TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
export TEST_MODULES_DIR=modules/bash
export USER_DATA_PATH=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/bash-scripts
export TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/$CLOUD.tfvars
export SSH_KEY_PATH=$(pwd)/modules/terraform/$CLOUD/private_key.pem
export STORAGE_ACCOUNT_TIER=Standard
export STORAGE_ACCOUNT_REPLICATION_TYPE=LRS
export STORAGE_SHARE_ENABLED_PROTOCOL=NFS
```

### Provision Resources

Login into Azure account and set subscription for testing
```
az login
az account set --subscription <subscriptionId>
```

If this is on a un-managed device without web browser like Linux devbox, please create a service principle first
```
az ad sp create-for-rbac --name <servicePrincipleName> --role contributor --scopes /subscriptions/<subscriptionId>
{
  "appId": "xxx",
  "displayName": "xxx",
  "password": "xxx",
  "tenant": "xxx"
}
```

and then login with service principle
```
az login --service-principal --username <appId> --password <password> --tenant <tenant>
```

Provision test resources using terraform
```
INPUT_JSON=$(jq -n \
--arg owner "$OWNER" \
--arg run_id "$RUN_ID" \
--arg region "$REGION" \
--arg machine_type "$MACHINE_TYPE" \
--arg accelerated_networking "$ACCERLATED_NETWORKING" \
--arg user_data_path "$USER_DATA_PATH" \
--arg public_key_path "$SSH_PUBLIC_KEY_PATH" \
--arg storage_account_tier "$STORAGE_ACCOUNT_TIER" \
--arg storage_account_replication_type "$STORAGE_ACCOUNT_REPLICATION_TYPE" \
--arg storage_share_enabled_protocol "$STORAGE_SHARE_ENABLED_PROTOCOL" \
'{owner: $owner, run_id: $run_id, region: $region, machine_type: $machine_type, accelerated_networking: $accelerated_networking,user_data_path:$user_data_path,public_key_path:$public_key_path,storage_account_tier:$storage_account_tier,storage_account_replication_type:$storage_account_replication_type,storage_share_enabled_protocol:$storage_share_enabled_protocol}')
 
az group create --name $RUN_ID --location $REGION --tags "run_id=$RUN_ID" "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" "owner=azure_devops" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"

pushd $TERRAFORM_MODULES_DIR
terraform init
terraform plan -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE --auto-approve
popd
```

### Validate Resources
Validate client VM is running and ready for https traffic
```
VM_ID=$(az resource list --resource-type Microsoft.Compute/virtualMachines --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '${CLIENT_ROLE}')].id" --output tsv)
VM_PUBLIC_IP=$(az vm list-ip-addresses --ids $VM_ID --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
```

Validate pe is deployed and ready for https traffic
```
PE_ID=$(az resource list --resource-type Microsoft.Network/privateEndpoints --query "[?(resourceGroup == '${RUN_ID}')].id" -o tsv)
PE_IP=$(az network private-endpoint show --ids $PE_ID --query 'customDnsConfigs[0].ipAddresses[0]' -o tsv)
```

Validate storage account name and create Azure REST API endpoint
```
STORAGE_NAME=$(az storage account list --resource-group $RUN_ID --query '[].name' -o tsv)

STORAGE_ENDPONT=/subscriptions/<subscriptionId>/resourceGroups/$RUN_ID/providers/Microsoft.Storage/storageAccounts/$STORAGE_NAME/fileServices/default/shares?api-version=2023-01-01
(this value can be changed out for any Azure Storage REST Api Endpoint, this specific one is to Get all fileshares for the given account name)
```

Retrieve Azure account access token to be passed in with https request as auth bearer token
```
token=$(az account get-access-token --query accessToken --output tsv)
```

### Execute Tests
Leverage scp to transfer jmeter properties and text.jmx files to client vm
```
source ./${TEST_MODULES_DIR}/jmeter.sh

run_scp_remote $ssh_key_path ubuntu $VM_PUBLIC_IP 2222 "${USER_DATA_PATH}/jmeter.properties" "${TEMP_JMETER}/jmeter.properties"
run_scp_remote $ssh_key_path ubuntu $VM_PUBLIC_IP 2222 "${USER_DATA_PATH}/https_test.jmx" "${TEMP_JMETER}/${cloud}/https_test.jmx"

mkdir -p $RESULT_PATH
```

Execute jmeter test for single thread @ 100 loops (this is a constraint of Azure REST Api, after an undisclosed amount of request, the api will continuously return 429 bad request responses)
```
JMETER_HTTP_PROPERTY="-JProtocol=https -JPort=443 -Jip_address=$PE_IP -Jthread_num=1 -Jloop_count=100 -Japi_endpoint=$STORAGE_ENDPONT -Jauth_token=$token -Jrequest_delay=200"
run_jmeter $VM_PUBLIC_IP $ssh_key_path https 1 "$JMETER_HTTP_PROPERTY" "$TEMP_JMETER/$cloud" $RESULT_PATH
```

### Collect Results
Collect and parse jmeter https test result(s)
```
collect_result_jmeter https 1 $RESULT_PATH $RUN_ID "" ""
```

Check the results
```
cat $RESULT_PATH/results.json | jq .
```

### Cleanup Resources
Cleanup test resources using terraform
```
pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
popd
```