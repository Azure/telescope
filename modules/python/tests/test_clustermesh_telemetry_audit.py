"""Tests for the ClusterMesh telemetry coverage auditor."""

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "telemetry"
    / "audit.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "clustermesh_telemetry_audit",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
audit_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(audit_module)


def test_self_hosted_audit_requires_real_node_targets():
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
    ]
    targets = [
        {"labels": {"job": "kubelet-real-nodes"}, "health": "up"},
        {"labels": {"job": "cadvisor-real-nodes"}, "health": "up"},
    ]

    report = audit_module.build_self_hosted_audit(
        metric_names,
        targets,
        require_real_node_kubelet=True,
    )

    assert report["complete"] is True
    assert {check["status"] for check in report["checks"]} == {"covered"}


def test_managed_audit_requires_every_cluster_for_core_components():
    manifest = {
        "clusters": [
            {"name": "clustermesh-1", "role": "mesh-1"},
            {"name": "clustermesh-2", "role": "mesh-2"},
        ],
        "workspace": {"id": "/subscriptions/s/resourceGroups/r/providers/Microsoft.Monitor/accounts/a"},
    }
    jobs = [
        "controlplane-apiserver",
        "controlplane-etcd",
        "controlplane-kube-scheduler",
        "controlplane-kube-controller-manager",
    ]
    up_series = [
        {"job": job, "cluster": cluster}
        for job in jobs
        for cluster in ("clustermesh-1", "clustermesh-2")
    ]
    process_series = [
        {"job": job, "cluster": cluster}
        for job in jobs
        for cluster in ("clustermesh-1", "clustermesh-2")
    ]
    series = {
        "up": up_series,
        "apiserver_request_total": [
            item for item in up_series if item["job"] == "controlplane-apiserver"
        ],
        "etcd_server_has_leader": [
            item for item in up_series if item["job"] == "controlplane-etcd"
        ],
        "scheduler_schedule_attempts_total": [
            item
            for item in up_series
            if item["job"] == "controlplane-kube-scheduler"
        ],
        "workqueue_depth": [
            item
            for item in up_series
            if item["job"] == "controlplane-kube-controller-manager"
        ],
        "process_cpu_seconds_total": process_series,
        "process_resident_memory_bytes": process_series,
    }
    metric_names = [
        "apiserver_request_total",
        "etcd_server_has_leader",
        "scheduler_schedule_attempts_total",
        "workqueue_depth",
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
    ]

    report = audit_module.build_managed_audit(metric_names, series, manifest)

    assert report["complete"] is True
    required = [check for check in report["checks"] if check["required"]]
    assert all(check["status"] == "covered" for check in required)


def test_managed_audit_reports_missing_scheduler_cluster():
    manifest = {
        "clusters": [
            {"name": "clustermesh-1", "role": "mesh-1"},
            {"name": "clustermesh-2", "role": "mesh-2"},
        ],
    }
    jobs = [
        "controlplane-apiserver",
        "controlplane-etcd",
        "controlplane-kube-controller-manager",
    ]
    up_series = [
        {"job": job, "cluster": cluster}
        for job in jobs
        for cluster in ("clustermesh-1", "clustermesh-2")
    ]
    up_series.append(
        {"job": "controlplane-kube-scheduler", "cluster": "clustermesh-1"}
    )
    process_series = list(up_series)
    series = {
        "up": up_series,
        "apiserver_request_total": [
            item for item in up_series if item["job"] == "controlplane-apiserver"
        ],
        "etcd_server_has_leader": [
            item for item in up_series if item["job"] == "controlplane-etcd"
        ],
        "scheduler_schedule_attempts_total": [
            item
            for item in up_series
            if item["job"] == "controlplane-kube-scheduler"
        ],
        "workqueue_depth": [
            item
            for item in up_series
            if item["job"] == "controlplane-kube-controller-manager"
        ],
        "process_cpu_seconds_total": process_series,
        "process_resident_memory_bytes": process_series,
    }

    report = audit_module.build_managed_audit([], series, manifest)

    scheduler = next(
        check for check in report["checks"] if check["name"] == "kube-scheduler"
    )
    cpu = next(
        check
        for check in report["checks"]
        if check["name"] == "resource:process_cpu_seconds_total"
    )
    assert report["complete"] is False
    assert scheduler["missing_target_clusters"] == ["mesh-2"]
    assert scheduler["missing_metric_clusters"] == ["mesh-2"]
    assert "kube-scheduler:mesh-2" in cpu["missing_targets"]


def test_managed_audit_uses_run_unique_cluster_alias():
    manifest = {
        "clusters": [
            {
                "name": "clustermesh-1",
                "role": "mesh-1",
                "prometheus_cluster_alias": "73076-abc-mesh-1",
            },
        ],
    }
    jobs = [
        "controlplane-apiserver",
        "controlplane-etcd",
        "controlplane-kube-scheduler",
        "controlplane-kube-controller-manager",
    ]
    series = [
        {"job": job, "cluster": "73076-abc-mesh-1"}
        for job in jobs
    ]
    series_by_metric = {
        "up": series,
        "apiserver_request_total": [
            item for item in series if item["job"] == "controlplane-apiserver"
        ],
        "etcd_server_has_leader": [
            item for item in series if item["job"] == "controlplane-etcd"
        ],
        "scheduler_schedule_attempts_total": [
            item
            for item in series
            if item["job"] == "controlplane-kube-scheduler"
        ],
        "workqueue_depth": [
            item
            for item in series
            if item["job"] == "controlplane-kube-controller-manager"
        ],
        "process_cpu_seconds_total": series,
        "process_resident_memory_bytes": series,
    }

    report = audit_module.build_managed_audit([], series_by_metric, manifest)

    assert report["complete"] is True


def test_managed_audit_rejects_up_without_component_metrics():
    manifest = {
        "clusters": [
            {"name": "clustermesh-1", "role": "mesh-1"},
        ],
    }
    up_series = [
        {"job": definition["job"], "cluster": "clustermesh-1"}
        for definition in audit_module.MANAGED_COMPONENTS.values()
        if definition["required"]
    ]

    report = audit_module.build_managed_audit(
        ["up"],
        {"up": up_series},
        manifest,
    )

    assert report["complete"] is False
    required_components = [
        check
        for check in report["checks"]
        if check["required"] and not check["name"].startswith("resource:")
    ]
    assert all(check["status"] == "missing" for check in required_components)
