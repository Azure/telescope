"""Coordinate five verified layer downloads from one registry-selected replica."""

import argparse
import base64
from datetime import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from download import (
    DownloadError, LAYER_BYTES, WINDOW_SECONDS, WORKER_TIMEOUT_SECONDS,
    error_message, open_request, sanitize_diagnostic, storage_account, utc, validate_target,
)


NAMESPACE = "acr-five-pulls"
SERVICE_ACCOUNT = "acr-download"
PULL_COUNT = 5
SUPPORTED_PULL_COUNTS = (4, PULL_COUNT)
TIMEOUT_SECONDS = WORKER_TIMEOUT_SECONDS
POLL_SECONDS = 5
KUBECTL_TIMEOUT_SECONDS = 45
# Reserve one status query and one log read per worker, plus the polling interval.
RESULT_COLLECTION_SECONDS = (PULL_COUNT + 1) * KUBECTL_TIMEOUT_SECONDS + POLL_SECONDS
# Allow kubelet's Secret-volume refresh before the common start time.
SECRET_PROPAGATION_SECONDS = 180


def kubectl(*arguments, payload=None):
    operation = "kubectl " + " ".join(arguments)
    secrets = [os.environ.get("ACR_PULL_PASSWORD", "")]
    if payload is not None:
        operation += f" [{payload.get('kind', 'object')}/{payload.get('metadata', {}).get('name', '')}]"
        if payload.get("kind") == "Secret":
            for field in ("data", "stringData"):
                for value in payload.get(field, {}).values():
                    secrets.append(value)
                    secrets.extend(re.findall(r'https?://[^"\s]+', value))
    operation = sanitize_diagnostic(operation, secrets)
    try:
        return subprocess.run(
            ["kubectl", "--request-timeout=30s", *arguments],
            input=json.dumps(payload) if payload is not None else None,
            text=True, capture_output=True, check=True, timeout=KUBECTL_TIMEOUT_SECONDS,
        ).stdout
    except subprocess.CalledProcessError as error:
        details = sanitize_diagnostic(error.stderr or error.stdout, secrets) or "no diagnostic output"
        raise DownloadError(f"{operation} failed (exit {error.returncode}): {details}") from None
    except subprocess.TimeoutExpired as error:
        details = sanitize_diagnostic(error.stderr or error.output, secrets) or "no diagnostic output"
        raise DownloadError(f"{operation} timed out after {error.timeout}s: {details}") from None
    except OSError as error:
        details = sanitize_diagnostic(error, secrets)
        raise DownloadError(f"{operation} could not execute ({type(error).__name__}): {details}") from None


def get_json(*arguments):
    return json.loads(kubectl("get", *arguments, "-o", "json"))


def parse_image(image):
    match = re.fullmatch(r"([a-z0-9.-]+)/([a-z0-9._/-]+)@(sha256:[0-9a-f]{64})", image)
    if not match:
        raise DownloadError("Use a fully qualified immutable image digest")
    return match.groups()


def resolve_target(image, username, password, *, start_immediately=False):
    registry, repository, manifest_digest = parse_image(image)
    token_url = f"https://{registry}/oauth2/token?" + urllib.parse.urlencode({
        "service": registry, "scope": f"repository:{repository}:pull",
    })
    basic = base64.b64encode(f"{username}:{password}".encode()).decode()
    with open_request(urllib.request.Request(token_url, headers={"Authorization": "Basic " + basic})) as response:
        token_response = json.load(response)
    token = token_response.get("token") or token_response.get("access_token")
    if not isinstance(token, str) or not token:
        raise DownloadError("Registry token response contains no pull token")
    manifest_url = f"https://{registry}/v2/{repository}/manifests/{manifest_digest}"
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
    }
    with open_request(urllib.request.Request(manifest_url, headers=headers)) as response:
        body = response.read(1024 * 1024 + 1)
    if "sha256:" + hashlib.sha256(body).hexdigest() != manifest_digest:
        raise DownloadError("Registry manifest bytes do not match the pinned digest")
    manifest = json.loads(body)
    layers = manifest.get("layers", [])
    if len(layers) != 1 or layers[0].get("size") != LAYER_BYTES:
        raise DownloadError("The pinned image must contain exactly one one-GiB layer")
    digest = layers[0]["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise DownloadError("Invalid layer digest in registry manifest")
    blob_url = f"https://{registry}/v2/{repository}/blobs/{digest}"
    try:
        with open_request(urllib.request.Request(blob_url, headers={"Authorization": "Bearer " + token})):
            raise DownloadError("Registry returned a proxy response instead of a direct storage redirect")
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 307, 308):
            raise
        url = error.headers.get("Location", "")
        error.close()
    account = storage_account(url, digest)
    now = time.time()
    if start_immediately:
        start = int(now)
    else:
        start = (int(now) // WINDOW_SECONDS + 1) * WINDOW_SECONDS
        if start - now < SECRET_PROPAGATION_SECONDS:
            start += WINDOW_SECONDS
    target = {
        "url": url, "account": account, "digest": digest, "size": LAYER_BYTES,
        "start": start, "end": start + WINDOW_SECONDS,
        "start_mode": "immediate" if start_immediately else "aligned",
    }
    validate_target(target)
    return target


def manifests(runner_image, nodes):
    return {
        "apiVersion": "v1", "kind": "List",
        "items": [{
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": f"pull-{index}", "namespace": NAMESPACE, "labels": {"app": "acr-five-pulls"}},
            "spec": {
                "nodeName": node,
                "restartPolicy": "Never",
                "activeDeadlineSeconds": TIMEOUT_SECONDS,
                "serviceAccountName": SERVICE_ACCOUNT,
                "automountServiceAccountToken": False,
                "containers": [{
                    "name": "pull",
                    "image": runner_image,
                    "command": ["python3", "-B", "/scripts/download.py"],
                    "readinessProbe": {
                        "exec": {"command": ["/bin/sh", "-c", "test -f /tmp/ready"]},
                        "periodSeconds": 2,
                    },
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "128Mi"},
                        "limits": {"cpu": "1", "memory": "512Mi"},
                    },
                    "volumeMounts": [
                        {"name": "target", "mountPath": "/target", "readOnly": True},
                        {"name": "script", "mountPath": "/scripts", "readOnly": True},
                    ],
                }],
                "volumes": [
                    {"name": "target", "secret": {"secretName": "acr-download-target"}},
                    {"name": "script", "configMap": {"name": "acr-download-script"}},
                ],
            },
        } for index, node in enumerate(nodes, 1)],
    }


def pod_snapshot():
    pods = get_json("pods", "-n", NAMESPACE, "-l", "app=acr-five-pulls")["items"]
    return {pod["metadata"]["name"]: pod for pod in pods}


def collect_snapshot(result, pods, target=None):
    errors = []
    unexpected = set(pods) - {pull["pod"] for pull in result["pulls"]}
    if unexpected:
        errors.append("Unexpected workload Pods in the test namespace: " + ", ".join(sorted(unexpected)))
    secrets = [os.environ.get("ACR_PULL_PASSWORD", "")]
    if target:
        secrets.append(target["url"])
    for pull in result["pulls"]:
        pod = pods.get(pull["pod"])
        if pod is None or pull["status"] != "pending":
            continue
        try:
            if pod["spec"]["nodeName"] != pull["node"]:
                raise DownloadError("Workload Pod is running on the wrong worker")
            status = pod.get("status", {})
            container = next((
                item for item in status.get("containerStatuses", []) if item["name"] == "pull"
            ), {})
            if container.get("restartCount", 0) > 0:
                raise DownloadError("Worker restarted; refusing extra downloads")
            waiting = container.get("state", {}).get("waiting", {})
            if waiting.get("reason") in ("ErrImagePull", "ImagePullBackOff", "InvalidImageName"):
                raise DownloadError("Could not pull the Python worker image: " + sanitize_diagnostic(
                    f"{waiting['reason']}: {waiting.get('message', '')}", secrets))
            if status.get("phase") not in ("Failed", "Succeeded"):
                continue
            raw_log = kubectl("logs", "-n", NAMESPACE, pull["pod"], "-c", "pull")
            try:
                log = json.loads(raw_log)
            except ValueError:
                raise DownloadError("Worker logs are not valid JSON: " + sanitize_diagnostic(raw_log, secrets)) from None
            if status["phase"] == "Failed":
                details = status.get("reason") or "worker exited unsuccessfully"
                if isinstance(log, dict) and isinstance(log.get("error"), str):
                    details = log["error"]
                pull["exit_code"] = container.get("state", {}).get("terminated", {}).get("exitCode")
                raise DownloadError(sanitize_diagnostic(details, secrets))
            if container.get("state", {}).get("terminated", {}).get("exitCode") != 0:
                raise DownloadError("Worker did not exit successfully")
            if target is None:
                raise DownloadError("Worker completed before a download target was published")
            verify_result(log, target)
            for field in (
                "storage_account", "blob_digest", "downloaded_bytes", "started_at", "finished_at",
                "duration_seconds", "window_start", "window_end", "client_request_id", "storage_request_id",
            ):
                pull[field] = log[field]
            pull["status"] = "success"
        except (OSError, ValueError, KeyError, TypeError, DownloadError, subprocess.SubprocessError) as error:
            details = error_message(error, secrets)
            pull.update(status="failure", error=details)
            errors.append(f"{pull['pod']} on {pull['node']}: {details}")
    result["successful_pulls"] = sum(pull["status"] == "success" for pull in result["pulls"])
    if errors:
        raise DownloadError("; ".join(errors))


def ensure_schedule_fits(target, deadline):
    required = target["end"] - time.time() + RESULT_COLLECTION_SECONDS
    remaining = deadline - time.monotonic()
    if required > remaining:
        raise DownloadError(
            f"Selected download window requires {required:.1f}s including result collection, "
            f"but only {max(0, remaining):.1f}s of remaining lifetime is available; target was not published"
        )


def verify_result(log, target):
    if not isinstance(log, dict):
        raise DownloadError("Worker logs are not a JSON object")
    if (
        log["status"] != "success"
        or log["storage_account"] != target["account"]
        or log["blob_digest"] != target["digest"]
        or log["downloaded_bytes"] != target["size"]
        or log["window_start"] != utc(target["start"])
        or log["window_end"] != utc(target["end"])
        or log["duration_seconds"] < 0
        or not log["client_request_id"]
        or not log["storage_request_id"]
    ):
        raise DownloadError("Worker result does not match the selected account, layer, or window")
    start = datetime.fromisoformat(log["started_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(log["finished_at"].replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or not target["start"] <= start.timestamp() <= end.timestamp() < target["end"]:
        raise DownloadError("Worker downloaded outside the permitted five-minute interval")


def run(
    args, *, node_count=PULL_COUNT, region="australiaeast", registry_resource_group="rg_wj_cus1",
    start_immediately=False, pull_count=PULL_COUNT,
):
    result = {
        "timestamp": utc(time.time()), "run_id": args.run_id, "run_url": args.run_url,
        "namespace": NAMESPACE,
        "image": args.image, "runner_image": args.runner_image,
        "registry_resource_group": registry_resource_group, "region": region,
        "node_count": node_count, "status": "failure", "successful_pulls": 0,
        "expected_pulls": pull_count,
        "start_mode": "immediate" if start_immediately else "aligned",
        "pulls": [], "errors": [],
    }
    owned_namespace = False
    try:
        username = os.environ.get("ACR_PULL_USERNAME", "")
        password = os.environ.get("ACR_PULL_PASSWORD", "")
        if any(not value or value.startswith("$(") for value in (username, password)):
            raise DownloadError("Set ACR_PULL_USERNAME and secret ACR_PULL_PASSWORD")
        parse_image(args.image)
        if pull_count not in SUPPORTED_PULL_COUNTS:
            raise DownloadError("Expected four or five downloads")
        if node_count not in (1, PULL_COUNT):
            raise DownloadError("Use one local node or five distinct workers")
        if node_count > pull_count:
            raise DownloadError("The requested node count exceeds the download count")
        nodes = get_json("nodes", "-l", "cri-resource-consume=true")["items"]
        if len(nodes) != node_count or any(
            node.get("spec", {}).get("unschedulable", False) or not any(
                condition["type"] == "Ready" and condition["status"] == "True"
                for condition in node["status"].get("conditions", [])
            ) for node in nodes
        ):
            raise DownloadError(f"Expected exactly {node_count} Ready, schedulable worker nodes")
        node_names = sorted(node["metadata"]["name"] for node in nodes)
        if len(set(node_names)) != node_count:
            raise DownloadError(f"Expected {node_count} distinct worker nodes")
        assigned_nodes = [node_names[index % node_count] for index in range(pull_count)]
        result["pulls"] = [
            {"pod": f"pull-{index}", "node": node, "status": "pending"}
            for index, node in enumerate(assigned_nodes, 1)
        ]
        kubectl("create", "namespace", NAMESPACE)
        owned_namespace = True
        kubectl("create", "serviceaccount", SERVICE_ACCOUNT, "-n", NAMESPACE)
        secret = {
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": "acr-download-target", "namespace": NAMESPACE},
            "type": "Opaque", "stringData": {"target.json": "{}"},
        }
        kubectl("create", "-f", "-", payload={
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": "acr-download-script", "namespace": NAMESPACE},
            "data": {"download.py": Path(__file__).with_name("download.py").read_text(encoding="utf-8")},
        })
        # Starting the shared budget before Pod creation is conservative for both
        # Pod activeDeadlineSeconds and the worker process's identical timeout.
        deadline = time.monotonic() + TIMEOUT_SECONDS
        target = None
        if start_immediately:
            target = resolve_target(args.image, username, password, start_immediately=True)
            ensure_schedule_fits(target, deadline)
            secret["stringData"]["target.json"] = json.dumps(target)
        # Immediate mode mounts the populated Secret on first start, avoiding refresh delays.
        kubectl("create", "-f", "-", payload=secret)
        kubectl("create", "-f", "-", payload=manifests(args.runner_image, assigned_nodes))
        if not start_immediately:
            while time.monotonic() < deadline:
                pods = pod_snapshot()
                collect_snapshot(result, pods)
                if len(pods) == pull_count and all(any(
                    condition["type"] == "Ready" and condition["status"] == "True"
                    for condition in pod.get("status", {}).get("conditions", [])
                ) for pod in pods.values()):
                    break
                time.sleep(POLL_SECONDS)
            else:
                raise DownloadError(f"Timed out waiting for all {pull_count} download workers to be ready")
            target = resolve_target(args.image, username, password)
            ensure_schedule_fits(target, deadline)
            # Replace over stdin; never put the SAS in arguments, local files, or logs.
            secret["stringData"]["target.json"] = json.dumps(target)
            kubectl("replace", "-f", "-", payload=secret)
        result.update(
            storage_account=target["account"], blob_digest=target["digest"],
            window_start=utc(target["start"]), window_end=utc(target["end"]),
        )
        while time.monotonic() < deadline:
            pods = pod_snapshot()
            collect_snapshot(result, pods, target)
            if result["successful_pulls"] == pull_count:
                if time.monotonic() >= deadline:
                    raise DownloadError("Coordinator deadline exceeded")
                if len({pull["storage_request_id"] for pull in result["pulls"]}) != pull_count:
                    raise DownloadError(f"Expected {pull_count} distinct Azure Storage request IDs")
                break
            time.sleep(POLL_SECONDS)
        else:
            raise DownloadError(f"Timed out waiting for all {pull_count} single-account downloads")
    except (OSError, ValueError, KeyError, TypeError, DownloadError, subprocess.SubprocessError, http.client.HTTPException) as error:
        result["errors"].append(error_message(error))
    finally:
        if owned_namespace:
            try:
                kubectl("delete", "namespace", NAMESPACE, "--wait=false")
            except (OSError, DownloadError, subprocess.SubprocessError) as error:
                result["errors"].append(f"Namespace cleanup failed: {error_message(error)}")
        result["finished_at"] = utc(time.time())
        if result["successful_pulls"] == pull_count and not result["errors"]:
            result["status"] = "success"
        output = Path(args.result_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    for error in result["errors"]:
        print(f"IMAGE DOWNLOAD FAILED: {error}", file=sys.stderr)
    return 0 if result["status"] == "success" else 1


def main():
    global NAMESPACE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--namespace", default=NAMESPACE)
    parser.add_argument("--local", action="store_true", help="Use one local node instead of five Azure workers")
    parser.add_argument("--start-immediately", action="store_true")
    args = parser.parse_args()
    if len(args.namespace) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", args.namespace):
        parser.error("--namespace must be a valid Kubernetes namespace name")
    NAMESPACE = args.namespace
    if args.local:
        return run(
            args, node_count=1, region="local", registry_resource_group=None,
            start_immediately=args.start_immediately,
        )
    return run(args, start_immediately=args.start_immediately)


if __name__ == "__main__":
    sys.exit(main())
