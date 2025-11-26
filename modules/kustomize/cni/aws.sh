CLUSTER_NAME=cni-prototype-1764030057
REGION=us-east-1
# aws eks update-kubeconfig --name $CLUSTER_NAME --region $REGION

# Create a managed node group with CNI disabled
SUBNETS=$(aws eks describe-cluster --name $CLUSTER_NAME --query "cluster.resourcesVpcConfig.subnetIds" --output text)
NODE_ROLE=$(aws eks describe-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name default \
    --query "nodegroup.nodeRole" --output text)
NODE_GROUP_TAGS=$(aws eks describe-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name default \
    --query "nodegroup.tags" --output json)
TAGS=$(echo "$NODE_GROUP_TAGS" | jq -r 'del(.Name)')
echo "TAGS: $TAGS"

aws eks create-nodegroup \
    --cluster-name $CLUSTER_NAME \
    --nodegroup-name user \
    --subnets $SUBNETS \
    --node-role $NODE_ROLE \
    --instance-types m6i.4xlarge \
    --ami-type AL2023_x86_64_STANDARD \
    --scaling-config minSize=2,maxSize=2,desiredSize=2 \
    --taints key=no-cni,value=true,effect=NO_SCHEDULE \
    --disk-size 20 \
    --tags "$TAGS"

FETCH_VERSION=1.7.1
FETCH_URL=https://github.com/containernetworking/plugins/archive/refs/tags/v${FETCH_VERSION}.tar.gz
VISIT_URL=https://github.com/containernetworking/plugins/tree/v${FETCH_VERSION}/plugins
## Fetch the CNI plugins
echo "Fetching Container networking plugins v${FETCH_VERSION} from upstream release"
echo "Visit upstream project for plugin details:"
echo "$VISIT_URL"

CORE_PLUGIN_DIR=/opt/cni/bin
CORE_PLUGIN_TMP=/tmp/core-plugins
mkdir -p $CORE_PLUGIN_TMP
curl -s -L $FETCH_URL | tar xzf - -C $CORE_PLUGIN_TMP
cd $CORE_PLUGIN_TMP/plugins-$FETCH_VERSION && ./build_linux.sh
cp -a $CORE_PLUGIN_TMP/plugins-$FETCH_VERSION/LICENSE $CORE_PLUGIN_DIR
cp -a $CORE_PLUGIN_TMP/plugins-$FETCH_VERSION/bin/* $CORE_PLUGIN_DIR
rm -rf $CORE_PLUGIN_TMP

# Run debug pod in another cluster and node
kubectl --context=cni-prototype debug node/aks-default-42863573-vms1 -it --image=mcr.microsoft.com/cbl-mariner/busybox:2.0 --profile=sysadmin

## Node routing and interface
[root@ip-10-0-13-44 net.d]# ip route show
default via 10.0.0.1 dev ens5 proto dhcp src 10.0.13.44 metric 512 # default gateway of subnet
10.0.0.0/20 dev ens5 proto kernel scope link src 10.0.13.44 metric 512 # subnet route
10.0.0.1 dev ens5 proto dhcp scope link src 10.0.13.44 metric 512 # gateway IP of subnet
10.0.0.2 dev ens5 proto dhcp scope link src 10.0.13.44 metric 512 
10.0.11.132 dev veth79826650 scope link 
10.0.13.170 dev veth4a735bf2 scope link 
[root@ip-10-0-34-111 net.d]# ip route show
default via 10.0.32.1 dev ens5 proto dhcp src 10.0.34.111 metric 512 
10.0.0.2 via 10.0.32.1 dev ens5 proto dhcp src 10.0.34.111 metric 512 
10.0.32.0/20 dev ens5 proto kernel scope link src 10.0.34.111 metric 512 
10.0.32.1 dev ens5 proto dhcp scope link src 10.0.34.111 metric 512 
10.0.42.165 dev veth176aa736 scope link 
10.0.42.237 dev vethf6d44e3b scope link

[root@ip-10-0-13-44 net.d]# ip a show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host noprefixroute 
       valid_lft forever preferred_lft forever
2: ens5: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc mq state UP group default qlen 1000
    link/ether 12:4b:58:0c:24:b3 brd ff:ff:ff:ff:ff:ff
    altname enp0s5
    inet 10.0.13.44/20 metric 512 brd 10.0.15.255 scope global dynamic ens5
       valid_lft 3076sec preferred_lft 3076sec
    inet6 fe80::104b:58ff:fe0c:24b3/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
3: ens6: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc mq state UP group default qlen 1000
    link/ether 12:0a:11:a3:87:0f brd ff:ff:ff:ff:ff:ff
    altname enp0s6
    inet6 fe80::100a:11ff:fea3:870f/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
4: veth4a735bf2@if4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue state UP group default 
    link/ether f2:a3:71:14:24:ec brd ff:ff:ff:ff:ff:ff link-netns cni-d1e73d62-3372-5866-89a8-73e7337c0e54
    inet6 fe80::f0a3:71ff:fe14:24ec/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
5: veth79826650@if4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue state UP group default 
    link/ether 9e:f3:27:1c:11:36 brd ff:ff:ff:ff:ff:ff link-netns cni-81cde27e-f3e7-c57e-ec18-05aaabe0ea1d
    inet6 fe80::9cf3:27ff:fe1c:1136/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever

[root@ip-10-0-34-111 net.d]# ip a show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host noprefixroute 
       valid_lft forever preferred_lft forever
2: ens5: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc mq state UP group default qlen 1000
    link/ether 0e:75:38:1f:2d:fb brd ff:ff:ff:ff:ff:ff
    altname enp0s5
    inet 10.0.34.111/20 metric 512 brd 10.0.47.255 scope global dynamic ens5
       valid_lft 3066sec preferred_lft 3066sec
    inet6 fe80::c75:38ff:fe1f:2dfb/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
3: ens6: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc mq state UP group default qlen 1000
    link/ether 0e:3c:1a:29:f4:07 brd ff:ff:ff:ff:ff:ff
    altname enp0s6
    inet6 fe80::c3c:1aff:fe29:f407/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
4: veth176aa736@if4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue state UP group default 
    link/ether 82:1a:62:4e:96:83 brd ff:ff:ff:ff:ff:ff link-netns cni-cd7d61f1-8aec-f9ec-59f0-3785268283fb
    inet6 fe80::801a:62ff:fe4e:9683/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
5: vethf6d44e3b@if4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue state UP group default 
    link/ether 92:8e:a5:a5:4f:7a brd ff:ff:ff:ff:ff:ff link-netns cni-56bb19e0-9e61-5ce2-38fb-33f03357a2f8
    inet6 fe80::908e:a5ff:fea5:4f7a/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever

(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ kubectl exec pod1 -- ip addr show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host 
       valid_lft forever preferred_lft forever
2: eth0@if3: <BROADCAST,MULTICAST,UP,LOWER_UP,M-DOWN> mtu 9001 qdisc noqueue 
    link/ether 12:0a:11:a3:87:0f brd ff:ff:ff:ff:ff:ff
    inet 10.0.13.170/20 brd 10.0.15.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::120a:1100:1a3:870f/64 scope link 
       valid_lft forever preferred_lft forever
4: eth1@eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue 
    link/ether 3e:54:42:db:b2:2c brd ff:ff:ff:ff:ff:ff
    inet6 fe80::3c54:42ff:fedb:b22c/64 scope link 
       valid_lft forever preferred_lft forever
(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ kubectl exec pod1 -- ip route show
default via 10.0.13.44 dev eth1 
10.0.0.0/20 dev eth0 scope link  src 10.0.13.170 
10.0.0.0/16 via 10.0.0.1 dev eth0 
10.0.13.44 dev eth1 scope link

(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ kubectl exec pod2 -- ip addr show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host 
       valid_lft forever preferred_lft forever
2: eth0@if3: <BROADCAST,MULTICAST,UP,LOWER_UP,M-DOWN> mtu 9001 qdisc noqueue 
    link/ether 0e:3c:1a:29:f4:07 brd ff:ff:ff:ff:ff:ff
    inet 10.0.42.165/20 brd 10.0.47.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::e3c:1a00:129:f407/64 scope link 
       valid_lft forever preferred_lft forever
4: eth1@eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue 
    link/ether ae:6a:2a:a0:d9:24 brd ff:ff:ff:ff:ff:ff
    inet6 fe80::ac6a:2aff:fea0:d924/64 scope link 
       valid_lft forever preferred_lft forever
(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ kubectl exec pod2 -- ip route show
default via 10.0.34.111 dev eth1 
10.0.0.0/16 via 10.0.32.1 dev eth0 
10.0.32.0/20 dev eth0 scope link  src 10.0.42.165 
10.0.34.111 dev eth1 scope link

## Iperf3
(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ k exec -it iperf3-client -- ip a show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host proto kernel_lo 
       valid_lft forever preferred_lft forever
2: eth0@if3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue state UNKNOWN group default 
    link/ether 12:0a:11:a3:87:0f brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet 10.0.11.132/20 brd 10.0.15.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::120a:1100:2a3:870f/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
4: eth1@if5: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue state UP group default 
    link/ether 2a:14:c1:c4:a3:a6 brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet6 fe80::2814:c1ff:fec4:a3a6/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ k exec -it iperf3-client -- ip route show
default via 10.0.13.44 dev eth1 
10.0.0.0/20 dev eth0 proto kernel scope link src 10.0.11.132 
10.0.0.0/16 via 10.0.0.1 dev eth0 
10.0.13.44 dev eth1 scope link

(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ k exec -it iperf3-server -- ip a show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host proto kernel_lo 
       valid_lft forever preferred_lft forever
2: eth0@if3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue state UNKNOWN group default 
    link/ether 0e:3c:1a:29:f4:07 brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet 10.0.42.237/20 brd 10.0.47.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::e3c:1a00:229:f407/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
4: eth1@if5: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9001 qdisc noqueue state UP group default 
    link/ether 82:f6:bb:b5:48:d1 brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet6 fe80::80f6:bbff:feb5:48d1/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
(env) alyssavu@CPC-alyss-5IIXY:~/telescope$ k exec -it iperf3-server -- ip route show
default via 10.0.34.111 dev eth1 
10.0.0.0/16 via 10.0.32.1 dev eth0 
10.0.32.0/20 dev eth0 proto kernel scope link src 10.0.42.237 
10.0.34.111 dev eth1 scope link


## Copy to node
pod_name=nsenter-eitmex
kubectl cp cni-ipvlan-vpc-k8s-ipam ${pod_name}:/opt/cni/bin
kubectl cp cni-ipvlan-vpc-k8s-ipvlan ${pod_name}:/opt/cni/bin
kubectl cp cni-ipvlan-vpc-k8s-tool ${pod_name}:/opt/cni/bin
kubectl cp cni-ipvlan-vpc-k8s-unnumbered-ptp ${pod_name}:/opt/cni/bin