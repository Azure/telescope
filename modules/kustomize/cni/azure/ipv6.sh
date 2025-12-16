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

# Node 1
# Subnet: fd5d:beb3:90df:4910:2::/80, Gateway: fd5d:beb3:90df:4910:2::1
ip -6 addr add fd5d:beb3:90df:4910:2::/80 dev ipvlan-dummy0
ip -6 route add fd5d:beb3:90df:4910:3::/80 via fd5d:beb3:90df:4910:3::1 dev eth0 onlink
ip -6 route add fd5d:beb3:90df:4910:1::/80 via fd5d:beb3:90df:4910:1::1 dev eth0 onlink
# Node 2
# Subnet: fd5d:beb3:90df:4910:3::/80, Gateway: fd5d:beb3:90df:4910:3::1
ip -6 addr add fd5d:beb3:90df:4910:3::/80 dev ipvlan-dummy0
ip -6 route add fd5d:beb3:90df:4910:2::/80 via fd5d:beb3:90df:4910:2::1 dev eth0 onlink
ip -6 route add fd5d:beb3:90df:4910:1::/80 via fd5d:beb3:90df:4910:1::1 dev eth0 onlink
# Node 3
# Subnet: fd5d:beb3:90df:4910:1::/80, Gateway: fd5d:beb3:90df:4910:1::1
ip -6 addr add fd5d:beb3:90df:4910:1::/80 dev ipvlan-dummy0
ip -6 route add fd5d:beb3:90df:4910:2::/80 via fd5d:beb3:90df:4910:2::1 dev eth0 onlink
ip -6 route add fd5d:beb3:90df:4910:3::/80 via fd5d:beb3:90df:4910:3::1 dev eth0 onlink

dummy_name="ipvlan"
subnet_prefix="fdb5:7b65:a6ea:436e::/64"
node_range="fdb5:7b65:a6ea:436e:1000::/80"
node_range="fdb5:7b65:a6ea:436e:2000::/80"
node_range="fdb5:7b65:a6ea:436e:3000::/80"

# Create and configure dummy interface
ip link add ${dummy_name} type dummy || true
ip link set ${dummy_name} up
ip -6 addr replace ${node_range} dev ${dummy_name}

# Extract prefix and add a specific /128 gateway address
gateway_ip=$(echo ${node_range} | cut -d/ -f1 | sed 's/::$/::1/')
ip -6 addr add ${gateway_ip}/80 dev ${dummy_name} 2>/dev/null || true

# Enable IPv6 forwarding
sysctl -w net.ipv6.conf.all.forwarding=1
sysctl -w net.ipv6.conf.${dummy_name}.forwarding=1
sysctl -w net.ipv6.conf.eth0.forwarding=1

# Enable proxy NDP on both interfaces
sysctl -w net.ipv6.conf.${dummy_name}.proxy_ndp=1
sysctl -w net.ipv6.conf.eth0.proxy_ndp=1

# Disable RA on dummy interface
sysctl -w net.ipv6.conf.${dummy_name}.accept_ra=0

# NAT for external traffic
ip6tables -t nat -A POSTROUTING -s ${node_range} ! -d ${subnet_prefix} -j MASQUERADE

cat > /etc/cni/net.d/01-ipvlan-ipv6.conf << EOF
{
    "cniVersion": "0.3.1",
    "name": "ipvlan-ipv6",
    "type": "ipvlan",
    "master": "ipvlan",
    "linkInContainer": false,
    "mode": "l3s",
    "ipam": {
        "type": "host-local",
        "ranges": [
            [
                {
                    "subnet": "${node_range}"
                }
            ]
        ],
        "routes": [{"dst": "::/0"}]
    }
}
EOF

### Debug
tcpdump -i ipvlan-dummy0 -n "icmp6"

mkdir -p /etc/systemd/network/10-netplan-ipvlan-dummy0.network.d
# cat > /etc/systemd/network/10-netplan-ipvlan-dummy0.network.d/00-ra.conf << EOF

cat > /etc/systemd/network/05-ipvlan-dummy0.network << EOF
[Match]
Name=ipvlan-dummy0

[Link]
Unmanaged=no

[Network]
IPv6SendRA=yes
IPv6AcceptRA=no
# iPXE can't cope with multiple RAs, so help it out via neighbour discovery
# https://lists.ipxe.org/pipermail/ipxe-devel/2024-August/007627.html
IPv6ProxyNDP=yes
IPv6ProxyNDPAddress=fd5d:beb3:90df:4910:3::1

[IPv6SendRA]
RouterLifetimeSec=0
HopLimit=64

[IPv6RoutePrefix]
Route=fd5d:beb3:90df:4910:3::/80
EOF

systemctl restart systemd-networkd
networkctl reload
networkctl reconfigure ipvlan-dummy0
networkctl status ipvlan-dummy0


# Step 1: Remove the manually created ipvlan-dummy0
ip link delete ipvlan-dummy0 2>/dev/null || true

# Step 2: Create .netdev file to define the interface
cat > /etc/systemd/network/05-ipvlan-dummy0.netdev << 'EOF'
[NetDev]
Name=ipvlan-dummy0
Kind=ipvlan

[IPVLAN]
Mode=L3S
Flags=bridge
EOF

# Step 3: Create .network file with RA configuration
cat > /etc/systemd/network/05-ipvlan-dummy0.network << 'EOF'
[Match]
Name=ipvlan-dummy0

[Network]
Address=fd5d:beb3:90df:4910:3::/80
Address=fd5d:beb3:90df:4910:3::1/80
IPv6SendRA=yes
IPv6ProxyNDP=yes
IPv6ProxyNDPAddress=fd5d:beb3:90df:4910:3::1

[IPv6SendRA]
RouterLifetimeSec=0
HopLimit=64

[IPv6RoutePrefix]
Route=fd5d:beb3:90df:4910:3::/80
EOF

# Step 4: Restart systemd-networkd to create and configure the interface
systemctl restart systemd-networkd
sleep 2

# Step 5: Verify the interface is now managed
networkctl status ipvlan-dummy0

# Step 6: Manually add any additional addresses if needed
ip -6 addr show dev ipvlan-dummy0

### Check IP address
kubectl get nodes -o=custom-columns="NAME:.metadata.name,ADDRESSES:.status.addresses[?(@.type=='InternalIP')].address,PODCIDRS:.spec.podCIDRs[*]"
kubectl get pods -o custom-columns="NAME:.metadata.name,IPs:.status.podIPs[*].ip,NODE:.spec.nodeName,READY:.status.conditions[?(@.type=='Ready')].status"