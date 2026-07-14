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
KWOK_RESOURCE_PATH = MONITOR_PATH.parent / "00-kwok-resource-usage.yaml"
KWOK_SCRAPE_PATH = MONITOR_PATH.parent / "02-kwok-resource-scrape-secret.yaml"
EVENT_DEPLOYMENT_PATH = (
    MONITOR_PATH.parents[1]
    / "modules"
    / "event-throughput-deployment.yaml"
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


def test_kwok_resource_usage_and_node_discovery_are_configured():
    resources = list(
        yaml.safe_load_all(KWOK_RESOURCE_PATH.read_text(encoding="utf-8"))
    )
    kinds = {resource["kind"] for resource in resources}
    metric = next(resource for resource in resources if resource["kind"] == "Metric")
    secret = yaml.safe_load(KWOK_SCRAPE_PATH.read_text(encoding="utf-8"))
    scrape_configs = yaml.safe_load(
        secret["stringData"]["prometheus-additional.yaml"]
    )

    assert kinds == {"Metric", "ClusterResourceUsage"}
    assert metric["spec"]["path"] == "/metrics/nodes/{nodeName}/metrics/resource"
    assert {
        item["name"] for item in metric["spec"]["metrics"]
    } >= {
        "container_cpu_usage_seconds_total",
        "container_memory_working_set_bytes",
        "node_cpu_usage_seconds_total",
        "node_memory_working_set_bytes",
    }
    assert scrape_configs[0]["job_name"] == "kwok-resource"
    assert scrape_configs[0]["kubernetes_sd_configs"] == [{"role": "node"}]


def test_mock_workload_template_includes_synthetic_usage_annotations():
    template = EVENT_DEPLOYMENT_PATH.read_text(encoding="utf-8")

    assert 'kwok.x-k8s.io/usage-cpu: "{{.KwokUsageCPU}}"' in template
    assert 'kwok.x-k8s.io/usage-memory: "{{.KwokUsageMemory}}"' in template


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
        "etcd_request_duration_seconds_count",
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
        "aks_apiserver_backend_process_cpu_seconds_total",
        "aks_apiserver_backend_process_resident_memory_bytes",
        "pod_cpu_usage_seconds_total",
        "pod_memory_working_set_bytes",
        "node_cpu_usage_seconds_total",
        "node_memory_working_set_bytes",
        "clustermesh_cluster_identity_info",
    ]
    targets = [
        {"labels": {"job": "apiserver-backend-exporter"}, "health": "up"},
        {"labels": {"job": "kubelet-real-nodes"}, "health": "up"},
        {"labels": {"job": "cadvisor-real-nodes"}, "health": "up"},
        {"labels": {"job": "kwok-resource"}, "health": "up"},
    ]

    report = audit_module.build_audit(
        metric_names,
        targets,
        require_real_node_kubelet=True,
        require_kwok_resource=True,
        identity_series=[
            {
                "run_id": "run-1",
                "cluster_role": "mesh-1",
                "cluster_name": "clustermesh-1",
                "cluster_resource_id": "/subscriptions/sub-1/clustermesh-1",
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "region": "eastus2euap",
                "prometheus_cluster_alias": "run_1_mesh_1",
            }
        ],
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
        "etcd_request_duration_seconds_count",
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
        "aks_apiserver_backend_process_cpu_seconds_total",
        "aks_apiserver_backend_process_resident_memory_bytes",
        "pod_cpu_usage_seconds_total",
        "pod_memory_working_set_bytes",
        "node_cpu_usage_seconds_total",
        "node_memory_working_set_bytes",
        "clustermesh_cluster_identity_info",
    ]
    targets = [
        {"labels": {"job": "apiserver-backend-exporter"}, "health": "up"},
        {"labels": {"job": "kubelet-real-nodes"}, "health": "up"},
        {"labels": {"job": "cadvisor-real-nodes"}, "health": "down"},
        {"labels": {"job": "kwok-resource"}, "health": "up"},
    ]

    report = audit_module.build_audit(
        metric_names,
        targets,
        require_real_node_kubelet=True,
        require_kwok_resource=True,
        identity_series=[
            {
                "run_id": "run-1",
                "cluster_role": "mesh-1",
                "cluster_name": "clustermesh-1",
                "cluster_resource_id": "/subscriptions/sub-1/clustermesh-1",
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "region": "eastus2euap",
                "prometheus_cluster_alias": "run_1_mesh_1",
            }
        ],
    )

    cadvisor = next(
        check
        for check in report["checks"]
        if check["name"] == "target:cadvisor-real-nodes"
    )
    assert report["complete"] is False
    assert cadvisor["status"] == "missing"
