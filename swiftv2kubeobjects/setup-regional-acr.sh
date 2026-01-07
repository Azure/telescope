#!/bin/bash
# This script creates a regional ACR and mirrors images to avoid throttling on shared team ACR.
# This is a one-time setup per region that should be run manually before perf tests.

# Prerequisites:
# - Azure CLI installed and logged in
# - Docker installed and running
# - Proper permissions to create ACR and role assignments
# - shared-config.sh with proper configuration

# Usage:
# export LOCATION=<your-region>  # e.g., uksouth, eastus2euap
# ./setup-regional-acr.sh

set -euo pipefail

# Source shared configuration
echo "Loading shared configuration..."
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$SCRIPT_DIR/shared-config.sh"

echo "=========================================="
echo "Regional ACR Setup for Location: $LOCATION"
echo "=========================================="
echo "Regional ACR Name: $REGIONAL_ACR_NAME"
echo "Resource Group: $CUST_RG"
echo "Source ACR: $SOURCE_ACR_NAME"
echo ""

# =============================================================================
# CREATE REGIONAL ACR
# =============================================================================
echo "Step 1: Creating Regional ACR..."

if az acr show --name $REGIONAL_ACR_NAME --resource-group $CUST_RG &>/dev/null; then
  echo "✓ Regional ACR $REGIONAL_ACR_NAME already exists"
else
  echo "Creating regional ACR: $REGIONAL_ACR_NAME (Standard SKU)"
  az acr create \
    --resource-group $CUST_RG \
    --name $REGIONAL_ACR_NAME \
    --sku Standard \
    --location $LOCATION
  
  echo "Waiting for ACR to be fully provisioned..."
  sleep 15
  echo "✓ Regional ACR created successfully"
fi

# Get regional ACR resource ID for role assignments
export REGIONAL_ACR_RESOURCE_ID=$(az acr show \
  --name $REGIONAL_ACR_NAME \
  --resource-group $CUST_RG \
  --query id \
  --output tsv)

echo "Regional ACR Resource ID: $REGIONAL_ACR_RESOURCE_ID"
echo ""

# =============================================================================
# MIRROR IMAGES TO REGIONAL ACR
# =============================================================================
echo "Step 2: Mirroring images to regional ACR..."

echo "Logging into regional ACR: $REGIONAL_ACR_NAME"
az acr login --name $REGIONAL_ACR_NAME

# Function to mirror an image
mirror_image() {
  local source_image=$1
  local source_type=$2  # "acr" or "docker"
  
  # Extract image name and tag
  local image_name=$(echo "$source_image" | rev | cut -d'/' -f1 | rev)  # Extract name:tag from end
  local target_image="$REGIONAL_ACR_NAME.azurecr.io/$image_name"
  
  echo ""
  echo "----------------------------------------"
  echo "Mirroring: $source_image"
  echo "Target: $target_image"
  echo "----------------------------------------"
  
  # Check if image already exists in regional ACR
  local repo_name=$(echo "$image_name" | cut -d':' -f1)
  local image_tag=$(echo "$image_name" | cut -d':' -f2)
  
  if az acr repository show-tags --name $REGIONAL_ACR_NAME --repository $repo_name 2>/dev/null | grep -q "\"$image_tag\""; then
    echo "✓ Image already exists in regional ACR, skipping"
    return 0
  fi
  
  # Login to source ACR if needed
  if [ "$source_type" = "acr" ]; then
    echo "Logging into source ACR ($SOURCE_ACR_NAME)..."
    az account set --subscription $SOURCE_ACR_SUBSCRIPTION
    az acr login --name $SOURCE_ACR_NAME
    az account set --subscription $CUST_SUB
  fi
  
  echo "Pulling from source..."
  docker pull "$source_image"
  
  echo "Tagging for regional ACR..."
  docker tag "$source_image" "$target_image"
  
  echo "Pushing to regional ACR..."
  docker push "$target_image"
  
  echo "✓ Successfully mirrored $image_name"
}

# Mirror datapath-reporter from source ACR
mirror_image "$SOURCE_DATAPATH_REPORTER_IMAGE" "acr"

# Mirror datapath-controller from source ACR
mirror_image "$SOURCE_DATAPATH_CONTROLLER_IMAGE" "acr"

# Mirror nginx from Docker Hub (lightweight ~150MB web server image)
mirror_image "$SOURCE_NGINX_IMAGE" "docker"

echo ""
echo "✓ All images mirrored successfully to regional ACR"
echo ""

# =============================================================================
# GRANT PERMISSIONS TO KUBELET IDENTITY
# =============================================================================
echo "Step 3: Granting AcrPull permissions to kubelet identity..."

# Check if kubelet identity exists
if ! az identity show --name $SHARED_KUBELET_IDENTITY_NAME --resource-group $CUST_RG &>/dev/null; then
  echo "ERROR: Kubelet identity '$SHARED_KUBELET_IDENTITY_NAME' not found!"
  echo "Please run runCustomerSetup.sh first to create the shared identities."
  exit 1
fi

export KUBELET_PRINCIPAL_ID=$(az identity show \
  --name $SHARED_KUBELET_IDENTITY_NAME \
  --resource-group $CUST_RG \
  --query principalId \
  --output tsv)

echo "Kubelet Identity: $SHARED_KUBELET_IDENTITY_NAME (Principal ID: $KUBELET_PRINCIPAL_ID)"

# Grant AcrPull permission to regional ACR only
if az role assignment list --assignee $KUBELET_PRINCIPAL_ID --scope $REGIONAL_ACR_RESOURCE_ID --role AcrPull 2>/dev/null | jq -e 'length > 0' &>/dev/null; then
  echo "✓ AcrPull role assignment already exists for regional ACR"
else
  echo "Creating AcrPull role assignment for regional ACR..."
  az role assignment create \
    --assignee-object-id $KUBELET_PRINCIPAL_ID \
    --assignee-principal-type ServicePrincipal \
    --role AcrPull \
    --scope $REGIONAL_ACR_RESOURCE_ID
  
  echo "✓ AcrPull permission granted successfully"
fi

echo ""
echo "=========================================="
echo "Regional ACR Setup Complete!"
echo "=========================================="
echo "ACR Name: $REGIONAL_ACR_NAME"
echo "ACR URL: $REGIONAL_ACR_NAME.azurecr.io"
echo ""
echo "Mirrored Images:"
echo "  - datapath-reporter:2026.01.05.01"
echo "  - datapath-controller:2026.01.05.01"
echo "  - nginx:latest"
echo ""
echo "Next Steps:"
echo "  1. Update your pipeline to use: $REGIONAL_ACR_NAME.azurecr.io"
echo "  2. Run your performance tests"
echo "=========================================="
