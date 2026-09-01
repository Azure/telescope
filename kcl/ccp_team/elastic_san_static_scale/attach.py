#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from esan_common import CSI_DRIVER, canonical_handle, load_cluster_info, resolve_cluster, write_json
from provision import ArmClient, inventory_managed_sans, utc_now


def kubectl_json(kubeconfig: str, arguments: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, *arguments, "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def kubectl(kubeconfig: str, arguments: list[str]) -> None:
    subprocess.run(["kubectl", "--kubeconfig", kubeconfig, *arguments], check=True)


def ensure_namespace(kubeconfig: str, namespace: str) -> None:
    manifest = subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "create",
            "namespace",
            namespace,
            "--dry-run=client",
            "-o",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"],
        input=manifest.stdout,
        check=True,
        text=True,
    )


def resource_suffix(handle: str) -> str:
    return hashlib.sha256(handle.encode()).hexdigest()[:20]


def attached_volume_handles(kubeconfig: str) -> set[str]:
    persistent_volumes = kubectl_json(kubeconfig, ["get", "pv"])
    volume_attachments = kubectl_json(kubeconfig, ["get", "volumeattachments"])
    handles_by_pv = {
        item["metadata"]["name"]: csi["volumeHandle"].casefold()
        for item in persistent_volumes.get("items", [])
        if (csi := item.get("spec", {}).get("csi"))
        and csi.get("driver") == CSI_DRIVER
        and csi.get("volumeHandle")
    }
    return {
        handles_by_pv[persistent_volume]
        for item in volume_attachments.get("items", [])
        if item.get("spec", {}).get("attacher") == CSI_DRIVER
        and item.get("status", {}).get("attached") is True
        and (persistent_volume := item.get("spec", {}).get("source", {}).get("persistentVolumeName"))
        in handles_by_pv
    }


def volume_record(
    resource_group: str,
    san: str,
    group: str,
    volume: dict[str, Any],
) -> dict[str, Any] | None:
    properties = volume.get("properties", {})
    target = properties.get("storageTarget", {})
    if properties.get("provisioningState") != "Succeeded":
        return None
    if not target.get("targetIqn") or not target.get("targetPortalHostname"):
        return None
    handle = canonical_handle(resource_group, san, group, volume["name"])
    return {
        "handle": handle,
        "resource_group": resource_group,
        "san": san,
        "group": group,
        "volume": volume["name"],
        "size_gib": properties.get("sizeGiB", 1),
        "target_iqn": target["targetIqn"],
        "target_portal": f"{target['targetPortalHostname']}:{target.get('targetPortalPort', 3260)}",
    }


def select_ready_nodes(
    *,
    kubeconfig: str,
    selector: str,
    required: int,
    pods_per_node: int,
    pod_slot_headroom: int,
) -> list[str]:
    arguments = ["get", "nodes"]
    if selector:
        arguments.extend(["--selector", selector])
    payload = kubectl_json(kubeconfig, arguments)
    pods = kubectl_json(kubeconfig, ["get", "pods", "--all-namespaces"])
    scheduled_counts: dict[str, int] = {}
    for pod in pods.get("items", []):
        node_name = pod.get("spec", {}).get("nodeName")
        if node_name:
            scheduled_counts[node_name] = scheduled_counts.get(node_name, 0) + 1

    candidates: list[tuple[int, str]] = []
    for node in payload.get("items", []):
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in node.get("status", {}).get("conditions", [])
        )
        unschedulable = node.get("spec", {}).get("unschedulable", False)
        no_schedule = any(
            taint.get("effect") in ("NoSchedule", "NoExecute")
            for taint in node.get("spec", {}).get("taints", [])
        )
        node_name = node["metadata"]["name"]
        is_linux = node.get("metadata", {}).get("labels", {}).get("kubernetes.io/os") == "linux"
        scheduled = scheduled_counts.get(node_name, 0)
        allocatable = int(node.get("status", {}).get("allocatable", {}).get("pods", 0))
        available = allocatable - scheduled - pod_slot_headroom
        if (
            ready
            and is_linux
            and not unschedulable
            and not no_schedule
            and available >= pods_per_node
        ):
            candidates.append((scheduled, node_name))
    candidates.sort()
    if len(candidates) < required:
        raise RuntimeError(
            f"node selector {selector!r} has {len(candidates)} nodes with at least "
            f"{pods_per_node} free Pod slots plus {pod_slot_headroom} headroom; "
            f"{required} nodes required"
        )
    return [name for _, name in candidates[:required]]


def build_resources(
    record: dict[str, Any],
    *,
    namespace_prefix: str,
    node_label_key: str,
    node_label_value: str,
    image: str,
    cpu_request: str,
    memory_request: str,
) -> tuple[str, list[dict[str, Any]]]:
    suffix = resource_suffix(record["handle"])
    namespace = f"{namespace_prefix}-{suffix[:2]}"
    pv_name = f"tesan-pv-{suffix}"
    pvc_name = f"tesan-pvc-{suffix}"
    pod_name = f"tesan-attach-{suffix}"
    labels = {
        "telescope-workload": "elastic-san-static-scale",
        "telescope-cluster": node_label_value,
        "telescope-volume": suffix,
    }
    pv = {
        "apiVersion": "v1",
        "kind": "PersistentVolume",
        "metadata": {"name": pv_name, "labels": labels},
        "spec": {
            "capacity": {"storage": f"{record['size_gib']}Gi"},
            "accessModes": ["ReadWriteOnce"],
            "volumeMode": "Filesystem",
            "persistentVolumeReclaimPolicy": "Retain",
            "storageClassName": "",
            "claimRef": {"namespace": namespace, "name": pvc_name},
            "csi": {
                "driver": CSI_DRIVER,
                "fsType": "ext4",
                "volumeHandle": record["handle"],
                "volumeAttributes": {
                    "discoveryCHAPAuth": "false",
                    "iqn": record["target_iqn"],
                    "iscsiInterface": "default",
                    "lun": "0",
                    "numsessions": "8",
                    "portals": "[]",
                    "san": record["san"],
                    "sessionCHAPAuth": "false",
                    "targetPortal": record["target_portal"],
                },
            },
        },
    }
    pvc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": pvc_name, "namespace": namespace, "labels": labels},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "volumeMode": "Filesystem",
            "resources": {"requests": {"storage": f"{record['size_gib']}Gi"}},
            "storageClassName": "",
            "volumeName": pv_name,
        },
    }
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": labels,
            "annotations": {"telescope-volume-handle": record["handle"]},
        },
        "spec": {
            "automountServiceAccountToken": False,
            "restartPolicy": "Always",
            "terminationGracePeriodSeconds": 5,
            "nodeSelector": {
                "kubernetes.io/os": "linux",
                node_label_key: node_label_value,
            },
            "topologySpreadConstraints": [
                {
                    "maxSkew": 1,
                    "topologyKey": "kubernetes.io/hostname",
                    "whenUnsatisfiable": "DoNotSchedule",
                    "labelSelector": {
                        "matchLabels": {
                            "telescope-workload": "elastic-san-static-scale",
                            "telescope-cluster": node_label_value,
                        }
                    },
                }
            ],
            "containers": [
                {
                    "name": "volume-holder",
                    "image": image,
                    "command": ["sh", "-c", "trap : TERM INT; sleep infinity & wait"],
                    "resources": {
                        "requests": {"cpu": cpu_request, "memory": memory_request}
                    },
                    "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                }
            ],
            "volumes": [
                {"name": "data", "persistentVolumeClaim": {"claimName": pvc_name}}
            ],
        },
    }
    return namespace, [pv, pvc, pod]


def apply_resources(
    *,
    kubeconfig: str,
    records: list[dict[str, Any]],
    args: argparse.Namespace,
    node_label_value: str,
) -> None:
    namespaces = {
        f"{args.namespace_prefix}-{resource_suffix(record['handle'])[:2]}"
        for record in records
    }
    for namespace in sorted(namespaces):
        ensure_namespace(kubeconfig, namespace)

    with tempfile.TemporaryDirectory() as temporary_directory:
        output_directory = Path(temporary_directory)
        chunk: list[dict[str, Any]] = []
        chunk_number = 0
        for record_index, record in enumerate(records):
            _, resources = build_resources(
                record,
                namespace_prefix=args.namespace_prefix,
                node_label_key=args.node_label_key,
                node_label_value=node_label_value,
                image=args.pod_image,
                cpu_request=args.cpu_request,
                memory_request=args.memory_request,
            )
            chunk.extend(resources)
            if len(chunk) >= args.apply_batch_size * 3 or record_index + 1 == len(records):
                path = output_directory / f"resources-{chunk_number:05d}.json"
                path.write_text(json.dumps({"apiVersion": "v1", "kind": "List", "items": chunk}))
                kubectl(
                    kubeconfig,
                    [
                        "apply",
                        "--server-side",
                        "--field-manager=telescope-esan-static",
                        "--force-conflicts",
                        "-f",
                        str(path),
                    ],
                )
                chunk = []
                chunk_number += 1


def wait_ready(
    kubeconfig: str,
    cluster_label: str,
    expected_pods: set[str],
    timeout_seconds: int,
) -> dict[str, int]:
    deadline = time.monotonic() + timeout_seconds
    selector = (
        "telescope-workload=elastic-san-static-scale,"
        f"telescope-cluster={cluster_label}"
    )
    while time.monotonic() < deadline:
        payload = kubectl_json(kubeconfig, ["get", "pods", "--all-namespaces", "-l", selector])
        total = len(payload.get("items", []))
        selected = [
            pod for pod in payload.get("items", []) if pod["metadata"]["name"] in expected_pods
        ]
        ready = sum(
            any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in pod.get("status", {}).get("conditions", [])
            )
            for pod in selected
        )
        pending = sum(pod.get("status", {}).get("phase") == "Pending" for pod in selected)
        expected = len(expected_pods)
        print(
            f"[attach] managed-total={total} selected={len(selected)} ready={ready} "
            f"pending={pending} expected={expected}"
        )
        if len(selected) == expected and ready == expected:
            return {
                "managed_total": total,
                "selected": len(selected),
                "ready": ready,
                "pending": pending,
            }
        time.sleep(30)
    raise TimeoutError(f"timed out waiting for {expected} attached Pods")


def wait_attached(
    kubeconfig: str,
    expected_handles: set[str],
    timeout_seconds: int,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        attached = attached_volume_handles(kubeconfig)
        attached_count = len(expected_handles & attached)
        print(
            f"[attach] volumeattachments={attached_count}/{len(expected_handles)}"
        )
        if attached_count == len(expected_handles):
            return attached_count
        time.sleep(30)
    raise TimeoutError(
        f"timed out waiting for {len(expected_handles)} attached VolumeAttachments"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attach pipeline-managed static Elastic SAN volumes")
    cluster = parser.add_mutually_exclusive_group(required=True)
    cluster.add_argument("--cluster-id", help="Full AKS ARM resource ID")
    cluster.add_argument("--cluster-info", type=Path, help="Resolved cluster JSON from the pipeline")
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--attach-limit", type=int, default=0, help="0 attaches all successful volumes")
    parser.add_argument("--workload-node-selector", default="kubernetes.azure.com/mode=user")
    parser.add_argument("--pods-per-node", type=int, default=150)
    parser.add_argument("--pod-slot-headroom", type=int, default=10)
    parser.add_argument("--node-label-key", default="telescope-esan-attach")
    parser.add_argument("--namespace-prefix", default="telescope-esan")
    parser.add_argument("--apply-batch-size", type=int, default=100)
    parser.add_argument("--pod-image", default="mcr.microsoft.com/azurelinux/busybox:1.36")
    parser.add_argument("--cpu-request", default="300m")
    parser.add_argument("--memory-request", default="32Mi")
    parser.add_argument("--wait-timeout-seconds", type=int, default=14_400)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    if (
        args.attach_limit < 0
        or args.pods_per_node < 1
        or args.pod_slot_headroom < 0
        or args.apply_batch_size < 1
    ):
        raise ValueError("attach limit must be non-negative; density and batch size must be positive")
    cluster = (
        load_cluster_info(args.cluster_info)
        if args.cluster_info
        else resolve_cluster(args.cluster_id)
    )
    async with ArmClient(cluster.subscription_id) as client:
        inventories = await inventory_managed_sans(client, cluster.resource_uid)

    records = []
    failed_or_unready = 0
    for inventory in inventories:
        for group, volumes in inventory.groups.items():
            for volume in volumes:
                record = volume_record(
                    inventory.san.resource_group, inventory.san.name, group, volume
                )
                if record:
                    records.append(record)
                else:
                    failed_or_unready += 1
    records.sort(key=lambda item: item["handle"])
    already_attached = attached_volume_handles(args.kubeconfig)
    successful_managed_count = len(records)
    records = [record for record in records if record["handle"] not in already_attached]
    unattached_count = len(records)
    if args.attach_limit:
        if len(records) < args.attach_limit:
            raise RuntimeError(
                f"attach-limit={args.attach_limit}, but only {len(records)} successful managed volumes exist"
            )
        records = records[: args.attach_limit]

    required_nodes = math.ceil(len(records) / args.pods_per_node) if records else 0
    nodes = select_ready_nodes(
        kubeconfig=args.kubeconfig,
        selector=args.workload_node_selector,
        required=required_nodes,
        pods_per_node=args.pods_per_node,
        pod_slot_headroom=args.pod_slot_headroom,
    )
    node_label_value = hashlib.sha256(cluster.resource_uid.encode()).hexdigest()[:12]
    plan = {
        "generated_utc": utc_now(),
        "cluster": cluster.__dict__,
        "managed_sans": len(inventories),
        "successful_managed_volumes": successful_managed_count,
        "already_attached_volumes": successful_managed_count - unattached_count,
        "unattached_volumes_available": unattached_count,
        "unattached_volumes_selected": len(records),
        "failed_or_unready_volumes": failed_or_unready,
        "required_nodes": required_nodes,
        "candidate_selector": args.workload_node_selector,
        "selected_nodes": nodes,
        "pods_per_node": args.pods_per_node,
        "pod_slot_headroom": args.pod_slot_headroom,
        "dry_run": args.dry_run,
    }
    write_json(args.results_dir / "attach-plan.json", plan)
    print(json.dumps(plan, indent=2, default=list))
    if args.dry_run or not records:
        return 0

    label_selector = f"{args.node_label_key}={node_label_value}"
    for node in nodes:
        kubectl(
            args.kubeconfig,
            ["label", "node", node, label_selector, "--overwrite"],
        )

    started = utc_now()
    start_time = time.monotonic()
    apply_resources(
        kubeconfig=args.kubeconfig,
        records=records,
        args=args,
        node_label_value=node_label_value,
    )
    expected_pods = {f"tesan-attach-{resource_suffix(record['handle'])}" for record in records}
    status = wait_ready(
        args.kubeconfig,
        node_label_value,
        expected_pods,
        args.wait_timeout_seconds,
    )
    expected_handles = {record["handle"] for record in records}
    status["volume_attachments_attached"] = wait_attached(
        args.kubeconfig,
        expected_handles,
        args.wait_timeout_seconds,
    )
    summary = {
        **plan,
        "dry_run": False,
        "started_utc": started,
        "completed_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - start_time, 3),
        "status": status,
    }
    write_json(args.results_dir / "attach-summary.json", summary)
    print(json.dumps(summary, indent=2, default=list))
    return 0


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())