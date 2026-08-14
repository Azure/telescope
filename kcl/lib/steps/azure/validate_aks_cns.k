import azure_pipelines.ap.steps

# azure-cns: a new pod gets an IP from the CNI IPAM, and the pod dataplane can
# reach in-cluster services. For daemonset/pod health, pair with
# ValidateWorkloadHealth(kind="daemonset", name="azure-cns", namespace="kube-system").
ValidateAzureCNS = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate azure-cns"
    script = """
set +e

pod="aks-validation-cns-$RANDOM"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1' EXIT

# Verify CNI IP allocation and routing to the kubernetes API ClusterIP.
# Kubernetes provides the API service address through KUBERNETES_SERVICE_HOST
# and KUBERNETES_SERVICE_PORT. Redirect stdin with /dev/null so nc exits after connecting.
reach_out=$(kubectl run "$pod" --image=mcr.microsoft.com/azurelinux/busybox:1.36 --restart=Never -i --rm --pod-running-timeout=120s \
  --command -- sh -c 'nc -w5 "$KUBERNETES_SERVICE_HOST" "$KUBERNETES_SERVICE_PORT" </dev/null && echo REACHABLE' 2>&1)
echo "dataplane check: $reach_out"
if ! echo "$reach_out" | grep -q 'REACHABLE'; then
  echo "FAILED AZURE-CNS CHECK: pod did not start or could not reach in-cluster kubernetes service"; exit 1
fi
echo "azure-cns validation passed"
"""
    AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
