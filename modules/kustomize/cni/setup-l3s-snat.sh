#!/bin/bash
# Enable SNAT for IPvlan L3s mode egress

echo "=== Setting up SNAT on Node 1 ==="
echo "Run: kubectl node-shell aks-user-40702790-vms1"
echo "Then execute these commands:"
cat <<'EOF'
# Enable IP forwarding (if not already enabled)
sudo sysctl -w net.ipv4.ip_forward=1

# Add SNAT rule for pod subnet
# This NATs traffic from 10.224.0.16/28 going to destinations outside 10.224.0.0/16
sudo iptables -t nat -C POSTROUTING -s 10.224.0.16/28 ! -d 10.224.0.0/16 -j MASQUERADE 2>/dev/null || \
sudo iptables -t nat -A POSTROUTING -s 10.224.0.16/28 ! -d 10.224.0.0/16 -j MASQUERADE

# Verify the rule
sudo iptables -t nat -L POSTROUTING -n -v | grep 10.224.0.16

exit
EOF

echo ""
echo "=== Setting up SNAT on Node 2 ==="
echo "Run: kubectl node-shell aks-user-40702790-vms2"
echo "Then execute these commands:"
cat <<'EOF'
# Enable IP forwarding (if not already enabled)
sudo sysctl -w net.ipv4.ip_forward=1

# Add SNAT rule for pod subnet
# This NATs traffic from 10.224.0.32/28 going to destinations outside 10.224.0.0/16
sudo iptables -t nat -C POSTROUTING -s 10.224.0.32/28 ! -d 10.224.0.0/16 -j MASQUERADE 2>/dev/null || \
sudo iptables -t nat -A POSTROUTING -s 10.224.0.32/28 ! -d 10.224.0.0/16 -j MASQUERADE

# Verify the rule
sudo iptables -t nat -L POSTROUTING -n -v | grep 10.224.0.32

exit
EOF

echo ""
echo "=== After configuring both nodes, test: ==="
echo "kubectl exec pod3 -- ping -c3 8.8.8.8"
echo "kubectl exec pod3 -- wget -q -O- -T 5 http://google.com | head -10"
