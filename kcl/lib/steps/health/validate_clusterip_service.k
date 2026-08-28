import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

# Validate that ClusterIP service routing works: a backend behind a ClusterIP is
# reachable from a separate pod. This exercises whatever service proxy the
# cluster runs (kube-proxy, Cilium eBPF, etc.). For the health of the proxy
# workload itself, pair with ValidateWorkloadHealth on the workload the cluster
# actually runs (e.g. daemonset kube-system/kube-proxy, or the cilium daemonset
# on kube-proxy-replacement clusters).
ValidateClusterIPService = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate ClusterIP service routing"
    script = """
fail() { echo "FAILED CLUSTERIP CHECK: $*"; exit 1; }

# ClusterIP reachability: deploy a service + backend and reach it from within
# the cluster to exercise service routing.
suffix=$RANDOM
app="aks-validation-clusterip-$suffix"
client="$app-client"
trap 'kubectl delete deploy/"$app" svc/"$app" pod/"$client" --ignore-not-found >/dev/null 2>&1' EXIT

cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $app
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
          image: ${const.BUSYBOX_IMAGE}
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
spec:
  selector:
    app: $app
  ports:
    - port: 80
      targetPort: 8080
EOF

if ! kubectl wait --for=condition=Available deploy/"$app" --timeout=120s; then
  fail "backend deployment did not become Available"
fi

clusterip=$(kubectl get svc "$app" -o jsonpath='{.spec.clusterIP}')
echo "service ClusterIP: $clusterip"
# Reach the ClusterIP from a separate disposable client pod. The command
# verifies the response in the pod so kubectl's --rm output cannot affect it.
if ! out=$(kubectl run "$client" --image=${const.BUSYBOX_IMAGE} --restart=Never \
  -i --rm --pod-running-timeout=120s --command -- \
  sh -c 'out=$(wget -T 10 -t 1 -qO- "http://'"$clusterip"':80/ping") && echo "$out" && [ "$out" = "pong" ]' 2>&1); then
  fail "ClusterIP service not reachable (got '$out')"
fi

echo "client output: $out"
echo "ClusterIP service validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
