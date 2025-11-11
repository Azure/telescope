# IPv6 IPvlan L3S Setup for AKS

## Network Architecture

This setup creates flat IPv6 networking across 2 AKS nodes using IPvlan in L3S mode:

- **Cluster Subnet**: `fd00:5852:d4bf::/64`
- **Node 0 Range**: `fd00:5852:d4bf::/112` (16,384 addresses)
  - Usable range: `fd00:5852:d4bf::100` to `fd00:5852:d4bf::ffff`
- **Node 1 Range**: `fd00:5852:d4bf::1:0/112` (16,384 addresses)
  - Usable range: `fd00:5852:d4bf::1:100` to `fd00:5852:d4bf::1:ffff`

## Prerequisites

1. AKS cluster with IPv6 enabled
2. Multus CNI installed (if using network attachments)
3. Two worker nodes named:
   - `aks-user-12474502-vmss000000` (node0)
   - `aks-user-12474502-vmss000001` (node1)

## Deployment Steps

### Step 1: Deploy IPvlan CNI Configuration

This creates configuration pods that write the IPvlan CNI config to each node:

```bash
kubectl apply -f ipvlan-config.yaml
```

Wait for configuration pods to complete:

```bash
kubectl wait --for=condition=Ready pod/ipvlan-node0 -n kube-system --timeout=60s
kubectl wait --for=condition=Ready pod/ipvlan-node1 -n kube-system --timeout=60s
```

Check logs to verify configuration was written:

```bash
kubectl logs -n kube-system ipvlan-node0
kubectl logs -n kube-system ipvlan-node1
```

### Step 2: Deploy Test Pods

Deploy test pods on each node:

```bash
kubectl apply -f ipvlan-test-pods.yaml
```

Wait for pods to be ready:

```bash
kubectl wait --for=condition=Ready pod/ipvlan-test-node0 --timeout=120s
kubectl wait --for=condition=Ready pod/ipvlan-test-node1 --timeout=120s
```

### Step 3: Verify IPv6 Addresses

Check pod IPv6 addresses on node0:

```bash
kubectl exec ipvlan-test-node0 -- ip -6 addr show
```

Expected output should show an address in range `fd00:5852:d4bf::100` to `fd00:5852:d4bf::ffff`

Check pod IPv6 addresses on node1:

```bash
kubectl exec ipvlan-test-node1 -- ip -6 addr show
```

Expected output should show an address in range `fd00:5852:d4bf::1:100` to `fd00:5852:d4bf::1:ffff`

### Step 4: Test Pod-to-Pod Connectivity

Get the IPv6 address of the pod on node1:

```bash
NODE1_IPV6=$(kubectl exec ipvlan-test-node1 -- ip -6 addr show net1 | grep "inet6 fd00" | awk '{print $2}' | cut -d'/' -f1)
echo "Node1 pod IPv6: $NODE1_IPV6"
```

Ping from node0 pod to node1 pod:

```bash
kubectl exec ipvlan-test-node0 -- ping6 -c 4 $NODE1_IPV6
```

Get the IPv6 address of the pod on node0:

```bash
NODE0_IPV6=$(kubectl exec ipvlan-test-node0 -- ip -6 addr show net1 | grep "inet6 fd00" | awk '{print $2}' | cut -d'/' -f1)
echo "Node0 pod IPv6: $NODE0_IPV6"
```

Ping from node1 pod to node0 pod:

```bash
kubectl exec ipvlan-test-node1 -- ping6 -c 4 $NODE0_IPV6
```

### Step 5: Advanced Connectivity Tests

Test bidirectional bandwidth with iperf3:

On node1 pod, start iperf3 server:

```bash
kubectl exec ipvlan-test-node1 -- iperf3 -s -B $NODE1_IPV6 &
```

On node0 pod, run iperf3 client:

```bash
kubectl exec ipvlan-test-node0 -- iperf3 -c $NODE1_IPV6 -t 10
```

Test UDP bandwidth:

```bash
kubectl exec ipvlan-test-node0 -- iperf3 -c $NODE1_IPV6 -u -b 1G -t 10
```

## Troubleshooting

### Check CNI Configuration Files on Nodes

SSH to node or use debug pod:

```bash
# Check if config was created
ls -la /etc/cni/net.d/ipvlan-l3.conf
cat /etc/cni/net.d/ipvlan-l3.conf
```

### Check Routing

From test pods:

```bash
kubectl exec ipvlan-test-node0 -- ip -6 route show
kubectl exec ipvlan-test-node1 -- ip -6 route show
```

### Check Network Interfaces

```bash
kubectl exec ipvlan-test-node0 -- ip link show
kubectl exec ipvlan-test-node1 -- ip link show
```

### Verify IPvlan Mode

```bash
kubectl exec ipvlan-test-node0 -- ip -d link show net1
```

Should show `ipvlan mode l3s`

### Common Issues

1. **Pods not getting IPv6 addresses**: 
   - Verify CNI config was written to `/etc/cni/net.d/`
   - Check CNI plugin is installed on nodes
   - Restart pods after config deployment

2. **Connectivity fails**:
   - Check IPv6 forwarding: `sysctl net.ipv6.conf.all.forwarding`
   - Verify routing tables with `ip -6 route`
   - Check firewall rules aren't blocking IPv6

3. **Wrong subnet assigned**:
   - Verify node selectors match actual node names
   - Check IPAM configuration in CNI config

## Cleanup

Remove test pods:

```bash
kubectl delete -f ipvlan-test-pods.yaml
```

Remove configuration pods:

```bash
kubectl delete -f ipvlan-config.yaml
```

Remove CNI config from nodes (requires node access):

```bash
rm /etc/cni/net.d/ipvlan-l3.conf
```

## Network Diagram

```
┌─────────────────────────────────────────────────────────┐
│ Cluster Subnet: fd00:5852:d4bf::/64                     │
└─────────────────────────────────────────────────────────┘
                          │
         ┌────────────────┴────────────────┐
         │                                  │
┌────────▼──────────┐            ┌─────────▼─────────┐
│ Node 0 (vmss000000)│            │ Node 1 (vmss000001)│
│ fd00:5852:d4bf::/112│            │ fd00:5852:d4bf::1:0/112│
│                    │            │                    │
│ ┌────────────────┐ │            │ ┌────────────────┐ │
│ │ Pod (net1)     │ │   IPv6     │ │ Pod (net1)     │ │
│ │ ::100 - ::ffff │ │◄──────────►│ │ ::1:100-::1:ffff││
│ └────────────────┘ │  L3 Route  │ └────────────────┘ │
└────────────────────┘            └────────────────────┘
```

## IPvlan L3S Mode Details

- **Mode**: L3S (Layer 3 Slave)
- **Master Interface**: eth0 (node's primary interface)
- **IPAM**: host-local (assigns IPs from configured ranges)
- **Advantages**:
  - Flat network without overlays
  - Direct routing between pods
  - Lower CPU overhead than overlay networks
  - Native IPv6 support
