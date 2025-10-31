ls -la /opt/cni/bin/ # List all CNI plugins

/opt/cni/bin/host-local
# CNI host-local plugin v1.6.2
# CNI protocol versions supported: 0.1.0, 0.2.0, 0.3.0, 0.3.1, 0.4.0, 1.0.0, 1.1.0

/opt/cni/bin/ipvlan
# CNI ipvlan plugin v1.6.2
# CNI protocol versions supported: 0.1.0, 0.2.0, 0.3.0, 0.3.1, 0.4.0, 1.0.0, 1.1.0

# Create a CNI bridge config file
cat > /etc/cni/net.d/10-bridge.conf << EOF
{
  "cniVersion": "0.3.1",
  "name": "mynet",
  "type": "bridge",
  "bridge": "cni0",
  "isGateway": true,
  "ipMasq": true,
  "ipam": {
    "type": "host-local",
    "subnet": "10.22.0.0/16",
    "routes": [
      { "dst": "0.0.0.0/0" }
    ]
  }
}
EOF



# Create NetworkAttachmentDefinitions for ipvlan L3
cat <<EOF > /etc/cni/multus/net.d/ipv6-l3-node0.conf
{
    "cniVersion": "0.3.1",
    "name": "ipv6-l3-node0",
    "type": "ipvlan",
    "master": "eth0",
    "mode": "l3",
    "isDefaultGateway": true,
    "ipam": {
        "type": "host-local",
        "ranges": [
            [
                {
                    "subnet": "fd00:ae48:be9:1::/64",
                    "rangeStart": "fd00:ae48:be9:1::100",
                    "rangeEnd": "fd00:ae48:be9:1::1ff"
                }
            ]
        ],
        "routes": [
            {
                "dst": "fd00:ae48:be9:2::/64"
            }
        ]
    }
}
EOF

cat <<EOF > /etc/cni/multus/net.d/ipv6-l3-node1.conf
{
    "cniVersion": "0.3.1",
    "name": "ipv6-l3-node1",
    "type": "ipvlan",
    "master": "eth0",
    "mode": "l3",
    "isDefaultGateway": true,
    "ipam": {
        "type": "host-local",
        "ranges": [
            [
                {
                    "subnet": "fd00:ae48:be9:2::/64",
                    "rangeStart": "fd00:ae48:be9:2::100",
                    "rangeEnd": "fd00:ae48:be9:2::1ff"
                }
            ]
        ],
        "routes": [
            {
                "dst": "fd00:ae48:be9:1::/64"
            }
        ]
    }
}
EOF

# Create NetworkAttachmentDefinitions for ipvlan L3s
cat <<EOF > /etc/cni/multus/net.d/ipv6-l3s-node0.conf
{
    "cniVersion": "0.3.1",
    "name": "ipv6-l3s-node0",
    "type": "ipvlan",
    "master": "eth0",
    "mode": "l3s",
    "ipam": {
        "type": "host-local",
        "ranges": [
            [
                {
                    "subnet": "fd00:ae48:be9:1::/64",
                    "rangeStart": "fd00:ae48:be9:1::101",
                    "rangeEnd": "fd00:ae48:be9:1::1ff",
                    "gateway": "fd00:ae48:be9:1::100"
                }
            ]
        ],
        "routes": [
            {
                "dst": "fd00:ae48:be9:2::/64"
            }
        ]
    }
}
EOF

cat <<EOF > /etc/cni/multus/net.d/ipv6-l3s-node1.conf
{
    "cniVersion": "0.3.1",
    "name": "ipv6-l3s-node1",
    "type": "ipvlan",
    "master": "eth0",
    "mode": "l3s",
    "ipam": {
        "type": "host-local",
        "ranges": [
            [
                {
                    "subnet": "fd00:ae48:be9:2::/64",
                    "rangeStart": "fd00:ae48:be9:2::101",
                    "rangeEnd": "fd00:ae48:be9:2::1ff",
                    "gateway": "fd00:ae48:be9:2::100"
                }
            ]
        ],
        "routes": [
            {
                "dst": "fd00:ae48:be9:1::/64"
            }
        ]
    }
}
EOF

kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml
kubectl get pods -n kube-system -l app=multus -o wide
kubectl get crd
kubectl get net-attach-def
kubectl rollout restart ds kube-multus-ds -n kube-system
kubectl rollout status ds kube-multus-ds -n kube-system

# Updated ipvlan l3 with correct subnet fd00:5852:d4bf::/64
cat <<EOF > /etc/cni/net.d/ipv6-l3-node0.conf
{
    "cniVersion": "0.3.1",
    "name": "ipv6-l3-node0",
    "type": "ipvlan",
    "master": "eth0",
    "mode": "l3",
    "ipam": {
        "type": "host-local",
        "ranges": [
            [
                {
                    "subnet": "fd00:5852:d4bf::/64",
                    "rangeStart": "fd00:5852:d4bf::1000",
                    "rangeEnd": "fd00:5852:d4bf::1fff"
                }
            ]
        ]
    }
}
EOF

cat <<EOF > /etc/cni/net.d/ipv6-l3-node1.conf
{
    "cniVersion": "0.3.1",
    "name": "ipv6-l3-node1",
    "type": "ipvlan",
    "master": "eth0",
    "mode": "l3",
    "ipam": {
        "type": "host-local",
        "ranges": [
            [
                {
                    "subnet": "fd00:5852:d4bf::/64",
                    "rangeStart": "fd00:5852:d4bf::2000",
                    "rangeEnd": "fd00:5852:d4bf::2fff"
                }
            ]
        ]
    }
}
EOF

# Check IPv6 addresses
kubectl get pods -o wide
kubectl exec pod0 -- ip -6 addr show
kubectl exec pod1 -- ip -6 addr show
kubectl exec pod0 -- ip -6 route show
kubectl exec pod1 -- ip -6 route show

# Test connectivity with updated subnet ranges
kubectl exec pod0 -- ping6 -c 1 fd00:5852:d4bf::2001  # ping node1 pod range
kubectl exec pod1 -- ping6 -c 1 fd00:5852:d4bf::1001  # ping node0 pod range

kubectl delete -f /home/alyssavu/telescope/debug/cni/pods.yaml && kubectl apply -f /home/alyssavu/telescope/debug/cni/pods.yaml

# On each node, add routes to reach the other subnet through the master interface
# Run this on node0:
ip -6 route add fd00:ae48:be9:2::/64 dev eth0
# Run this on node1:  
ip -6 route add fd00:ae48:be9:1::/64 dev eth0
ip -6 route show

az aks nodepool add --name agent --cluster-name ipvlan -g ipv6-test --subscription 137f0351-8235-42a6-ac7a-6b46be2d21c7 \
    --node-count 2 --node-vm-size Standard_D8ds_v5 --mode User --vm-set-type VirtualMachines