import azure_pipelines.ap.steps
import lib.steps.azure

# Validation steps for AKS "overlay" system components (add-ons that run as
# DaemonSets/Deployments in kube-system and provide DNS, metrics, networking,
# storage, etc.). Each lambda returns a single pipeline Step that runs a
# functional check and fails the pipeline if the component is unhealthy.
#
# All steps require kubectl on the agent and a kubeconfig already in place
# (e.g. via azure.GetCredentials). The default test image is a small busybox
# from the Microsoft container registry so it works on Airlock agents.
_TEST_IMAGE = "mcr.microsoft.com/cbl-mariner/busybox:1.35"

# ---------------------------------------------------------------------------
# coredns: all coredns pods Running and a DNS query resolves the in-cluster
# kubernetes API service to a valid ClusterIP.
# ---------------------------------------------------------------------------
ValidateCoreDNS = lambda serviceConnection: str, image: str = _TEST_IMAGE, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate coredns"
    script = """
set +e
failures=0
fail() { echo "FAILED COREDNS CHECK: $*"; failures=$((failures + 1)); }

not_running=$(kubectl -n kube-system get pods -l k8s-app=kube-dns --no-headers 2>/dev/null | awk '$3 != "Running" {print $1}')
if [ -n "$not_running" ]; then
  fail "coredns pods not Running: $not_running"
fi
if [ -z "$(kubectl -n kube-system get pods -l k8s-app=kube-dns --no-headers 2>/dev/null)" ]; then
  fail "no coredns pods found"
fi

pod="overlay-dns-test-$RANDOM"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1' EXIT
out=$(kubectl run "$pod" --image=${image} --restart=Never -i --rm --pod-running-timeout=120s \
  --command -- nslookup kubernetes.default.svc.cluster.local 2>&1)
echo "$out"
# busybox nslookup prints the resolved name followed by an Address line.
if ! printf '%s\\n' "$out" | grep -A2 'kubernetes.default.svc.cluster.local' | grep -qiE 'Address[ :]+[0-9]+\\.'; then
  fail "DNS query did not return a valid ClusterIP for kubernetes.default.svc.cluster.local"
fi

if [ "$failures" -gt 0 ]; then
  echo "coredns validation failed with $failures error(s)"; exit 1
fi
echo "coredns validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}

# ---------------------------------------------------------------------------
# metrics-server: pods Running and `kubectl top nodes` returns CPU/memory for
# every node.
# ---------------------------------------------------------------------------
ValidateMetricsServer = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate metrics-server"
    script = """
set +e
failures=0
fail() { echo "FAILED METRICS-SERVER CHECK: $*"; failures=$((failures + 1)); }

not_running=$(kubectl -n kube-system get pods -l k8s-app=metrics-server --no-headers 2>/dev/null | awk '$3 != "Running" {print $1}')
if [ -n "$not_running" ]; then
  fail "metrics-server pods not Running: $not_running"
fi
if [ -z "$(kubectl -n kube-system get pods -l k8s-app=metrics-server --no-headers 2>/dev/null)" ]; then
  fail "no metrics-server pods found"
fi

node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
top=$(kubectl top nodes --no-headers 2>&1)
echo "$top"
if printf '%s\\n' "$top" | grep -qiE 'error|<unknown>|not available'; then
  fail "kubectl top nodes reported an error or missing metrics"
fi
metrics_count=$(printf '%s\\n' "$top" | grep -cE '[0-9]+m[[:space:]]+[0-9]+%')
echo "nodes=$node_count nodes_with_metrics=$metrics_count"
if [ "$metrics_count" != "$node_count" ] || [ "$node_count" = "0" ]; then
  fail "metrics returned for $metrics_count of $node_count nodes"
fi

if [ "$failures" -gt 0 ]; then
  echo "metrics-server validation failed with $failures error(s)"; exit 1
fi
echo "metrics-server validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}

# ---------------------------------------------------------------------------
# konnectivity-agent: the tunnel from control plane to nodes works, exercised
# via kubectl exec / logs / port-forward against a temporary pod.
# ---------------------------------------------------------------------------
ValidateKonnectivityAgent = lambda serviceConnection: str, image: str = _TEST_IMAGE, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate konnectivity-agent"
    script = """
set +e
failures=0
fail() { echo "FAILED KONNECTIVITY CHECK: $*"; failures=$((failures + 1)); }

not_running=$(kubectl -n kube-system get pods -l app=konnectivity-agent --no-headers 2>/dev/null | awk '$3 != "Running" {print $1}')
if [ -n "$not_running" ]; then
  fail "konnectivity-agent pods not Running: $not_running"
fi

pod="overlay-konnectivity-test-$RANDOM"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1' EXIT
kubectl run "$pod" --image=${image} --restart=Never --command -- \
  sh -c 'mkdir -p /www && echo pong > /www/ping && httpd -f -p 8080 -h /www'
kubectl wait --for=condition=Ready pod/"$pod" --timeout=120s
if [ $? -ne 0 ]; then
  fail "test pod did not become Ready"
  echo "konnectivity validation failed with $failures error(s)"; exit 1
fi

# exec traverses the konnectivity tunnel to the kubelet.
exec_out=$(kubectl exec "$pod" -- wget -qO- localhost:8080/ping 2>&1)
echo "exec output: $exec_out"
if [ "$exec_out" != "pong" ]; then
  fail "kubectl exec did not return expected output (got '$exec_out')"
fi

# logs also traverse the tunnel.
if ! kubectl logs "$pod" >/dev/null 2>&1; then
  fail "kubectl logs failed"
fi

# port-forward traverses the tunnel too. The HTTP client runs on the agent,
# so use curl and fall back to wget for portability.
kubectl port-forward pod/"$pod" 18080:8080 >/dev/null 2>&1 &
pf_pid=$!
sleep 3
if command -v curl >/dev/null 2>&1; then
  pf_out=$(curl -s http://127.0.0.1:18080/ping 2>&1)
elif command -v wget >/dev/null 2>&1; then
  pf_out=$(wget -qO- http://127.0.0.1:18080/ping 2>&1)
else
  pf_out="NO_HTTP_CLIENT"
fi
kill "$pf_pid" >/dev/null 2>&1
echo "port-forward output: $pf_out"
if [ "$pf_out" != "pong" ]; then
  fail "kubectl port-forward did not return expected output (got '$pf_out')"
fi

if [ "$failures" -gt 0 ]; then
  echo "konnectivity-agent validation failed with $failures error(s)"; exit 1
fi
echo "konnectivity-agent validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}

# ---------------------------------------------------------------------------
# azure-cns: the CNS daemonset is Running, a new pod gets an IP from the CNI
# IPAM, and the pod dataplane can reach in-cluster services.
# ---------------------------------------------------------------------------
ValidateAzureCNS = lambda serviceConnection: str, image: str = _TEST_IMAGE, errorPatterns: str = "panic|fatal", displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    assert "'" not in errorPatterns, "errorPatterns must not contain single quotes (got ${errorPatterns})"
    title = displayName if displayName else "Validate azure-cns"
    script = """
set +e
failures=0
fail() { echo "FAILED AZURE-CNS CHECK: $*"; failures=$((failures + 1)); }

not_running=$(kubectl -n kube-system get pods -l k8s-app=azure-cns --no-headers 2>/dev/null | awk '$3 != "Running" {print $1}')
if [ -n "$not_running" ]; then
  fail "azure-cns pods not Running: $not_running"
fi
if [ -z "$(kubectl -n kube-system get pods -l k8s-app=azure-cns --no-headers 2>/dev/null)" ]; then
  fail "no azure-cns pods found"
fi

# Scan azure-cns logs for fatal errors.
cns_logs=$(kubectl -n kube-system logs -l k8s-app=azure-cns --tail=200 --prefix=true 2>&1)
matches=$(printf '%s\\n' "$cns_logs" | grep -wEi '${errorPatterns}')
if [ -n "$matches" ]; then
  echo "--- azure-cns error lines ---"; printf '%s\\n' "$matches"; echo "--- end ---"
  fail "azure-cns logs contain error pattern"
fi

pod="overlay-cns-test-$RANDOM"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1' EXIT
kubectl run "$pod" --image=${image} --restart=Never --command -- sleep 300
kubectl wait --for=condition=Ready pod/"$pod" --timeout=120s
if [ $? -ne 0 ]; then
  fail "test pod did not become Ready (IP allocation may have failed)"
  echo "azure-cns validation failed with $failures error(s)"; exit 1
fi

pod_ip=$(kubectl get pod "$pod" -o jsonpath='{.status.podIP}')
echo "pod IP: $pod_ip"
if [ -z "$pod_ip" ]; then
  fail "pod did not receive an IP from azure-cns"
fi

# Dataplane reachability: resolve + connect to an in-cluster service.
reach=$(kubectl exec "$pod" -- nslookup kubernetes.default.svc.cluster.local 2>&1)
echo "$reach"
if ! printf '%s\\n' "$reach" | grep -qiE 'Address[ :]+[0-9]+\\.'; then
  fail "pod could not reach in-cluster services"
fi

if [ "$failures" -gt 0 ]; then
  echo "azure-cns validation failed with $failures error(s)"; exit 1
fi
echo "azure-cns validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}

# ---------------------------------------------------------------------------
# cloud-node-manager: every node is Ready and carries a providerID (set by the
# cloud provider integration).
# ---------------------------------------------------------------------------
ValidateCloudNodeManager = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate cloud-node-manager"
    script = """
set +e
failures=0
fail() { echo "FAILED CLOUD-NODE-MANAGER CHECK: $*"; failures=$((failures + 1)); }

kubectl get nodes -o wide

nodes=$(kubectl get nodes -o jsonpath='{.items[*].metadata.name}')
if [ -z "$nodes" ]; then
  fail "no nodes found"
fi
for n in $nodes; do
  ready=$(kubectl get node "$n" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
  provider=$(kubectl get node "$n" -o jsonpath='{.spec.providerID}')
  echo "node $n: Ready=$ready providerID=$provider"
  if [ "$ready" != "True" ]; then
    fail "node $n not Ready (Ready=$ready)"
  fi
  if [ -z "$provider" ]; then
    fail "node $n missing providerID"
  fi
done

if [ "$failures" -gt 0 ]; then
  echo "cloud-node-manager validation failed with $failures error(s)"; exit 1
fi
echo "cloud-node-manager validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}

# ---------------------------------------------------------------------------
# csi-azuredisk-node / csi-azurefile-node: create a PVC (disk or file), mount
# it in a short-lived pod, write+read a file to prove attach/mount/RW works,
# then delete the pod and PVC.
#
# driver="disk" -> ReadWriteOnce, default storageClass "managed-csi"
# driver="file" -> ReadWriteMany, default storageClass "azurefile-csi"
# ---------------------------------------------------------------------------
ValidateCsiNode = lambda serviceConnection: str, driver: "disk" | "file", storageClass: str = "", image: str = _TEST_IMAGE, namespace: str = "default", displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    sc = storageClass if storageClass else ("managed-csi" if driver == "disk" else "azurefile-csi")
    accessMode = "ReadWriteOnce" if driver == "disk" else "ReadWriteMany"
    dsLabel = "csi-azuredisk-node" if driver == "disk" else "csi-azurefile-node"
    title = displayName if displayName else "Validate csi-azure${driver}-node"
    script = """
set +e
failures=0
fail() { echo "FAILED CSI-${driver} CHECK: $*"; failures=$((failures + 1)); }

not_running=$(kubectl -n kube-system get pods -l app=${dsLabel} --no-headers 2>/dev/null | awk '$3 != "Running" {print $1}')
if [ -n "$not_running" ]; then
  fail "${dsLabel} pods not Running: $not_running"
fi

suffix=$RANDOM
pvc="overlay-csi-${driver}-pvc-$suffix"
pod="overlay-csi-${driver}-pod-$suffix"
trap 'kubectl -n ${namespace} delete pod "$pod" --ignore-not-found >/dev/null 2>&1; kubectl -n ${namespace} delete pvc "$pvc" --ignore-not-found >/dev/null 2>&1' EXIT

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $pvc
  namespace: ${namespace}
spec:
  accessModes:
    - ${accessMode}
  storageClassName: ${sc}
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: $pod
  namespace: ${namespace}
spec:
  restartPolicy: Never
  containers:
    - name: writer
      image: ${image}
      command:
        - sh
        - -c
        - "echo telescope-csi-check > /mnt/test/data && cat /mnt/test/data && echo CSI_OK"
      volumeMounts:
        - name: vol
          mountPath: /mnt/test
  volumes:
    - name: vol
      persistentVolumeClaim:
        claimName: $pvc
EOF

# Wait for the pod to finish (Succeeded) or fail.
end=$((SECONDS + 300))
phase=""
while [ $SECONDS -lt $end ]; do
  phase=$(kubectl -n ${namespace} get pod "$pod" -o jsonpath='{.status.phase}' 2>/dev/null)
  [ "$phase" = "Succeeded" ] && break
  [ "$phase" = "Failed" ] && break
  sleep 5
done
echo "pod ${namespace}/$pod phase=$phase"

if [ "$phase" != "Succeeded" ]; then
  fail "csi-${driver} pod did not succeed (phase=$phase); attach/mount likely failed"
  echo "--- pod describe ---"
  kubectl -n ${namespace} describe pod "$pod" | tail -30
fi

logs=$(kubectl -n ${namespace} logs "$pod" 2>&1)
echo "pod logs: $logs"
if ! printf '%s\\n' "$logs" | grep -q 'CSI_OK'; then
  fail "csi-${driver} read/write test did not succeed"
fi

if [ "$failures" -gt 0 ]; then
  echo "csi-azure${driver}-node validation failed with $failures error(s)"; exit 1
fi
echo "csi-azure${driver}-node validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}

# ---------------------------------------------------------------------------
# kube-proxy: pods Running with no sync errors in logs, and a ClusterIP service
# is reachable from within the cluster.
# ---------------------------------------------------------------------------
ValidateKubeProxy = lambda serviceConnection: str, image: str = _TEST_IMAGE, namespace: str = "default", displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate kube-proxy"
    script = """
set +e
failures=0
fail() { echo "FAILED KUBE-PROXY CHECK: $*"; failures=$((failures + 1)); }

kp_pods=$(kubectl -n kube-system get pods -l k8s-app=kube-proxy --no-headers 2>/dev/null)
if [ -z "$kp_pods" ]; then
  # Clusters using a kube-proxy replacement (e.g. Cilium eBPF) have no
  # kube-proxy pods. Service routing is still validated by the ClusterIP
  # reachability test below, so treat absence as informational, not a failure.
  echo "NOTE: no kube-proxy pods found; cluster likely uses a kube-proxy replacement (e.g. Cilium). Skipping pod/log checks."
else
  not_running=$(printf '%s\\n' "$kp_pods" | awk '$3 != "Running" {print $1}')
  if [ -n "$not_running" ]; then
    fail "kube-proxy pods not Running: $not_running"
  fi
  # Scan kube-proxy logs for sync failures.
  kp_logs=$(kubectl -n kube-system logs -l k8s-app=kube-proxy --tail=200 --prefix=true 2>&1)
  sync_errors=$(printf '%s\\n' "$kp_logs" | grep -iE 'failed to sync|syncProxyRules failed|error syncing')
  if [ -n "$sync_errors" ]; then
    echo "--- kube-proxy sync errors ---"; printf '%s\\n' "$sync_errors"; echo "--- end ---"
    fail "kube-proxy logs contain sync errors"
  fi
fi

# ClusterIP reachability: deploy a service + backend and reach it from within
# the cluster to exercise service routing.
suffix=$RANDOM
app="overlay-kp-test-$suffix"
trap 'kubectl -n ${namespace} delete deploy "$app" svc "$app" --ignore-not-found >/dev/null 2>&1' EXIT

cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $app
  namespace: ${namespace}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: $app
  template:
    metadata:
      labels:
        app: $app
    spec:
      containers:
        - name: web
          image: ${image}
          command:
            - sh
            - -c
            - "mkdir -p /www && echo pong > /www/ping && httpd -f -p 8080 -h /www"
          ports:
            - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: $app
  namespace: ${namespace}
spec:
  selector:
    app: $app
  ports:
    - port: 80
      targetPort: 8080
EOF

kubectl -n ${namespace} wait --for=condition=Available deploy/"$app" --timeout=120s
if [ $? -ne 0 ]; then
  fail "backend deployment did not become Available"
  echo "kube-proxy validation failed with $failures error(s)"; exit 1
fi

clusterip=$(kubectl -n ${namespace} get svc "$app" -o jsonpath='{.spec.clusterIP}')
echo "service ClusterIP: $clusterip"
# Reach the ClusterIP from within a running pod (exec output is clean, no
# --rm deletion notice to filter). This exercises the service dataplane.
backend_pod=$(kubectl -n ${namespace} get pods -l app="$app" -o jsonpath='{.items[0].metadata.name}')
out=$(kubectl -n ${namespace} exec "$backend_pod" -- wget -qO- "http://$clusterip:80/ping" 2>/dev/null)
echo "client output: $out"
if [ "$out" != "pong" ]; then
  fail "ClusterIP service not reachable (got '$out')"
fi

if [ "$failures" -gt 0 ]; then
  echo "kube-proxy validation failed with $failures error(s)"; exit 1
fi
echo "kube-proxy validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}

# ---------------------------------------------------------------------------
# Convenience: run every overlay-component validation in sequence.
# ---------------------------------------------------------------------------
ValidateOverlayComponents = lambda serviceConnection: str, namespace: str = "default", continueOnError: bool = Undefined -> [steps.Step] {
    [
        ValidateCoreDNS(serviceConnection, continueOnError=continueOnError)
        ValidateMetricsServer(serviceConnection, continueOnError=continueOnError)
        ValidateKonnectivityAgent(serviceConnection, continueOnError=continueOnError)
        ValidateAzureCNS(serviceConnection, continueOnError=continueOnError)
        ValidateCloudNodeManager(serviceConnection, continueOnError=continueOnError)
        ValidateCsiNode(serviceConnection, "disk", namespace=namespace, continueOnError=continueOnError)
        ValidateCsiNode(serviceConnection, "file", namespace=namespace, continueOnError=continueOnError)
        ValidateKubeProxy(serviceConnection, namespace=namespace, continueOnError=continueOnError)
    ]
}
