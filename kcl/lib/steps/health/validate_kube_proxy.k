import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

# kube-proxy: a ClusterIP service is reachable from within the cluster,
# exercising service routing. For daemonset/pod health, pair with
# ValidateWorkloadHealth(kind="daemonset", name="kube-proxy", namespace="kube-system")
# only on clusters that run kube-proxy; skip it when a replacement (e.g. Cilium
# eBPF) is used, since there is no kube-proxy daemonset to check.
ValidateKubeProxy = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate kube-proxy"
    script = """
fail() { echo "FAILED KUBE-PROXY CHECK: $*"; exit 1; }

# ClusterIP reachability: deploy a service + backend and reach it from within
# the cluster to exercise service routing.
suffix=$RANDOM
app="aks-validation-kp-$suffix"
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
  sh -c 'out=$(wget -T 10 -t 1 -qO- "http://'$clusterip':80/ping") && echo "$out" && [ "$out" = "pong" ]' 2>&1); then
  fail "ClusterIP service not reachable (got '$out')"
fi

echo "client output: $out"
echo "kube-proxy validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
