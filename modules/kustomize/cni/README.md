# AKS Integration

## Setup Cluster

```bash
RESOURCE_GROUP=$(date +%s)
CLUSTER_NAME=test
LOCATION=eastus2

az group create -n ${RESOURCE_GROUP} -l $LOCATION --tags "SkipAKSCluster=1" "SkipASB_Audit=true" "SkipLinuxAzSecPack=true"

az aks create -l $LOCATION \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${CLUSTER_NAME}" \
    --tier standard \
    --kubernetes-version 1.33.0 \
    --network-plugin none \
    --nodepool-name system \
    --vm-set-type VirtualMachines \
    --node-vm-size Standard_D8ds_v6 \
    --node-count 3 \
    --os-sku Ubuntu2404
    # --ip-families "IPv4,IPv6"
    # --aks-custom-headers AKSHTTPCustomFeatures="CustomIPV6SupportedPodSubnet,CustomIPV6SupportedPodSubnetIPAddressPrefixLength=80" \
    # --debug

az aks get-credentials -n ${CLUSTER_NAME} -g ${RESOURCE_GROUP}
```

## Setup CNI

```bash
python3 setup.py \
  --resource-group "${RESOURCE_GROUP}" \
  --cluster-name "${CLUSTER_NAME}" \
  --address-version "IPv4" \
  --ipvlan-config-count 2 \
  --boostrap-cni-config True
```

## Test CNI

```bash
kubectl apply -f deployment.yaml
```

```bash
kubectl apply -f service.yaml
```

```bash
kubectl apply -f iperf3.yaml
```
