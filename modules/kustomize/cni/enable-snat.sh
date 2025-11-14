#!/bin/bash
# Enable SNAT/IP Masquerading for pod egress traffic

echo "=== Enabling SNAT on Node 1 ==="
kubectl debug node/aks-user-40702790-vms1 -it --image=alpine -- sh -c '
apk add iptables
# Enable IP forwarding
sysctl -w net.ipv4.ip_forward=1

# Add SNAT rule for pod subnet
iptables -t nat -A POSTROUTING -s 10.224.0.16/28 ! -d 10.224.0.0/16 -j MASQUERADE

# Verify rules
echo "NAT rules:"
iptables -t nat -L POSTROUTING -v -n
'

echo -e "\n=== Enabling SNAT on Node 2 ==="
kubectl debug node/aks-user-40702790-vms2 -it --image=alpine -- sh -c '
apk add iptables
# Enable IP forwarding
sysctl -w net.ipv4.ip_forward=1

# Add SNAT rule for pod subnet
iptables -t nat -A POSTROUTING -s 10.224.0.32/28 ! -d 10.224.0.0/16 -j MASQUERADE

# Verify rules
echo "NAT rules:"
iptables -t nat -L POSTROUTING -v -n
'

echo -e "\n=== Testing Egress ==="
kubectl exec pod3 -- ping -c3 8.8.8.8
