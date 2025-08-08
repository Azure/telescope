#!/bin/bash
# Shared configuration for customer setup scripts
# This file should be sourced by both runCustomerSetup.sh and createclusterforping.sh

# Common subscription and location settings
SUB=${SUB:-"9b8218f9-902a-4d20-a65c-e98acec5362f"}
LOCATION=${LOCATION:-"uksouth"}

# Customer VNet configuration
CUST_VNET_NAME="custvnet"
CUST_SCALE_DEL_SUBNET="scaledel"
CUST_AKS_NODE_SUBNET="aksnodes"
CUST_AKS_POD_SUBNET="akspods"

# Resource group naming - use dynamic naming based on location
CUST_RG="sv2-perf-cust-$LOCATION"

# Shared identity names
SHARED_KUBELET_IDENTITY_NAME="sharedKubeletIdentity"
SHARED_CONTROL_PLANE_IDENTITY_NAME="sharedControlPlaneIdentity"

# Export all variables so they're available to child processes
export SUB LOCATION CUST_VNET_NAME CUST_SCALE_DEL_SUBNET CUST_AKS_NODE_SUBNET CUST_AKS_POD_SUBNET
export CUST_RG SHARED_KUBELET_IDENTITY_NAME SHARED_CONTROL_PLANE_IDENTITY_NAME
