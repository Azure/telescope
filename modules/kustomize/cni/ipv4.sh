# Add secondary IP to eth0 interface and configure cross-node routing
# Note: These are temporary and will be lost on reboot
# For persistent configuration, use systemd-networkd or cloud-init

## Node 1 (aks-user-40702790-vms1, IP: 10.224.0.7)
sudo ip addr add 10.224.0.16/28 dev eth0
# Add route to Node2's pod subnet via Node2's IP
sudo ip route add 10.224.0.32/28 via 10.224.0.8 dev eth0
ip -4 a show eth0
ip route show

## Node 2 (aks-user-40702790-vms2, IP: 10.224.0.8)
sudo ip addr add 10.224.0.32/28 dev eth0
# Add route to Node1's pod subnet via Node1's IP
sudo ip route add 10.224.0.16/28 via 10.224.0.7 dev eth0
ip -4 a show eth0
ip route show

# Test cross-node connectivity
kubectl exec pod0 -- ip -4 addr show
kubectl exec pod0 -- ip -4 route show
kubectl exec pod0 -- ping -c3 10.224.0.37  # pod2 on node2
kubectl exec iperf3-client -- iperf3 -c 10.224.0.39 -t 10 -p 20003