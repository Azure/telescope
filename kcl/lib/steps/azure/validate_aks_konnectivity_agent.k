import azure_pipelines.ap.steps
import lib.const

# konnectivity-agent: the tunnel from control plane to nodes works, exercised
# via kubectl exec against a temporary pod. For pod/controller health, pair with
# ValidateWorkloadHealth(kind="deployment", name="konnectivity-agent", namespace="kube-system").
ValidateKonnectivityAgent = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate konnectivity-agent"
    script = """
set +e
pod="aks-validation-konnectivity-$RANDOM"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1' EXIT
kubectl run "$pod" --image=${const.BUSYBOX_IMAGE} --restart=Never --command -- sleep 300
if ! kubectl wait --for=condition=Ready pod/"$pod" --timeout=120s; then
  echo "konnectivity-agent validation failed: test pod did not become Ready"
  exit 1
fi

# exec traverses the konnectivity tunnel to the kubelet.
exec_out=$(kubectl exec "$pod" -- printf pong 2>&1)
echo "exec output: $exec_out"
if [ "$exec_out" != "pong" ]; then
  echo "konnectivity-agent validation failed: kubectl exec returned '$exec_out'"
  exit 1
fi
echo "konnectivity-agent validation passed"
"""
    AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
