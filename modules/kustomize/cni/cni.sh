ls -la /opt/cni/bin/ # List all CNI plugins

/opt/cni/bin/host-local
# CNI host-local plugin v1.6.2
# CNI protocol versions supported: 0.1.0, 0.2.0, 0.3.0, 0.3.1, 0.4.0, 1.0.0, 1.1.0

/opt/cni/bin/ipvlan
# CNI ipvlan plugin v1.6.2
# CNI protocol versions supported: 0.1.0, 0.2.0, 0.3.0, 0.3.1, 0.4.0, 1.0.0, 1.1.0

kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml
kubectl get pods -n kube-system -l app=multus -o wide
kubectl get crd
kubectl get net-attach-def
kubectl rollout restart ds kube-multus-ds -n kube-system
kubectl rollout status ds kube-multus-ds -n kube-system
kubectl logs -n kube-system -l app=multus

# IPv4 test
kubectl get pods -l app=ipvlan -n kube-system
kubectl delete pods -l app=ipvlan -n kube-system

journalctl -u containerd | grep CNI
journalctl -u containerd -n 100 --no-pager
systemctl status containerd

# Check IPv6 addresses
kubectl get pods -o wide
kubectl exec pod0 -- ip -6 addr show
kubectl exec pod0 -- ip -6 route show
kubectl exec pod0 -- ping6 -c1 fd00:5852:d4bf::1

az aks nodepool add --name user --cluster-name ipvlan -g ipv6-test --subscription 137f0351-8235-42a6-ac7a-6b46be2d21c7 \
    --node-count 2 --node-vm-size Standard_D8ds_v5 --mode User --vm-set-type VirtualMachines
az aks nodepool delete --name agent --cluster-name ipvlan -g ipv6-test --subscription 137f0351-8235-42a6-ac7a-6b46be2d21c7
az aks create --resource-group $rg --name default \
    --network-plugin azure --network-plugin-mode overlay --tier standard \
    --ip-families ipv4,ipv6

# Inspect pods
crictl ps -a
container_pid=$(crictl inspect $container_id | jq .info.pid)
crictl stats $container_id
crictl logs $container_id
crictl images

## Obtain ns of process
lsns -p $container_pid
#         NS TYPE   NPROCS   PID USER  COMMAND
# 4026531834 time      210     1 root  /sbin/init
# 4026531837 user      210     1 root  /sbin/init
# 4026532323 net         3  5512 root  /pause
# 4026532394 uts         3  5512 root  /pause
# 4026532395 ipc         3  5512 root  /pause
# 4026532407 mnt         1  5670 65532 /metrics-server --kubelet-insecure-tls --kubelet-preferred-address-types=InternalIP --tls-cipher-suites=TLS_ECDHE_RS
# 4026532408 pid         1  5670 65532 /metrics-server --kubelet-insecure-tls --kubelet-preferred-address-types=InternalIP --tls-cipher-suites=TLS_ECDHE_RS
# 4026532409 cgroup      1  5670 65532 /metrics-server --kubelet-insecure-tls --kubelet-preferred-address-types=InternalIP --tls-cipher-suites=TLS_ECDHE_RS

#         NS TYPE   NPROCS   PID USER  COMMAND
# 4026531834 time      210     1 root  /sbin/init
# 4026531837 user      210     1 root  /sbin/init
# 4026532323 net         3  5512 root  /pause
# 4026532394 uts         3  5512 root  /pause
# 4026532395 ipc         3  5512 root  /pause
# 4026532401 mnt         1  5572 65532 /pod_nanny --config-dir=/etc/config --cpu=150m --extra-cpu=0.5m --memory=100Mi --extra-memory=4Mi --poll-period=1800
# 4026532402 pid         1  5572 65532 /pod_nanny --config-dir=/etc/config --cpu=150m --extra-cpu=0.5m --memory=100Mi --extra-memory=4Mi --poll-period=1800
# 4026532403 cgroup      1  5572 65532 /pod_nanny --config-dir=/etc/config --cpu=150m --extra-cpu=0.5m --memory=100Mi --extra-memory=4Mi --poll-period=1800

## Example
kubectl get pod metrics-server-864f9bf8cf-9z5mj -o json -n kube-system | jq .status.containerStatuses[].containerID
# "containerd://6561d1ac05f6ef5fc8f1c137693432c18f32abc43a6abe0ccab20fe49dac8414"
# "containerd://361704b548a294ed2f24e68ae1fd27c8df79371956c51c0987ac586574e30e9a"

## Pod to pod in overlay

### In pod
ip link sh
# 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
#     link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
# 13: eth0@if14: <BROADCAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
#     link/ether 9a:34:32:be:31:a4 brd ff:ff:ff:ff:ff:ff link-netnsid 0
ethtool -S eth0
# NIC statistics:
#      peer_ifindex: 14
#      rx_queue_0_xdp_packets: 0
#      rx_queue_0_xdp_bytes: 0
#      rx_queue_0_drops: 0
#      rx_queue_0_xdp_redirect: 0
#      rx_queue_0_xdp_drops: 0
#      rx_queue_0_xdp_tx: 0
#      rx_queue_0_xdp_tx_errors: 0
#      tx_queue_0_xdp_xmit: 0
#      tx_queue_0_xdp_xmit_errors: 0

### In host
root@aks-nodepool1-30494987-vmss000000:/# ip link sh
# 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
#     link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
# 3: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
#     link/ether 7c:1e:52:25:a2:a9 brd ff:ff:ff:ff:ff:ff
# 4: enP275s1: <BROADCAST,MULTICAST,SLAVE,UP,LOWER_UP> mtu 1500 qdisc mq master eth0 state UP mode DEFAULT group default qlen 1000
#     link/ether 7c:1e:52:25:a2:a9 brd ff:ff:ff:ff:ff:ff
#     altname enP275p0s2
# 6: azvb6078e49d36@if5: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
#     link/ether aa:aa:aa:aa:aa:aa brd ff:ff:ff:ff:ff:ff link-netns cni-e088b728-e234-0eb8-423a-7aed3958ccb6
# 8: azv72136b28d24@if7: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
#     link/ether aa:aa:aa:aa:aa:aa brd ff:ff:ff:ff:ff:ff link-netns cni-4905d329-d3c6-981f-35ea-2ccc526013d3
# 10: azv4cc095926ea@if9: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
#     link/ether aa:aa:aa:aa:aa:aa brd ff:ff:ff:ff:ff:ff link-netns cni-1e3af2b9-f8e4-a95e-cfb1-f91930debc1b
# 12: azv5a25448317d@if11: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
#     link/ether aa:aa:aa:aa:aa:aa brd ff:ff:ff:ff:ff:ff link-netns cni-757d305f-217f-cda2-3bcd-ff6731ef91cd
# 14: azv7ac1b8e1615@if13: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
#     link/ether aa:aa:aa:aa:aa:aa brd ff:ff:ff:ff:ff:ff link-netns cni-a0e87b67-aa0b-5505-c1da-10dbd79c4a24


## Pod to pod - BYO

### In pod
ip a show
# 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue qlen 1000
#     link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
#     inet 127.0.0.1/8 scope host lo
#        valid_lft forever preferred_lft forever
#     inet6 ::1/128 scope host 
#        valid_lft forever preferred_lft forever
# 2: eth0@if9: <BROADCAST,MULTICAST,UP,LOWER_UP,M-DOWN> mtu 1500 qdisc noqueue qlen 1000
#     link/ether a6:d9:9d:c3:84:0d brd ff:ff:ff:ff:ff:ff
#     inet 10.22.0.6/16 brd 10.22.255.255 scope global eth0
#        valid_lft forever preferred_lft forever
#     inet6 fe80::a4d9:9dff:fec3:840d/64 scope link 
#        valid_lft forever preferred_lft forever

### In node
root@aks-user-35262288-vms1:/etc/cni# ip a show
# 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
#     link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
#     inet 127.0.0.1/8 scope host lo
#        valid_lft forever preferred_lft forever
#     inet6 ::1/128 scope host 
#        valid_lft forever preferred_lft forever
# 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
#     link/ether 7c:1e:52:d3:d1:10 brd ff:ff:ff:ff:ff:ff
#     inet 10.224.0.8/16 metric 100 brd 10.224.255.255 scope global eth0
#        valid_lft forever preferred_lft forever
#     inet6 fe80::7e1e:52ff:fed3:d110/64 scope link 
#        valid_lft forever preferred_lft forever
# 3: enP43473s1: <BROADCAST,MULTICAST,SLAVE,UP,LOWER_UP> mtu 1500 qdisc mq master eth0 state UP group default qlen 1000
#     link/ether 7c:1e:52:d3:d1:10 brd ff:ff:ff:ff:ff:ff
#     altname enP43473p0s2
# 4: cni0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
#     link/ether 42:5c:f8:0e:b5:5d brd ff:ff:ff:ff:ff:ff
#     inet 10.22.0.1/16 brd 10.22.255.255 scope global cni0
#        valid_lft forever preferred_lft forever
#     inet6 fe80::405c:f8ff:fe0e:b55d/64 scope link 
#        valid_lft forever preferred_lft forever
# 9: vethac2d46eb@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue master cni0 state UP group default qlen 1000
#     link/ether 7e:19:73:2d:27:06 brd ff:ff:ff:ff:ff:ff link-netns cni-5403e994-5116-fad1-2002-6222ad4dc8a5
#     inet6 fe80::7c19:73ff:fe2d:2706/64 scope link 
#        valid_lft forever preferred_lft forever
# 10: vethdfe5d684@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue master cni0 state UP group default qlen 1000
#     link/ether 32:0e:23:19:53:46 brd ff:ff:ff:ff:ff:ff link-netns cni-760e7c99-f1c1-6fb5-521e-547e927b5ee2
#     inet6 fe80::300e:23ff:fe19:5346/64 scope link 
#        valid_lft forever preferred_lft forever
# Check routes in host

### In pod
ip route sh
# default via 10.22.0.1 dev eth0 
# 10.22.0.0/16 dev eth0 scope link  src 10.22.0.6 

### In node
root@aks-user-35262288-vms1:/etc/cni# ip route sh
# default via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.8 metric 100 
# 10.22.0.0/16 dev cni0 proto kernel scope link src 10.22.0.1 
# 10.224.0.0/16 dev eth0 proto kernel scope link src 10.224.0.8 metric 100 
# 10.224.0.1 dev eth0 proto dhcp scope link src 10.224.0.8 metric 100 
# 168.63.129.16 via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.8 metric 100 
# 169.254.169.254 via 10.224.0.1 dev eth0 proto dhcp src 10.224.0.8 metric 100 

# Node 1
cat <<EOF > /etc/systemd/network/10-eth0.network.d/00-ra.conf
[Network]
IPv6SendRA=yes
IPv6ProxyNDP=yes
IPv6ProxyNDPAddress=fd00:5852:d4bf:0:1:0:1:0

[IPv6SendRA]
RouterLifetimeSec=0
HopLimit=64

[IPv6RoutePrefix]
Route=fd00:5852:d4bf:0:1:0:1:0/112
EOF

# Node 2
cat <<EOF > /etc/systemd/network/10-eth0.network.d/00-ra.conf
[Network]
IPv6SendRA=yes
IPv6ProxyNDP=yes
IPv6ProxyNDPAddress=fd00:5852:d4bf:0:1:0:0:0

[IPv6SendRA]
RouterLifetimeSec=0
HopLimit=64

[IPv6RoutePrefix]
Route=fd00:5852:d4bf:0:1:0:0:0/112
EOF

cat <<EOF > /etc/systemd/network/00-ipvlan0.netdev
[NetDev]
Name=ipvlan0
Kind=ipvlan

[IPVLAN]
Mode=L3S
Flags=bridge
EOF

mkdir -p /etc/systemd/network/10-eth0.network.d
cat <<EOF > /etc/systemd/network/10-eth0.network.d/00-eth0.conf
[Network]
IPVLAN=ipvlan0

[IPv6AcceptRA]
DHCPv6Client=no
UseAutonomousPrefix=no
EOF

# Configure ipvlan0 with node IP
cat > /etc/systemd/network/20-ipvlan0.network <<EOF
[Match]
Name=ipvlan0

[Network]
Address=fd00:5852:d4bf:0:1:0:0:0/112
EOF

# 3. Create CNI configuration for pods
SUBNET="fd00:5852:d4bf::/64"
echo "Creating CNI configuration..."
mkdir -p /etc/cni/net.d
cat > /etc/cni/net.d/10-ipvlan.conflist <<EOF
{
  "cniVersion": "0.4.0",
  "name": "network",
  "type": "ipvlan",
  "master": "eth0",
  "mode": "l3s",
  "ipam": {
    "type": "host-local",
    "ranges": [
      [
        {
          "subnet": "$SUBNET"
        }
      ]
    ]
  }
}
EOF

systemctl restart containerd
systemctl status systemd-networkd