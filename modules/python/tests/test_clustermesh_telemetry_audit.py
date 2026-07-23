"""Tests for the ClusterMesh telemetry coverage auditor."""

import argparse
import importlib.util
import json
import re
import threading
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest


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

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_PATH = REPO_ROOT / "pipelines" / "system" / "new-pipeline-test.yml"


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
            workers=1,
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


def test_managed_audit_accepts_label_stripped_identity_for_exact_scope():
    manifest = {
        "managed_query_scope": "cluster-1",
        "clusters": [
            {
                "id": "cluster-1",
                "name": "clustermesh-1",
                "role": "mesh-1",
            },
        ],
    }
    jobs = [
        "controlplane-apiserver",
        "controlplane-etcd",
        "controlplane-kube-scheduler",
        "controlplane-kube-controller-manager",
    ]
    component_series = [
        {"job": job, "cluster": "clustermesh-1"}
        for job in jobs
    ]
    series = {
        "up": component_series,
        "apiserver_request_total": [component_series[0]],
        "etcd_server_has_leader": [component_series[1]],
        "scheduler_schedule_attempts_total": [component_series[2]],
        "workqueue_depth": [component_series[3]],
        "clustermesh_cluster_identity_info": [
            {"microsoft.amwresourceid": "amw-1"},
        ],
    }

    report = audit_module.build_managed_audit([], series, manifest)

    identity = next(
        check
        for check in report["checks"]
        if check["name"] == "cluster-identity"
    )
    assert report["complete"] is True
    assert identity["status"] == "covered"
    assert identity["coverage_mode"] == {"mesh-1": "resource-scope"}


def test_managed_audit_rejects_label_stripped_identity_without_scope():
    manifest = {
        "clusters": [
            {
                "id": "cluster-1",
                "name": "clustermesh-1",
                "role": "mesh-1",
            },
        ],
    }

    report = audit_module.build_managed_audit(
        [],
        {
            "clustermesh_cluster_identity_info": [
                {"microsoft.amwresourceid": "amw-1"},
            ],
        },
        manifest,
    )

    identity = next(
        check
        for check in report["checks"]
        if check["name"] == "cluster-identity"
    )
    assert identity["status"] == "missing"
    assert identity["missing_clusters"] == ["mesh-1"]


def _schema_v2_manifest(tmp_path, cluster_defs):
    """Build+write a minimal schema-v2 (per-cluster workspace) manifest.

    cluster_defs is a list of (role, endpoint, resource_id) tuples, in the
    intended manifest cluster order.
    """
    clusters = []
    for role, endpoint, resource_id in cluster_defs:
        clusters.append(
            {
                "name": f"clustermesh-{role}",
                "role": role,
                "rg": "run-rg",
                "id": resource_id,
                "prometheus_cluster_alias": f"run_{role}",
                "workspace": {
                    "name": f"amw-{role}",
                    "id": f"amw-id-{role}",
                    "prometheus_query_endpoint": endpoint,
                },
            }
        )
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
    return manifest, manifest_path


def _managed_args(manifest_path, workers):
    return SimpleNamespace(
        manifest=str(manifest_path),
        start="2026-07-19T00:00:00Z",
        end="2026-07-19T01:00:00Z",
        endpoint="",
        resource_scope="",
        workers=workers,
    )


def test_run_managed_workers_execute_concurrently(tmp_path, monkeypatch):
    cluster_count = 4
    manifest, manifest_path = _schema_v2_manifest(
        tmp_path,
        [
            (f"mesh-{i}", f"https://amw-{i}.example", f"cluster-{i}")
            for i in range(cluster_count)
        ],
    )
    # A barrier that requires every worker to arrive before any can proceed.
    # With true bounded concurrency (workers == cluster_count) all 4 threads
    # reach the barrier together; a serial (or under-parallelized) execution
    # would leave threads waiting alone and the barrier would time out.
    barrier = threading.Barrier(cluster_count, timeout=5)

    def fake_run_managed_query(_args, _cluster_manifest, _endpoint, _scope):
        barrier.wait()
        return {"complete": True, "checks": []}

    monkeypatch.setattr(audit_module, "_run_managed_query", fake_run_managed_query)

    report = audit_module.run_managed(
        _managed_args(manifest_path, workers=cluster_count)
    )

    assert report["complete"] is True
    assert len(report["cluster_reports"]) == cluster_count
    del manifest  # unused beyond construction


def test_run_managed_single_worker_does_not_overlap(tmp_path, monkeypatch):
    manifest, manifest_path = _schema_v2_manifest(
        tmp_path,
        [
            ("mesh-0", "https://amw-0.example", "cluster-0"),
            ("mesh-1", "https://amw-1.example", "cluster-1"),
        ],
    )
    barrier = threading.Barrier(2, timeout=0.5)

    def fake_run_managed_query(_args, _cluster_manifest, _endpoint, _scope):
        barrier.wait()
        return {"complete": True, "checks": []}

    monkeypatch.setattr(audit_module, "_run_managed_query", fake_run_managed_query)

    # With workers=1, clusters run strictly one-at-a-time, so the second
    # cluster's call never arrives at the barrier while the first is
    # waiting on it: the barrier times out and raises.
    with pytest.raises(threading.BrokenBarrierError):
        audit_module.run_managed(_managed_args(manifest_path, workers=1))
    del manifest


def test_run_managed_preserves_manifest_cluster_order(tmp_path, monkeypatch):
    manifest, manifest_path = _schema_v2_manifest(
        tmp_path,
        [
            ("mesh-a", "https://amw-a.example", "cluster-a"),
            ("mesh-b", "https://amw-b.example", "cluster-b"),
            ("mesh-c", "https://amw-c.example", "cluster-c"),
        ],
    )
    # Sleep durations are deliberately inverted relative to manifest order,
    # so under concurrency the LAST manifest cluster finishes FIRST. If
    # run_managed's ordering depended on completion order rather than
    # manifest order, cluster_reports/checks would come back as c, b, a.
    sleep_by_role = {"mesh-a": 0.3, "mesh-b": 0.15, "mesh-c": 0.0}

    def fake_run_managed_query(_args, cluster_manifest, _endpoint, _scope):
        role = cluster_manifest["clusters"][0]["role"]
        time.sleep(sleep_by_role[role])
        return {
            "complete": True,
            "checks": [
                {"name": "check", "status": "covered", "required": True}
            ],
        }

    monkeypatch.setattr(audit_module, "_run_managed_query", fake_run_managed_query)

    report = audit_module.run_managed(
        _managed_args(manifest_path, workers=3)
    )

    assert [item["role"] for item in report["cluster_reports"]] == [
        "mesh-a",
        "mesh-b",
        "mesh-c",
    ]
    assert [check["cluster_role"] for check in report["checks"]] == [
        "mesh-a",
        "mesh-b",
        "mesh-c",
    ]
    del manifest


def test_run_managed_propagates_worker_exception(tmp_path, monkeypatch):
    manifest, manifest_path = _schema_v2_manifest(
        tmp_path,
        [
            ("mesh-1", "https://amw-1.example", "cluster-1"),
            ("mesh-2", "https://amw-2.example", "cluster-2"),
        ],
    )

    def fake_run_managed_query(_args, cluster_manifest, _endpoint, _scope):
        role = cluster_manifest["clusters"][0]["role"]
        if role == "mesh-2":
            raise RuntimeError("simulated managed Prometheus query failure")
        return {"complete": True, "checks": []}

    monkeypatch.setattr(audit_module, "_run_managed_query", fake_run_managed_query)

    with pytest.raises(
        RuntimeError, match="simulated managed Prometheus query failure"
    ):
        audit_module.run_managed(_managed_args(manifest_path, workers=2))
    del manifest


def test_run_managed_uses_exact_scope_for_shared_workspace_clusters(
    tmp_path, monkeypatch
):
    shared_endpoint = "https://amw-shared.example"
    manifest, manifest_path = _schema_v2_manifest(
        tmp_path,
        [
            ("mesh-1", shared_endpoint, "cluster-1"),
            ("mesh-2", shared_endpoint, "cluster-2"),
        ],
    )
    calls = []
    lock = threading.Lock()

    def fake_get(endpoint, path, params=None, scope=""):
        with lock:
            calls.append((endpoint, scope))
        del path, params
        return []

    monkeypatch.setattr(audit_module, "_http_prometheus_get", fake_get)

    report = audit_module.run_managed(
        _managed_args(manifest_path, workers=2)
    )

    assert report["schema_version"] == 2
    # Both clusters share the SAME workspace endpoint, but concurrency must
    # not leak or mix up the per-cluster x-ms-azure-scoping resource id: all
    # calls hit the shared endpoint, tagged with exactly the right scope.
    endpoints = {endpoint for endpoint, _ in calls}
    assert endpoints == {shared_endpoint}
    expected_calls_per_cluster = 1 + len(audit_module.MANAGED_SERIES_METRICS)
    counts = Counter(scope for _, scope in calls)
    assert counts == {
        "cluster-1": expected_calls_per_cluster,
        "cluster-2": expected_calls_per_cluster,
    }
    del manifest


def test_positive_int_rejects_non_positive_and_non_numeric_values():
    for bad_value in ("0", "-1", "abc", "1.5", ""):
        with pytest.raises(argparse.ArgumentTypeError):
            audit_module._positive_int(bad_value)  # pylint: disable=protected-access


def test_positive_int_accepts_positive_integers():
    assert audit_module._positive_int("1") == 1  # pylint: disable=protected-access
    assert audit_module._positive_int("10") == 10  # pylint: disable=protected-access


def test_managed_parser_rejects_invalid_workers(capsys):
    with pytest.raises(SystemExit):
        audit_module.parse_args(
            [
                "managed",
                "--manifest",
                "manifest.json",
                "--start",
                "s",
                "--end",
                "e",
                "--output-prefix",
                "out",
                "--workers",
                "0",
            ]
        )
    captured = capsys.readouterr()
    assert "workers" in captured.err


def test_managed_parser_workers_defaults_to_one():
    args = audit_module.parse_args(
        [
            "managed",
            "--manifest",
            "manifest.json",
            "--start",
            "s",
            "--end",
            "e",
            "--output-prefix",
            "out",
        ]
    )
    assert args.workers == 1


def _pipeline_stage_block(pipeline_text, stage_name):
    pattern = re.compile(
        rf"- stage:\s*{re.escape(stage_name)}\b.*?(?=\n\s*- stage:|\Z)",
        re.DOTALL,
    )
    match = pattern.search(pipeline_text)
    assert match, f"stage {stage_name} not found in {PIPELINE_PATH}"
    return match.group(0)


def test_pipeline_sets_static_managed_prometheus_audit_workers():
    pipeline_text = PIPELINE_PATH.read_text(encoding="utf-8")

    n2_block = _pipeline_stage_block(
        pipeline_text, "azure_canadacentral_n2_mock_full_telemetry"
    )
    n100_block = _pipeline_stage_block(
        pipeline_text, "azure_canadacentral_n100_mock"
    )

    n2_match = re.search(
        r'AKS_MANAGED_PROMETHEUS_AUDIT_WORKERS:\s*"(\d+)"', n2_block
    )
    n100_match = re.search(
        r'AKS_MANAGED_PROMETHEUS_AUDIT_WORKERS:\s*"(\d+)"', n100_block
    )
    assert n2_match is not None, "n2 stage missing AKS_MANAGED_PROMETHEUS_AUDIT_WORKERS"
    assert n100_match is not None, (
        "n100 stage missing AKS_MANAGED_PROMETHEUS_AUDIT_WORKERS"
    )
    assert n2_match.group(1) == "2"
    assert n100_match.group(1) == "10"
