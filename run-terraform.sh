# Check prerequisites
echo "🔍 Checking prerequisites..."
echo "==========================================="

# Check Terraform
if command -v terraform &> /dev/null; then
    TERRAFORM_VERSION=$(terraform version -json | jq -r '.terraform_version')
    echo "✅ Terraform: $TERRAFORM_VERSION"
else
    echo "❌ Terraform not found"
fi

# Check Azure CLI
if command -v az &> /dev/null; then
    AZ_VERSION=$(az version --output tsv --query '"azure-cli"')
    echo "✅ Azure CLI: $AZ_VERSION"
else
    echo "❌ Azure CLI not found"
fi

# Check jq
if command -v jq &> /dev/null; then
    JQ_VERSION=$(jq --version)
    echo "✅ jq: $JQ_VERSION"
else
    echo "❌ jq not found"
fi

echo ""
echo "📍 Current directory: $(pwd)"
echo "💡 Make sure you're running from the telescope repository root"

# Navigate to repository root if not already there
if [ ! -f "scenarios" ] && [ ! -d "scenarios" ]; then
    echo "🔄 Navigating to repository root..."
    cd ../../../
    echo "📍 New directory: $(pwd)"
    export ROOT_DIR=$(pwd)
fi
export ROOT_DIR=$(pwd)
# step 2 define variables
# Define test scenario variables
export SCENARIO_TYPE=perf-eval
export SCENARIO_NAME=nap
export OWNER=$(whoami)
export RUN_ID=$(date +%s)
export CLOUD=azure
export REGION=eastus2
export AZURE_SUBSCRIPTION_ID="c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
export SKU_TIER="Standard"
export KUBERNETES_VERSION="1.33"
export NETWORK_POLICY=""
export NETWORK_DATAPLANE=""
export TERRAFORM_MODULES_DIR=$ROOT_DIR/modules/terraform/$CLOUD
export TERRAFORM_INPUT_FILE=$ROOT_DIR/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/azure-cli.tfvars
export SYSTEM_NODE_POOL=${SYSTEM_NODE_POOL:-null}
export USER_NODE_POOL=${USER_NODE_POOL:-null}

echo "📋 Configuration Summary:"
echo "========================"
echo "Scenario: $SCENARIO_TYPE/$SCENARIO_NAME"
echo "Owner: $OWNER"
echo "Run ID: $RUN_ID"
echo "Cloud: $CLOUD"
echo "Region: $REGION"
echo "SKU Tier: $SKU_TIER"
echo "Kubernetes Version: $KUBERNETES_VERSION"
echo "Network Policy: $NETWORK_POLICY"
echo "Network Dataplane: $NETWORK_DATAPLANE"
echo "Terraform Input File: $TERRAFORM_INPUT_FILE"
echo ""
echo "⚠️  Note: RUN_ID should be unique as it's used to name the Azure resource group"


# step 3
# Azure login
echo "🔐 Azure Authentication"
echo "======================"

# Check if already logged in
if az account show &> /dev/null; then
    echo "✅ Already logged into Azure"
    az account set -s $AZURE_SUBSCRIPTION_ID
    CURRENT_SUB=$(az account show --query name -o tsv)
    echo "Current subscription: $CURRENT_SUB"    
else
    echo "🌐 Logging into Azure..."
    az login --use-device-code
    az account set -s $AZURE_SUBSCRIPTION_ID
fi

echo ""
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
export ARM_TENANT_ID=$(az account show --query tenantId -o tsv)

# Verify subscription
az account show --query "{Name:name, SubscriptionId:id, State:state}" --output table 


# step 3 create resource group 

# Create Resource Group
echo "🏗️  Creating Azure Resource Group"
echo "================================="

# Create resource group with appropriate tags
az group create \
  --name $RUN_ID \
  --location $REGION \
  --tags \
    "run_id=$RUN_ID" \
    "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" \
    "owner=${OWNER}" \
    "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"

echo ""
echo "✅ Resource Group Created: $RUN_ID"
echo "📍 Location: $REGION"
echo "⏰ Deletion due time: $(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"


# step 4 terraform input

# Create INPUT_JSON variable
echo "📝 Preparing Terraform Input JSON"
echo "================================="

export INPUT_JSON=$(jq -n \
  --arg run_id $RUN_ID \
  --arg region $REGION \
  --arg aks_sku_tier "$SKU_TIER" \
  --arg aks_kubernetes_version "$KUBERNETES_VERSION" \
  --arg aks_network_policy "$NETWORK_POLICY" \
  --arg aks_network_dataplane "$NETWORK_DATAPLANE" \
  --arg k8s_machine_type "$K8S_MACHINE_TYPE" \
  --arg k8s_os_disk_type "$K8S_OS_DISK_TYPE" \
  --argjson aks_cli_system_node_pool "$SYSTEM_NODE_POOL" \
  --argjson aks_cli_user_node_pool "$USER_NODE_POOL" \
  '{
    run_id: $run_id,
    region: $region,
    aks_sku_tier: $aks_sku_tier,
    aks_kubernetes_version: $aks_kubernetes_version,
    aks_network_policy: $aks_network_policy,
    aks_network_dataplane: $aks_network_dataplane,
    k8s_machine_type: $k8s_machine_type,
    k8s_os_disk_type: $k8s_os_disk_type,
    aks_cli_system_node_pool: $aks_cli_system_node_pool,
    aks_cli_user_node_pool: $aks_cli_user_node_pool
  }' | jq 'with_entries(select(.value != null and .value != ""))')

echo "📋 Terraform Input JSON:"
echo "$INPUT_JSON" | jq .

echo ""
echo "📂 Terraform Input File: $TERRAFORM_INPUT_FILE"
if [ -f "$TERRAFORM_INPUT_FILE" ]; then
    echo "✅ Terraform input file exists"
    echo "📄 Contents of terraform input file:"
    cat "$TERRAFORM_INPUT_FILE"
else
    echo "⚠️  Terraform input file not found at: $TERRAFORM_INPUT_FILE"
fi

echo ""
echo "💡 Note: The jq command removes any null or empty values from the JSON object"
echo "💡 Note: Variables surrounded by double quotes are optional and can be removed if not needed"


#step 6 Terraform initialization
echo "🚀 Terraform Initialization"
echo "==========================="

# Change to terraform directory
pushd $TERRAFORM_MODULES_DIR

echo "📂 Current directory: $(pwd)"
echo "🔧 Initializing Terraform..."
terraform init
echo "🚀 Terraform Plan"
echo "==========================="
terraform plan \
  -var json_input="$(echo $INPUT_JSON | jq -c .)" \
  -var-file $TERRAFORM_INPUT_FILE

echo ""
popd

# Terraform apply
echo "🚀 Terraform Apply"
echo "=================="

echo "⚠️  WARNING: This will provision actual Azure resources!"
echo "💰 This may incur costs in your Azure subscription"
echo "⏰ Resources will be tagged for deletion in 2 hours"
echo ""

pushd $TERRAFORM_MODULES_DIR
terraform apply -var json_input="$(echo $INPUT_JSON | jq -c .)" -var-file $TERRAFORM_INPUT_FILE --auto-approve
popd

# Cleanup with Terraform
echo "🧹 Terraform Cleanup"
echo "====================="

echo "⚠️  WARNING: This will destroy all provisioned resources!"
echo "💾 Make sure to save any important data before proceeding"
echo ""

pushd $TERRAFORM_MODULES_DIR
terraform destroy -var json_input="$(echo $INPUT_JSON | jq -c .)" -var-file $TERRAFORM_INPUT_FILE --auto-approve
popd

# Final cleanup - Delete Resource Group
echo "🗑️  Final Cleanup"
echo "================"

echo "🧹 After Terraform destroys resources, delete the resource group:"
echo ""
az group delete --name $RUN_ID -y

echo "✅ This will ensure all resources are completely removed"
echo "💰 This prevents any lingering costs from orphaned resources"