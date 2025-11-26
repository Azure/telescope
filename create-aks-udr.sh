#!/bin/bash
set -e

# Variables
PREFIX="nap"
RG="${PREFIX}-rg"
LOC="eastus2"
VNET_NAME="${PREFIX}-vnet-ms"
AKS_SUBNET_NAME="${PREFIX}-subnet-ms"
FWSUBNET_NAME="AzureFirewallSubnet"
FWNAME="${PREFIX}-firewall"
FWPUBLICIP_NAME="firewall-pip"
FWIPCONFIG_NAME="${PREFIX}-fw-ipconfig"
FWROUTE_TABLE_NAME="${PREFIX}-rt"
AKSNAME="${PREFIX}-complex"
K8S_VERSION="1.33"

echo "Creating resource group..."
az group create --name $RG --location $LOC

echo "Creating virtual network..."
az network vnet create \
    --resource-group $RG \
    --name $VNET_NAME \
    --location $LOC \
    --address-prefixes 10.192.0.0/10 \
    --subnet-name $AKS_SUBNET_NAME \
    --subnet-prefix 10.192.0.0/16

echo "Creating Azure Firewall subnet..."
az network vnet subnet create \
    --resource-group $RG \
    --vnet-name $VNET_NAME \
    --name $FWSUBNET_NAME \
    --address-prefix 10.193.0.0/26

echo "Creating public IP for firewall..."
az network public-ip create \
    --resource-group $RG \
    --name $FWPUBLICIP_NAME \
    --location $LOC \
    --sku "Standard"

echo "Creating Azure Firewall (this takes ~6 minutes)..."
az network firewall create \
    --resource-group $RG \
    --name $FWNAME \
    --location $LOC \
    --enable-dns-proxy true

echo "Configuring firewall IP configuration..."
az network firewall ip-config create \
    --resource-group $RG \
    --firewall-name $FWNAME \
    --name $FWIPCONFIG_NAME \
    --public-ip-address $FWPUBLICIP_NAME \
    --vnet-name $VNET_NAME

echo "Getting firewall IPs..."
FWPUBLIC_IP=$(az network public-ip show \
    --resource-group $RG \
    --name $FWPUBLICIP_NAME \
    --query "ipAddress" -o tsv)
FWPRIVATE_IP=$(az network firewall show \
    --resource-group $RG \
    --name $FWNAME \
    --query "ipConfigurations[0].privateIPAddress" -o tsv)

echo "Firewall Public IP: $FWPUBLIC_IP"
echo "Firewall Private IP: $FWPRIVATE_IP"

echo "Adding firewall network rules..."
az network firewall network-rule create \
    --resource-group $RG \
    --firewall-name $FWNAME \
    --collection-name 'aksfwnr' \
    --name 'apiudp' \
    --protocols 'UDP' \
    --source-addresses '*' \
    --destination-addresses "AzureCloud.$LOC" \
    --destination-ports 1194 \
    --action allow \
    --priority 100

az network firewall network-rule create \
    --resource-group $RG \
    --firewall-name $FWNAME \
    --collection-name 'aksfwnr' \
    --name 'apitcp' \
    --protocols 'TCP' \
    --source-addresses '*' \
    --destination-addresses "AzureCloud.$LOC" \
    --destination-ports 9000

az network firewall network-rule create \
    --resource-group $RG \
    --firewall-name $FWNAME \
    --collection-name 'aksfwnr' \
    --name 'time' \
    --protocols 'UDP' \
    --source-addresses '*' \
    --destination-fqdns 'ntp.ubuntu.com' \
    --destination-ports 123

echo "Adding firewall application rules..."
az network firewall application-rule create \
    --resource-group $RG \
    --firewall-name $FWNAME \
    --collection-name 'aksfwar' \
    --name 'fqdn' \
    --source-addresses '*' \
    --protocols 'http=80' 'https=443' \
    --fqdn-tags "AzureKubernetesService" \
    --action allow \
    --priority 100

echo "Creating route table..."
az network route-table create \
    --resource-group $RG \
    --location $LOC \
    --name $FWROUTE_TABLE_NAME \
    --disable-bgp-route-propagation true

echo "Creating default route via firewall..."
az network route-table route create \
    --resource-group $RG \
    --name "default-route" \
    --route-table-name $FWROUTE_TABLE_NAME \
    --address-prefix 0.0.0.0/0 \
    --next-hop-type VirtualAppliance \
    --next-hop-ip-address $FWPRIVATE_IP

echo "Creating internet route for firewall public IP..."
az network route-table route create \
    --resource-group $RG \
    --name "firewall-internet" \
    --route-table-name $FWROUTE_TABLE_NAME \
    --address-prefix $FWPUBLIC_IP/32 \
    --next-hop-type Internet

echo "Associating route table to AKS subnet..."
az network vnet subnet update \
    --resource-group $RG \
    --vnet-name $VNET_NAME \
    --name $AKS_SUBNET_NAME \
    --route-table $FWROUTE_TABLE_NAME

echo "Getting subnet ID..."
SUBNET_ID=$(az network vnet subnet show \
    --resource-group $RG \
    --vnet-name $VNET_NAME \
    --name $AKS_SUBNET_NAME \
    --query id -o tsv)

echo "Creating AKS cluster with UDR (this takes ~5-8 minutes)..."
az aks create \
    --resource-group $RG \
    --name $AKSNAME \
    --location $LOC \
    --node-count 3 \
    --network-plugin azure \
    --network-plugin-mode overlay \
    --outbound-type userDefinedRouting \
    --vnet-subnet-id $SUBNET_ID \
    --pod-cidr 10.128.0.0/11 \
    --kubernetes-version $K8S_VERSION \
    --node-vm-size Standard_D4_v5 \
    --tier standard \
    --generate-ssh-keys

echo "Getting AKS credentials..."
az aks get-credentials \
    --resource-group $RG \
    --name $AKSNAME \
    --overwrite-existing

echo "Verifying cluster..."
kubectl get nodes

echo ""
echo "=========================================="
echo "✅ AKS cluster with UDR created successfully!"
echo "Resource Group: $RG"
echo "AKS Cluster: $AKSNAME"
echo "Firewall Public IP: $FWPUBLIC_IP"
echo "Firewall Private IP: $FWPRIVATE_IP"
echo "=========================================="
echo ""
echo "To delete all resources:"
echo "  az group delete --name $RG --yes --no-wait"
