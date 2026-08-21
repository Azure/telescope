import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

# coredns: a DNS query resolves the in-cluster kubernetes API service to a
# valid ClusterIP. For pod/controller health, pair with
# ValidateWorkloadHealth(kind="deployment", name="coredns", namespace="kube-system").
ValidateCoreDNS = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate coredns"
    script = """
set +e

pod="aks-validation-dns-$RANDOM"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1' EXIT
out=$(kubectl run "$pod" --image=${const.BUSYBOX_IMAGE} --restart=Never -i --rm --pod-running-timeout=120s \
  --command -- nslookup kubernetes.default.svc.cluster.local 2>&1)
echo "$out"
# busybox nslookup prints the resolved name followed by an Address line.
if ! echo "$out" | grep -A2 'kubernetes.default.svc.cluster.local' | grep -qiE 'Address.*[0-9]{1,3}(\\.[0-9]{1,3}){3}'; then
  echo "FAILED COREDNS CHECK: DNS query did not return a valid ClusterIP for kubernetes.default.svc.cluster.local"; exit 1
fi

echo "coredns validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
