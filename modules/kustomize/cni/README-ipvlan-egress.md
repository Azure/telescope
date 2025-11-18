# IPvlan CNI Configuration for AKS (network-plugin: None)

This configuration enables **ipvlan in L3s mode** with support for:
- ✅ Pod-to-pod communication (within 10.224.0.0/16)
- ✅ Pod egress to internet
- ✅ Pod ingress (from internet)
- ✅ DNS resolution

## Architecture

### How it works

1. **IPvlan L3s Mode**: Each pod gets an IP from the node's subnet, with L3 routing
2. **Default Route**: Pods route all traffic through the ipvlan interface (no explicit gateway needed)
3. **IP Masquerading (SNAT)**: Node NATs pod traffic using its own IP for egress
4. **Pod-to-Pod**: Direct routing within the 10.224.0.0/16 CIDR

### Network Flow

```
Pod (10.224.0.17) 
  → ipvlan interface (eth0)
  → Node kernel routing (via master interface eth0)
  → Node iptables MASQUERADE
  → Node eth0 (with node IP)
  → Internet
```

## Files

- **ipv4-config-egress.yaml**: Configures ipvlan CNI on each node
- **ipv4-enable-masquerade.yaml**: Sets up IP masquerading for egress traffic

## Configuration Details

### CNI Configuration (per node)

Each node gets a /28 subnet:

- Node 1: 10.224.0.16/28 (IPs: .17-.30)
- Node 2: 10.224.0.32/28 (IPs: .33-.46)
- Node 3: 10.224.0.48/28 (IPs: .49-.62)

### Key CNI Parameters

```json
{
  "mode": "l3s",              // L3 routing with separate network stack
  "master": "eth0",           // Use node's primary interface
  "routes": [
    { "dst": "0.0.0.0/0" }    // Default route (no gateway needed in L3s mode)
  ]
}
```

**Important**: In ipvlan L3s mode, you don't specify a gateway. The kernel automatically routes traffic through the master interface.

### IP Masquerading Rules

```bash
iptables -t nat -A POSTROUTING -s 10.224.0.16/28 ! -d 10.224.0.0/16 -j MASQUERADE
```

This rule:

- Applies to traffic FROM pod subnet (`-s 10.224.0.16/28`)
- Going to internet (NOT to pod network: `! -d 10.224.0.0/16`)
- Masquerades (SNAT) using the node's IP

The command pattern used in the YAML files ensures idempotent rule creation:

```bash
iptables -t nat -C POSTROUTING ... 2>/dev/null || iptables -t nat -A POSTROUTING ...
```

This checks if the rule exists first, and only adds it if it doesn't (prevents duplicate rules on pod restarts).

## Deployment

### Manual Deployment

```bash
# 1. Apply CNI configuration
kubectl apply -f ipv4-config-egress.yaml

# 2. Enable IP masquerading
kubectl apply -f ipv4-enable-masquerade.yaml

# 3. Restart CoreDNS
kubectl delete pod -n kube-system -l k8s-app=kube-dns
```

## Verification

### Test Egress Connectivity

```bash
kubectl run test-egress --image=busybox --rm -it --restart=Never -- wget -O- http://www.google.com
```

### Test DNS Resolution

```bash
kubectl run test-dns --image=busybox --rm -it --restart=Never -- nslookup google.com
```

### Test Pod-to-Pod Communication

```bash
# Start a server pod
kubectl run server --image=nginx

# Get server IP
SERVER_IP=$(kubectl get pod server -o jsonpath='{.status.podIP}')

# Test from client
kubectl run client --image=busybox --rm -it --restart=Never -- wget -O- http://$SERVER_IP
```

### Check Routing

```bash
# Check pod routes (from a privileged pod)
kubectl run debug --image=nicolaka/netshoot --rm -it --restart=Never -- ip route

# Expected output:
# default dev eth0 scope link
```

## Troubleshooting

### CoreDNS Pods Failing

**Symptom**: `network is unreachable` when trying to reach 168.63.129.16

**Solution**: Ensure:

1. Default route is configured: `{ "dst": "0.0.0.0/0" }` (no gateway needed)
2. IP masquerading is enabled on the node
3. IP forwarding is enabled: `echo 1 > /proc/sys/net/ipv4/ip_forward`

### Pods Can't Reach Internet

**Check**:

```bash
# Verify masquerade pods are running
kubectl get pods -l app=ipv4-masq

# Check iptables rules on node
kubectl exec -it ipv4-masq-node1 -- iptables -t nat -L POSTROUTING -n -v
```

### Pod-to-Pod Communication Broken

**Check**:

```bash
# Verify ipvlan interfaces exist in pods
kubectl run debug --image=nicolaka/netshoot --rm -it --restart=Never -- ip link show
```

## Why This Configuration Works

### Problem with Original Config

Your original configuration only had:

```json
"routes": [
  { "dst": "10.224.0.0/16" }
]
```

This means:

- ❌ No default route → pods can't reach internet
- ❌ No gateway → packets don't know where to go
- ❌ No SNAT → even if packets reach node, they use pod IP (which is not routable externally)

### Solution

1. **Removed Non-existent Gateway**: Original tried to use `10.224.0.1` which doesn't exist in the VNet
2. **Simplified Route**: `{ "dst": "0.0.0.0/0" }` - L3s mode doesn't need an explicit gateway
3. **Added MASQUERADE**: NATs pod traffic using node IP for internet access

In ipvlan L3s mode, the kernel automatically routes traffic through the master interface (`eth0`), so no gateway parameter is needed.

## Notes

- **IP Forwarding**: Automatically enabled by masquerade pods
- **iptables Persistence**: Rules are set by long-running masquerade pods
- **Scale**: Adjust subnet sizes (currently /28 = 14 usable IPs per node) as needed
- **Azure DNS**: 168.63.129.16 is Azure's metadata service DNS - accessible via default route

## References

- [IPvlan CNI Documentation](https://www.cni.dev/plugins/current/main/ipvlan/)
- [Kubernetes Network Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/network-plugins/)
- [Azure AKS Custom CNI](https://learn.microsoft.com/en-us/azure/aks/concepts-network-cni-overview)
