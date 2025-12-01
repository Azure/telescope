# Add secondary IP to eth0 interface and configure cross-node routing
# Note: These are temporary and will be lost on reboot
# For persistent configuration, use systemd-networkd or cloud-init

## Node 1 (aks-default-42863573-vms1, IP: 10.224.0.6)
sudo ip addr add 10.224.0.16/28 dev eth0
# Add route to Node2's pod subnet via Node2's IP
sudo ip route add 10.224.0.32/28 via 10.224.0.4 dev eth0
sudo ip route add 10.224.0.48/28 via 10.224.0.5 dev eth0
ip -4 a show eth0
ip route show

## Node 2 (aks-default-42863573-vms2, IP: 10.224.0.4)
sudo ip addr add 10.224.0.32/28 dev eth0
# Add route to Node1's pod subnet via Node1's IP
sudo ip route add 10.224.0.16/28 via 10.224.0.6 dev eth0
sudo ip route add 10.224.0.48/28 via 10.224.0.5 dev eth0
ip -4 a show eth0
ip route show

## Node 3 (aks-default-42863573-vms3, IP: 10.224.0.5)
sudo ip addr add 10.224.0.48/28 dev eth0
sudo ip route add 10.224.0.16/28 via 10.224.0.6 dev eth0
sudo ip route add 10.224.0.32/28 via 10.224.0.4 dev eth0
ip -4 a show eth0
ip route show

# Test cross-node connectivity
kubectl exec pod1 -- ip -4 addr show
kubectl exec pod1 -- ip -4 route show
kubectl exec pod1 -- ping -c1 10.224.0.34  # pod2 on node2
kubectl exec pod2 -- ping -c1 10.224.0.18 # pod1 on node1
kubectl exec iperf3-client -- iperf3 -c 10.224.0.39 -t 10 -p 20003

# Test ingress-egress connectivity
kubectl exec pod1 -- ping -c1 8.8.8.8
kubectl exec pod1 -- wget -q -O- -T 5 http://google.com
kubectl exec pod1 -- wget bing.com


# ---------------------------------
## Reproduce
# On Node 1
root@aks-user-20102827-vms1:/etc/cni/net.d# ip -4 a show eth0
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    inet 10.224.0.8/16 metric 100 brd 10.224.255.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet 10.224.0.16/28 scope global eth0
       valid_lft forever preferred_lft forever
root@aks-user-20102827-vms1:/etc/cni/net.d# ip -4 route show
default via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.8 metric 100 # default gateway of subnet
10.224.0.0/16 dev eth0 proto kernel scope link src 10.224.0.8 metric 100 # subnet route
10.224.0.1 dev eth0 proto dhcp scope link src 10.224.0.8 metric 100 # gateway IP of subnet
10.224.0.16/28 dev eth0 proto kernel scope link src 10.224.0.16 
10.224.0.32/28 via 10.224.0.7 dev eth0 
168.63.129.16 via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.8 metric 100 
169.254.169.254 via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.8 metric 100 

# On Node 2
root@aks-user-20102827-vms2:/etc/cni/net.d# ip -4 a show eth0
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    inet 10.224.0.7/16 metric 100 brd 10.224.255.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet 10.224.0.32/28 scope global eth0
       valid_lft forever preferred_lft forever
root@aks-user-20102827-vms2:/etc/cni/net.d# ip -4 route show 
default via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.7 metric 100 
10.224.0.0/16 dev eth0 proto kernel scope link src 10.224.0.7 metric 100 
10.224.0.1 dev eth0 proto dhcp scope link src 10.224.0.7 metric 100 
10.224.0.16/28 via 10.224.0.8 dev eth0 
10.224.0.32/28 dev eth0 proto kernel scope link src 10.224.0.32 
168.63.129.16 via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.7 metric 100 
169.254.169.254 via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.7 metric 100

# ---------------------------------
# Clean up
ls /var/lib/cni/networks/ipv4-l3
rm /var/lib/cni/networks/ipv4-l3/last_reserved_ip.0

# --------------------------------
# Ingress egress - SNAT configuration for L3s mode
sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv4.conf.all.rp_filter=0
sysctl -w net.ipv4.conf.default.rp_filter=0
sysctl -w net.ipv4.conf.eth0.rp_filter=0

sysctl net.ipv4.ip_forward
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.default.rp_filter

# Remove old broad rule if exists
iptables -t nat -D POSTROUTING -s 10.224.0.0/16 -o eth0 -j MASQUERADE 2>/dev/null || true

# Add specific MASQUERADE rules for each pod subnet going to external destinations
# Node 1 - pod subnet 10.224.0.16/28
iptables -t nat -C POSTROUTING -s 10.224.0.16/28 ! -d 10.224.0.0/16 -j MASQUERADE 2>/dev/null || \
iptables -t nat -A POSTROUTING -s 10.224.0.16/28 ! -d 10.224.0.0/16 -j MASQUERADE

# Node 2 - pod subnet 10.224.0.32/28  
iptables -t nat -C POSTROUTING -s 10.224.0.32/28 ! -d 10.224.0.0/16 -j MASQUERADE 2>/dev/null || \
iptables -t nat -A POSTROUTING -s 10.224.0.32/28 ! -d 10.224.0.0/16 -j MASQUERADE

# Verify rules
echo "NAT POSTROUTING rules:"
iptables -t nat -L POSTROUTING -n -v | grep -E "10.224.0.16|10.224.0.32|MASQ"

kubectl exec pod1 -- cat /etc/resolv.conf
search default.svc.cluster.local svc.cluster.local cluster.local exz5m5sne1cubltuen44ahsuja.cx.internal.cloudapp.net
nameserver 10.0.0.10
options ndots:5

# ---------------------------------
# Bridge mode
/ # ip route show
default via 10.22.0.1 dev eth0 
10.22.0.0/16 dev eth0 scope link  src 10.22.0.7

# Ipvlan mode
(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ kubectl exec pod1 -- ip -4 route show
10.224.0.0/16 via 10.224.0.17 dev eth0 
10.224.0.16/28 dev eth0 scope link  src 10.224.0.20 

## Combine mode: bridge first, ipvlan second
(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ kubectl exec pod1 -- ip -4 route show
default via 10.22.0.1 dev eth0 
10.22.0.0/16 dev eth0 scope link  src 10.22.0.3 
10.224.0.0/16 via 10.224.0.17 dev net1 
10.224.0.16/28 dev net1 scope link  src 10.224.0.18 

# Command to add ipconfig
mc_rg=MC_1764202814_cni-prototype_eastus2
nic_name=aks-default-22830941-vmsnic-1-b478587a
az network nic ip-config create -g $mc_rg --nic-name $nic_name --name ipvlan --private-ip-prefix-len 28