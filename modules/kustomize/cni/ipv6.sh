nic_name="aks-system-32909501-vmsnic-3-5aa59887"
mc_rg="MC_1764636058_cni-test_eastus2"
subnet="/subscriptions/137f0351-8235-42a6-ac7a-6b46be2d21c7/resourceGroups/MC_1764636058_cni-test_eastus2/providers/Microsoft.Network/virtualNetworks/aks-vnet-32558824/subnets/aks-subnet"
az network nic ip-config create -g $mc_rg --nic-name $nic_name --name ipvlan \
    --private-ip-prefix-len 80 --private-ip-address-version IPv6 \
    --subnet $subnet --debug > create.log 2>&1

az network nic ip-config show --name ipvlan --nic-name $nic_name --resource-group $mc_rg

ip -6 addr show
ip -6 route show
ip -6 neigh show dev eth0
ip6tables -t nat -L -v -n
ip6tables -t nat -L POSTROUTING -v -n

ip -6 addr replace fd5d:beb3:90df:4910:1::/80 dev ipvlan-dummy0

kubectl exec pod1 -- ping6 -c1 fd5d:beb3:90df:4910:3::4

kubectl exec pod2 -- ip -6 route show
# fd5d:beb3:90df:4910:2::/80 dev eth0  metric 256 
# fe80::/64 dev eth0  metric 256 
# default via fd5d:beb3:90df:4910:2::1 dev eth0  metric 1024 

root@aks-system-14767067-vms2:/# ip -6 route show
# fd5d:beb3:90df:4910:2::/80 dev eth0 proto kernel metric 256 pref medium
# fe80::/64 dev eth0 proto kernel metric 256 pref medium
# fe80::/64 dev enP30832s1 proto kernel metric 256 pref medium