import azure_pipelines.ap.steps

# cloud-node-manager: every node is Ready and carries a providerID (set by the
# cloud provider integration).
ValidateCloudNodeManager = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate cloud-node-manager"
    script = """
set +e
failures=0
fail() { echo "FAILED CLOUD-NODE-MANAGER CHECK: $*"; failures=$((failures + 1)); }

pods=$(kubectl -n kube-system get pods -l k8s-app=cloud-node-manager --no-headers 2>/dev/null)
if [ -z "$pods" ]; then
  fail "no cloud-node-manager pods found"
else
  bad=$(printf '%s\\n' "$pods" | awk '{split($2,r,"/"); if ($3 != "Running" || r[1] != r[2]) print $1}')
  if [ -n "$bad" ]; then
    fail "cloud-node-manager pods not Running/Ready: $bad"
  fi
fi

# Check every node in a single list call so no node is missed; a per-node
# "kubectl get node" would be one call per node and is too slow on large
# clusters. All nodes are scanned locally; only problem nodes are printed.
node_table=$(kubectl get nodes --no-headers -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,PROVIDER:.spec.providerID' 2>/dev/null)
if [ -z "$node_table" ]; then
  fail "no nodes found"
fi

report=$(printf '%s\\n' "$node_table" | awk '
{
  total++
  if ($2 != "True") { print "node " $1 " not Ready (Ready=" $2 ")"; bad++ }
  if ($3 == "<none>" || $3 == "") { print "node " $1 " missing providerID"; bad++ }
}
END { print "checked " total " nodes, " bad+0 " problem(s)"; exit (bad > 0) }')
rc=$?
echo "$report"
if [ "$rc" -ne 0 ]; then
  fail "cloud-node-manager: some nodes are not Ready or missing providerID"
fi

if [ "$failures" -gt 0 ]; then
  echo "cloud-node-manager validation failed with $failures error(s)"; exit 1
fi
echo "cloud-node-manager validation passed"
"""
    AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
