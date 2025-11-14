# Ingress and Egress Testing Guide

## Prerequisites
- CNI configuration updated with default route (0.0.0.0/0)
- Pods recreated to pick up new routes
- Node routes configured for cross-node communication

## 1. EGRESS Testing (Pod → Internet)

### Test 1: Ping external IP
```bash
kubectl exec pod0 -- ping -c3 8.8.8.8
```
**Expected**: Successful ping to Google DNS

### Test 2: HTTP request to external site
```bash
kubectl exec pod0 -- wget -q -O- -T 5 http://google.com
```
**Expected**: HTML response from Google

### Test 3: DNS resolution
```bash
kubectl exec pod0 -- nslookup google.com
```
**Expected**: DNS resolution works (requires DNS server configuration)

## 2. INGRESS Testing (External → Pod)

### Test 1: Deploy a simple HTTP server in a pod
```bash
# Create a pod with a web server
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: web-server
  labels:
    app: web
spec:
  containers:
  - name: nginx
    image: nginx:alpine
    ports:
    - containerPort: 80
EOF

# Wait for pod to be ready
kubectl wait --for=condition=ready pod/web-server --timeout=60s

# Get pod IP
WEB_IP=$(kubectl get pod web-server -o jsonpath='{.status.podIP}')
echo "Web server IP: $WEB_IP"
```

### Test 2: Access from node (same node)
```bash
# Get the node where web-server is running
WEB_NODE=$(kubectl get pod web-server -o jsonpath='{.spec.nodeName}')

# Access from that node
kubectl debug node/$WEB_NODE -it --image=curlimages/curl -- curl http://$WEB_IP
```
**Expected**: Nginx welcome page

### Test 3: Access from another pod
```bash
kubectl exec pod0 -- wget -q -O- http://$WEB_IP
```
**Expected**: Nginx welcome page

### Test 4: Create a Service and test
```bash
# Create a service
kubectl expose pod web-server --port=80 --name=web-service

# Get service IP
SVC_IP=$(kubectl get svc web-service -o jsonpath='{.spec.clusterIP}')

# Test from a pod
kubectl exec pod0 -- wget -q -O- http://$SVC_IP
```
**Expected**: Nginx welcome page (if kube-proxy supports your CNI)

## 3. EAST-WEST Testing (Pod ↔ Pod)

### Test 1: Same node communication
```bash
kubectl exec pod0 -- ping -c3 $(kubectl get pod pod1 -o jsonpath='{.status.podIP}')
```

### Test 2: Cross-node communication
```bash
POD2_IP=$(kubectl get pod pod2 -o jsonpath='{.status.podIP}')
kubectl exec pod0 -- ping -c3 $POD2_IP
kubectl exec pod2 -- ping -c3 $(kubectl get pod pod0 -o jsonpath='{.status.podIP}')
```

## 4. Common Issues and Troubleshooting

### Issue: Egress not working
**Cause**: Missing default route or SNAT
**Fix**: 
- Ensure CNI config has `{ "dst": "0.0.0.0/0" }` route
- Configure SNAT on nodes or use Azure NAT Gateway

### Issue: Ingress from internet not working
**Cause**: Azure NSG, Load Balancer, or routing not configured
**Fix**:
- Use Azure Load Balancer with Service type LoadBalancer
- Configure Azure NSG rules
- Use Ingress Controller (nginx-ingress, traefik, etc.)

### Issue: DNS not working
**Cause**: No DNS server configured in pods
**Fix**: Configure CoreDNS or add nameserver in CNI config

## 5. Advanced: Load Balancer Service

```bash
# Create a LoadBalancer service
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: web-lb
spec:
  type: LoadBalancer
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 80
EOF

# Wait for external IP
kubectl get svc web-lb -w

# Once external IP is assigned, test from your local machine
EXTERNAL_IP=$(kubectl get svc web-lb -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://$EXTERNAL_IP
```
