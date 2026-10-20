"""Verify node autoscaling at Azure Disk CSI attachment boundaries."""

import argparse
import csv
import json
import os
import random
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
import numpy as np

from clients.kubernetes_client import KubernetesClient
from clusterloader2.autoscale.autoscale import _build_report_template
from utils.logger_config import get_logger

logger = get_logger(__name__)
DRIVER = "disk.csi.azure.com"
WORKLOAD = "disk-workload"
LABEL = f"app={WORKLOAD}"
POD_TIMING_COLUMNS = (
    "pod_name", "pod_uid", "node_name", "requested_at", "pod_created_at",
    "pod_started_at", "ready_transition_at", "ready_observed_at",
    "e2e_ready_seconds", "phase",
)
NODE_TIMING_COLUMNS = (
    "node_name", "node_uid", "requested_at", "node_registered_at",
    "ready_transition_at", "ready_observed_at", "e2e_ready_seconds",
)


def stage_targets(node_count, disks_per_node):
    """Add 5-30 pods per batch after bootstrap, capped at the target disk capacity."""
    if not 2 <= node_count <= 10 or disks_per_node < 1:
        raise ValueError("The boundary test requires 2-10 nodes and a positive disk limit")
    replicas, previous_nodes = 1, 1
    capacity = node_count * disks_per_node
    while replicas < capacity:
        replicas = min(capacity, replicas + random.randint(5, 30))
        expected_nodes = (replicas + disks_per_node - 1) // disks_per_node
        yield expected_nodes, replicas, expected_nodes > previous_nodes
        previous_nodes = expected_nodes


def disk_limit(kube, node_name):
    drivers = kube.storage.read_csi_node(node_name).spec.drivers
    for driver in drivers:
        if driver.name == DRIVER and driver.allocatable:
            count = driver.allocatable.count
            if count is not None and count > 0:
                return count
    raise ValueError(f"{node_name} does not advertise a positive {DRIVER} disk limit")


def is_ready(resource):
    return any(
        condition.type == "Ready" and condition.status == "True"
        for condition in resource.status.conditions or []
    )


def summarize_pod_readiness(samples, expected_pod_count):
    """Only publish latency percentiles when all requested pods were observed Ready."""
    complete = expected_pod_count is not None and len(samples) == expected_pod_count
    percentiles = (
        np.percentile(
            [sample["e2e_ready_seconds"] for sample in samples.values()],
            [50, 90, 99],
            method="linear",
        ).tolist()
        if complete and samples else [None, None, None]
    )
    return {
        "sample_count": len(samples),
        "expected_pod_count": expected_pod_count,
        "complete": complete,
        "p50": percentiles[0],
        "p90": percentiles[1],
        "p99": percentiles[2],
    }


def create_stage_timings(requested_at, previous_replicas, replicas):
    return {
        "requested_at": requested_at,
        "pods": {
            f"{WORKLOAD}-{index}": {
                **dict.fromkeys(POD_TIMING_COLUMNS),
                "pod_name": f"{WORKLOAD}-{index}",
                "requested_at": requested_at,
                "phase": "NotObserved",
            }
            for index in range(previous_replicas, replicas)
        },
        "nodes": {},
    }


def resource_timestamp(resource, attribute):
    value = getattr(resource, attribute, None)
    return value.isoformat() if value is not None else None


def ready_transition_timestamp(resource):
    for condition in resource.status.conditions or []:
        if condition.type == "Ready" and condition.status == "True":
            return resource_timestamp(condition, "last_transition_time")
    return None


def record_timing_rows(timings, nodes, pods, old_nodes, elapsed, readiness_samples):
    observed_at = datetime.now(timezone.utc).isoformat()
    for node in nodes:
        name = node.metadata.name
        if name in old_nodes:
            continue
        row = timings["nodes"].setdefault(name, {
            **dict.fromkeys(NODE_TIMING_COLUMNS),
            "node_name": name,
            "node_uid": getattr(node.metadata, "uid", None),
            "requested_at": timings["requested_at"],
            "node_registered_at": resource_timestamp(node.metadata, "creation_timestamp"),
        })
        if row["ready_observed_at"] is None and is_ready(node) and not node.spec.unschedulable:
            row.update(
                ready_transition_at=ready_transition_timestamp(node),
                ready_observed_at=observed_at,
                e2e_ready_seconds=elapsed,
            )
    for pod in pods:
        name = pod.metadata.name
        if name not in timings["pods"]:
            continue
        row = timings["pods"][name]
        if row["pod_uid"] is not None and row["pod_uid"] != pod.metadata.uid:
            row.update(dict.fromkeys(POD_TIMING_COLUMNS))
            row.update(pod_name=name, requested_at=timings["requested_at"])
        row.update(
            pod_uid=pod.metadata.uid,
            node_name=pod.spec.node_name,
            pod_created_at=resource_timestamp(pod.metadata, "creation_timestamp"),
            pod_started_at=resource_timestamp(pod.status, "start_time"),
            phase=pod.status.phase,
        )
        sample = readiness_samples.get(name)
        if sample and row["ready_observed_at"] is None:
            row.update(
                ready_transition_at=ready_transition_timestamp(pod),
                ready_observed_at=observed_at,
                e2e_ready_seconds=sample["e2e_ready_seconds"],
            )


def write_timing_tables(report, report_file):
    for kind in ("pod", "node"):
        rows = [
            row for stage in report["stages"]
            for row in stage.get("timings", {}).get(f"{kind}s", {}).values()
        ]
        report[f"{kind}_timings"] = rows
    for kind, columns in (("pod", POD_TIMING_COLUMNS), ("node", NODE_TIMING_COLUMNS)):
        path = Path(report_file).with_name(f"{kind}-readiness.csv")
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(report[f"{kind}_timings"])


def scale_up_evidence(events, pod_uid, existing_node_count):
    events = [event for event in events if event.involved_object.uid == pod_uid]
    volume_events = [
        event for event in events
        if event.reason == "FailedScheduling"
        and (existing_node_count == 0 or re.search(
            r"\b[1-9]\d* node\(s\) exceed max volume count\b", event.message or ""
        ))
    ]
    scale_events = [event for event in events if event.reason == "TriggeredScaleUp"]
    if not volume_events or not scale_events:
        return None
    return {
        "failed_scheduling": volume_events[-1].message,
        "triggered_scale_up": scale_events[-1].message,
    }


def verify_disks(kube, namespace, pods, node_names, limit, full):
    """Require distinct bound Azure disks, attached to each pod's actual node."""
    distribution = Counter(pod.spec.node_name for pod in pods)
    if set(distribution) != node_names:
        raise ValueError(f"Unexpected pod placement: {dict(distribution)}")
    if any(count > limit or (full and count != limit) for count in distribution.values()):
        raise ValueError(f"Unexpected disk density: {dict(distribution)}, limit={limit}")
    claims = {
        claim.metadata.name: claim
        for claim in kube.api.list_namespaced_persistent_volume_claim(namespace).items
    }
    attachments = {
        (attachment.spec.source.persistent_volume_name, attachment.spec.node_name)
        for attachment in kube.storage.list_volume_attachment().items
        if attachment.spec.attacher == DRIVER
        and attachment.status and attachment.status.attached
    }
    handles = set()
    for pod in pods:
        volumes = [
            volume.persistent_volume_claim
            for volume in pod.spec.volumes or [] if volume.persistent_volume_claim
        ]
        if len(volumes) != 1:
            raise ValueError(f"{pod.metadata.name} must use exactly one PVC")
        claim = claims[volumes[0].claim_name]
        if claim.status.phase != "Bound":
            raise ValueError(f"PVC {claim.metadata.name} is not Bound")
        volume = kube.api.read_persistent_volume(claim.spec.volume_name)
        if not volume.spec.csi or volume.spec.csi.driver != DRIVER:
            raise ValueError(f"PV {volume.metadata.name} is not an Azure Disk CSI volume")
        if volume.spec.csi.volume_handle in handles:
            raise ValueError("Two workload pods share the same Azure disk")
        handles.add(volume.spec.csi.volume_handle)
        if (volume.metadata.name, pod.spec.node_name) not in attachments:
            raise ValueError(f"PV {volume.metadata.name} is not attached to its pod's node")
    if len(claims) != len(pods):
        raise ValueError(f"Expected {len(pods)} PVCs, found {len(claims)}")
    return dict(distribution)


def wait_for_stage(kube, namespace, selector, replicas, expected_nodes, limit,
                   old_nodes, overflow, timeout, interval=5, started=None,
                   previous_replicas=0, readiness_samples=None, timings=None):
    started = time.monotonic() if started is None else started
    deadline = started + timeout
    evidence = None
    node_ready_seconds = None
    running_seconds = None
    readiness_samples = {} if readiness_samples is None else readiness_samples
    new_pod_names = {
        f"{WORKLOAD}-{index}" for index in range(previous_replicas, replicas)
    }
    if timings is None:
        timings = create_stage_timings(
            datetime.now(timezone.utc).isoformat(), previous_replicas, replicas
        )
    while True:
        nodes = kube.get_nodes(label_selector=selector)
        pods = kube.api.list_namespaced_pod(namespace, label_selector=LABEL).items
        node_names = {node.metadata.name for node in nodes}
        if len(nodes) > expected_nodes:
            raise ValueError(f"Expected {expected_nodes} workload nodes, found {len(nodes)}")
        if overflow and evidence is None:
            for pod in pods:
                if pod.metadata.name not in new_pod_names:
                    continue
                events = kube.api.list_namespaced_event(
                    namespace, field_selector=f"involvedObject.name={pod.metadata.name}"
                ).items
                evidence = scale_up_evidence(
                    events, pod.metadata.uid, len(old_nodes)
                )
                if evidence:
                    evidence["pod_name"] = pod.metadata.name
                    break
        elapsed = time.monotonic() - started
        for pod in pods:
            name = pod.metadata.name
            if name not in new_pod_names:
                continue
            sample = readiness_samples.get(name)
            if sample and sample["pod_uid"] != pod.metadata.uid:
                del readiness_samples[name]
            if pod.status.phase == "Running" and is_ready(pod):
                readiness_samples.setdefault(name, {
                    "pod_uid": pod.metadata.uid,
                    "e2e_ready_seconds": elapsed,
                })
        record_timing_rows(timings, nodes, pods, old_nodes, elapsed, readiness_samples)
        nodes_ready = len(nodes) == expected_nodes and all(
            is_ready(node) and not node.spec.unschedulable for node in nodes
        )
        all_running = len(pods) == replicas and all(
            pod.status.phase == "Running" for pod in pods
        )
        if nodes_ready and node_ready_seconds is None:
            node_ready_seconds = elapsed
        if all_running and running_seconds is None:
            running_seconds = elapsed
        if nodes_ready and all_running and all(is_ready(pod) for pod in pods):
            if overflow and evidence is None:
                # Events may arrive after the pod becomes Ready.
                pass
            else:
                if not old_nodes.issubset(node_names):
                    raise ValueError("An existing workload node disappeared during scale-up")
                if limit is None:
                    limit = disk_limit(kube, nodes[0].metadata.name)
                for node in nodes:
                    if disk_limit(kube, node.metadata.name) != limit:
                        raise ValueError("Workload nodes advertise different disk limits")
                new_pod_nodes = {
                    pod.spec.node_name for pod in pods if pod.metadata.name in new_pod_names
                }
                if overflow and not (node_names - old_nodes).issubset(new_pod_nodes):
                    raise ValueError("New batch pods did not run on every newly added node")
                distribution = verify_disks(
                    kube, namespace, pods, node_names, limit,
                    full=replicas == expected_nodes * limit,
                )
                return {
                    "replicas": replicas,
                    "node_count": expected_nodes,
                    "phase": "bootstrap" if not old_nodes else (
                        "overflow" if overflow else "fill"
                    ),
                    "disks_per_node": limit,
                    "node_ready_seconds": node_ready_seconds,
                    "all_pods_running_seconds": running_seconds,
                    "all_pods_storage_ready_seconds": elapsed,
                    "pods_per_node": distribution,
                    "evidence": evidence,
                    "pod_readiness_samples": readiness_samples,
                    "timings": timings,
                    "pod_readiness_e2e_seconds": summarize_pod_readiness(
                        readiness_samples, replicas - previous_replicas
                    ),
                }, node_names
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Stage timed out: replicas={replicas}, expected_nodes={expected_nodes}, "
                f"observed_nodes={len(nodes)}, observed_pods={len(pods)}, "
                f"disk_limit_scale_up_evidence={evidence}"
            )
        time.sleep(interval)


def cleanup(kube, namespace, selector, timeout, storage_timeout, result_file):
    volume_names = {
        volume.metadata.name for volume in kube.api.list_persistent_volume().items
        if volume.spec.claim_ref and volume.spec.claim_ref.namespace == namespace
    }
    storage_deadline = time.monotonic() + storage_timeout * 60
    kube.api.delete_namespace(namespace)
    while True:
        claims = [
            claim for claim in kube.api.list_persistent_volume_claim_for_all_namespaces().items
            if claim.metadata.namespace == namespace
        ]
        volumes = [
            volume for volume in kube.api.list_persistent_volume().items
            if volume.spec.claim_ref and volume.spec.claim_ref.namespace == namespace
        ]
        volume_names.update(volume.metadata.name for volume in volumes)
        attachments = [
            attachment for attachment in kube.storage.list_volume_attachment().items
            if attachment.spec.source.persistent_volume_name in volume_names
        ]
        storage = {
            "pvc_remaining": len(claims),
            "pv_remaining": len(volumes),
            "volume_attachments_remaining": len(attachments),
        }
        if not claims and not volumes and not attachments:
            break
        if time.monotonic() >= storage_deadline:
            raise TimeoutError(f"Storage cleanup timed out: {storage}")
        time.sleep(10)
    Path(result_file).parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as file:
        json.dump(storage, file)
    deadline = time.monotonic() + timeout
    while True:
        nodes = kube.get_nodes(label_selector=selector)
        if not nodes:
            return storage
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Workload pool did not return to zero nodes: {len(nodes)} remain")
        time.sleep(10)


def execute(kube, node_count, selector, storage_class, timeout, down_timeout,
            storage_timeout, report_file):
    report = {"result": "failure", "stages": [], "node_count": node_count}
    namespace = f"autoscale-disk-{uuid.uuid4().hex[:12]}"
    created = False
    try:
        if not 2 <= node_count <= 10:
            raise ValueError("The boundary test requires 2-10 workload nodes")
        if min(timeout, down_timeout, storage_timeout) <= 0:
            raise ValueError("All timeouts must be positive")
        if kube.get_nodes(label_selector=selector):
            raise ValueError("Start with zero workload nodes to verify scale-from-zero")
        report["namespace"] = namespace
        storage = kube.storage.read_storage_class(storage_class)
        if (storage.provisioner != DRIVER or storage.reclaim_policy != "Delete"
                or storage.volume_binding_mode != "WaitForFirstConsumer"):
            raise ValueError("StorageClass must use Azure Disk CSI, Delete and WaitForFirstConsumer")
        manifest_path = Path(__file__).with_name("config") / "disk_statefulset.yaml"
        with manifest_path.open(encoding="utf-8") as file:
            manifest = yaml.safe_load(file)
        manifest["spec"]["template"]["spec"]["nodeSelector"] = {
            key.strip(): value.strip()
            for key, value in (part.split("=", 1) for part in selector.split(","))
        }
        manifest["spec"]["volumeClaimTemplates"][0]["spec"]["storageClassName"] = storage_class
        kube.api.create_namespace({"metadata": {"name": namespace}})
        created = True
        kube.app.create_namespaced_stateful_set(namespace, manifest)
        def run_stage(expected_nodes, replicas, overflow, limit, old_nodes, previous_replicas):
            logger.info("Requesting %s pods; expecting %s workload nodes", replicas, expected_nodes)
            requested_at = datetime.now(timezone.utc).isoformat()
            started = time.monotonic()
            stage = {
                "requested_at": requested_at,
                "replicas": replicas,
                "node_count": expected_nodes,
                "new_pod_count": replicas - previous_replicas,
                "pod_readiness_samples": {},
                "timings": create_stage_timings(requested_at, previous_replicas, replicas),
                "result": "failure",
            }
            report["stages"].append(stage)
            try:
                kube.app.patch_namespaced_stateful_set_scale(
                    WORKLOAD, namespace, {"spec": {"replicas": replicas}}
                )
                measurements, old_nodes = wait_for_stage(
                    kube, namespace, selector, replicas, expected_nodes, limit,
                    old_nodes, overflow, timeout, started=started,
                    previous_replicas=previous_replicas,
                    readiness_samples=stage["pod_readiness_samples"],
                    timings=stage["timings"],
                )
                stage.update(measurements)
                stage["result"] = "success"
            finally:
                stage["pod_readiness_e2e_seconds"] = summarize_pod_readiness(
                    stage["pod_readiness_samples"], stage["new_pod_count"]
                )
            return stage, old_nodes

        bootstrap, old_nodes = run_stage(1, 1, True, None, set(), 0)
        limit = bootstrap["disks_per_node"]
        report.update(disks_per_node=limit, pod_count=node_count * limit)
        previous_replicas = 1
        for expected_nodes, replicas, overflow in stage_targets(node_count, limit):
            _, old_nodes = run_stage(
                expected_nodes, replicas, overflow, limit, old_nodes, previous_replicas
            )
            previous_replicas = replicas
        report["result"] = "success"
    except Exception as error:
        report["error"] = str(error)
        logger.exception("Disk-bound autoscale test failed")
        raise
    finally:
        if report["stages"]:
            samples = {
                name: sample for stage in report["stages"]
                for name, sample in stage["pod_readiness_samples"].items()
            }
            report["pod_readiness_e2e_seconds"] = summarize_pod_readiness(
                samples, report.get("pod_count")
            )
        try:
            if created:
                report["storage_cleanup"] = cleanup(
                    kube, namespace, selector, down_timeout, storage_timeout,
                    str(Path(report_file).with_name("storage-cleanup.json")),
                )
        except Exception as error:
            report["result"] = "failure"
            report["cleanup_error"] = str(error)
            logger.exception("Disk-bound autoscale cleanup failed")
            raise
        finally:
            Path(report_file).parent.mkdir(parents=True, exist_ok=True)
            try:
                write_timing_tables(report, report_file)
            except OSError as error:
                report["result"] = "failure"
                report["timing_export_error"] = str(error)
                logger.exception("Failed to export readiness timing tables")
                raise
            finally:
                with open(report_file, "w", encoding="utf-8") as file:
                    json.dump(report, file, indent=2)
    return report


def collect(report_file, result_file):
    with open(report_file, encoding="utf-8") as file:
        report = json.load(file)
    result = _build_report_template(
        "on-demand", report.get("pod_count", 0), os.environ["CLOUD_INFO"],
        os.environ["RUN_ID"], os.environ["RUN_URL"],
        autoscale_type="disk_boundary", node_count=report["node_count"], data=report,
    )
    Path(result_file).parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as file:
        file.write(json.dumps(result) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("execute")
    run.add_argument("--node-count", type=int, default=10)
    run.add_argument("--selector", default="cas=dedicated")
    run.add_argument("--storage-class", default="managed-csi")
    run.add_argument("--timeout-seconds", type=int, default=1800)
    run.add_argument("--scale-down-timeout-seconds", type=int, default=1800)
    run.add_argument("--storage-cleanup-timeout-minutes", type=int, default=30)
    run.add_argument("--report-file", required=True)
    gather = subparsers.add_parser("collect")
    gather.add_argument("--report-file", required=True)
    gather.add_argument("--result-file", required=True)
    args = parser.parse_args()
    if args.command == "execute":
        execute(
            KubernetesClient(os.path.expanduser("~/.kube/config")),
            args.node_count, args.selector, args.storage_class, args.timeout_seconds,
            args.scale_down_timeout_seconds, args.storage_cleanup_timeout_minutes,
            args.report_file,
        )
    else:
        collect(args.report_file, args.result_file)


if __name__ == "__main__":
    main()
