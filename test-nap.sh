# =========================================
# VARIABLES
# =========================================

RG=nap-test
LOCATION=australiaeast

CLUSTER=nap

VNET=nap-vnet
VNET_CIDR=10.192.0.0/10

SUBNET=nap-subnet
SUBNET_CIDR=10.192.0.0/16

IDENTITY=nap-identity

NODEPOOL=system
NODECOUNT=5
VMSIZE=Standard_D4_v5



# =========================================
# CREATE VNET
# =========================================

az network vnet create \
  -g $RG \
  -n $VNET \
  --address-prefixes $VNET_CIDR \
  --subnet-name $SUBNET \
  --subnet-prefixes $SUBNET_CIDR


# =========================================
# GET SUBNET ID (IMPORTANT)
# =========================================

SUBNET_ID=$(az network vnet subnet show \
  -g $RG \
  --vnet-name $VNET \
  -n $SUBNET \
  --query id -o tsv)

echo $SUBNET_ID


# =========================================
# CREATE MANAGED IDENTITY
# =========================================

az identity create \
  -g $RG \
  -n $IDENTITY


# =========================================
# GET IDENTITY RESOURCE ID
# =========================================

IDENTITY_ID=$(az identity show \
  -g $RG \
  -n $IDENTITY \
  --query id -o tsv)

echo $IDENTITY_ID


# =========================================
# GET IDENTITY PRINCIPAL ID
# =========================================

PRINCIPAL_ID=$(az identity show \
  -g $RG \
  -n $IDENTITY \
  --query principalId -o tsv)

echo $PRINCIPAL_ID


# =========================================
# ASSIGN NETWORK CONTRIBUTOR
# =========================================

az role assignment create \
  --assignee-object-id $PRINCIPAL_ID \
  --role "Network Contributor" \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG


# =========================================
# CREATE AKS CLUSTER
# CRITICAL:
# USE FULL SUBNET ID
# =========================================

az aks create \
  -g $RG \
  -n $CLUSTER \
  --location $LOCATION \
  --sku-tier standard \
  --enable-managed-identity \
  --assign-identity $IDENTITY_ID \
  --network-plugin azure \
  --vnet-subnet-id $SUBNET_ID \
  --node-count $NODECOUNT \
  --nodepool-name $NODEPOOL \
  --node-vm-size $VMSIZE \
  --node-init-taints CriticalAddonsOnly=true:NoSchedule \
  --node-provisioning-mode Auto \
  --enable-oidc-issuer \
  --generate-ssh-keys


# =========================================
# GET KUBECONFIG
# =========================================

az aks get-credentials \
  -g $RG \
  -n $CLUSTER \
  --overwrite-existing


# =========================================
# VERIFY CLUSTER SUBNET BINDING
# MUST POINT TO 66998-3093b6fc
# NOT MC_*
# =========================================

az aks show \
  -g $RG \
  -n $CLUSTER \
  --query agentPoolProfiles[0].vnetSubnetId -o tsv


# =========================================
# VERIFY KARPENTER NODECLASS
# =========================================

kubectl get aksnodeclass -o yaml


# =========================================
# EXPECTED RESULT
# =========================================
#
# status:
#   conditions:
#   - type: SubnetsReady
#     status: "True"
#
# =========================================
