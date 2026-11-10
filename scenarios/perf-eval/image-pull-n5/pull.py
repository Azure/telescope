"""Coordinate verified layer downloads from pinned registry-selected replicas."""

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
    error_message, open_request, primary_location, sanitize_diagnostic, storage_account, utc, validate_layer_size,
    validate_target,
)


NAMESPACE = "acr-five-pulls"
SERVICE_ACCOUNT = "acr-download"
PULL_COUNT = 5
SUPPORTED_PULL_COUNTS = (4, PULL_COUNT)
WARM_ACCOUNT_COUNT = 2
WARM_PULLS_PER_ACCOUNT = 3
WARM_PULL_COUNT = WARM_ACCOUNT_COUNT * WARM_PULLS_PER_ACCOUNT
DEFAULT_SCALE_IN_THRESHOLD_BYTES = 4 * LAYER_BYTES
DEFAULT_SCALE_OUT_THRESHOLD_BYTES = 5 * LAYER_BYTES
MAX_ACCOUNT_SELECTION_ATTEMPTS = 20
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


def resolve_layer(image, username, password):
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
    if not isinstance(layers, list) or len(layers) != 1 or not isinstance(layers[0], dict):
        raise DownloadError("The pinned image must contain exactly one layer")
    size = layers[0].get("size")
    validate_layer_size(size)
    digest = layers[0].get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise DownloadError("Invalid layer digest in registry manifest")
    blob_url = f"https://{registry}/v2/{repository}/blobs/{digest}"
    return blob_url, token, digest, size


def resolve_redirect(blob_url, token, digest, size):
    try:
        with open_request(urllib.request.Request(blob_url, headers={"Authorization": "Bearer " + token})):
            raise DownloadError("Registry returned a proxy response instead of a direct storage redirect")
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 307, 308):
            raise
        url = error.headers.get("Location", "")
        error.close()
    account = storage_account(url, digest)
    return {"url": url, "account": account, "digest": digest, "size": size}


def schedule_targets(targets, *, start_immediately=False):
    now = time.time()
    if start_immediately:
        start = int(now)
    else:
        start = (int(now) // WINDOW_SECONDS + 1) * WINDOW_SECONDS
        if start - now < SECRET_PROPAGATION_SECONDS:
            start += WINDOW_SECONDS
    for target in targets:
        target.update(
            start=start, end=start + WINDOW_SECONDS,
            start_mode="immediate" if start_immediately else "aligned",
        )
        validate_target(target)
    return targets


def resolve_target(image, username, password, *, start_immediately=False):
    target = resolve_redirect(*resolve_layer(image, username, password))
    return schedule_targets([target], start_immediately=start_immediately)[0]


def resolve_primary_target(image, bundle, *, start_immediately=False):
    registry, _, _ = parse_image(image)
    if not isinstance(bundle, dict) or bundle.get("image") != image:
        raise DownloadError("Primary input does not match the pinned image")
    registry_id = bundle.get("registry_id", "")
    if not isinstance(registry_id, str) or not re.fullmatch(r"[0-9a-f]{32}", registry_id):
        raise DownloadError("Primary input requires the internal registry ID")
    manifest = bundle.get("manifest")
    layers = manifest.get("layers", []) if isinstance(manifest, dict) else []
    if not isinstance(layers, list) or len(layers) != 1 or not isinstance(layers[0], dict):
        raise DownloadError("The primary image must have exactly one layer")
    digest, size = layers[0].get("digest"), layers[0].get("size")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise DownloadError("Invalid primary layer digest")
    validate_layer_size(size)
    location = bundle.get("location")
    account, container = primary_location(location, digest)
    if (
        location["PartitionKey"] != f"{digest.removeprefix('sha256:')}&{registry_id}"
        or location.get("RegistryLoginUri") not in (None, "", registry)
    ):
        raise DownloadError("Primary location does not belong to the requested registry")
    url = bundle.get("url")
    if not isinstance(url, str):
        raise DownloadError("Primary input is missing a signed blob URL")
    target = {
        "url": url, "account": account, "digest": digest, "size": size,
        "storage_role": "primary", "primary_location": location, "container": container,
    }
    return schedule_targets([target], start_immediately=start_immediately)[0]


def validate_warm_traffic(size, scale_in_threshold_bytes, scale_out_threshold_bytes):
    validate_layer_size(size)
    if type(scale_in_threshold_bytes) is not int or scale_in_threshold_bytes < 0:
        raise DownloadError("Scale-in threshold must be a nonnegative integer byte count")
    if type(scale_out_threshold_bytes) is not int or scale_out_threshold_bytes <= 0:
        raise DownloadError("Scale-out threshold must be a positive integer byte count")
    per_account = WARM_PULLS_PER_ACCOUNT * size
    aggregate = WARM_ACCOUNT_COUNT * per_account
    if per_account >= scale_out_threshold_bytes:
        raise DownloadError(
            f"Three downloads per account ({per_account} bytes) must stay below "
            f"the scale-out threshold ({scale_out_threshold_bytes} bytes)"
        )
    if not per_account <= scale_in_threshold_bytes < aggregate:
        raise DownloadError(
            f"To isolate aggregate warmth, configure and specify a scale-in threshold "
            f"between {per_account} (inclusive) and {aggregate} (exclusive) bytes; "
            f"received {scale_in_threshold_bytes}. No downloads were started."
        )


def resolve_warm_targets(
    image, username, password, *, start_immediately=False,
    scale_in_threshold_bytes=DEFAULT_SCALE_IN_THRESHOLD_BYTES,
    scale_out_threshold_bytes=DEFAULT_SCALE_OUT_THRESHOLD_BYTES,
):
    layer = resolve_layer(image, username, password)
    validate_warm_traffic(layer[3], scale_in_threshold_bytes, scale_out_threshold_bytes)
    targets = {}
    for _ in range(MAX_ACCOUNT_SELECTION_ATTEMPTS):
        target = resolve_redirect(*layer)
        targets.setdefault(target["account"], target)
        if len(targets) == WARM_ACCOUNT_COUNT:
            return schedule_targets(list(targets.values()), start_immediately=start_immediately)
    raise DownloadError(
        f"ACR did not select two distinct eligible replica accounts within "
        f"{MAX_ACCOUNT_SELECTION_ATTEMPTS} redirects; no downloads were started"
    )


def manifests(runner_image, nodes, *, target_names=None):
    if target_names is None:
        target_names = ["acr-download-target"] * len(nodes)
    if len(target_names) != len(nodes):
        raise DownloadError("Every download worker must have exactly one target Secret")
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
                    {"name": "target", "secret": {"secretName": target_names[index - 1]}},
                    {"name": "script", "configMap": {"name": "acr-download-script"}},
                ],
            },
        } for index, node in enumerate(nodes, 1)],
    }


def pod_snapshot():
    pods = get_json("pods", "-n", NAMESPACE, "-l", "app=acr-five-pulls")["items"]
    return {pod["metadata"]["name"]: pod for pod in pods}


def collect_snapshot(result, pods, target=None, *, targets_by_pod=None):
    errors = []
    unexpected = set(pods) - {pull["pod"] for pull in result["pulls"]}
    if unexpected:
        errors.append("Unexpected workload Pods in the test namespace: " + ", ".join(sorted(unexpected)))
    secrets = [os.environ.get("ACR_PULL_PASSWORD", "")]
    if target:
        secrets.append(target["url"])
    if targets_by_pod:
        secrets.extend(selected["url"] for selected in targets_by_pod.values())
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
            selected = targets_by_pod[pull["pod"]] if targets_by_pod is not None else target
            if selected is None:
                raise DownloadError("Worker completed before a download target was published")
            record_download(pull, log, selected)
        except (OSError, ValueError, KeyError, TypeError, DownloadError, subprocess.SubprocessError) as error:
            details = error_message(error, secrets)
            pull.update(status="failure", error=details)
            errors.append(f"{pull['pod']} on {pull['node']}: {details}")
    result["successful_pulls"] = sum(pull["status"] == "success" for pull in result["pulls"])
    if errors:
        raise DownloadError("; ".join(errors))


def ensure_schedule_fits(target, deadline, *, pull_count=PULL_COUNT):
    collection_seconds = (pull_count + 1) * KUBECTL_TIMEOUT_SECONDS + POLL_SECONDS
    required = target["end"] - time.time() + collection_seconds
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
        or log.get("storage_role", "replica") != target.get("storage_role", "replica")
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


def record_download(entry, log, target):
    verify_result(log, target)
    for field in (
        "storage_account", "blob_digest", "downloaded_bytes", "started_at", "finished_at",
        "duration_seconds", "window_start", "window_end", "client_request_id", "storage_request_id",
    ):
        entry[field] = log[field]
    for field in ("time_to_headers_seconds", "hashing_seconds", "cpu_seconds"):
        if field in log:
            if type(log[field]) not in (int, float) or not 0 <= log[field] < float("inf"):
                raise DownloadError("Worker reported an invalid performance measurement")
            entry[field] = log[field]
    entry.update(storage_role=log.get("storage_role", "replica"), status="success")


def summarize_downloads(result, targets, *, warm_traffic=False):
    completed = [entry for entry in result["pulls"] if entry["status"] == "success"]
    result["successful_pulls"] = len(completed)
    result["total_downloaded_bytes"] = sum(entry["downloaded_bytes"] for entry in completed)
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    elapsed = (parse(result["finished_at"]) - parse(result["timestamp"])).total_seconds()
    result["performance"] = {"coordinator_seconds": max(0, elapsed)}
    if completed:
        first = min(parse(entry["started_at"]) for entry in completed)
        last = max(parse(entry["finished_at"]) for entry in completed)
        duration = (last - first).total_seconds()
        result["performance"].update(
            startup_to_first_get_seconds=max(0, (first - parse(result["timestamp"])).total_seconds()),
            transfer_wall_seconds=duration,
            aggregate_mbit_per_second=(
                result["total_downloaded_bytes"] * 8 / duration / 1_000_000 if duration > 0 else None
            ),
            completed_worker_cpu_seconds=(
                sum(entry["cpu_seconds"] for entry in completed)
                if all("cpu_seconds" in entry for entry in completed) else None
            ),
            completed_worker_hashing_seconds=(
                sum(entry["hashing_seconds"] for entry in completed)
                if all("hashing_seconds" in entry for entry in completed) else None
            ),
        )
    if warm_traffic:
        result["storage_accounts"] = [{
            "storage_account": target["account"],
            "expected_pulls": WARM_PULLS_PER_ACCOUNT,
            "successful_pulls": sum(entry["storage_account"] == target["account"] for entry in completed),
            "downloaded_bytes": sum(
                entry["downloaded_bytes"] for entry in completed if entry["storage_account"] == target["account"]
            ),
        } for target in targets]


def run(
    args, *, node_count=PULL_COUNT, region="australiaeast", registry_resource_group="rg_wj_cus1",
    start_immediately=False, pull_count=PULL_COUNT,
    warm_traffic=False, scale_in_threshold_bytes=DEFAULT_SCALE_IN_THRESHOLD_BYTES,
    scale_out_threshold_bytes=DEFAULT_SCALE_OUT_THRESHOLD_BYTES,
    primary_bundle=None,
):
    result = {
        "timestamp": utc(time.time()), "run_id": args.run_id, "run_url": args.run_url,
        "namespace": NAMESPACE,
        "image": args.image, "runner_image": args.runner_image,
        "registry_resource_group": registry_resource_group, "region": region,
        "node_count": node_count, "status": "failure", "successful_pulls": 0,
        "expected_pulls": pull_count,
        "start_mode": "immediate" if start_immediately else "aligned",
        "storage_role": "primary" if primary_bundle is not None else "replica",
        "execution_backend": "pods",
        "pulls": [], "errors": [],
    }
    owned_namespace = False
    targets = []
    if warm_traffic:
        result.update(
            scenario="TC-SI-03", pulls_per_account=WARM_PULLS_PER_ACCOUNT,
            scale_in_threshold_bytes=scale_in_threshold_bytes,
            scale_out_threshold_bytes=scale_out_threshold_bytes,
            server_validation_required=True,
        )
    try:
        username = os.environ.get("ACR_PULL_USERNAME", "")
        password = os.environ.get("ACR_PULL_PASSWORD", "")
        if primary_bundle is None and any(not value or value.startswith("$(") for value in (username, password)):
            raise DownloadError("Set ACR_PULL_USERNAME and secret ACR_PULL_PASSWORD")
        if primary_bundle is not None and (warm_traffic or node_count != 1):
            raise DownloadError("Primary downloads require a single local node and cannot use warm-traffic mode")
        parse_image(args.image)
        if warm_traffic and (pull_count != WARM_PULL_COUNT or node_count != 1):
            raise DownloadError("Warm traffic requires exactly six downloads on one local node")
        if not warm_traffic and pull_count not in SUPPORTED_PULL_COUNTS:
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
        account_count = WARM_ACCOUNT_COUNT if warm_traffic else 1
        secrets = [{
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {
                "name": f"acr-download-target-{index + 1}" if warm_traffic else "acr-download-target",
                "namespace": NAMESPACE,
            },
            "type": "Opaque", "stringData": {"target.json": "{}"},
        } for index in range(account_count)]
        target_names = [
            secrets[index // WARM_PULLS_PER_ACCOUNT if warm_traffic else 0]["metadata"]["name"]
            for index in range(pull_count)
        ]
        kubectl("create", "-f", "-", payload={
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": "acr-download-script", "namespace": NAMESPACE},
            "data": {"download.py": Path(__file__).with_name("download.py").read_text(encoding="utf-8")},
        })
        # Starting the shared budget before Pod creation is conservative for both
        # Pod activeDeadlineSeconds and the worker process's identical timeout.
        deadline = time.monotonic() + TIMEOUT_SECONDS

        def select_targets():
            if primary_bundle is not None:
                selected = [resolve_primary_target(
                    args.image, primary_bundle, start_immediately=start_immediately,
                )]
            elif warm_traffic:
                selected = resolve_warm_targets(
                    args.image, username, password, start_immediately=start_immediately,
                    scale_in_threshold_bytes=scale_in_threshold_bytes,
                    scale_out_threshold_bytes=scale_out_threshold_bytes,
                )
            else:
                selected = [resolve_target(args.image, username, password, start_immediately=start_immediately)]
            ensure_schedule_fits(selected[0], deadline, pull_count=pull_count)
            return selected

        if start_immediately:
            targets = select_targets()
            for secret, target in zip(secrets, targets):
                secret["stringData"]["target.json"] = json.dumps(target)
        # Immediate mode mounts the populated Secret on first start, avoiding refresh delays.
        for secret in secrets:
            kubectl("create", "-f", "-", payload=secret)
        kubectl("create", "-f", "-", payload=manifests(
            args.runner_image, assigned_nodes, target_names=target_names,
        ))
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
            targets = select_targets()
            # Replace over stdin; never put the SAS in arguments, local files, or logs.
            for secret, target in zip(secrets, targets):
                secret["stringData"]["target.json"] = json.dumps(target)
                kubectl("replace", "-f", "-", payload=secret)
        target = targets[0]
        targets_by_pod = {
            entry["pod"]: targets[index // WARM_PULLS_PER_ACCOUNT if warm_traffic else 0]
            for index, entry in enumerate(result["pulls"])
        }
        result.update(
            blob_digest=target["digest"], blob_size_bytes=target["size"],
            window_start=utc(target["start"]), window_end=utc(target["end"]),
        )
        if not warm_traffic:
            result["storage_account"] = target["account"]
        if primary_bundle is not None:
            result.update(
                storage_container=target["container"],
                primary_partition_key=target["primary_location"]["PartitionKey"],
                primary_row_key=target["primary_location"]["RowKey"],
            )
        while time.monotonic() < deadline:
            pods = pod_snapshot()
            collect_snapshot(result, pods, targets_by_pod=targets_by_pod)
            if result["successful_pulls"] == pull_count:
                if time.monotonic() >= deadline:
                    raise DownloadError("Coordinator deadline exceeded")
                if len({pull["storage_request_id"] for pull in result["pulls"]}) != pull_count:
                    raise DownloadError(f"Expected {pull_count} distinct Azure Storage request IDs")
                if len({pull["client_request_id"] for pull in result["pulls"]}) != pull_count:
                    raise DownloadError(f"Expected {pull_count} distinct client request IDs")
                break
            time.sleep(POLL_SECONDS)
        else:
            raise DownloadError(f"Timed out waiting for all {pull_count} verified downloads")
    except (OSError, ValueError, KeyError, TypeError, DownloadError, subprocess.SubprocessError, http.client.HTTPException) as error:
        result["errors"].append(error_message(error))
    finally:
        if owned_namespace:
            try:
                kubectl("delete", "namespace", NAMESPACE, "--wait=false")
            except (OSError, DownloadError, subprocess.SubprocessError) as error:
                result["errors"].append(f"Namespace cleanup failed: {error_message(error)}")
        result["finished_at"] = utc(time.time())
        summarize_downloads(result, targets, warm_traffic=warm_traffic)
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
