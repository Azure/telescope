"""Download the pinned test image once on each of five Kubernetes workers."""

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


NAMESPACE = "acr-five-pulls"
PULL_COUNT = 5
TIMEOUT_SECONDS = 1200
POLL_SECONDS = 5
LAYER_BYTES = 1073741824

# The target is a synthetic OCI artifact: preserve its bytes without unpacking.
DOWNLOAD_SCRIPT = """
set -eu
start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
start_seconds=$(date +%s)
mkdir /download/image
if skopeo copy --retry-times 0 --preserve-digests \\
    --authfile /auth/.dockerconfigjson \\
    "docker://$TARGET_IMAGE" dir:/download/image >/download/copy.log 2>&1; then
  bytes=0
  for file in /download/image/*; do
    size=$(wc -c < "$file")
    bytes=$(( bytes + size ))
  done
  end=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  duration=$(( $(date +%s) - start_seconds ))
  printf '{"started_at":"%s","finished_at":"%s","duration_seconds":%s,"downloaded_bytes":%s}\\n' \\
    "$start" "$end" "$duration" "$bytes"
else
  # Keep credentials and signed redirect URLs out of published diagnostics.
  echo "skopeo image download failed; check registry permissions and connectivity" >&2
  exit 1
fi
"""


def kubectl(*arguments, payload=None):
    return subprocess.run(
        ["kubectl", "--request-timeout=30s", *arguments],
        input=json.dumps(payload) if payload is not None else None,
        text=True, capture_output=True, check=True, timeout=45,
    ).stdout


def get_json(*arguments):
    return json.loads(kubectl("get", *arguments, "-o", "json"))


def manifests(image, runner_image, nodes):
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [{
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"pull-{index}",
                "namespace": NAMESPACE,
                "labels": {"app": "acr-five-pulls"},
            },
            "spec": {
                "nodeName": node,
                "restartPolicy": "Never",
                "activeDeadlineSeconds": TIMEOUT_SECONDS,
                "automountServiceAccountToken": False,
                "containers": [{
                    "name": "pull",
                    "image": runner_image,
                    "command": ["/bin/sh", "-c", DOWNLOAD_SCRIPT],
                    "env": [{"name": "TARGET_IMAGE", "value": image}],
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "128Mi", "ephemeral-storage": "2Gi"},
                        "limits": {"cpu": "1", "memory": "512Mi", "ephemeral-storage": "3Gi"},
                    },
                    "volumeMounts": [
                        {"name": "auth", "mountPath": "/auth", "readOnly": True},
                        {"name": "download", "mountPath": "/download"},
                    ],
                }],
                "volumes": [
                    {"name": "auth", "secret": {"secretName": "acr-pull"}},
                    {"name": "download", "emptyDir": {"sizeLimit": "2Gi"}},
                ],
            },
        } for index, node in enumerate(nodes, 1)],
    }


def run(args):
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": args.run_id,
        "run_url": args.run_url,
        "image": args.image,
        "runner_image": args.runner_image,
        "registry_resource_group": "rg_wj_cus1",
        "region": "australiaeast",
        "node_count": PULL_COUNT,
        "status": "failure",
        "successful_pulls": 0,
        "pulls": [],
        "errors": [],
    }
    owned_namespace = False
    try:
        username = os.environ.get("ACR_PULL_USERNAME", "")
        password = os.environ.get("ACR_PULL_PASSWORD", "")
        if any(not value or value.startswith("$(") for value in (username, password)):
            raise ValueError("Set ACR_PULL_USERNAME and secret ACR_PULL_PASSWORD")
        if not re.fullmatch(r"[^/\s]+/[^@\s]+@sha256:[0-9a-f]{64}", args.image):
            raise ValueError("Use a fully qualified immutable image digest")
        nodes = get_json("nodes", "-l", "cri-resource-consume=true")["items"]
        if len(nodes) != PULL_COUNT or any(
            node.get("spec", {}).get("unschedulable", False) or not any(
                condition["type"] == "Ready" and condition["status"] == "True"
                for condition in node["status"].get("conditions", [])
            ) for node in nodes
        ):
            raise RuntimeError("Expected exactly five Ready, schedulable worker nodes")
        node_names = sorted(node["metadata"]["name"] for node in nodes)
        if len(set(node_names)) != PULL_COUNT:
            raise RuntimeError("Expected five distinct worker nodes")
        result["pulls"] = [
            {"pod": f"pull-{index}", "node": node, "status": "pending"}
            for index, node in enumerate(node_names, 1)
        ]
        kubectl("create", "namespace", NAMESPACE)
        owned_namespace = True
        docker_config = {"auths": {args.image.split("/", 1)[0]: {
            "auth": base64.b64encode(f"{username}:{password}".encode()).decode()
        }}}
        kubectl("create", "-f", "-", payload={
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "acr-pull", "namespace": NAMESPACE},
            "type": "kubernetes.io/dockerconfigjson",
            "data": {".dockerconfigjson": base64.b64encode(
                json.dumps(docker_config).encode()).decode()},
        })
        result["started_at"] = datetime.now(timezone.utc).isoformat()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        kubectl("create", "-f", "-", payload=manifests(args.image, args.runner_image, node_names))
        while time.monotonic() < deadline:
            pods = get_json("pods", "-n", NAMESPACE, "-l", "app=acr-five-pulls")["items"]
            by_name = {pod["metadata"]["name"]: pod for pod in pods}
            if set(by_name) - {pull["pod"] for pull in result["pulls"]}:
                raise RuntimeError("Unexpected workload Pods in the test namespace")
            for pull in result["pulls"]:
                pod = by_name.get(pull["pod"])
                if pod is None or pull["status"] == "success":
                    continue
                if pod["spec"]["nodeName"] != pull["node"]:
                    raise RuntimeError("Workload Pod is running on the wrong worker")
                status = pod.get("status", {})
                if status.get("phase") == "Failed":
                    pull["status"] = "failure"
                    raise RuntimeError(f"{pull['pod']} failed on {pull['node']}")
                container = next((
                    item for item in status.get("containerStatuses", [])
                    if item["name"] == "pull"
                ), {})
                if container.get("restartCount", 0) > 0:
                    raise RuntimeError(f"{pull['pod']} restarted; refusing extra downloads")
                if container.get("state", {}).get("waiting", {}).get("reason") in (
                    "ErrImagePull", "ImagePullBackOff", "InvalidImageName"
                ):
                    raise RuntimeError(f"{pull['pod']} could not pull the skopeo runner image")
                if status.get("phase") == "Succeeded":
                    if container.get("state", {}).get("terminated", {}).get("exitCode") != 0:
                        raise RuntimeError(f"{pull['pod']} did not exit successfully")
                    log = json.loads(kubectl("logs", "-n", NAMESPACE, pull["pod"], "-c", "pull"))
                    start = datetime.fromisoformat(log["started_at"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(log["finished_at"].replace("Z", "+00:00"))
                    if log["downloaded_bytes"] < LAYER_BYTES or log["duration_seconds"] < 0 or end < start:
                        raise ValueError(f"{pull['pod']} returned invalid download metrics")
                    pull.update(log, status="success")
                    result["successful_pulls"] += 1
            if time.monotonic() >= deadline:
                raise RuntimeError("Image-download deadline exceeded")
            if result["successful_pulls"] == PULL_COUNT:
                break
            time.sleep(POLL_SECONDS)
        else:
            raise RuntimeError("Timed out waiting for all five image downloads")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        result["errors"].append(str(error))
    finally:
        if owned_namespace:
            try:
                kubectl("delete", "namespace", NAMESPACE, "--wait=false")
            except (OSError, subprocess.SubprocessError) as error:
                result["errors"].append(f"Namespace cleanup failed: {error}")
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        if result["successful_pulls"] == PULL_COUNT and not result["errors"]:
            result["status"] = "success"
        output = Path(args.result_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    for error in result["errors"]:
        print(f"IMAGE DOWNLOAD FAILED: {error}", file=sys.stderr)
    return 0 if result["status"] == "success" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
