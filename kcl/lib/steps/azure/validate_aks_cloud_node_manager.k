import azure_pipelines.ap.steps

# cloud-node-manager: the DaemonSet is fully rolled out on every node and each
# node carries a providerID (set by the cloud provider integration).
ValidateCloudNodeManager = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate cloud-node-manager"
    script = """
set +e
failures=0
fail() { echo "FAILED CLOUD-NODE-MANAGER CHECK: $*"; failures=$((failures + 1)); }

# Use the DaemonSet status for whole-node coverage in one call.
ds_status=$(kubectl -n kube-system get ds cloud-node-manager \
  -o jsonpath='{.status.desiredNumberScheduled}/{.status.numberReady}/{.status.numberAvailable}/{.status.updatedNumberScheduled}/{.status.numberMisscheduled}' 2>/dev/null)
if [ -z "$ds_status" ]; then
  fail "cloud-node-manager daemonset not found"
else
  echo "cloud-node-manager ds desired/ready/available/updated/misscheduled: $ds_status"
  desired=$(echo "$ds_status" | cut -d/ -f1)
  ready=$(echo "$ds_status" | cut -d/ -f2)
  available=$(echo "$ds_status" | cut -d/ -f3)
  updated=$(echo "$ds_status" | cut -d/ -f4)
  misscheduled=$(echo "$ds_status" | cut -d/ -f5)
  if [ -z "$desired" ] || [ "$desired" = "0" ]; then
    fail "cloud-node-manager desiredNumberScheduled is '${desired:-empty}'"
  fi
  [ "$ready" = "$desired" ]      || fail "cloud-node-manager numberReady ($ready) != desired ($desired)"
  [ "$available" = "$desired" ]  || fail "cloud-node-manager numberAvailable ($available) != desired ($desired)"
  [ "$updated" = "$desired" ]    || fail "cloud-node-manager updatedNumberScheduled ($updated) != desired ($desired)"
  [ "${misscheduled:-0}" = "0" ] || fail "cloud-node-manager numberMisscheduled = $misscheduled"
fi

# cloud-node-manager's job is to stamp each Node with a providerID; verify that
# in a single list call so no node is missed and large clusters stay fast.
node_table=$(kubectl get nodes --no-headers -o custom-columns='NAME:.metadata.name,PROVIDER:.spec.providerID' 2>/dev/null)
if [ -z "$node_table" ]; then
  fail "no nodes found"
else
  report=$(printf '%s\\n' "$node_table" | awk '
{
  total++
  if ($2 == "<none>" || $2 == "") { print "node " $1 " missing providerID"; bad++ }
}
END { print "checked " total " nodes, " bad+0 " problem(s)"; exit (bad > 0) }')
  rc=$?
  echo "$report"
  if [ "$rc" -ne 0 ]; then
    fail "cloud-node-manager: some nodes are missing providerID"
  fi
fi

if [ "$failures" -gt 0 ]; then
  echo "cloud-node-manager validation failed with $failures error(s)"; exit 1
fi
echo "cloud-node-manager validation passed"
"""
    AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
