"""Tests for the scenario cleanup reconciler (scenario_cleanup_reconcile.py).

Uses a small in-memory fake `kubectl` (monkeypatching `subprocess.run` inside
the reconciler module) instead of a real cluster, consistent with how
test_clustermesh_mock_layer_reconcile.py fakes its kubectl layer.
"""

import importlib.util
import json
import types
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "scenario_cleanup_reconcile.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "scenario_cleanup_reconcile",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
reconciler = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(reconciler)


# ---------------------------------------------------------------------------
# Fake kubectl: a tiny in-memory cluster driven purely by the `subprocess.run`
# calls the reconciler issues (get namespaces/objects -o json, existence
# probes, and delete).
# ---------------------------------------------------------------------------

def _completed(stdout):
    return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _failed(stderr):
    return types.SimpleNamespace(returncode=1, stdout="", stderr=stderr)


def _namespace_of(cmd):
    if "-n" in cmd:
        return cmd[cmd.index("-n") + 1]
    return None


class FakeCleanupCluster:
    """Minimal fake standing in for a real apiserver across cleanup attempts."""

    def __init__(self, namespaces=("monitoring",), transient_get_failures=0, stuck_namespaces=()):
        self.namespaces = set(namespaces)
        self.acns_cnl_present = False
        self.acns_cnm_present = False
        self.monitoring_objects = []  # list of (kind, name)
        self.cluster_rbac_objects = []  # list of (kind, name)
        self.monitoring_discovered_types = []
        self.transient_get_failures = transient_get_failures
        self.stuck_namespaces = set(stuck_namespaces)
        self.delete_calls = []

    def add_namespace(self, name):
        self.namespaces.add(name)

    def add_acns(self, cnl=True, cnm=True, namespace=True):
        self.acns_cnl_present = cnl
        self.acns_cnm_present = cnm
        if namespace:
            self.namespaces.add(reconciler.ACNS_NAMESPACE)

    def add_monitoring_object(self, kind, name):
        self.monitoring_objects.append((kind, name))

    def add_rbac_object(self, kind, name):
        self.cluster_rbac_objects.append((kind, name))

    def run(self, cmd, input=None, capture_output=True, text=True,  # pylint: disable=redefined-builtin
             timeout=None, check=False):
        del input, capture_output, text, timeout, check  # unused; fake honors them implicitly
        if "api-resources" in cmd:
            body = "\n".join(self.monitoring_discovered_types)
            return _completed(body + ("\n" if body else ""))
        if "get" in cmd:
            if self.transient_get_failures > 0:
                self.transient_get_failures -= 1
                return _failed("transient apiserver error")
            get_idx = cmd.index("get")
            rest = cmd[get_idx + 1:]
            has_json = "-o" in rest and "json" in rest
            namespace = _namespace_of(cmd)
            if has_json:
                resource_arg = rest[0]
                if resource_arg == "namespaces":
                    items = [{"metadata": {"name": name}} for name in sorted(self.namespaces)]
                    return _completed(json.dumps({"items": items}))
                if namespace == reconciler.MONITORING_NAMESPACE:
                    if reconciler.MONITORING_NAMESPACE not in self.namespaces:
                        return _failed(
                            'Error from server (NotFound): namespaces "monitoring" not found'
                        )
                    items = [
                        {"kind": kind, "metadata": {"name": name}}
                        for kind, name in self.monitoring_objects
                    ]
                    return _completed(json.dumps({"items": items}))
                if resource_arg.startswith("clusterroles"):
                    items = [
                        {"kind": kind, "metadata": {"name": name}}
                        for kind, name in self.cluster_rbac_objects
                    ]
                    return _completed(json.dumps({"items": items}))
                raise AssertionError(f"unexpected json get: {cmd}")
            # Existence probe: get <kind> <name> (no -o json).
            kind, name = rest[0], rest[1]
            if kind == "namespace":
                if name in self.namespaces:
                    return _completed("")
                return _failed(f'Error from server (NotFound): namespaces "{name}" not found')
            if kind == "containernetworklog":
                if self.acns_cnl_present:
                    return _completed("")
                return _failed(
                    f'Error from server (NotFound): containernetworklogs.acn.azure.com "{name}" not found'
                )
            if kind == "containernetworkmetric":
                if self.acns_cnm_present:
                    return _completed("")
                return _failed(
                    f'Error from server (NotFound): containernetworkmetrics.acn.azure.com "{name}" not found'
                )
            raise AssertionError(f"unexpected existence probe: {cmd}")
        if "delete" in cmd:
            del_idx = cmd.index("delete")
            kind, name = cmd[del_idx + 1], cmd[del_idx + 2]
            namespace = _namespace_of(cmd)
            self.delete_calls.append((kind, name, namespace))
            if kind == "namespace":
                if name in self.stuck_namespaces:
                    pass  # simulate a namespace stuck Terminating (finalizer) -- never removed
                else:
                    self.namespaces.discard(name)
            elif kind == "containernetworklog":
                self.acns_cnl_present = False
            elif kind == "containernetworkmetric":
                self.acns_cnm_present = False
            else:
                self.monitoring_objects = [
                    (k, n) for (k, n) in self.monitoring_objects
                    if not (k.lower() == kind and n == name)
                ]
                self.cluster_rbac_objects = [
                    (k, n) for (k, n) in self.cluster_rbac_objects
                    if not (k.lower() == kind and n == name)
                ]
            return _completed("")
        raise AssertionError(f"unexpected fake kubectl invocation: {cmd}")


def _reconcile(monkeypatch, cluster, scenario, **kwargs):
    monkeypatch.setattr(reconciler.subprocess, "run", cluster.run)
    namespace_prefix = reconciler.SCENARIO_NAMESPACE_PREFIXES[scenario]
    defaults = {
        "attempts": 3,
        "settle_seconds": 0,
        "request_timeout_seconds": 5,
    }
    defaults.update(kwargs)
    return reconciler.reconcile_cluster("mesh-1", "/kube/mesh-1.config", namespace_prefix, **defaults)


# ---------------------------------------------------------------------------
# 1. Healthy no-op
# ---------------------------------------------------------------------------

def test_healthy_cluster_is_a_noop(monkeypatch):
    cluster = FakeCleanupCluster()

    result = _reconcile(monkeypatch, cluster, "event-throughput")

    assert result["status"] == "ok"
    assert result["no_op"] is True
    assert result["deleted"] == []
    assert result["remaining"] == []
    assert result["errors"] == []
    assert not cluster.delete_calls


# ---------------------------------------------------------------------------
# 2. Only the current scenario's namespace prefix is deleted
# ---------------------------------------------------------------------------

def test_only_current_scenario_prefix_deleted(monkeypatch):
    cluster = FakeCleanupCluster()
    cluster.add_namespace("clustermesh-et")
    cluster.add_namespace("clustermesh-et-worker-1")

    result = _reconcile(monkeypatch, cluster, "event-throughput")

    assert result["status"] == "ok"
    assert result["no_op"] is False
    assert set(result["deleted"]) == {"Namespace/clustermesh-et", "Namespace/clustermesh-et-worker-1"}
    assert result["remaining"] == []
    assert "clustermesh-et" not in cluster.namespaces
    assert "clustermesh-et-worker-1" not in cluster.namespaces


def test_namespace_lookalike_without_hyphen_is_not_matched(monkeypatch):
    """"clustermesh-etcetera" is NOT "clustermesh-et" or "clustermesh-et-*"."""
    cluster = FakeCleanupCluster()
    cluster.add_namespace("clustermesh-etcetera")

    result = _reconcile(monkeypatch, cluster, "event-throughput")

    assert result["status"] == "ok"
    assert result["no_op"] is True
    assert "clustermesh-etcetera" in cluster.namespaces


# ---------------------------------------------------------------------------
# 3. Unrelated clustermesh-* prefix (a different scenario) is untouched
# ---------------------------------------------------------------------------

def test_unrelated_clustermesh_prefix_untouched(monkeypatch):
    cluster = FakeCleanupCluster()
    cluster.add_namespace("clustermesh-et")
    cluster.add_namespace("clustermesh-pcc-1")  # pod-churn-combined's own namespace

    result = _reconcile(monkeypatch, cluster, "event-throughput")

    assert result["status"] == "ok"
    assert result["deleted"] == ["Namespace/clustermesh-et"]
    assert "clustermesh-pcc-1" in cluster.namespaces
    assert not any(name == "clustermesh-pcc-1" for _, name, _ in cluster.delete_calls)


# ---------------------------------------------------------------------------
# 4. Exact ACNS shared residue is deleted
# ---------------------------------------------------------------------------

def test_acns_exact_resources_deleted(monkeypatch):
    cluster = FakeCleanupCluster()
    cluster.add_acns()

    result = _reconcile(monkeypatch, cluster, "isolation")

    assert result["status"] == "ok"
    assert set(result["deleted"]) == {
        "ContainerNetworkLog/clustermesh-scale-acns",
        "ContainerNetworkMetric/container-network-metric",
        "Namespace/acns-telemetry",
    }
    assert cluster.acns_cnl_present is False
    assert cluster.acns_cnm_present is False
    assert reconciler.ACNS_NAMESPACE not in cluster.namespaces


# ---------------------------------------------------------------------------
# 5. Allowlisted monitoring/exporter resources deleted, protected baseline stays
# ---------------------------------------------------------------------------

def test_monitoring_allowlist_deleted_protected_baseline_remains(monkeypatch):
    cluster = FakeCleanupCluster()
    # Scenario-owned, allowlisted -- must be deleted.
    cluster.add_monitoring_object("ConfigMap", "clustermesh-apiserver-config")
    cluster.add_monitoring_object("Service", "hubble-metrics-svc")
    cluster.add_monitoring_object("Deployment", "kvstoremesh-standalone")
    cluster.add_monitoring_object("Pod", "mock-cilium-agent-leftover")
    cluster.add_monitoring_object("Deployment", "apiserver-backend-exporter")
    cluster.add_rbac_object("ClusterRole", "apiserver-backend-exporter-role")
    cluster.add_rbac_object("ClusterRoleBinding", "apiserver-backend-exporter-binding")
    # Protected baseline -- must never be touched even though it lives
    # alongside the scenario-owned objects above.
    cluster.add_monitoring_object("Deployment", "prometheus-operator")
    cluster.add_monitoring_object("StatefulSet", "kube-state-metrics")
    cluster.add_monitoring_object("DaemonSet", "ama-metrics-node")
    cluster.add_monitoring_object("Deployment", "controlplane-apiserver-exporter")
    cluster.add_monitoring_object("ConfigMap", "managed-prometheus-config")
    # Unrelated/unknown -- also never touched (not in any allowlist).
    cluster.add_monitoring_object("ConfigMap", "grafana-dashboards")
    cluster.add_rbac_object("ClusterRole", "cluster-admin")

    result = _reconcile(monkeypatch, cluster, "policy-scale")

    assert result["status"] == "ok"
    assert set(result["deleted"]) == {
        "monitoring/ConfigMap/clustermesh-apiserver-config",
        "monitoring/Service/hubble-metrics-svc",
        "monitoring/Deployment/kvstoremesh-standalone",
        "monitoring/Pod/mock-cilium-agent-leftover",
        "monitoring/Deployment/apiserver-backend-exporter",
        "ClusterRole/apiserver-backend-exporter-role",
        "ClusterRoleBinding/apiserver-backend-exporter-binding",
    }
    remaining_names = {name for _, name in cluster.monitoring_objects}
    assert remaining_names == {
        "prometheus-operator",
        "kube-state-metrics",
        "ama-metrics-node",
        "controlplane-apiserver-exporter",
        "managed-prometheus-config",
        "grafana-dashboards",
    }
    remaining_rbac_names = {name for _, name in cluster.cluster_rbac_objects}
    assert remaining_rbac_names == {"cluster-admin"}


# ---------------------------------------------------------------------------
# 6. Transient API failure is retried, not treated as zero
# ---------------------------------------------------------------------------

def test_transient_api_failure_is_retried(monkeypatch):
    cluster = FakeCleanupCluster(transient_get_failures=1)
    cluster.add_namespace("clustermesh-iso")

    result = _reconcile(monkeypatch, cluster, "isolation", attempts=3, settle_seconds=0)

    assert result["status"] == "ok"
    assert result["attempts_used"] >= 2
    assert result["deleted"] == ["Namespace/clustermesh-iso"]


# ---------------------------------------------------------------------------
# 7. Stuck namespace produces a failure summary (never fabricates success)
# ---------------------------------------------------------------------------

def test_stuck_namespace_produces_failure_summary(monkeypatch):
    cluster = FakeCleanupCluster(stuck_namespaces={"clustermesh-ncc"})
    cluster.add_namespace("clustermesh-ncc")

    result = _reconcile(monkeypatch, cluster, "node-churn-combined", attempts=2, settle_seconds=0)

    assert result["status"] == "failed"
    assert result["remaining"] == ["Namespace/clustermesh-ncc"]
    assert result["errors"]
    assert result["attempts_used"] == 2
    # A delete WAS attempted (best-effort), it just never converged.
    assert any(name == "clustermesh-ncc" for _, name, _ in cluster.delete_calls)


def test_persistent_api_failure_fails_cleanly_without_fabricating_success(monkeypatch):
    """Every gather attempt fails -- result must be failed with remaining=None
    (unknown), never an empty list masquerading as "confirmed clean"."""
    cluster = FakeCleanupCluster(transient_get_failures=99)

    result = _reconcile(monkeypatch, cluster, "isolation", attempts=2, settle_seconds=0)

    assert result["status"] == "failed"
    assert result["remaining"] is None
    assert result["deleted"] == []
    assert result["errors"]


# ---------------------------------------------------------------------------
# 8. Multiple clusters aggregate correctly
# ---------------------------------------------------------------------------

def test_reconcile_all_aggregates_multiple_clusters(monkeypatch, tmp_path):
    ok_role = "mesh-1"
    failed_role = "mesh-2"
    clusters = {
        ok_role: FakeCleanupCluster(),
        failed_role: FakeCleanupCluster(stuck_namespaces={"clustermesh-ub"}),
    }
    clusters[ok_role].add_namespace("clustermesh-ub")
    clusters[failed_role].add_namespace("clustermesh-ub")

    def dispatch(cmd, **kwargs):
        kubeconfig = cmd[cmd.index("--kubeconfig") + 1]
        role = Path(kubeconfig).stem
        return clusters[role].run(cmd, **kwargs)

    monkeypatch.setattr(reconciler.subprocess, "run", dispatch)

    results = reconciler.reconcile_all(
        [
            {"role": ok_role, "kubeconfig": f"/kube/{ok_role}.config"},
            {"role": failed_role, "kubeconfig": f"/kube/{failed_role}.config"},
        ],
        namespace_prefix=reconciler.SCENARIO_NAMESPACE_PREFIXES["upper-bound"],
        max_concurrent=2,
        attempts=2,
        settle_seconds=0,
        request_timeout_seconds=5,
    )

    by_role = {r["role"]: r for r in results}
    assert by_role[ok_role]["status"] == "ok"
    assert by_role[ok_role]["deleted"] == ["Namespace/clustermesh-ub"]
    assert by_role[failed_role]["status"] == "failed"
    assert by_role[failed_role]["remaining"] == ["Namespace/clustermesh-ub"]

    summary_file = tmp_path / "summary.json"
    failed_roles = sorted(r["role"] for r in results if r["status"] != "ok")
    reconciler.write_summary(str(summary_file), {
        "schema_version": 1,
        "success": not failed_roles,
        "total_clusters": len(results),
        "failed_roles": failed_roles,
        "results": sorted(results, key=lambda r: r["role"]),
    })
    written = json.loads(summary_file.read_text(encoding="utf-8"))
    assert written["failed_roles"] == [failed_role]
    assert written["success"] is False


# ---------------------------------------------------------------------------
# 9. Invalid scenario / invalid config fails cleanly (main())
# ---------------------------------------------------------------------------

def test_main_unknown_scenario_fails_cleanly(tmp_path, capsys):
    clusters_file = tmp_path / "clusters.json"
    clusters_file.write_text(
        json.dumps([{"role": "mesh-1", "kubeconfig": "/kube/mesh-1.config"}]),
        encoding="utf-8",
    )
    summary_file = tmp_path / "summary.json"

    rc = reconciler.main([
        "--clusters", str(clusters_file),
        "--scenario", "not-a-real-scenario",
        "--summary-file", str(summary_file),
    ])

    assert rc == 1
    assert not summary_file.exists()
    captured = capsys.readouterr()
    assert "unknown scenario" in captured.err


def test_main_missing_clusters_file_fails_cleanly(tmp_path):
    summary_file = tmp_path / "summary.json"

    rc = reconciler.main([
        "--clusters", str(tmp_path / "does-not-exist.json"),
        "--scenario", "isolation",
        "--summary-file", str(summary_file),
    ])

    assert rc == 1
    assert not summary_file.exists()


def test_main_empty_clusters_array_fails_cleanly(tmp_path):
    clusters_file = tmp_path / "clusters.json"
    clusters_file.write_text("[]", encoding="utf-8")
    summary_file = tmp_path / "summary.json"

    rc = reconciler.main([
        "--clusters", str(clusters_file),
        "--scenario", "isolation",
        "--summary-file", str(summary_file),
    ])

    assert rc == 1
    assert not summary_file.exists()


def test_main_healthy_end_to_end_writes_success_summary(tmp_path, monkeypatch):
    cluster = FakeCleanupCluster()
    monkeypatch.setattr(reconciler.subprocess, "run", cluster.run)
    clusters_file = tmp_path / "clusters.json"
    clusters_file.write_text(
        json.dumps([{"role": "mesh-1", "kubeconfig": "/kube/mesh-1.config"}]),
        encoding="utf-8",
    )
    summary_file = tmp_path / "summary.json"

    rc = reconciler.main([
        "--clusters", str(clusters_file),
        "--scenario", "event-throughput",
        "--summary-file", str(summary_file),
        "--attempts", "2",
        "--settle-seconds", "0",
    ])

    assert rc == 0
    written = json.loads(summary_file.read_text(encoding="utf-8"))
    assert written["schema_version"] == 1
    assert written["success"] is True
    assert written["scenario"] == "event-throughput"
    assert written["namespace_prefix"] == "clustermesh-et"
    assert written["healthy_count"] == 1
    assert written["failed_count"] == 0
