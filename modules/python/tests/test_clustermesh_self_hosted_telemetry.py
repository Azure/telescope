"""Tests for the ClusterMesh self-hosted telemetry auditor."""

import importlib.util
from pathlib import Path

import yaml


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "telemetry"
    / "audit_self_hosted.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "clustermesh_self_hosted_telemetry",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
audit_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(audit_module)
MONITOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "prometheus-additional-monitors"
    / "real-node-kubelet.yaml"
)


def test_real_node_monitor_scrapes_kubelet_and_cadvisor():
    monitor = yaml.safe_load(MONITOR_PATH.read_text(encoding="utf-8"))

    assert monitor["spec"]["selector"]["matchLabels"] == {"k8s-app": "cilium"}
    endpoints = monitor["spec"]["podMetricsEndpoints"]
    assert [endpoint["path"] for endpoint in endpoints] == [
        "/metrics",
        "/metrics/cadvisor",
    ]
    assert all(endpoint["port"] == "prometheus" for endpoint in endpoints)
    assert all(
        any(
            relabel.get("sourceLabels") == ["__meta_kubernetes_pod_host_ip"]
            and relabel.get("replacement") == "$1:10250"
            for relabel in endpoint["relabelings"]
        )
        for endpoint in endpoints
    )


def test_audit_requires_real_node_kubelet_targets():
    metric_names = [
        "apiserver_request_total",
        "apiserver_flowcontrol_rejected_requests_total",
        "kube_pod_info",
        "kubelet_running_pods",
        "container_cpu_usage_seconds_total",
        "container_memory_working_set_bytes",
        "cilium_version",
        "cilium_kvstoremesh_kvstore_events_total",
        "etcd_request_duration_seconds",
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
    ]
    targets = [
        {"labels": {"job": "kubelet-real-nodes"}, "health": "up"},
        {"labels": {"job": "cadvisor-real-nodes"}, "health": "up"},
    ]

    report = audit_module.build_audit(
        metric_names,
        targets,
        require_real_node_kubelet=True,
    )

    assert report["complete"] is True
    assert {check["status"] for check in report["checks"]} == {"covered"}


def test_audit_fails_when_cadvisor_target_is_down():
    metric_names = [
        "apiserver_request_total",
        "apiserver_flowcontrol_rejected_requests_total",
        "kube_pod_info",
        "kubelet_running_pods",
        "container_cpu_usage_seconds_total",
        "container_memory_working_set_bytes",
        "cilium_version",
        "etcd_request_duration_seconds",
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
    ]
    targets = [
        {"labels": {"job": "kubelet-real-nodes"}, "health": "up"},
        {"labels": {"job": "cadvisor-real-nodes"}, "health": "down"},
    ]

    report = audit_module.build_audit(
        metric_names,
        targets,
        require_real_node_kubelet=True,
    )

    cadvisor = next(
        check
        for check in report["checks"]
        if check["name"] == "target:cadvisor-real-nodes"
    )
    assert report["complete"] is False
    assert cadvisor["status"] == "missing"
