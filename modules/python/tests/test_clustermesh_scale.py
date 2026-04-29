"""Unit tests for the clustermesh-scale CL2 harness.

Target module: modules/python/clusterloader2/clustermesh-scale/scale.py.
Mirrors tests/test_network_scale.py — the module is loaded via importlib because
the ``clustermesh-scale`` directory contains a hyphen and is not a valid Python
package name.

The key invariant under test is multi-cluster attribution: when collect_clusterloader2
is called once per cluster (as the pipeline's collect.yml does), the resulting JSONL
rows must each carry distinct cluster identity while sharing run-level fields. Without
this, downstream Kusto queries cannot group/filter by cluster across the mesh.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "scale.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "clusterloader2_clustermesh_scale", MODULE_PATH
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
clustermesh_scale_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(clustermesh_scale_module)

configure_clusterloader2 = clustermesh_scale_module.configure_clusterloader2
collect_clusterloader2 = clustermesh_scale_module.collect_clusterloader2
main = clustermesh_scale_module.main

MOCK_REPORT_ROOT = os.path.join(
    os.path.dirname(__file__), "mock_data", "clustermesh-scale", "report"
)


class TestConfigureClustermeshScale(unittest.TestCase):
    """configure_clusterloader2 writes the CL2 overrides file the pipeline expects."""

    def test_overrides_file_contents(self):
        """Every CL2_* knob the config template reads must appear in the overrides file."""
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name

        try:
            configure_clusterloader2(
                namespaces=2,
                deployments_per_namespace=3,
                replicas_per_deployment=4,
                operation_timeout="20m",
                override_file=tmp_path,
            )

            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Prometheus knobs — must match what the CL2 config template reads so
            # cilium-agent + cilium-operator are scraped on every cluster.
            self.assertIn("CL2_PROMETHEUS_TOLERATE_MASTER: true", content)
            self.assertIn("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 100.0", content)
            self.assertIn("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 100.0", content)
            self.assertIn("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0", content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true", content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true", content)
            self.assertIn('CL2_PROMETHEUS_NODE_SELECTOR: "prometheus: \\"true\\""', content)
            self.assertIn("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m", content)

            # Topology knobs round-tripped from arguments.
            self.assertIn("CL2_NAMESPACES: 2", content)
            self.assertIn("CL2_DEPLOYMENTS_PER_NAMESPACE: 3", content)
            self.assertIn("CL2_REPLICAS_PER_DEPLOYMENT: 4", content)
            self.assertIn("CL2_OPERATION_TIMEOUT: 20m", content)
        finally:
            os.remove(tmp_path)

    def test_overrides_file_timeout_passthrough(self):
        """Caller-provided operation_timeout flows through unchanged (no clamping)."""
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="45m",
                override_file=tmp_path,
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                self.assertIn("CL2_OPERATION_TIMEOUT: 45m", f.read())
        finally:
            os.remove(tmp_path)


class TestCollectSingleCluster(unittest.TestCase):
    """collect_clusterloader2 emits one JSONL row per call, tagged with cluster identity."""

    def _collect(self, *, cluster_name, cluster_count=2, mesh_size=2, report_subdir="mesh-1"):
        result_file = tempfile.mktemp(suffix=".jsonl")
        collect_clusterloader2(
            cl2_report_dir=os.path.join(MOCK_REPORT_ROOT, report_subdir),
            cloud_info=json.dumps({"cloud": "azure", "region": "eastus2"}),
            run_id="test-run-123",
            run_url="http://example.com/run123",
            result_file=result_file,
            test_type="unit-test",
            start_timestamp="2026-04-28T15:00:00Z",
            cluster_name=cluster_name,
            cluster_count=cluster_count,
            mesh_size=mesh_size,
            namespaces=2,
            deployments_per_namespace=3,
            replicas_per_deployment=4,
            trigger_reason="Manual",
        )
        return result_file

    def test_collect_creates_result_file(self):
        """collect_clusterloader2 writes a non-empty JSONL with run-level fields."""
        result_file = self._collect(cluster_name="mesh-1")
        try:
            self.assertTrue(os.path.exists(result_file))
            with open(result_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertGreater(len(content), 0)
            lines = content.strip().split("\n")
            self.assertGreaterEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["status"], "success")
            self.assertEqual(row["run_id"], "test-run-123")
            self.assertEqual(row["test_type"], "unit-test")
            self.assertEqual(row["start_timestamp"], "2026-04-28T15:00:00Z")
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)

    def test_collect_attributes_cluster_identity(self):
        """Cluster identity is propagated to BOTH top-level and test_details, per Kusto schema."""
        result_file = self._collect(cluster_name="mesh-1", cluster_count=2)
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                row = json.loads(f.read().strip().split("\n")[0])
            self.assertEqual(row["cluster"], "mesh-1")
            self.assertEqual(row["cluster_count"], 2)
            self.assertEqual(row["test_details"]["cluster"], "mesh-1")
            self.assertEqual(row["test_details"]["cluster_count"], 2)
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)

    def test_collect_computes_pods_per_cluster(self):
        """pods_per_cluster = namespaces * deployments * replicas (2 * 3 * 4 = 24)."""
        result_file = self._collect(cluster_name="mesh-1")
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                row = json.loads(f.read().strip().split("\n")[0])
            self.assertEqual(row["test_details"]["pods_per_cluster"], 24)
            self.assertEqual(row["namespaces"], 2)
            self.assertEqual(row["deployments_per_namespace"], 3)
            self.assertEqual(row["replicas_per_deployment"], 4)
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)

    def test_collect_emits_mesh_size_independent_of_cluster_count(self):
        """mesh_size (configured target) and cluster_count (observed) must be distinct fields.

        Querying ``mesh_size != cluster_count`` in Kusto is how we surface
        partial-mesh runs — a Fleet member that failed to join would manifest
        as a smaller observed cluster_count than the configured mesh_size.
        Both fields must be present at top level AND in test_details.
        """
        result_file = self._collect(cluster_name="mesh-1", cluster_count=4, mesh_size=5)
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                row = json.loads(f.read().strip().split("\n")[0])
            self.assertEqual(row["mesh_size"], 5)
            self.assertEqual(row["cluster_count"], 4)
            self.assertEqual(row["test_details"]["mesh_size"], 5)
            self.assertEqual(row["test_details"]["cluster_count"], 4)
            self.assertNotEqual(row["mesh_size"], row["cluster_count"])
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)


class TestCollectMultiCluster(unittest.TestCase):
    """The multi-cluster aggregation invariant — the reason this scenario exists.

    collect.yml calls scale.py once per cluster and concatenates per-cluster JSONL
    files into a single TEST_RESULTS_FILE. The resulting stream MUST have:
      * one logical row per cluster
      * each row's `cluster` field distinct
      * `cluster_count` consistent across rows
      * `run_id` consistent across rows (same pipeline run)
    Without this, downstream Kusto cannot group/filter by cluster.
    """

    def _collect(self, *, cluster_name, report_subdir):
        result_file = tempfile.mktemp(suffix=f".{cluster_name}.jsonl")
        collect_clusterloader2(
            cl2_report_dir=os.path.join(MOCK_REPORT_ROOT, report_subdir),
            cloud_info=json.dumps({"cloud": "azure"}),
            run_id="multi-cluster-run",
            run_url="http://example.com/multi",
            result_file=result_file,
            test_type="unit-test",
            start_timestamp="2026-04-28T15:00:00Z",
            cluster_name=cluster_name,
            cluster_count=2,
            mesh_size=2,
            namespaces=1,
            deployments_per_namespace=1,
            replicas_per_deployment=1,
            trigger_reason="",
        )
        return result_file

    def test_two_clusters_aggregate_with_distinct_attribution(self):
        """Aggregating per-cluster JSONLs yields rows with distinct cluster identity."""
        f1 = self._collect(cluster_name="mesh-1", report_subdir="mesh-1")
        f2 = self._collect(cluster_name="mesh-2", report_subdir="mesh-2")
        try:
            # Mirror what collect.yml does: cat per-cluster files into one stream.
            aggregated = ""
            for path in (f1, f2):
                with open(path, "r", encoding="utf-8") as f:
                    aggregated += f.read()

            rows = [json.loads(line) for line in aggregated.strip().split("\n") if line]
            # Each per-cluster collect emits at least one row (overall testsuite line).
            self.assertGreaterEqual(len(rows), 2)

            clusters_seen = {row["cluster"] for row in rows}
            self.assertEqual(clusters_seen, {"mesh-1", "mesh-2"})

            # Run-level fields must be identical across all rows.
            run_ids = {row["run_id"] for row in rows}
            cluster_counts = {row["cluster_count"] for row in rows}
            mesh_sizes = {row["mesh_size"] for row in rows}
            self.assertEqual(run_ids, {"multi-cluster-run"})
            self.assertEqual(cluster_counts, {2})
            # mesh_size is a run-level constant — it must be identical across
            # every per-cluster row in the aggregated stream.
            self.assertEqual(mesh_sizes, {2})
        finally:
            for path in (f1, f2):
                if os.path.exists(path):
                    os.remove(path)


class TestCollectFailureStatus(unittest.TestCase):
    """A junit.xml with failures>0 must produce status=failure (no silent green)."""

    def test_failure_in_junit_propagates_to_status(self):
        """A junit testsuite with failures>0 must surface as status=failure in the JSONL."""
        result_file = tempfile.mktemp(suffix=".jsonl")
        try:
            collect_clusterloader2(
                cl2_report_dir=os.path.join(MOCK_REPORT_ROOT, "mesh-fail"),
                cloud_info="",
                run_id="fail-run",
                run_url="",
                result_file=result_file,
                test_type="unit-test",
                start_timestamp="2026-04-28T15:00:00Z",
                cluster_name="mesh-fail",
                cluster_count=2,
                mesh_size=2,
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                trigger_reason="",
            )
            with open(result_file, "r", encoding="utf-8") as f:
                row = json.loads(f.read().strip().split("\n")[0])
            self.assertEqual(row["status"], "failure")
            self.assertEqual(row["cluster"], "mesh-fail")
            details = row["test_details"]["details"]
            self.assertIsNotNone(details)
            self.assertIn("timeout", json.dumps(details).lower())
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)


class TestMainArgumentParsing(unittest.TestCase):
    """main() dispatches subcommands to the right function with the right args."""

    @patch.object(clustermesh_scale_module, "configure_clusterloader2")
    def test_configure_command_parsing(self, mock_configure):
        """`configure` subcommand wires CLI args through to configure_clusterloader2."""
        test_args = [
            "clustermesh-scale/scale.py",
            "configure",
            "--namespaces", "2",
            "--deployments-per-namespace", "3",
            "--replicas-per-deployment", "4",
            "--operation-timeout", "20m",
            "--cl2_override_file", "/tmp/overrides.yaml",
        ]
        with patch.object(sys, "argv", test_args):
            main()
        mock_configure.assert_called_once_with(2, 3, 4, "20m", "/tmp/overrides.yaml")

    @patch.object(clustermesh_scale_module, "execute_clusterloader2")
    def test_execute_command_parsing(self, mock_execute):
        """`execute` subcommand wires CLI args through to execute_clusterloader2."""
        test_args = [
            "clustermesh-scale/scale.py",
            "execute",
            "--cl2-image", "ghcr.io/azure/clusterloader2:v20250513",
            "--cl2-config-dir", "/path/to/config",
            "--cl2-report-dir", "/path/to/report",
            "--cl2-config-file", "config.yaml",
            "--kubeconfig", "/path/to/kubeconfig",
            "--provider", "aks",
        ]
        with patch.object(sys, "argv", test_args):
            main()
        mock_execute.assert_called_once_with(
            "ghcr.io/azure/clusterloader2:v20250513",
            "/path/to/config",
            "/path/to/report",
            "config.yaml",
            "/path/to/kubeconfig",
            "aks",
        )

    @patch.object(clustermesh_scale_module, "collect_clusterloader2")
    def test_collect_command_parsing(self, mock_collect):
        """`collect` subcommand wires CLI args through to collect_clusterloader2."""
        test_args = [
            "clustermesh-scale/scale.py",
            "collect",
            "--cl2_report_dir", "/path/to/report",
            "--cloud_info", "{}",
            "--run_id", "abc",
            "--run_url", "http://example.com",
            "--result_file", "/tmp/results.jsonl",
            "--test_type", "default-config",
            "--start_timestamp", "2026-04-28T15:00:00Z",
            "--cluster-name", "mesh-1",
            "--cluster-count", "2",
            "--mesh-size", "2",
            "--namespaces", "1",
            "--deployments-per-namespace", "1",
            "--replicas-per-deployment", "1",
            "--trigger_reason", "Manual",
        ]
        with patch.object(sys, "argv", test_args):
            main()
        mock_collect.assert_called_once_with(
            "/path/to/report",
            "{}",
            "abc",
            "http://example.com",
            "/tmp/results.jsonl",
            "default-config",
            "2026-04-28T15:00:00Z",
            "mesh-1",
            2,
            2,
            1,
            1,
            1,
            "Manual",
        )


if __name__ == "__main__":
    unittest.main()
