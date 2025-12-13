LOCATION="eastus2"
RESOURCE_GROUP=pod-subnet-ipvlan
CLUSTER_NAME=test
VNET_NAME="aks-vnet"
SUBNET="aks-subnet"
# NODE_SUBNET="subnet0"
# POD_SUBNET="subnet1"

create_cluster() {
    az group create -n ${RESOURCE_GROUP} -l eastus2 --tags "SkipAKSCluster=1" "SkipASB_Audit=true" "SkipLinuxAzSecPack=true"

    az network vnet create --resource-group $RESOURCE_GROUP --location $LOCATION --name $VNET_NAME --address-prefixes 10.0.0.0/8 -o none
    az network vnet subnet create --resource-group $RESOURCE_GROUP --vnet-name $VNET_NAME --name $SUBNET --address-prefixes 10.128.0.0/10 -o none
    # az network vnet subnet create --resource-group $RESOURCE_GROUP --vnet-name $VNET_NAME --name $NODE_SUBNET --address-prefixes 10.240.0.0/12 -o none 
    # az network vnet subnet create --resource-group $RESOURCE_GROUP --vnet-name $VNET_NAME --name $POD_SUBNET --address-prefixes 10.128.0.0/11 -o none

    vnet_id=$(az network vnet show --resource-group $RESOURCE_GROUP --name $VNET_NAME --query id -o tsv)
    subnet_id=$(az network vnet subnet show --resource-group $RESOURCE_GROUP --vnet-name $VNET_NAME --name $SUBNET --query id -o tsv)
    # node_subnet_id=$(az network vnet subnet show --resource-group $RESOURCE_GROUP --vnet-name $VNET_NAME --name $NODE_SUBNET --query id -o tsv)

    # Create user-assigned managed identity
    IDENTITY_NAME="${CLUSTER_NAME}-identity"
    az identity create --name $IDENTITY_NAME --resource-group $RESOURCE_GROUP --location $LOCATION

    # Get the identity resource ID and principal ID
    identity_id=$(az identity show --name $IDENTITY_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)
    identity_principal_id=$(az identity show --name $IDENTITY_NAME --resource-group $RESOURCE_GROUP --query principalId -o tsv)

    # Assign Network Contributor role to the identity to vnet
    az role assignment create --assignee $identity_principal_id --role "Network Contributor" --scope $vnet_id

    az aks create \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${CLUSTER_NAME}" \
        --location $LOCATION \
        --kubernetes-version 1.33.0 \
        --node-count 3 \
        --nodepool-name system \
        --vm-set-type VirtualMachines \
        --node-vm-size Standard_D8ds_v6 \
        --os-sku Ubuntu2404 \
        --network-plugin none \
        --vnet-subnet-id $subnet_id \
        --enable-managed-identity \
        --assign-identity $identity_id
        # --node-osdisk-type Managed \


}

create_secondary_nics() {
    mc_rg="MC_${RESOURCE_GROUP}_${CLUSTER_NAME}_${LOCATION}"
    nsg_name=$(az network nsg list --resource-group $mc_rg --query '[0].name' -o tsv)
    pod_subnet_id=$(az network vnet subnet show --resource-group $RESOURCE_GROUP --vnet-name $VNET_NAME --name $POD_SUBNET --query id -o tsv)
    vm_list=$(az vm list -g $mc_rg --query "[].name" -o tsv)
    for vm in $vm_list; do
        nic_name=${vm}-pod-nic
        az network nic create --resource-group $mc_rg --network-security-group $nsg_name \
            --subnet $pod_subnet_id --name $nic_name \
            --accelerated-networking true --ip-forwarding true
        az vm deallocate --resource-group $mc_rg --name $vm
        az vm nic add --resource-group $mc_rg --vm-name $vm --nics $nic_name
        az vm start --resource-group $mc_rg --name $vm
    done
}

set_up_nic() {
    # cat /etc/netplan/50-cloud-init.yaml
    # ip link set eth1 up
    # ip addr replace 10.128.0.4/11 dev eth1
    mc_rg="MC_${RESOURCE_GROUP}_${CLUSTER_NAME}_${LOCATION}"
    vm_list=$(az vm list -g $mc_rg --query "[].name" -o tsv)
    for vm in $vm_list; do
        nic_name=${vm}-pod-nic
        ip_address=$(az network nic ip-config list --resource-group $mc_rg --nic-name $nic_name --query "[1].privateIPAddress" -o tsv)
        echo "Configuring VM: $vm with IP: $ip_address"

        cat > /etc/cni/net.d/01-ipvlan-eth1.conf << EOF
{
    "cniVersion": "0.3.1",
    "name": "ipvlan-eth1",
    "type": "ipvlan",
    "master": "eth1",
    "mode": "l3s",
    "ipam": {
        "type": "host-local",
        "ranges": [
            [
                {
                    "subnet": "$ip_address"
                }
            ]
        ],
        "routes": [
            { "dst": "0.0.0.0/0" }
        ]
    }
}
EOF

    done
}

# create_cluster
# create_secondary_nics
set_up_nic

# Set up multiple NICs
node_ip="10.128.0.6"
gateway_ip="10.128.0.1"
ipconfig="10.128.0.48/28"
subnet="10.128.0.0/11"
subnet_prefix="11"

ip link set eth1 up
ip addr add $ipconfig dev eth1
ip addr add ${node_ip}/${subnet_prefix} dev eth1

ip route add default via $gateway_ip dev eth1 proto static src $node_ip metric 200
ip route add $gateway_ip dev eth1 proto static src $node_ip metric 200
# ip route add 10.128.0.0/11 dev eth1
ip route add 168.63.129.16 via $gateway_ip proto static src $node_ip metric 200
ip route add 169.254.169.254 via $gateway_ip proto static src $node_ip metric 200

# Set up iptables rules
# iptables -t nat -A POSTROUTING -s $subnet ! -d 10.0.0.0/8 -j MASQUERADE
# iptables -t nat -A POSTROUTING -s $subnet -d 168.63.129.16 -j MASQUERADE
# iptables -t nat -A POSTROUTING -s $subnet -d 169.254.169.254 -j MASQUERADE
iptables -t nat -A POSTROUTING -s $ipconfig ! -d $subnet -j MASQUERADE
iptables -t nat -L POSTROUTING -n -v

iptables -t nat -I KUBE-POSTROUTING 1 -s $ipconfig -d $ipconfig -j RETURN
iptables -t nat -L KUBE-POSTROUTING -n -v


# Cross subnet
another_subnet="10.128.0.0/11"
gateway_ip="10.96.0.1"
node_ip="10.96.0.4"
ip route add $another_subnet via $gateway_ip dev eth1 src $node_ip
iptables -t nat -I KUBE-SVC-TCOU7JCQXEZGVUNU 1 -s 10.128.0.32/28 -d 10.128.0.32/28 -j KUBE-SEP-JUCE2ZC33P3WLTVY