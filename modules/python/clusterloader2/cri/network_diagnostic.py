"""
Network diagnostic module to measure raw ACR download throughput.
This bypasses containerd to isolate network vs unpack performance.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

from clients.kubernetes_client import KubernetesClient
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

DIAGNOSTIC_JOB_TEMPLATE = """
apiVersion: batch/v1
kind: Job
metadata:
  name: network-diagnostic
  namespace: {namespace}
  labels:
    app: network-diagnostic
spec:
  completions: {completions}
  parallelism: {parallelism}
  backoffLimit: 0
  ttlSecondsAfterFinished: 300
  template:
    metadata:
      labels:
        app: network-diagnostic
    spec:
      restartPolicy: Never
      nodeSelector:
        cri-resource-consume: "true"
      containers:
      - name: curl-diagnostic
        image: curlimages/curl:8.5.0
        imagePullPolicy: Always
        command:
        - /bin/sh
        - -c
        - |
          echo "NODE=$(hostname)"
          echo "TIMESTAMP=$(date -Iseconds)"
          
          REGISTRY="{registry}"
          REPO="{repo}"
          TAG="{tag}"
          
          # Get token
          TOKEN=$(curl -s "https://$REGISTRY/oauth2/token?service=$REGISTRY&scope=repository:$REPO:pull" 2>/dev/null | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
          
          if [ -z "$TOKEN" ]; then
            echo "ERROR=failed_to_get_token"
            echo "DEBUG_REGISTRY=$REGISTRY"
            echo "DEBUG_REPO=$REPO"
            exit 1
          fi
          
          # Get manifest and extract digest
          MANIFEST=$(curl -s -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.docker.distribution.manifest.v2+json" "https://$REGISTRY/v2/$REPO/manifests/$TAG" 2>/dev/null)
          DIGEST=$(echo "$MANIFEST" | grep -o '"digest":"sha256:[a-f0-9]*"' | head -1 | cut -d'"' -f4)
          
          if [ -z "$DIGEST" ]; then
            echo "ERROR=failed_to_get_digest"
            echo "DEBUG_MANIFEST=$MANIFEST"
            exit 1
          fi
          
          # Download and measure
          BLOB_URL="https://$REGISTRY/v2/$REPO/blobs/$DIGEST"
          RESULT=$(curl -o /dev/null -w "%{{size_download}} %{{time_total}} %{{speed_download}}" -H "Authorization: Bearer $TOKEN" -s "$BLOB_URL" 2>/dev/null)
          
          SIZE=$(echo $RESULT | cut -d' ' -f1)
          TIME=$(echo $RESULT | cut -d' ' -f2)
          SPEED=$(echo $RESULT | cut -d' ' -f3)
          MBPS=$(echo "$SIZE $TIME" | awk '{{if($2>0) printf "%.2f", $1/$2/1048576; else print "0"}}')
          
          echo "SIZE_BYTES=$SIZE"
          echo "TIME_SECONDS=$TIME"
          echo "THROUGHPUT_MBPS=$MBPS"
        resources:
          requests:
            cpu: 100m
            memory: 64Mi
      tolerations:
      - key: "cri-resource-consume"
        operator: "Equal"
        value: "true"
        effect: "NoSchedule"
      - key: "cri-resource-consume"
        operator: "Equal"
        value: "true"
        effect: "NoExecute"
"""


def run_diagnostic(registry: str, image: str, node_count: int, namespace: str = "default"):
    """Deploy and run network diagnostic job."""
    client = KubernetesClient()
    
    # Create namespace if not exists (uses client's built-in method)
    try:
        client.create_namespace(namespace)
        logger.info(f"Namespace {namespace} ready")
    except Exception:
        logger.info(f"Namespace {namespace} already exists")
    
    # Delete existing job if any
    try:
        client.batch.delete_namespaced_job(
            name="network-diagnostic",
            namespace=namespace,
            propagation_policy="Foreground"
        )
        logger.info("Deleted existing diagnostic job")
        time.sleep(5)
    except Exception:
        pass
    
    # Create the job - split image into repo and tag
    if ':' in image:
        repo, tag = image.rsplit(':', 1)
    else:
        repo, tag = image, 'latest'
    
    job_yaml = DIAGNOSTIC_JOB_TEMPLATE.format(
        namespace=namespace,
        completions=node_count,
        parallelism=node_count,
        registry=registry,
        repo=repo,
        tag=tag
    )
    
    import yaml
    job_dict = yaml.safe_load(job_yaml)
    
    client.batch.create_namespaced_job(namespace=namespace, body=job_dict)
    logger.info(f"Created diagnostic job with {node_count} completions")
    
    # Wait for completion
    logger.info("Waiting for diagnostic job to complete...")
    for _ in range(60):  # 5 minute timeout
        job = client.batch.read_namespaced_job(name="network-diagnostic", namespace=namespace)
        if job.status.succeeded == node_count:
            logger.info("Diagnostic job completed successfully")
            break
        if job.status.failed and job.status.failed > 0:
            logger.error(f"Diagnostic job failed: {job.status.failed} pods failed")
            break
        time.sleep(5)
    else:
        logger.warning("Diagnostic job timed out")
    
    return collect_results(client, namespace)


def collect_results(client: KubernetesClient, namespace: str):
    """Collect and parse results from diagnostic pods."""
    pods = client.api.list_namespaced_pod(
        namespace=namespace,
        label_selector="app=network-diagnostic"
    )
    
    results = []
    for pod in pods.items:
        try:
            logs = client.api.read_namespaced_pod_log(
                name=pod.metadata.name,
                namespace=namespace
            )
            
            result = {"pod": pod.metadata.name, "node": None, "throughput_mbps": None}
            for line in logs.split("\n"):
                if line.startswith("NODE="):
                    result["node"] = line.split("=", 1)[1]
                elif line.startswith("THROUGHPUT_MBPS="):
                    try:
                        result["throughput_mbps"] = float(line.split("=", 1)[1])
                    except ValueError:
                        pass
                elif line.startswith("SIZE_BYTES="):
                    try:
                        result["size_bytes"] = int(line.split("=", 1)[1])
                    except ValueError:
                        pass
                elif line.startswith("TIME_SECONDS="):
                    try:
                        result["time_seconds"] = float(line.split("=", 1)[1])
                    except ValueError:
                        pass
            
            if result["throughput_mbps"] is not None:
                results.append(result)
                
        except Exception as e:
            logger.warning(f"Failed to get logs from {pod.metadata.name}: {e}")
    
    return results


def analyze_results(results: list):
    """Analyze and summarize diagnostic results."""
    if not results:
        logger.error("No results to analyze")
        return None
    
    throughputs = [r["throughput_mbps"] for r in results if r.get("throughput_mbps")]
    
    if not throughputs:
        logger.error("No throughput data collected")
        return None
    
    throughputs.sort()
    n = len(throughputs)
    
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_count": n,
        "min_mbps": min(throughputs),
        "max_mbps": max(throughputs),
        "avg_mbps": sum(throughputs) / n,
        "p50_mbps": throughputs[int(n * 0.5)] if n > 0 else None,
        "p90_mbps": throughputs[int(n * 0.9)] if n > 0 else None,
        "p99_mbps": throughputs[int(n * 0.99)] if n > 1 else throughputs[-1] if n > 0 else None,
        "raw_results": results
    }
    
    logger.info("=" * 50)
    logger.info("NETWORK DIAGNOSTIC RESULTS (Raw ACR Download)")
    logger.info("=" * 50)
    logger.info(f"Samples:  {summary['sample_count']}")
    logger.info(f"Min:      {summary['min_mbps']:.2f} MB/s")
    logger.info(f"Max:      {summary['max_mbps']:.2f} MB/s")
    logger.info(f"Avg:      {summary['avg_mbps']:.2f} MB/s")
    logger.info(f"P50:      {summary['p50_mbps']:.2f} MB/s")
    logger.info(f"P90:      {summary['p90_mbps']:.2f} MB/s")
    logger.info(f"P99:      {summary['p99_mbps']:.2f} MB/s")
    logger.info("=" * 50)
    
    return summary


def main():
    parser = argparse.ArgumentParser(description="Network diagnostic for ACR throughput")
    parser.add_argument("--registry", type=str, required=True, help="Registry endpoint")
    parser.add_argument("--image", type=str, required=True, help="Image to test (e.g., benchmark/payload-1gb:v0)")
    parser.add_argument("--node_count", type=int, default=10, help="Number of nodes to test")
    parser.add_argument("--namespace", type=str, default="network-diagnostic", help="Namespace for diagnostic pods")
    parser.add_argument("--output", type=str, help="Output file for JSON results")
    
    args = parser.parse_args()
    
    results = run_diagnostic(args.registry, args.image, args.node_count, args.namespace)
    summary = analyze_results(results)
    
    if args.output and summary:
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
