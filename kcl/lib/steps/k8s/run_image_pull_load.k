import azure_pipelines.ap.steps
import lib.steps.azure

# RunImagePullLoad applies a DaemonSet that continuously pulls and evicts images
# on every target node (one puller per node), sustains that load for
# `durationSeconds`, then tears the DaemonSet down.
#
# Unlike a ClusterLoader2 deployment (which primes each node's image cache once
# and then goes quiet), the underlying pull -> rmi loop forces a fresh blob
# download from the registry on every iteration, producing steady throughput
# against the ACR stamp for the entire window.
#
# The manifest must name the DaemonSet `image-pull-load` and target `namespace`.
# RunImagePullLoad applies a DaemonSet that continuously pulls and evicts images
# on every target node (one puller per node) and sustains that load for
# `durationSeconds`. Teardown is intentionally left to a separate step
# (CollectImagePullThroughput) so the puller logs survive long enough to be
# scraped for throughput metrics.
#
# Unlike a ClusterLoader2 deployment (which primes each node's image cache once
# and then goes quiet), the underlying pull -> rmi loop forces a fresh blob
# download from the registry on every iteration, producing steady throughput
# against the ACR stamp for the entire window.
#
# The manifest must name the DaemonSet `image-pull-load` and target `namespace`.
#
# `images` is a space-separated list of fully-qualified image refs to pull. It
# overrides the IMAGES env baked into the manifest, so the registry/image under
# test can be set from the pipeline. Listing DISTINCT tags/digests raises
# per-node concurrency (containerd coalesces concurrent pulls of an identical ref).
RunImagePullLoad = lambda serviceConnection: str, namespace: str, manifest: str, durationSeconds: str, images: str -> steps.Step {
    script = """
kubectl create namespace "${namespace}" || true
kubectl apply -f $(Pipeline.Workspace)/s/${manifest}

# Set the image(s) under test from the pipeline (overrides the manifest default).
kubectl --namespace="${namespace}" set env daemonset/image-pull-load IMAGES="${images}"

# Wait for one puller pod per eligible node to be scheduled and running.
kubectl --namespace="${namespace}" rollout status daemonset/image-pull-load --timeout=10m

echo "Sustaining image-pull load for ${durationSeconds}s..."
start=$(date +%s)
while [ $(( $(date +%s) - start )) -lt ${durationSeconds} ]; do
  ready=$(kubectl --namespace="${namespace}" get daemonset image-pull-load -o jsonpath='{.status.numberReady}')
  desired=$(kubectl --namespace="${namespace}" get daemonset image-pull-load -o jsonpath='{.status.desiredNumberScheduled}')
  echo "[$(date -u +%H:%M:%S)] pullers ready: $ready/$desired"
  sleep 30
done

echo "Load window complete; pullers left running for metric collection."
"""
    azure.AzCli(serviceConnection, "Run image-pull load", script)
}

# CollectImagePullThroughput scrapes the per-pull THROUGHPUT_SAMPLE lines emitted
# by every puller pod, aggregates them into containerd image-pull throughput
# stats (cluster-wide MB/s plus per-pull avg/percentiles), writes the result JSON
# to `resultFile`, then tears the DaemonSet down. It must run after
# RunImagePullLoad and before the DaemonSet is deleted (it does the delete).
#
# NOTE: this scrapes `kubectl logs` from every puller pod. At very large node
# counts the concurrent log fan-out is heavy; for large fleets prefer a
# Prometheus-based containerd metrics scrape instead.
CollectImagePullThroughput = lambda serviceConnection: str, namespace: str, manifest: str, region: str, nodeCount: int, durationSeconds: str, resultFile: str = "/tmp/run-result.json" -> steps.Step {
    script = """
# Scrape throughput samples from all puller pods (must happen before teardown).
kubectl --namespace="${namespace}" logs -l app=image-pull-load --tail=-1 --max-log-requests=2000 > /tmp/puller-logs.txt 2>/dev/null || true
grep "THROUGHPUT_SAMPLE" /tmp/puller-logs.txt > /tmp/samples.txt || true
echo "Collected $(wc -l < /tmp/samples.txt) throughput samples."

python3 - <<'PY'
import json, re, statistics
from datetime import datetime, timezone

pat = re.compile(r"bytes=(\\d+)\\s+seconds=(\\d+)")
mbps, total_bytes = [], 0
with open("/tmp/samples.txt", encoding="utf-8") as f:
    for line in f:
        m = pat.search(line)
        if not m:
            continue
        b, s = int(m.group(1)), int(m.group(2))
        if s <= 0:
            continue
        total_bytes += b
        mbps.append(b / 1e6 / s)

def pct(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = max(0, min(len(vals) - 1, round((p / 100) * (len(vals) - 1))))
    return round(vals[k], 2)

duration = ${durationSeconds}
result = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "status": "succeeded" if mbps else "failure",
    "region": "${region}",
    "puller_node_count": ${nodeCount},
    "load_duration_seconds": duration,
    "sample_count": len(mbps),
    "total_pulled_gb": round(total_bytes / 1e9, 2),
    # Sustained cluster-wide throughput delivered to nodes over the window.
    "cluster_throughput_mbps": round(total_bytes / 1e6 / duration, 2) if duration else None,
    # Per-pull (per-node) containerd image-pull throughput distribution.
    "per_pull_mbps_avg": round(statistics.fmean(mbps), 2) if mbps else None,
    "per_pull_mbps_p20": pct(mbps, 20),
    "per_pull_mbps_p25": pct(mbps, 25),
    "per_pull_mbps_p50": pct(mbps, 50),
    "per_pull_mbps_p75": pct(mbps, 75),
    "per_pull_mbps_p90": pct(mbps, 90),
    "per_pull_mbps_p95": pct(mbps, 95),
    "per_pull_mbps_p99": pct(mbps, 99),
    "per_pull_mbps_min": round(min(mbps), 2) if mbps else None,
    "per_pull_mbps_max": round(max(mbps), 2) if mbps else None,
}
with open("${resultFile}", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY

# Tear down the pullers now that metrics have been collected.
kubectl delete -f $(Pipeline.Workspace)/s/${manifest} --ignore-not-found
"""
    azure.AzCli(serviceConnection, "Collect image-pull throughput", script)
}
