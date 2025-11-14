# Complete IPvlan Setup Guide - Pod-to-Pod + Egress/Ingress

This guide shows different approaches to configure IPvlan for both cross-node pod communication AND internet access.

## Comparison of Approaches

| Feature | L3s + SNAT | L2 Mode | L3s + Azure NAT |
|---------|-----------|---------|-----------------|
| **Cross-node pods** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Egress (to internet)** | ✅ Yes (with SNAT) | ✅ Yes (native) | ✅ Yes (via NAT Gateway) |
| **Ingress (from internet)** | ⚠️ Via Load Balancer | ✅ Direct (if NSG allows) | ⚠️ Via Load Balancer |
| **Setup complexity** | Medium | Low | Medium |
| **Azure cost** | Low | Low | $$ (NAT Gateway) |
| **Security** | High (isolated namespaces) | Medium | High |
| **Best for** | Production | Testing/Simple setups | Enterprise |

## Recommended: L3s Mode with SNAT DaemonSet

### Step 1: Apply SNAT DaemonSet
```bash
kubectl apply -f /home/alyssavu/telescope/modules/kustomize/cni/ipvlan-snat-daemonset.yaml
kubectl wait --for=condition=ready pod -l app=ipvlan-snat -n kube-system --timeout=60s
```

### Step 2: Keep existing L3s CNI configuration
Your current `ipv4-config.yaml` with routes:
```json
"routes": [
    { "dst": "10.224.0.0/16" },
    { "dst": "0.0.0.0/0" }
]
```

### Step 3: Test all connectivity
```bash
# Cross-node pod-to-pod
kubectl exec pod0 -- ping -c3 <pod2-ip>

# Egress to internet
kubectl exec pod0 -- ping -c3 8.8.8.8
kubectl exec pod0 -- wget -q -O- http://google.com | head -5

# Ingress via LoadBalancer Service
kubectl expose pod pod0 --type=LoadBalancer --port=80 --target-port=8080
```

## Alternative: L2 Mode (Simpler)

### Step 1: Apply L2 CNI configuration
```bash
# Remove old L3s config
kubectl delete -f /home/alyssavu/telescope/modules/kustomize/cni/ipv4-config.yaml

# Apply L2 config
kubectl apply -f /home/alyssavu/telescope/modules/kustomize/cni/ipv4-l2-config.yaml
kubectl wait --for=condition=complete pod -l app=ipv4-l2 -n kube-system --timeout=30s
```

### Step 2: Update node routes (still needed for cross-node)
```bash
# On Node1
kubectl node-shell aks-user-40702790-vms1
sudo ip route add 10.224.0.32/28 via 10.224.0.8 dev eth0
exit

# On Node2
kubectl node-shell aks-user-40702790-vms2
sudo ip route add 10.224.0.16/28 via 10.224.0.7 dev eth0
exit
```

### Step 3: Recreate pods
```bash
kubectl delete -f /home/alyssavu/telescope/modules/kustomize/cni/pods.yaml
kubectl apply -f /home/alyssavu/telescope/modules/kustomize/cni/pods.yaml
kubectl wait --for=condition=ready pod -l app=test --timeout=60s
```

### Step 4: Test
```bash
# All should work without SNAT!
kubectl exec pod0 -- ping -c3 <pod2-ip>
kubectl exec pod0 -- ping -c3 8.8.8.8
kubectl exec pod0 -- wget -q -O- http://google.com | head -5
```

## L2 Mode Benefits
- **No SNAT needed** - Pods use Azure's default gateway (10.224.0.1)
- **Simpler setup** - Just CNI config + node routes
- **Azure native** - Pods behave like regular VMs on the network
- **Direct ingress** - Pods can receive traffic directly (if NSG allows)

## L2 Mode Trade-offs
- Less network isolation (shared L2 domain with host)
- Requires Azure NSG rules for security
- May have ARP table limitations at scale

## Production Recommendation

**For Azure AKS**: Use **L2 mode** for simplicity and native Azure integration

**For multi-cloud or strict isolation**: Use **L3s + SNAT DaemonSet**

## Quick Start Script

```bash
#!/bin/bash
# Complete IPvlan setup with L3s + SNAT

# 1. Apply SNAT DaemonSet
kubectl apply -f ipvlan-snat-daemonset.yaml

# 2. Wait for SNAT setup
kubectl wait --for=condition=ready pod -l app=ipvlan-snat -n kube-system --timeout=60s

# 3. Verify SNAT rules on each node
kubectl exec -n kube-system -l app=ipvlan-snat -- iptables -t nat -L POSTROUTING -v -n

# 4. Test everything
POD2_IP=$(kubectl get pod pod2 -o jsonpath='{.status.podIP}')

echo "Testing cross-node..."
kubectl exec pod0 -- ping -c3 $POD2_IP

echo "Testing egress..."
kubectl exec pod0 -- ping -c3 8.8.8.8
kubectl exec pod0 -- wget -q -O- -T 5 http://google.com | head -10

echo "All tests completed!"
```

## Troubleshooting

### Egress not working
```bash
# Check SNAT rules on nodes
kubectl exec -n kube-system -l app=ipvlan-snat -- iptables -t nat -L POSTROUTING -v -n | grep MASQUERADE

# Check IP forwarding
kubectl exec -n kube-system -l app=ipvlan-snat -- cat /proc/sys/net/ipv4/ip_forward
# Should show: 1

# Check pod routes
kubectl exec pod0 -- ip route show
# Should have: default via <gateway>
```

### Cross-node not working
```bash
# Check node routes
kubectl debug node/aks-user-40702790-vms1 -- ip route | grep "10.224.0.32"
kubectl debug node/aks-user-40702790-vms2 -- ip route | grep "10.224.0.16"

# Check Azure NIC IP forwarding
az network nic list -g <resource-group> --query "[].{name:name, enableIPForwarding:enableIPForwarding}"
```

### Ingress not working
```bash
# Create LoadBalancer service
kubectl expose pod pod0 --type=LoadBalancer --port=80 --name=pod0-lb

# Get external IP (may take 2-3 minutes)
kubectl get svc pod0-lb -w

# Test from outside
EXTERNAL_IP=$(kubectl get svc pod0-lb -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://$EXTERNAL_IP
```
