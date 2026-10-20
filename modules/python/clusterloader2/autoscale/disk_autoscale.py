"""Verify node autoscaling at Azure Disk CSI attachment boundaries."""

import argparse
import json
import os
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from clients.kubernetes_client import KubernetesClient
from clusterloader2.autoscale.autoscale import _build_report_template
from utils.logger_config import get_logger

logger = get_logger(__name__)
DRIVER = "disk.csi.azure.com"
WORKLOAD = "disk-workload"
LABEL = f"app={WORKLOAD}"


def stage_targets(node_count, disks_per_node):
    """Fill each node, then request one pod beyond the cluster's disk capacity."""
    if not 2 <= node_count <= 10 or disks_per_node < 1:
        raise ValueError("The boundary test requires 2-10 nodes and a positive disk limit")
    for count in range(1, node_count + 1):
        if count > 1:
            yield count, (count - 1) * disks_per_node + 1, True
        yield count, count * disks_per_node, False


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


def scale_up_evidence(events, pod_uid, full_node_count):
    events = [event for event in events if event.involved_object.uid == pod_uid]
    volume_message = f"{full_node_count} node(s) exceed max volume count"
    volume_events = [
        event for event in events
        if event.reason == "FailedScheduling"
        and (full_node_count == 0 or volume_message in (event.message or ""))
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
                   old_nodes, overflow, timeout, interval=5, started=None):
    started = time.monotonic() if started is None else started
    deadline = started + timeout
    evidence = None
    node_ready_seconds = None
    running_seconds = None
    overflow_name = f"{WORKLOAD}-{replicas - 1}"
    while True:
        nodes = kube.get_nodes(label_selector=selector)
        pods = kube.api.list_namespaced_pod(namespace, label_selector=LABEL).items
        node_names = {node.metadata.name for node in nodes}
        if len(nodes) > expected_nodes:
            raise ValueError(f"Expected {expected_nodes} workload nodes, found {len(nodes)}")
        if overflow:
            overflow_pod = next(
                (pod for pod in pods if pod.metadata.name == overflow_name), None
            )
            if overflow_pod:
                events = kube.api.list_namespaced_event(
                    namespace, field_selector=f"involvedObject.name={overflow_name}"
                ).items
                evidence = scale_up_evidence(
                    events, overflow_pod.metadata.uid, len(old_nodes)
                ) or evidence
        elapsed = time.monotonic() - started
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
                if overflow and overflow_pod.spec.node_name not in node_names - old_nodes:
                    raise ValueError("The overflow pod did not run on the newly added node")
                distribution = verify_disks(
                    kube, namespace, pods, node_names, limit, full=not overflow
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
        list(stage_targets(node_count, 1))
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
        def run_stage(expected_nodes, replicas, overflow, limit, old_nodes):
            logger.info("Requesting %s pods; expecting %s workload nodes", replicas, expected_nodes)
            requested_at = datetime.now(timezone.utc).isoformat()
            started = time.monotonic()
            kube.app.patch_namespaced_stateful_set_scale(
                WORKLOAD, namespace, {"spec": {"replicas": replicas}}
            )
            stage, old_nodes = wait_for_stage(
                kube, namespace, selector, replicas, expected_nodes, limit,
                old_nodes, overflow, timeout, started=started,
            )
            stage["requested_at"] = requested_at
            report["stages"].append(stage)
            return stage, old_nodes

        bootstrap, old_nodes = run_stage(1, 1, True, None, set())
        limit = bootstrap["disks_per_node"]
        report.update(disks_per_node=limit, pod_count=node_count * limit)
        for expected_nodes, replicas, overflow in stage_targets(node_count, limit):
            _, old_nodes = run_stage(expected_nodes, replicas, overflow, limit, old_nodes)
        report["result"] = "success"
    except Exception as error:
        report["error"] = str(error)
        logger.exception("Disk-bound autoscale test failed")
        raise
    finally:
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
