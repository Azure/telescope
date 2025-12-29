#!/bin/bash
# Shared configuration for customer setup scripts
# This file should be sourced by both runCustomerSetup.sh and createclusterforping.sh

# Common subscription and location settings
export CUST_SUB="37deca37-c375-4a14-b90a-043849bd2bf1"
export SD_SUB="9b8218f9-902a-4d20-a65c-e98acec5362f"
export LOCATION=${LOCATION:-"eastus2euap"}

# Customer VNet configuration
export CUST_VNET_NAME="custvnet"
export CUST_SCALE_DEL_SUBNET="scaledel"
export CUST_AKS_NODE_SUBNET="aksnodes"
export CUST_AKS_POD_SUBNET="akspods"

# Resource group naming - use dynamic naming based on location
export CUST_RG="sv2-perf-cust-$LOCATION"

# Shared identity names
export SHARED_KUBELET_IDENTITY_NAME="sharedKubeletIdentity"
export SHARED_CONTROL_PLANE_IDENTITY_NAME="sharedControlPlaneIdentity"

# Shared ACR configuration - use centralized ACR regardless of region/subscription
export ACR_NAME="acndev"
export ACR_RESOURCE_ID="/subscriptions/9b8218f9-902a-4d20-a65c-e98acec5362f/resourceGroups/acn-shared-resources/providers/Microsoft.ContainerRegistry/registries/acndev"
export ACR_SUBSCRIPTION="9b8218f9-902a-4d20-a65c-e98acec5362f"

# Export all variables so they're available to child processes
export CUST_SUB LOCATION CUST_VNET_NAME CUST_SCALE_DEL_SUBNET CUST_AKS_NODE_SUBNET CUST_AKS_POD_SUBNET
export CUST_RG SHARED_KUBELET_IDENTITY_NAME SHARED_CONTROL_PLANE_IDENTITY_NAME
export ACR_NAME ACR_RESOURCE_ID ACR_SUBSCRIPTION