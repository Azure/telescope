import azure_pipelines.ap.steps
import lib.steps.azure

# metrics-server: `kubectl top nodes` returns CPU/memory metrics. For
# pod/controller health, pair with
# ValidateWorkloadHealth(kind="deployment", name="metrics-server", namespace="kube-system").
ValidateMetricsServer = lambda serviceConnection: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    title = displayName if displayName else "Validate metrics-server"
    script = """
set +e
failures=0
fail() { echo "FAILED METRICS-SERVER CHECK: $*"; failures=$((failures + 1)); }

# Only the first 50 nodes are sampled to keep this check fast on large clusters.
sample_nodes=$(kubectl get nodes -o name 2>/dev/null | head -n 50 | cut -d/ -f2)
if [ -z "$sample_nodes" ]; then
  fail "no nodes found"
fi
sampled=0
metrics_count=0
for n in $sample_nodes; do
  sampled=$((sampled + 1))
  line=$(kubectl top node "$n" --no-headers 2>&1)
  echo "$line"
  # The regex matches only the CPU columns (millicores + CPU%); memory is not
  # separately validated, presence of a CPU reading implies metrics-server works.
  if echo "$line" | grep -qE '[0-9]+m[[:space:]]+[0-9]+%'; then
    metrics_count=$((metrics_count + 1))
  else
    fail "no metrics for node $n: $line"
  fi
done
echo "sampled=$sampled nodes_with_metrics=$metrics_count"

if [ "$failures" -gt 0 ]; then
  echo "metrics-server validation failed with $failures error(s)"; exit 1
fi
echo "metrics-server validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
