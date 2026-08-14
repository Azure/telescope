import azure_pipelines.ap.steps

# azure-cns: a new pod gets an IP from the CNI IPAM, and the pod dataplane can
# reach in-cluster services. For daemonset/pod health, pair with
# ValidateWorkloadHealth(kind="daemonset", name="azure-cns", namespace="kube-system").
ValidateAzureCNS = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate azure-cns"
    script = """
set +e
failures=0
fail() { echo "FAILED AZURE-CNS CHECK: $*"; failures=$((failures + 1)); }

pod="aks-validation-cns-$RANDOM"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1' EXIT
kubectl run "$pod" --image=mcr.microsoft.com/azurelinux/busybox:1.36 --restart=Never --command -- sleep 300
if ! kubectl wait --for=condition=Ready pod/"$pod" --timeout=120s; then
  fail "test pod did not become Ready (IP allocation may have failed)"
  echo "azure-cns validation failed with $failures error(s)"; exit 1
fi

pod_ip=$(kubectl get pod "$pod" -o jsonpath='{.status.podIP}')
echo "pod IP: $pod_ip"
if [ -z "$pod_ip" ]; then
  fail "pod did not receive an IP from azure-cns"
fi

# Verify the pod's dataplane can reach an in-cluster service (the kubernetes
# API ClusterIP), proving CNI routing works end-to-end, not just IPAM. Use a
# plain connect (busybox nc has no reliable -z) and gate on its exit code.
reach_out=$(kubectl exec "$pod" -- sh -c 'nc -w5 "$KUBERNETES_SERVICE_HOST" "$KUBERNETES_SERVICE_PORT" </dev/null && echo REACHABLE' 2>&1)
echo "dataplane check: $reach_out"
if ! echo "$reach_out" | grep -q 'REACHABLE'; then
  fail "pod dataplane could not reach in-cluster kubernetes service"
fi

if [ "$failures" -gt 0 ]; then
  echo "azure-cns validation failed with $failures error(s)"; exit 1
fi
echo "azure-cns validation passed"
"""
    AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
