"""Tests for the ClusterMesh telemetry coverage auditor."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


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


def identity_series(manifest):
    series = []
    for cluster in manifest["clusters"]:
        resource_group = cluster.get("rg", f"rg-{cluster['role']}")
        resource_id = cluster.get(
            "id",
            f"/subscriptions/sub-1/resourceGroups/{resource_group}/providers/"
            "Microsoft.ContainerService/managedClusters/"
            f"{cluster['name']}",
        )
        series.append(
            {
                "run_id": manifest.get("run_id", "run-1"),
                "cluster_role": cluster["role"],
                "cluster_name": cluster["name"],
                "cluster_resource_id": resource_id,
                "subscription_id": "sub-1",
                "resource_group": resource_group,
                "region": manifest.get("region", "eastus2euap"),
                "prometheus_cluster_alias": cluster.get(
                    "prometheus_cluster_alias",
                    cluster["name"],
                ),
            }
        )
    return series


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
        "clustermesh_cluster_identity_info": identity_series(manifest),
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


def test_managed_audit_queries_each_cluster_workspace(tmp_path, monkeypatch):
    clusters = [
        {
            "name": "clustermesh-1",
            "role": "mesh-1",
            "rg": "run-rg",
            "id": "cluster-1",
            "prometheus_cluster_alias": "run_mesh_1",
            "workspace": {
                "name": "amw-mesh-1",
                "id": "amw-1",
                "prometheus_query_endpoint": "https://amw-1.example",
            },
        },
        {
            "name": "clustermesh-2",
            "role": "mesh-2",
            "rg": "run-rg",
            "id": "cluster-2",
            "prometheus_cluster_alias": "run_mesh_2",
            "workspace": {
                "name": "amw-mesh-2",
                "id": "amw-2",
                "prometheus_query_endpoint": "https://amw-2.example",
            },
        },
    ]
    manifest = {
        "schema_version": 2,
        "run_id": "run",
        "region": "eastus2euap",
        "workspace": {"mode": "per-cluster"},
        "workspaces": [cluster["workspace"] for cluster in clusters],
        "clusters": clusters,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    calls = []

    def fake_get(endpoint, path, params=None, scope=""):
        calls.append((endpoint, path, scope))
        cluster = clusters[0] if "amw-1" in endpoint else clusters[1]
        alias = cluster["prometheus_cluster_alias"]
        jobs = [
            "controlplane-apiserver",
            "controlplane-etcd",
            "controlplane-kube-scheduler",
            "controlplane-kube-controller-manager",
        ]
        if path.endswith("/label/__name__/values"):
            return [
                "apiserver_request_total",
                "apiserver_flowcontrol_rejected_requests_total",
                "etcd_server_has_leader",
                "etcd_mvcc_db_total_size_in_bytes",
                "scheduler_schedule_attempts_total",
                "leader_election_master_status",
                "workqueue_depth",
                "clustermesh_cluster_identity_info",
            ]
        metric_name = next(
            value.split('"')[1]
            for key, value in params
            if key == "match[]"
        )
        if metric_name == "up":
            return [{"job": job, "cluster": alias} for job in jobs]
        if metric_name == "clustermesh_cluster_identity_info":
            return identity_series(
                {
                    "run_id": "run",
                    "region": "eastus2euap",
                    "clusters": [cluster],
                }
            )
        job_by_metric = {
            "apiserver_request_total": "controlplane-apiserver",
            "apiserver_flowcontrol_rejected_requests_total": (
                "controlplane-apiserver"
            ),
            "etcd_server_has_leader": "controlplane-etcd",
            "etcd_mvcc_db_total_size_in_bytes": "controlplane-etcd",
            "scheduler_schedule_attempts_total": (
                "controlplane-kube-scheduler"
            ),
            "leader_election_master_status": (
                "controlplane-kube-scheduler"
            ),
            "workqueue_depth": "controlplane-kube-controller-manager",
        }
        job = job_by_metric.get(metric_name)
        return [{"job": job, "cluster": alias}] if job else []

    monkeypatch.setattr(audit_module, "_http_prometheus_get", fake_get)
    report = audit_module.run_managed(
        SimpleNamespace(
            manifest=str(manifest_path),
            start="2026-07-19T00:00:00Z",
            end="2026-07-19T01:00:00Z",
            endpoint="",
            resource_scope="",
        )
    )

    assert report["schema_version"] == 2
    assert report["complete"] is True
    assert {item["role"] for item in report["cluster_reports"]} == {
        "mesh-1",
        "mesh-2",
    }
    assert {
        (endpoint, scope)
        for endpoint, _, scope in calls
    } == {
        ("https://amw-1.example", "cluster-1"),
        ("https://amw-2.example", "cluster-2"),
    }


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
        "clustermesh_cluster_identity_info": identity_series(manifest),
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
        "clustermesh_cluster_identity_info": identity_series(manifest),
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
        {
            "up": up_series,
            "clustermesh_cluster_identity_info": identity_series(manifest),
        },
        manifest,
    )

    assert report["complete"] is False
    required_components = [
        check
        for check in report["checks"]
        if (
            check["name"] in audit_module.MANAGED_COMPONENTS
            and audit_module.MANAGED_COMPONENTS[check["name"]]["required"]
        )
    ]
    assert all(check["status"] == "missing" for check in required_components)


def test_managed_audit_requires_cluster_identity_series():
    manifest = {
        "clusters": [
            {"name": "clustermesh-1", "role": "mesh-1"},
        ],
    }

    report = audit_module.build_managed_audit([], {}, manifest)

    identity = next(
        check
        for check in report["checks"]
        if check["name"] == "cluster-identity"
    )
    assert identity["status"] == "missing"
    assert identity["missing_clusters"] == ["mesh-1"]
