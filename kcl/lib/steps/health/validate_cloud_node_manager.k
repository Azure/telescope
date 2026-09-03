import azure_pipelines.ap.steps
import lib.steps.azure

# cloud-node-manager: verify the cloud provider integration by checking that
# every Node carries a providerID. For generic controller/pod health, pair this
# with ValidateWorkloadHealth(kind="daemonset", name="cloud-node-manager",
# namespace="kube-system") from k8s/validate_workload.k.
ValidateCloudNodeManager = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate cloud-node-manager"
    script = """
set +e

# cloud-node-manager's job is to stamp each Node with a providerID; verify that
# in a single list call so no node is missed and large clusters stay fast.
node_table=$(kubectl get nodes --no-headers -o custom-columns='NAME:.metadata.name,PROVIDER:.spec.providerID' 2>/dev/null)
if [ -z "$node_table" ]; then
  echo "FAILED CLOUD-NODE-MANAGER CHECK: no nodes found"; exit 1
fi

report=$(echo "$node_table" | awk '
{
  total++
  if ($2 == "<none>" || $2 == "") { print "node " $1 " missing providerID"; bad++ }
}
END { print "checked " total " nodes, " bad+0 " problem(s)"; exit (bad > 0) }')
rc=$?
echo "$report"
if [ "$rc" -ne 0 ]; then
  echo "FAILED CLOUD-NODE-MANAGER CHECK: some nodes are missing providerID"; exit 1
fi

echo "cloud-node-manager validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
