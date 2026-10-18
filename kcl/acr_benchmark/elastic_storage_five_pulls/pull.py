"""Pull one pinned image on each of five fresh Kubernetes workers."""

import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


PULL_COUNT = 5
NAMESPACE = "acr-five-pulls"
SECRET_NAME = "acr-pull"
POLL_SECONDS = 5
NODE_READY_TIMEOUT_SECONDS = 600
PULL_TIMEOUT_SECONDS = 600
EXPECTED_ERRORS = (OSError, ValueError, RuntimeError, subprocess.SubprocessError)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def credentials():
    values = [os.environ.get(name, "") for name in (
        "ACR_PULL_USERNAME", "ACR_PULL_PASSWORD"
    )]
    if any(not value or value.startswith("$(") for value in values):
        raise ValueError(
            "Set ACR_PULL_USERNAME and ACR_PULL_PASSWORD as secret pipeline "
            "variables with pull access to the Dogfood registry."
        )
    return values


def kubectl(*arguments, payload=None):
    completed = subprocess.run(
        ["kubectl", "--request-timeout=30s", *arguments],
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=True,
        timeout=45,
    )
    return completed.stdout


def get_json(*arguments):
    return json.loads(kubectl("get", *arguments, "-o", "json"))


def wait_for_nodes(node_pool):
    deadline = time.monotonic() + NODE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        nodes = get_json("nodes", "-l", f"agentpool={node_pool}")["items"]
        if len(nodes) > PULL_COUNT:
            raise RuntimeError(f"Expected exactly {PULL_COUNT} workers, found {len(nodes)}")
        ready = [
            node for node in nodes
            if not node.get("spec", {}).get("unschedulable", False)
            and any(
                condition["type"] == "Ready" and condition["status"] == "True"
                for condition in node["status"].get("conditions", [])
            )
        ]
        if len(ready) == PULL_COUNT:
            names = [node["metadata"]["name"] for node in ready]
            if len(set(names)) != PULL_COUNT:
                raise RuntimeError("Worker node names are not unique")
            return sorted(ready, key=lambda node: node["metadata"]["name"])
        print(f"Waiting for workers: {len(ready)}/{PULL_COUNT} ready", flush=True)
        time.sleep(POLL_SECONDS)
    raise RuntimeError("Timed out waiting for exactly five Ready worker nodes")


def pod_manifest(image, node_names):
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
                "nodeName": node_name,
                "restartPolicy": "Never",
                "activeDeadlineSeconds": PULL_TIMEOUT_SECONDS,
                "automountServiceAccountToken": False,
                "imagePullSecrets": [{"name": SECRET_NAME}],
                "tolerations": [{
                    "key": "acrpull",
                    "operator": "Equal",
                    "value": "true",
                    "effect": "NoSchedule",
                }],
                "containers": [{
                    "name": "image-pull",
                    "image": image,
                    "imagePullPolicy": "Always",
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "128Mi"},
                        "limits": {"cpu": "1", "memory": "1Gi"},
                    },
                }],
            },
        } for index, node_name in enumerate(node_names, 1)],
    }


def event_time(event):
    value = event.get("eventTime") or event.get("firstTimestamp")
    if not value:
        raise ValueError("Image-pull event is missing its timestamp")
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def pull_results(bindings, pods, events, image):
    by_name = {pod["metadata"]["name"]: pod for pod in pods}
    unexpected = set(by_name) - set(bindings)
    if unexpected:
        raise RuntimeError(f"Unexpected test pods: {sorted(unexpected)}")
    results = []
    for name, node_name in bindings.items():
        result = {"pod": name, "node": node_name, "status": "pending"}
        results.append(result)
        pod = by_name.get(name)
        if pod is None:
            continue
        if pod["spec"].get("nodeName") != node_name:
            raise RuntimeError(f"{name} is not bound to its assigned worker")
        containers = pod["spec"].get("containers", [])
        if len(containers) != 1 or containers[0].get("image") != image:
            raise RuntimeError(f"{name} does not use the expected pinned image")
        pod_events = [
            event for event in events
            if event["involvedObject"].get("uid") == pod["metadata"]["uid"]
        ]
        failures = [
            event for event in pod_events
            if event.get("reason") == "Failed"
            and "failed to pull image" in event.get("message", "").lower()
        ]
        statuses = pod.get("status", {}).get("containerStatuses", [])
        waiting = next((
            status.get("state", {}).get("waiting", {})
            for status in statuses if status["name"] == "image-pull"
        ), {})
        if failures or waiting.get("reason") in (
            "ErrImagePull", "ImagePullBackOff", "InvalidImageName"
        ):
            result.update(
                status="failed",
                error=failures[0]["message"] if failures else waiting["reason"],
            )
            continue
        pulling = [event for event in pod_events if event.get("reason") == "Pulling"]
        pulled = [event for event in pod_events if event.get("reason") == "Pulled"]
        if any(
            event.get("count", 1) != 1 or event.get("series", {}).get("count", 1) != 1
            for event in pulling + pulled
        ) or len(pulling) > 1 or len(pulled) > 1:
            result.update(status="failed", error="More than one image-pull attempt observed")
            continue
        if any("already present" in event.get("message", "").lower() for event in pulled):
            result.update(status="failed", error="Image was cached; this was not a cold pull")
            continue
        if not pulling or not pulled:
            continue
        started = event_time(pulling[0])
        finished = event_time(pulled[0])
        duration = (finished - started).total_seconds()
        if duration < 0:
            raise ValueError(f"Negative image-pull duration for {name}")
        result.update(
            status="succeeded",
            pulling_at=started.isoformat(),
            pulled_at=finished.isoformat(),
            pull_duration_seconds=duration,
            pod_phase=pod.get("status", {}).get("phase"),
            image_id=next((
                status.get("imageID") for status in statuses
                if status["name"] == "image-pull"
            ), None),
        )
    return results


def run_test(args):
    result = {
        "image": args.image,
        "registry_resource_group": "rg_wj_cus1",
        "region": "australiaeast",
        "expected_pull_count": PULL_COUNT,
        "successful_pull_count": 0,
        "status": "failed",
        "pulls": [],
        "errors": [],
    }
    namespace_created = False
    try:
        username, password = credentials()
        if not re.fullmatch(r"[^/\s]+/[^@\s]+@sha256:[0-9a-f]{64}", args.image):
            raise ValueError("Image must be a fully qualified sha256 digest reference")
        nodes = wait_for_nodes(args.node_pool)
        node_names = [node["metadata"]["name"] for node in nodes]
        result["nodes"] = [{
            "name": node["metadata"]["name"],
            "node_info": node["status"]["nodeInfo"],
        } for node in nodes]
        kubectl("create", "namespace", NAMESPACE)
        namespace_created = True
        registry = args.image.split("/", 1)[0]
        docker_config = {"auths": {registry: {
            "auth": base64.b64encode(f"{username}:{password}".encode()).decode()
        }}}
        # stdin avoids exposing registry credentials in process arguments or files.
        kubectl("create", "-f", "-", payload={
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": SECRET_NAME, "namespace": NAMESPACE},
            "type": "kubernetes.io/dockerconfigjson",
            "data": {
                ".dockerconfigjson": base64.b64encode(
                    json.dumps(docker_config).encode()
                ).decode()
            },
        })
        manifest = pod_manifest(args.image, node_names)
        bindings = {
            pod["metadata"]["name"]: pod["spec"]["nodeName"]
            for pod in manifest["items"]
        }
        result["started_at"] = utcnow()
        result["pulls"] = pull_results(bindings, [], [], args.image)
        deadline = time.monotonic() + PULL_TIMEOUT_SECONDS
        kubectl("create", "-f", "-", payload=manifest)
        while time.monotonic() < deadline:
            result["pulls"] = pull_results(
                bindings,
                get_json("pods", "-n", NAMESPACE, "-l", "app=acr-five-pulls")["items"],
                get_json("events", "-n", NAMESPACE)["items"],
                args.image,
            )
            result["successful_pull_count"] = sum(
                pull["status"] == "succeeded" for pull in result["pulls"]
            )
            if any(pull["status"] == "failed" for pull in result["pulls"]):
                raise RuntimeError("An image pull failed; see per-pod results")
            if time.monotonic() >= deadline:
                raise RuntimeError("Image-pull observation exceeded the ten-minute deadline")
            if result["successful_pull_count"] == PULL_COUNT:
                break
            time.sleep(POLL_SECONDS)
        else:
            raise RuntimeError("Timed out waiting for five successful cold pulls")
    except EXPECTED_ERRORS as error:
        result["errors"].append(str(error))
        if isinstance(error, subprocess.CalledProcessError):
            result["errors"].append(error.stderr.strip())
    finally:
        result["finished_at"] = utcnow()
        if namespace_created:
            try:
                kubectl("delete", "namespace", NAMESPACE, "--wait=false")
            except EXPECTED_ERRORS as error:
                result["errors"].append(f"Namespace cleanup failed: {error}")
        if result["successful_pull_count"] == PULL_COUNT and not result["errors"]:
            result["status"] = "succeeded"
        report = {
            "timestamp": utcnow(),
            "run_id": args.run_id,
            "run_url": args.run_url,
            "pipeline": args.pipeline,
            "result": result,
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    for error in result["errors"]:
        print(f"IMAGE PULL TEST FAILED: {error}", file=sys.stderr)
    return 0 if result["status"] == "succeeded" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-credentials", help="Validate secret pipeline variables")
    run = commands.add_parser("run", help="Pull on five Ready nodes in a fresh worker pool")
    run.add_argument("--image", required=True)
    run.add_argument("--node-pool", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--run-url", required=True)
    run.add_argument("--pipeline", required=True)
    args = parser.parse_args()
    if args.command == "run":
        return run_test(args)
    try:
        credentials()
    except ValueError as error:
        print(f"IMAGE PULL TEST FAILED: {error}", file=sys.stderr)
        return 1
    print("Registry pull credentials are configured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
