#!/bin/bash

################################################################################
# Telescope Azure Local Development Script
################################################################################
# This script provides a comprehensive workflow for manually running Terraform
# for Azure telescope testing. All commands should be run from the root of the
# repository and in a bash shell (Linux or WSL).
#
# Usage: ./azure-local-dev.sh [init|plan|apply|destroy|cleanup]
################################################################################

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

################################################################################
# 1. PREREQUISITES CHECK
################################################################################
check_prerequisites() {
    echo -e "${BLUE}🔍 Checking prerequisites...${NC}"
    echo "==========================================="
    
    local all_ok=true
    
    # Check Terraform
    if command -v terraform &> /dev/null; then
        TERRAFORM_VERSION=$(terraform version -json | jq -r '.terraform_version' 2>/dev/null || echo "unknown")
        echo -e "${GREEN}✅ Terraform: $TERRAFORM_VERSION${NC}"
    else
        echo -e "${RED}❌ Terraform not found${NC}"
        all_ok=false
    fi
    
    # Check Azure CLI
    if command -v az &> /dev/null; then
        AZ_VERSION=$(az version --output json | jq -r '.["azure-cli"]' 2>/dev/null || echo "unknown")
        echo -e "${GREEN}✅ Azure CLI: $AZ_VERSION${NC}"
    else
        echo -e "${RED}❌ Azure CLI not found${NC}"
        all_ok=false
    fi
    
    # Check jq
    if command -v jq &> /dev/null; then
        JQ_VERSION=$(jq --version)
        echo -e "${GREEN}✅ jq: $JQ_VERSION${NC}"
    else
        echo -e "${RED}❌ jq not found${NC}"
        all_ok=false
    fi
    
    echo ""
    echo -e "📍 Current directory: $(pwd)"
    
    # Navigate to repository root if not already there
    if [ ! -f "scenarios" ] && [ ! -d "scenarios" ]; then
        echo -e "${YELLOW}🔄 Navigating to repository root...${NC}"
        cd ../../../
        echo -e "📍 New directory: $(pwd)"
    fi
    
    export ROOT_DIR=$(pwd)
    
    if [ "$all_ok" = false ]; then
        echo -e "${RED}❌ Some prerequisites are missing. Please install them first.${NC}"
        exit 1
    fi
}

################################################################################
# 2. DEFINE VARIABLES
################################################################################
define_variables() {
    echo -e "${BLUE}📝 Defining environment variables...${NC}"
    
    # Define test scenario variables
    export SCENARIO_TYPE=${SCENARIO_TYPE:-perf-eval}
    export SCENARIO_NAME=${SCENARIO_NAME:-nap}
    export OWNER=${OWNER:-$(whoami)}
    export RUN_ID=${RUN_ID:-$(date +%s)}
    export CLOUD=${CLOUD:-azure}
    export REGION=${REGION:-eastus2}
    export AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID:-"c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"}
    export SKU_TIER=${SKU_TIER:-""}
    export KUBERNETES_VERSION=${KUBERNETES_VERSION:-""}
    export NETWORK_POLICY=${NETWORK_POLICY:-""}
    export NETWORK_DATAPLANE=${NETWORK_DATAPLANE:-""}
    export K8S_MACHINE_TYPE=${K8S_MACHINE_TYPE:-""}
    export K8S_OS_DISK_TYPE=${K8S_OS_DISK_TYPE:-""}
    export SYSTEM_NODE_POOL=${SYSTEM_NODE_POOL:-null}
    export USER_NODE_POOL=${USER_NODE_POOL:-null}
    
    export TERRAFORM_MODULES_DIR=$ROOT_DIR/modules/terraform/$CLOUD
    export TERRAFORM_INPUT_FILE=$ROOT_DIR/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
    
    echo -e "${GREEN}📋 Configuration Summary:${NC}"
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
    echo -e "${YELLOW}⚠️  Note: RUN_ID should be unique as it's used to name the Azure resource group${NC}"
}

################################################################################
# 3. AZURE AUTHENTICATION
################################################################################
azure_auth() {
    echo -e "${BLUE}🔐 Azure Authentication${NC}"
    echo "======================"
    
    # Check if already logged in
    if az account show &> /dev/null; then
        echo -e "${GREEN}✅ Already logged into Azure${NC}"
        az account set -s $AZURE_SUBSCRIPTION_ID
        CURRENT_SUB=$(az account show --query name -o tsv)
        echo "Current subscription: $CURRENT_SUB"
    else
        echo -e "${YELLOW}🌐 Logging into Azure...${NC}"
        az login --use-device-code
        az account set -s $AZURE_SUBSCRIPTION_ID
    fi
    
    echo ""
    export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
    export ARM_TENANT_ID=$(az account show --query tenantId -o tsv)
    
    # Verify subscription
    echo -e "${GREEN}✅ Subscription verified:${NC}"
    az account show --query "{Name:name, SubscriptionId:id, State:state}" --output table
}

################################################################################
# 4. CREATE RESOURCE GROUP
################################################################################
create_resource_group() {
    echo -e "${BLUE}🏗️  Creating Azure Resource Group${NC}"
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
            "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')" 2>/dev/null || true
    
    echo ""
    echo -e "${GREEN}✅ Resource Group Created: $RUN_ID${NC}"
    echo "📍 Location: $REGION"
    echo -e "⏰ Deletion due time: $(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')${NC}"
}

################################################################################
# 5. PREPARE TERRAFORM INPUT JSON
################################################################################
prepare_terraform_json() {
    echo -e "${BLUE}📝 Preparing Terraform Input JSON${NC}"
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
    
    echo -e "${GREEN}📋 Terraform Input JSON:${NC}"
    echo "$INPUT_JSON" | jq .
    
    echo ""
    echo "📂 Terraform Input File: $TERRAFORM_INPUT_FILE"
    if [ -f "$TERRAFORM_INPUT_FILE" ]; then
        echo -e "${GREEN}✅ Terraform input file exists${NC}"
        echo "📄 Contents of terraform input file:"
        cat "$TERRAFORM_INPUT_FILE"
    else
        echo -e "${YELLOW}⚠️  Terraform input file not found at: $TERRAFORM_INPUT_FILE${NC}"
    fi
    
    echo ""
    echo -e "${YELLOW}💡 Note: The jq command removes any null or empty values from the JSON object${NC}"
}

################################################################################
# 6. TERRAFORM INITIALIZATION
################################################################################
terraform_init() {
    echo -e "${BLUE}🔧 Terraform Initialization${NC}"
    echo "==========================="
    
    if [ ! -d "$TERRAFORM_MODULES_DIR" ]; then
        echo -e "${RED}❌ Terraform modules directory not found: $TERRAFORM_MODULES_DIR${NC}"
        exit 1
    fi
    
    pushd "$TERRAFORM_MODULES_DIR" > /dev/null
    
    echo -e "📂 Working directory: $(pwd)${NC}"
    echo "Initializing Terraform..."
    terraform init
    
    popd > /dev/null
    echo -e "${GREEN}✅ Terraform initialization complete${NC}"
}

################################################################################
# 7. TERRAFORM PLAN
################################################################################
terraform_plan() {
    echo -e "${BLUE}🚀 Terraform Plan${NC}"
    echo "==========================="
    
    pushd "$TERRAFORM_MODULES_DIR" > /dev/null
    
    terraform plan \
        -var "json_input=$(echo $INPUT_JSON | jq -c .)" \
        -var-file "$TERRAFORM_INPUT_FILE"
    
    popd > /dev/null
    echo -e "${GREEN}✅ Terraform plan complete${NC}"
}

################################################################################
# 8. TERRAFORM APPLY
################################################################################
terraform_apply() {
    echo -e "${RED}🚀 Terraform Apply${NC}"
    echo "=================="
    
    echo -e "${RED}⚠️  WARNING: This will provision actual Azure resources!${NC}"
    echo -e "${YELLOW}💰 This may incur costs in your Azure subscription${NC}"
    echo "⏰ Resources will be tagged for deletion in 2 hours"
    echo ""
    
    read -p "Do you want to proceed? (yes/no): " response
    if [[ ! "$response" =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Aborted."
        return 1
    fi
    
    pushd "$TERRAFORM_MODULES_DIR" > /dev/null
    
    terraform apply \
        -var "json_input=$(echo $INPUT_JSON | jq -c .)" \
        -var-file "$TERRAFORM_INPUT_FILE" \
        --auto-approve
    
    popd > /dev/null
    echo -e "${GREEN}✅ Terraform apply complete${NC}"
}

################################################################################
# 9. TERRAFORM DESTROY
################################################################################
terraform_destroy() {
    echo -e "${RED}🧹 Terraform Destroy${NC}"
    echo "====================="
    
    echo -e "${RED}⚠️  WARNING: This will destroy all provisioned resources!${NC}"
    echo -e "${YELLOW}💾 Make sure to save any important data before proceeding${NC}"
    echo ""
    
    read -p "Do you want to proceed? (yes/no): " response
    if [[ ! "$response" =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Aborted."
        return 1
    fi
    
    pushd "$TERRAFORM_MODULES_DIR" > /dev/null
    
    terraform destroy \
        -var "json_input=$(echo $INPUT_JSON | jq -c .)" \
        -var-file "$TERRAFORM_INPUT_FILE" \
        --auto-approve
    
    popd > /dev/null
    echo -e "${GREEN}✅ Terraform destroy complete${NC}"
}

################################################################################
# 10. DELETE RESOURCE GROUP
################################################################################
delete_resource_group() {
    echo -e "${BLUE}🗑️  Final Cleanup${NC}"
    echo "================"
    
    echo -e "${YELLOW}⚠️  This will delete the resource group: $RUN_ID${NC}"
    
    read -p "Do you want to proceed? (yes/no): " response
    if [[ ! "$response" =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Aborted."
        return 1
    fi
    
    echo "🧹 Deleting resource group..."
    az group delete --name $RUN_ID -y 2>/dev/null || true
    
    echo -e "${GREEN}✅ Resource group deletion complete${NC}"
    echo "💰 This ensures all resources are completely removed and prevents lingering costs"
}

################################################################################
# 11. TERRAFORM VALIDATE
################################################################################
terraform_validate() {
    echo -e "${BLUE}✅ Terraform Validate${NC}"
    echo "====================="
    
    pushd "$TERRAFORM_MODULES_DIR" > /dev/null
    
    terraform validate
    
    popd > /dev/null
    echo -e "${GREEN}✅ Terraform validation complete${NC}"
}

################################################################################
# MAIN WORKFLOW
################################################################################
main() {
    local command=${1:-all}
    
    case "$command" in
        prerequisites)
            check_prerequisites
            ;;
        variables)
            check_prerequisites
            define_variables
            ;;
        auth)
            check_prerequisites
            define_variables
            azure_auth
            ;;
        init)
            check_prerequisites
            define_variables
            terraform_init
            ;;
        plan)
            check_prerequisites
            define_variables
            azure_auth
            terraform_init
            prepare_terraform_json
            terraform_plan
            ;;
        validate)
            check_prerequisites
            define_variables
            terraform_validate
            ;;
        apply)
            check_prerequisites
            define_variables
            azure_auth
            create_resource_group
            terraform_init
            prepare_terraform_json
            terraform_plan
            terraform_apply
            ;;
        destroy)
            check_prerequisites
            define_variables
            terraform_destroy
            delete_resource_group
            ;;
        cleanup)
            check_prerequisites
            define_variables
            terraform_destroy
            delete_resource_group
            ;;
        all)
            check_prerequisites
            define_variables
            azure_auth
            create_resource_group
            terraform_init
            prepare_terraform_json
            terraform_plan
            terraform_apply
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo -e "${RED}❌ Unknown command: $command${NC}"
            show_help
            exit 1
            ;;
    esac
}

################################################################################
# HELP MESSAGE
################################################################################
show_help() {
    cat << EOF
${BLUE}Telescope Azure Local Development Script${NC}

${GREEN}Usage:${NC}
    ./azure-local-dev.sh [command] [OPTIONS]

${GREEN}Commands:${NC}
    prerequisites       Check if all required tools are installed
    variables           Define and display environment variables
    auth                Authenticate with Azure
    init                Initialize Terraform
    validate            Validate Terraform configuration
    plan                Run Terraform plan (includes init, auth, resource group)
    apply               Full workflow: init, plan, and apply (creates resources)
    destroy             Destroy Terraform resources
    cleanup             Destroy resources and delete resource group
    all                 Full workflow (default)
    help                Show this help message

${GREEN}Environment Variables:${NC}
    SCENARIO_TYPE       Test scenario type (default: perf-eval)
    SCENARIO_NAME       Test scenario name (default: nap)
    OWNER               Owner of resources (default: current user)
    CLOUD               Cloud provider (default: azure)
    REGION              Azure region (default: eastus2)
    SKU_TIER            AKS SKU tier (optional)
    KUBERNETES_VERSION  Kubernetes version (optional)
    NETWORK_POLICY      Network policy (optional)
    NETWORK_DATAPLANE   Network dataplane (optional)

${GREEN}Examples:${NC}
    # Check prerequisites
    ./azure-local-dev.sh prerequisites

    # Validate Terraform configuration
    ./azure-local-dev.sh validate

    # Run full workflow
    ./azure-local-dev.sh all

    # Destroy resources
    ./azure-local-dev.sh destroy

    # Custom scenario
    SCENARIO_NAME=my-scenario ./azure-local-dev.sh apply

${YELLOW}⚠️  WARNING:${NC}
    - 'apply' and 'destroy' commands will prompt for confirmation
    - 'apply' will create actual Azure resources and may incur costs
    - Always run 'cleanup' after testing to avoid lingering costs

${GREEN}For more information:${NC}
    See azure.ipynb for detailed step-by-step guide
EOF
}

# Run main function
main "$@"
