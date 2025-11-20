#!/bin/bash
set -e

# Configuration
NAMESPACE="${NAMESPACE:-endpoint-test}"
NUM_SERVICES="${NUM_SERVICES:-10}"
PODS_PER_SERVICE="${PODS_PER_SERVICE:-5}"
BATCH_SIZE="${BATCH_SIZE:-5}"
DELAY_BETWEEN_BATCHES="${DELAY_BETWEEN_BATCHES:-2}"
POD_IMAGE="${POD_IMAGE:-nginx:alpine}"

echo "=== EndpointSlice Load Test Setup (with Real Pods) ==="
echo "Namespace: $NAMESPACE"
echo "Number of Services: $NUM_SERVICES"
echo "Pods per Service: $PODS_PER_SERVICE"
echo "Batch Size: $BATCH_SIZE"
echo "Delay between batches: ${DELAY_BETWEEN_BATCHES}s"
echo "Pod Image: $POD_IMAGE"
echo "========================================================="

# Create namespace if it doesn't exist
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# Function to create a StatefulSet with headless service
create_service_with_pods() {
    local service_name=$1
    local num_pods=$2
    
    # Create headless service
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: ${service_name}
  namespace: ${NAMESPACE}
  labels:
    app: endpoint-load-test
    service: ${service_name}
spec:
  clusterIP: None
  selector:
    app: endpoint-load-test
    service: ${service_name}
  ports:
  - port: 80
    protocol: TCP
    targetPort: 80
    name: http
EOF

    # Create StatefulSet to generate pods with stable network identities
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: ${service_name}
  namespace: ${NAMESPACE}
  labels:
    app: endpoint-load-test
    service: ${service_name}
spec:
  serviceName: ${service_name}
  replicas: ${num_pods}
  selector:
    matchLabels:
      app: endpoint-load-test
      service: ${service_name}
  template:
    metadata:
      labels:
        app: endpoint-load-test
        service: ${service_name}
    spec:
      containers:
      - name: endpoint-pod
        image: ${POD_IMAGE}
        ports:
        - containerPort: 80
          name: http
        resources:
          requests:
            cpu: 10m
            memory: 32Mi
          limits:
            cpu: 50m
            memory: 64Mi
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 2
          periodSeconds: 2
        livenessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 5
      - name: dns-checker
        image: busybox:1.28
        env:
        - name: SERVICE_NAME
          value: "${service_name}"
        - name: NAMESPACE
          value: "${NAMESPACE}"
        command:
        - sh
        - -c
        - |
          echo "DNS Checker started for pod \${HOSTNAME} in service \${SERVICE_NAME}"
          while true; do            
            # Force DNS lookup by querying service name (not in /etc/hosts)
            echo "\$(date '+%Y-%m-%d %H:%M:%S') - Looking up service \${SERVICE_NAME}"
            OUTPUT=\$(nslookup \${SERVICE_NAME} 2>&1)
            echo "\$OUTPUT"
            if echo "\$OUTPUT" | grep -q "can't resolve\|not found\|No answer\|NXDOMAIN"; then
              echo "✗ FAILED"
            elif echo "\$OUTPUT" | grep -q "Name:.*\${SERVICE_NAME}"; then
              echo "✓ SUCCESS"
            else
              echo "✗ FAILED"
            fi
            echo "---"
            
            # Also lookup the FQDN to ensure DNS traffic
            FQDN="\${HOSTNAME}.\${SERVICE_NAME}.\${NAMESPACE}.svc.cluster.local"
            echo "\$(date '+%Y-%m-%d %H:%M:%S') - Looking up FQDN \${FQDN}"
            OUTPUT=\$(nslookup \${FQDN} 2>&1)
            echo "\$OUTPUT"
            if echo "\$OUTPUT" | grep -q "can't resolve\|not found\|No answer\|NXDOMAIN"; then
              echo "✗ FAILED"
            elif echo "\$OUTPUT" | grep -q "Name:"; then
              echo "✓ SUCCESS"
            else
              echo "✗ FAILED"
            fi
            echo "---"

            sleep 5
          done
        resources:
          requests:
            cpu: 5m
            memory: 16Mi
          limits:
            cpu: 20m
            memory: 32Mi
EOF
}

# Create services in batches
echo "Creating StatefulSets with headless services..."
for ((batch_start=1; batch_start<=NUM_SERVICES; batch_start+=BATCH_SIZE)); do
    batch_end=$((batch_start + BATCH_SIZE - 1))
    if [ $batch_end -gt $NUM_SERVICES ]; then
        batch_end=$NUM_SERVICES
    fi
    
    echo "Processing batch: services $batch_start to $batch_end"
    
    # Create services in parallel within the batch
    for ((i=batch_start; i<=batch_end; i++)); do
        create_service_with_pods "test-service-$i" "$PODS_PER_SERVICE" &
    done
    
    # Wait for batch to complete
    wait
    
    echo "Batch complete. Created $((batch_end - batch_start + 1)) services with StatefulSets"
    
    # Delay between batches
    if [ $batch_end -lt $NUM_SERVICES ]; then
        sleep "$DELAY_BETWEEN_BATCHES"
    fi
done

echo ""
echo "=== Waiting for pods to be ready ==="
echo "This may take a few minutes as pods start up..."

# Wait for all pods to be ready
for ((i=1; i<=NUM_SERVICES; i++)); do
    kubectl wait --for=condition=ready pod -l service=test-svc-$i -n $NAMESPACE --timeout=300s 2>/dev/null || true
    if [ $((i % 10)) -eq 0 ]; then
        echo "Waited for $i services..."
    fi
done

echo ""
echo "=== Setup Complete ==="
echo "Total services created: $NUM_SERVICES"
echo "Total pods: $((NUM_SERVICES * PODS_PER_SERVICE))"
echo ""
echo "To view resources:"
echo "  kubectl get svc,statefulsets,pods -n $NAMESPACE"
echo ""
echo "To view EndpointSlices with actual IPs:"
echo "  kubectl get endpointslices -n $NAMESPACE"
echo "  kubectl describe endpointslice -n $NAMESPACE test-svc-1"
echo ""
echo "To test DNS resolution (headless service):"
echo "  kubectl run -it --rm dns-test --image=busybox -n $NAMESPACE -- nslookup test-svc-1.$NAMESPACE.svc.cluster.local"
echo "  kubectl run -it --rm dns-test --image=busybox -n $NAMESPACE -- nslookup test-svc-1-0.test-svc-1.$NAMESPACE.svc.cluster.local"
echo ""
echo "To monitor endpointslice controller performance:"
echo "  kubectl top pod -n kube-system | grep endpoint"
echo ""
echo "To cleanup:"
echo "  kubectl delete namespace $NAMESPACE"
