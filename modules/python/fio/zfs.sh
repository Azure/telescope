rg="zfs-test"
cluster="test"
nodepool="gpu"
az group create --name $rg --location eastus
az aks create --resource-group $rg --name $cluster --node-count 3 \
    --node-vm-size Standard_D4_v3 \
    --generate-ssh-keys --kubernetes-version 1.31
az aks nodepool add --resource-group $rg --cluster-name $cluster \
    --name $nodepool --node-count 1 --node-vm-size Standard_NC24ads_A100_v4 \
    --node-taints sku=gpu:NoSchedule

az aks get-credentials --resource-group $rg --name $cluster

cluster="new"


# Check quota
az vm list-skus --size Standard_ND96asr_v4 -o table
az vm list-skus --size Standard_ND96isr_H100_v5 -o table

helm install zfs-localpv https://openebs.github.io/zfs-localpv/zfs-localpv-2.6.2.tgz -n openebs --create-namespace --skip-crds --set crds.csi.volumeSnapshots.enabled=false
