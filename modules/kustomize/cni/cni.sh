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


kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml
kubectl get pods -n kube-system -l app=multus -o wide
kubectl get crd
kubectl get net-attach-def
kubectl rollout restart ds kube-multus-ds -n kube-system
kubectl rollout status ds kube-multus-ds -n kube-system
kubectl logs -n kube-system -l app=multus

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
kubectl exec pod0 -- ping6 -c 3 fd00:5852:d4bf::2001
kubectl exec pod1 -- ping6 -c 3 fd00:5852:d4bf::1001

# Recreate pods to ensure they pick up the new network configuration
kubectl delete -f /home/alyssavu/telescope/modules/kustomize/cni/pods.yaml
kubectl apply -f /home/alyssavu/telescope/modules/kustomize/cni/pods.yaml

# Wait for pods to be ready
kubectl wait --for=condition=Ready pod/pod0 pod/pod1 --timeout=60s

az aks nodepool add --name user --cluster-name ipvlan -g ipv6-test --subscription 137f0351-8235-42a6-ac7a-6b46be2d21c7 \
    --node-count 2 --node-vm-size Standard_D8ds_v5 --mode User --vm-set-type VirtualMachines
az aks nodepool delete --name agent --cluster-name ipvlan -g ipv6-test --subscription 137f0351-8235-42a6-ac7a-6b46be2d21c7