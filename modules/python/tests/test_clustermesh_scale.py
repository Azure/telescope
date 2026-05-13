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
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from glob import glob
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

# Files/dirs that run-cl2-on-cluster.sh writes into every per-cluster
# $report_dir. Any new artifact added there MUST be mirrored in
# mock_data/clustermesh-scale/report/mesh-*/ so the local test suite
# exercises the same shape collect_clusterloader2 sees in real runs.
# The TestMockFixtureParity class below enforces this.
EXPECTED_PER_CLUSTER_ARTIFACTS = {
    "files": ["junit.xml"],
    "file_globs": ["*.json"],
    "subdirs": ["logs"],
    "logs_files": [
        "clustermesh-apiserver-apiserver.log",
        "clustermesh-apiserver-etcd.log",
        "clustermesh-apiserver-kvstoremesh.log",
        "cilium-agent.log",
        "cilium-operator.log",
    ],
}


class TestMockFixtureParity(unittest.TestCase):
    """Mock data must mirror the real run-cl2-on-cluster.sh output layout.

    Without this, collect_clusterloader2 tests can pass against a stale
    mock while real runs crash on shapes the mock doesn't include —
    exactly the IsADirectoryError on logs/ regression that triggered
    adding this guard.
    """

    def _assert_cluster_dir_shape(self, cluster_dir):
        for fname in EXPECTED_PER_CLUSTER_ARTIFACTS["files"]:
            self.assertTrue(
                os.path.isfile(os.path.join(cluster_dir, fname)),
                f"{cluster_dir}: missing required file {fname}",
            )
        for pattern in EXPECTED_PER_CLUSTER_ARTIFACTS["file_globs"]:
            self.assertTrue(
                glob(os.path.join(cluster_dir, pattern)),
                f"{cluster_dir}: no file matches {pattern}",
            )
        for sd in EXPECTED_PER_CLUSTER_ARTIFACTS["subdirs"]:
            self.assertTrue(
                os.path.isdir(os.path.join(cluster_dir, sd)),
                f"{cluster_dir}: missing required subdir {sd}/ "
                f"(run-cl2-on-cluster.sh writes this; "
                f"keep the mock in sync so collect tests stay realistic)",
            )
        log_dir = os.path.join(cluster_dir, "logs")
        for lf in EXPECTED_PER_CLUSTER_ARTIFACTS["logs_files"]:
            self.assertTrue(
                os.path.isfile(os.path.join(log_dir, lf)),
                f"{log_dir}: missing log file {lf}",
            )

    def test_mesh_1_mock_matches_engine_output(self):
        """mesh-1 mock has the same shape as a real per-cluster report dir."""
        self._assert_cluster_dir_shape(os.path.join(MOCK_REPORT_ROOT, "mesh-1"))

    def test_mesh_2_mock_matches_engine_output(self):
        """mesh-2 mock has the same shape as a real per-cluster report dir."""
        self._assert_cluster_dir_shape(os.path.join(MOCK_REPORT_ROOT, "mesh-2"))

    def test_mesh_fail_mock_matches_engine_output(self):
        """mesh-fail mock has the same shape as a real per-cluster report dir."""
        self._assert_cluster_dir_shape(os.path.join(MOCK_REPORT_ROOT, "mesh-fail"))


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

            # Prometheus knobs — scrape Cilium agent/operator so measurement
            # modules have data. Memory LIMIT honored via overrides; the
            # REQUEST is set via the --prometheus-memory-request CLI flag in
            # execute_clusterloader2 (CL2_PROMETHEUS_MEMORY_REQUEST is not a
            # real overrides key for this CL2 image). NODE_SELECTOR pins the
            # Prometheus pod to the dedicated `prompool` node defined in
            # azure-2.tfvars (label prometheus=true).
            self.assertIn("CL2_PROMETHEUS_TOLERATE_MASTER: true", content)
            self.assertIn("CL2_PROMETHEUS_MEMORY_LIMIT: 2Gi", content)
            self.assertIn('CL2_PROMETHEUS_NODE_SELECTOR: "prometheus: \\"true\\""', content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true", content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true", content)
            self.assertIn("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m", content)
            self.assertIn("CL2_ENABLE_VIOLATIONS_FOR_API_CALL_PROMETHEUS_SIMPLE: false", content)
            self.assertNotIn("CL2_PROMETHEUS_MEMORY_REQUEST", content)
            self.assertNotIn("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR", content)
            self.assertNotIn("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR", content)
            self.assertNotIn("CL2_PROMETHEUS_CPU_SCALE_FACTOR", content)

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

    def test_overrides_file_emits_phase4a_pod_churn_defaults(self):
        """Every CL2_* knob the pod-churn-{scale,kill}.yaml templates read must
        be emitted by configure_clusterloader2, even when not passed explicitly —
        so an event-throughput run that omits the churn args still produces
        a valid overrides file that pod-churn templates would accept.

        Defaults must match the documented Phase 4a defaults in plan.md.
        """
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="15m",
                override_file=tmp_path,
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            # pod-churn-scale knobs.
            self.assertIn("CL2_CHURN_CYCLES: 5", content)
            self.assertIn("CL2_CHURN_UP_DURATION: 60s", content)
            self.assertIn("CL2_CHURN_DOWN_DURATION: 60s", content)
            # pod-churn-kill knobs.
            self.assertIn("CL2_KILL_DURATION: 10m", content)
            self.assertIn("CL2_KILL_INTERVAL_SECONDS: 10", content)
            self.assertIn("CL2_KILL_BATCH: 5", content)
            self.assertIn("CL2_KILL_DURATION_SECONDS: 600", content)
            # Job deadline must exceed kill_duration so the activeDeadlineSeconds
            # safety net never fires before the killer's own time check.
            self.assertIn("CL2_KILL_JOB_DEADLINE_SECONDS: 660", content)
        finally:
            os.remove(tmp_path)

    def test_overrides_file_pod_churn_overrides_passthrough(self):
        """Explicit churn args override the defaults in the overrides file."""
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=5,
                deployments_per_namespace=4,
                replicas_per_deployment=10,
                operation_timeout="20m",
                override_file=tmp_path,
                churn_cycles=3,
                churn_up_duration="30s",
                churn_down_duration="45s",
                kill_duration="5m",
                kill_interval_seconds=15,
                kill_batch=3,
                kill_duration_seconds=300,
                kill_job_deadline_seconds=360,
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("CL2_CHURN_CYCLES: 3", content)
            self.assertIn("CL2_CHURN_UP_DURATION: 30s", content)
            self.assertIn("CL2_CHURN_DOWN_DURATION: 45s", content)
            self.assertIn("CL2_KILL_DURATION: 5m", content)
            self.assertIn("CL2_KILL_INTERVAL_SECONDS: 15", content)
            self.assertIn("CL2_KILL_BATCH: 3", content)
            self.assertIn("CL2_KILL_DURATION_SECONDS: 300", content)
            self.assertIn("CL2_KILL_JOB_DEADLINE_SECONDS: 360", content)
        finally:
            os.remove(tmp_path)

    def test_overrides_file_apiserver_failure_defaults(self):
        """Phase 4b — Scenario #4 (APIServer Failure) knobs landed in overrides
        with the documented defaults.

        Same unconditional-write pattern as churn knobs: every configure call
        writes these keys so a future event-throughput run with this overrides
        file still produces a valid (if unused) override set for the apiserver
        templates.
        """
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="15m",
                override_file=tmp_path,
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("CL2_APISERVER_KILL_TARGET_CONTEXT: clustermesh-1", content)
            self.assertIn("CL2_APISERVER_KILL_RECOVERY_TIMEOUT_SECONDS: 240", content)
            self.assertIn("CL2_APISERVER_KILL_OBSERVATION_SECONDS: 60", content)
        finally:
            os.remove(tmp_path)

    def test_overrides_file_apiserver_failure_overrides_passthrough(self):
        """Explicit apiserver-failure args override the defaults."""
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="15m",
                override_file=tmp_path,
                apiserver_kill_target_context="clustermesh-5",
                apiserver_kill_recovery_timeout_seconds=180,
                apiserver_kill_observation_seconds=90,
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("CL2_APISERVER_KILL_TARGET_CONTEXT: clustermesh-5", content)
            self.assertIn("CL2_APISERVER_KILL_RECOVERY_TIMEOUT_SECONDS: 180", content)
            self.assertIn("CL2_APISERVER_KILL_OBSERVATION_SECONDS: 90", content)
        finally:
            os.remove(tmp_path)


class TestApiserverFailureTimingPickup(unittest.TestCase):
    """collect_clusterloader2 appends a row from ApiserverFailureTimings_*.json
    if it finds one in the report dir. This is the Phase 4b mechanism for
    surfacing the killer script's recorded timestamps into the JSONL — vanilla
    process_cl2_reports() doesn't recognize the file pattern.
    """

    def test_timing_file_appends_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Copy the mock report dir so we can add a timing file alongside.
            src = os.path.join(MOCK_REPORT_ROOT, "mesh-1")
            report_dir = os.path.join(tmp, "mesh-1")
            shutil.copytree(src, report_dir)
            timing_path = os.path.join(
                report_dir, "ApiserverFailureTimings_clustermesh-1.json"
            )
            with open(timing_path, "w", encoding="utf-8") as f:
                json.dump({
                    "target_context": "clustermesh-1",
                    "t0_kill_epoch": 1746000000,
                    "t1_recovered_epoch": 1746000035,
                    "recovery_duration_seconds": 35,
                    "recovered": True,
                    "killed_pod_name": "clustermesh-apiserver-abc",
                    "killed_pod_uid": "old-uid",
                    "replacement_pod_uid": "new-uid",
                    "note": "ok",
                }, f)

            result_file = tempfile.mktemp(suffix=".jsonl")
            try:
                collect_clusterloader2(
                    cl2_report_dir=report_dir,
                    cloud_info="",
                    run_id="apf-test",
                    run_url="",
                    result_file=result_file,
                    test_type="apiserver-failure",
                    start_timestamp="2026-05-12T20:00:00Z",
                    cluster_name="mesh-1",
                    cluster_count=2,
                    mesh_size=2,
                    namespaces=5,
                    deployments_per_namespace=4,
                    replicas_per_deployment=10,
                    trigger_reason="Manual",
                )
                with open(result_file, "r", encoding="utf-8") as f:
                    lines = [json.loads(l) for l in f.read().strip().split("\n")]
                # At least one ApiserverFailureRecoveryTiming row appended
                timing_rows = [
                    r for r in lines
                    if r.get("measurement") == "ApiserverFailureRecoveryTiming"
                ]
                self.assertEqual(len(timing_rows), 1)
                tr = timing_rows[0]
                self.assertEqual(tr["group"], "apiserver-failure")
                self.assertEqual(tr["test_type"], "apiserver-failure")
                self.assertEqual(tr["cluster"], "mesh-1")
                self.assertEqual(tr["result"]["unit"], "seconds")
                data = tr["result"]["data"]
                self.assertEqual(data["target_context"], "clustermesh-1")
                self.assertEqual(data["recovery_duration_seconds"], 35)
                self.assertTrue(data["recovered"])
            finally:
                if os.path.exists(result_file):
                    os.remove(result_file)

    def test_no_timing_file_means_no_extra_row(self):
        """Non-target clusters skip writing the timing file; collect must not
        emit any ApiserverFailureRecoveryTiming row for those clusters.
        """
        result_file = tempfile.mktemp(suffix=".jsonl")
        try:
            collect_clusterloader2(
                cl2_report_dir=os.path.join(MOCK_REPORT_ROOT, "mesh-2"),
                cloud_info="",
                run_id="apf-test-no-timing",
                run_url="",
                result_file=result_file,
                test_type="apiserver-failure",
                start_timestamp="2026-05-12T20:00:00Z",
                cluster_name="mesh-2",
                cluster_count=2,
                mesh_size=2,
                namespaces=5,
                deployments_per_namespace=4,
                replicas_per_deployment=10,
                trigger_reason="Manual",
            )
            with open(result_file, "r", encoding="utf-8") as f:
                lines = [json.loads(l) for l in f.read().strip().split("\n") if l]
            timing_rows = [
                r for r in lines
                if r.get("measurement") == "ApiserverFailureRecoveryTiming"
            ]
            self.assertEqual(len(timing_rows), 0)
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)


class TestCollectSingleCluster(unittest.TestCase):
    """collect_clusterloader2 emits one JSONL row per call, tagged with cluster identity."""

    def _collect(self, *, cluster_name, cluster_count=2, mesh_size=2,
                 test_type="unit-test", report_subdir="mesh-1"):
        result_file = tempfile.mktemp(suffix=".jsonl")
        collect_clusterloader2(
            cl2_report_dir=os.path.join(MOCK_REPORT_ROOT, report_subdir),
            cloud_info=json.dumps({"cloud": "azure", "region": "eastus2"}),
            run_id="test-run-123",
            run_url="http://example.com/run123",
            result_file=result_file,
            test_type=test_type,
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

    def test_collect_propagates_test_type(self):
        """test_type tags every JSONL row so Kusto can filter scenario flavors.

        Scale-scenario #1 (event-throughput) and the default-config Phase-1
        smoke run share one results table; downstream dashboards filter on
        ``test_type == 'event-throughput'`` to scope the scaling-curve view
        to the right workload. Regression-guards that the field flows through
        unmodified.
        """
        result_file = self._collect(cluster_name="mesh-1", test_type="event-throughput")
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                row = json.loads(f.read().strip().split("\n")[0])
            self.assertEqual(row["test_type"], "event-throughput")
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)

    def test_collect_records_pod_churn_knobs(self):
        """Phase 4a — pod-churn scenarios record churn knobs on every row.

        Spec line 67 ("CPU/memory growth over time") requires historical
        comparison across runs with potentially-different churn parameters.
        Recording the knobs on the row means a future query for
        ``churn_cycles==5 AND kill_batch==5`` returns only directly-comparable
        rows. Non-churn test_types default to 0/"" — Kusto-friendly nulls.
        """
        result_file = tempfile.mktemp(suffix=".jsonl")
        try:
            collect_clusterloader2(
                cl2_report_dir=os.path.join(MOCK_REPORT_ROOT, "mesh-1"),
                cloud_info=json.dumps({"cloud": "azure", "region": "eastus2"}),
                run_id="test-run-churn",
                run_url="http://example.com/runchurn",
                result_file=result_file,
                test_type="pod-churn-scale",
                start_timestamp="2026-04-28T15:00:00Z",
                cluster_name="mesh-1",
                cluster_count=2,
                mesh_size=2,
                namespaces=5,
                deployments_per_namespace=4,
                replicas_per_deployment=10,
                trigger_reason="Manual",
                churn_cycles=5,
                churn_up_duration="60s",
                churn_down_duration="60s",
                kill_duration_seconds=600,
                kill_interval_seconds=10,
                kill_batch=5,
            )
            with open(result_file, "r", encoding="utf-8") as f:
                row = json.loads(f.read().strip().split("\n")[0])
            # Top-level fields — Kusto column convenience.
            self.assertEqual(row["churn_cycles"], 5)
            self.assertEqual(row["kill_duration_seconds"], 600)
            self.assertEqual(row["kill_interval_seconds"], 10)
            self.assertEqual(row["kill_batch"], 5)
            # Nested in test_details for richer queries.
            details = row["test_details"]
            self.assertEqual(details["churn_cycles"], 5)
            self.assertEqual(details["churn_up_duration"], "60s")
            self.assertEqual(details["churn_down_duration"], "60s")
            self.assertEqual(details["kill_duration_seconds"], 600)
            self.assertEqual(details["kill_interval_seconds"], 10)
            self.assertEqual(details["kill_batch"], 5)
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)

    def test_collect_pod_churn_knobs_default_to_zero_for_non_churn_runs(self):
        """Non-churn collect calls omit the churn knobs; defaults must be 0/""
        so the JSONL row is still schema-stable for Kusto (no missing fields).
        """
        result_file = self._collect(cluster_name="mesh-1", test_type="event-throughput")
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                row = json.loads(f.read().strip().split("\n")[0])
            self.assertEqual(row["churn_cycles"], 0)
            self.assertEqual(row["kill_duration_seconds"], 0)
            self.assertEqual(row["kill_interval_seconds"], 0)
            self.assertEqual(row["kill_batch"], 0)
            self.assertEqual(row["test_details"]["churn_up_duration"], "")
            self.assertEqual(row["test_details"]["churn_down_duration"], "")
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)

    def test_collect_skips_any_subdir_under_report_dir(self):
        """process_cl2_reports open()s every dir entry, so ANY subdir trips it.

        Today only logs/ exists (pod log capture from run-cl2-on-cluster.sh).
        Tomorrow could be phase-logs/ from a CL2 version bump, additional
        diag dumps, etc. collect_clusterloader2 must stash every subdir
        outside the report dir during the parse and restore each one
        afterward so the pipeline-level artifact publish still picks them up.
        """
        src = os.path.join(MOCK_REPORT_ROOT, "mesh-1")
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = os.path.join(tmp, "mesh-1")
            shutil.copytree(src, report_dir)
            # mesh-1 fixture already ships logs/; add two more synthetic
            # subdirs to lock in the "skip ALL subdirs" contract.
            extra_subdirs = {
                "phase-logs": "phase-0.log",
                "diag-dump": "events.txt",
            }
            for sd, fname in extra_subdirs.items():
                sd_path = os.path.join(report_dir, sd)
                os.makedirs(sd_path, exist_ok=True)
                with open(os.path.join(sd_path, fname), "w", encoding="utf-8") as f:
                    f.write(f"synthetic {sd}/{fname}\n")

            result_file = tempfile.mktemp(suffix=".jsonl")
            try:
                collect_clusterloader2(
                    cl2_report_dir=report_dir,
                    cloud_info=json.dumps({"cloud": "azure", "region": "eastus2"}),
                    run_id="test-run-subdirs",
                    run_url="http://example.com/runsubdirs",
                    result_file=result_file,
                    test_type="unit-test",
                    start_timestamp="2026-04-28T15:00:00Z",
                    cluster_name="mesh-1",
                    cluster_count=2,
                    mesh_size=2,
                    namespaces=1,
                    deployments_per_namespace=1,
                    replicas_per_deployment=1,
                    trigger_reason="Manual",
                )
                self.assertTrue(os.path.exists(result_file))
                with open(result_file, "r", encoding="utf-8") as f:
                    self.assertGreater(len(f.read()), 0)
                # All three subdirs (mock logs/ + 2 synthetic) restored
                # at original location with contents intact.
                self.assertTrue(os.path.isdir(os.path.join(report_dir, "logs")))
                for sd, fname in extra_subdirs.items():
                    self.assertTrue(os.path.isdir(os.path.join(report_dir, sd)),
                                    f"{sd}/ missing after collect")
                    nested = os.path.join(report_dir, sd, fname)
                    self.assertTrue(os.path.isfile(nested),
                                    f"{nested} missing after collect")
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
        mock_configure.assert_called_once_with(
            2, 3, 4, "20m", "/tmp/overrides.yaml",
            churn_cycles=5,
            churn_up_duration="60s",
            churn_down_duration="60s",
            kill_duration="10m",
            kill_interval_seconds=10,
            kill_batch=5,
            kill_duration_seconds=600,
            kill_job_deadline_seconds=660,
            apiserver_kill_target_context="clustermesh-1",
            apiserver_kill_recovery_timeout_seconds=240,
            apiserver_kill_observation_seconds=60,
        )

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
            tear_down_prometheus=False,
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
            churn_cycles=0,
            churn_up_duration="",
            churn_down_duration="",
            kill_duration_seconds=0,
            kill_interval_seconds=0,
            kill_batch=0,
        )

    @patch.object(clustermesh_scale_module, "execute_parallel")
    def test_execute_parallel_command_parsing(self, mock_exec_parallel):
        """`execute-parallel` subcommand wires CLI args through and exits with returned rc."""
        mock_exec_parallel.return_value = 0
        test_args = [
            "clustermesh-scale/scale.py",
            "execute-parallel",
            "--clusters", "/tmp/clusters.json",
            "--max-concurrent", "3",
            "--worker-script", "/path/to/run-cl2-on-cluster.sh",
            "--cl2-image", "ghcr.io/azure/clusterloader2:v20250513",
            "--cl2-config-dir", "/path/to/config",
            "--cl2-config-file", "config.yaml",
            "--cl2-report-dir-base", "/path/to/results",
            "--provider", "aks",
            "--python-script-file", "/path/to/scale.py",
            "--python-workdir", "/path/to/modules/python",
        ]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)
        mock_exec_parallel.assert_called_once_with(
            clusters_file="/tmp/clusters.json",
            max_concurrent=3,
            worker_script="/path/to/run-cl2-on-cluster.sh",
            cl2_image="ghcr.io/azure/clusterloader2:v20250513",
            cl2_config_dir="/path/to/config",
            cl2_config_file="config.yaml",
            cl2_report_dir_base="/path/to/results",
            provider="aks",
            python_script_file="/path/to/scale.py",
            python_workdir="/path/to/modules/python",
            tear_down_prometheus=False,
        )

    @patch.object(clustermesh_scale_module, "execute_parallel")
    def test_execute_parallel_default_max_concurrent_is_4(self, mock_exec_parallel):
        """Default --max-concurrent matches the plan.md Phase 3 spec value (4)."""
        mock_exec_parallel.return_value = 0
        test_args = [
            "clustermesh-scale/scale.py",
            "execute-parallel",
            "--clusters", "/tmp/c.json",
            "--worker-script", "/w.sh",
            "--cl2-image", "img",
            "--cl2-config-dir", "/cfg",
            "--cl2-config-file", "config.yaml",
            "--cl2-report-dir-base", "/r",
            "--provider", "aks",
            "--python-script-file", "/s.py",
            "--python-workdir", "/wd",
        ]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit):
                main()
        self.assertEqual(mock_exec_parallel.call_args.kwargs["max_concurrent"], 4)

    @patch.object(clustermesh_scale_module, "execute_parallel")
    def test_execute_parallel_propagates_nonzero_exit(self, mock_exec_parallel):
        """If execute_parallel returns nonzero, main() exits nonzero so the AzDO step fails."""
        mock_exec_parallel.return_value = 1
        test_args = [
            "clustermesh-scale/scale.py",
            "execute-parallel",
            "--clusters", "/tmp/c.json",
            "--worker-script", "/w.sh",
            "--cl2-image", "img",
            "--cl2-config-dir", "/cfg",
            "--cl2-config-file", "config.yaml",
            "--cl2-report-dir-base", "/r",
            "--provider", "aks",
            "--python-script-file", "/s.py",
            "--python-workdir", "/wd",
        ]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)

    @patch.object(clustermesh_scale_module, "execute_parallel")
    def test_execute_parallel_tear_down_prometheus_flag(self, mock_exec_parallel):
        """--tear-down-prometheus flag flows through to execute_parallel.

        Used by share-infra mode (multiple scenarios per provision/destroy
        lifecycle) so each scenario's CL2 invocation deploys a fresh
        Prometheus stack rather than colliding with the previous scenario's
        leftover Prom resources.
        """
        mock_exec_parallel.return_value = 0
        test_args_off = [
            "clustermesh-scale/scale.py", "execute-parallel",
            "--clusters", "/tmp/c.json", "--worker-script", "/w.sh",
            "--cl2-image", "img", "--cl2-config-dir", "/cfg",
            "--cl2-config-file", "config.yaml", "--cl2-report-dir-base", "/r",
            "--provider", "aks", "--python-script-file", "/s.py", "--python-workdir", "/wd",
        ]
        with patch.object(sys, "argv", test_args_off):
            with self.assertRaises(SystemExit):
                main()
        self.assertEqual(
            mock_exec_parallel.call_args.kwargs["tear_down_prometheus"], False)

        mock_exec_parallel.reset_mock()
        with patch.object(sys, "argv", test_args_off + ["--tear-down-prometheus"]):
            with self.assertRaises(SystemExit):
                main()
        self.assertEqual(
            mock_exec_parallel.call_args.kwargs["tear_down_prometheus"], True)


class _FakePopen:
    """Test double for subprocess.Popen used in execute_parallel tests.

    Records construction args, fakes a streamable stdout, sleeps inside wait()
    to force temporal overlap (so concurrency tests can observe max_active),
    and decrements an active counter on wait so the parent observes correct
    in-flight counts.

    Class attributes (lock, counters, instances) are intentionally public —
    the class itself is "private" via the leading underscore, and tests
    inspect this state directly to assert concurrency invariants.
    """

    # Class-level state mutated across instances by the test runner.
    lock = threading.Lock()
    active_now = 0
    max_active = 0
    instances = []  # list of FakePopen instances created
    wait_seconds = 0.05  # how long each fake CL2 "runs" in wait()
    # Per-role configuration: role -> (stdout_lines, exit_code)
    role_config = {}
    default_exit = 0
    default_stdout = []

    @classmethod
    def reset(cls, *, wait_seconds=0.05, role_config=None,
              default_stdout=None, default_exit=0):
        cls.active_now = 0
        cls.max_active = 0
        cls.instances = []
        cls.wait_seconds = wait_seconds
        cls.role_config = role_config or {}
        cls.default_stdout = default_stdout or []
        cls.default_exit = default_exit

    def __init__(self, args, **kwargs):
        # args is e.g. ["bash", worker_script, role, kubeconfig, ...]
        self.args = args
        self.kwargs = kwargs
        self.returncode = None
        self.role = args[2] if len(args) >= 3 else None
        lines, exit_code = self.__class__.role_config.get(
            self.role, (self.__class__.default_stdout, self.__class__.default_exit)
        )
        # Provide an iterator over the staged lines so `for line in proc.stdout`
        # in _run_one_cluster yields them once.
        self.stdout = iter(lines)
        self.exit_code = exit_code
        with self.__class__.lock:
            self.__class__.instances.append(self)
            self.__class__.active_now += 1
            self.__class__.max_active = max(
                self.__class__.max_active, self.__class__.active_now
            )

    def wait(self, timeout=None):  # pylint: disable=unused-argument
        # Sleep so peer workers have a chance to enter wait() concurrently.
        # Without this overlap window, the test couldn't distinguish parallel
        # execution from sequential.
        time.sleep(self.__class__.wait_seconds)
        with self.__class__.lock:
            self.__class__.active_now -= 1
        self.returncode = self.exit_code
        return self.exit_code

    def terminate(self):
        # No-op for tests — execute_parallel only terminates on signal,
        # which we don't trigger from these tests.
        pass


class TestExecuteParallel(unittest.TestCase):
    """execute_parallel fans out CL2 across N clusters with bounded concurrency.

    Validates the contract per plan.md Phase 3: bounded concurrent CL2
    invocations, per-cluster pass/fail aggregation, AzDO ##vso service
    messages preserved without [role] prefix, sensible validation errors.
    """

    def setUp(self):
        # Replace signal install with a no-op — installing real handlers in
        # unit tests can interact badly with pytest's signal handling.
        self._signal_patcher = patch.object(
            clustermesh_scale_module, "_install_parallel_signal_handlers", lambda: None
        )
        self._signal_patcher.start()

    def tearDown(self):
        self._signal_patcher.stop()

    def _write_clusters(self, clusters):
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clusters, f)
        return path

    def _call_execute_parallel(self, clusters_file, max_concurrent=4):
        return clustermesh_scale_module.execute_parallel(
            clusters_file=clusters_file,
            max_concurrent=max_concurrent,
            worker_script="/path/to/run-cl2-on-cluster.sh",
            cl2_image="img",
            cl2_config_dir="/cfg",
            cl2_config_file="config.yaml",
            cl2_report_dir_base="/r",
            provider="aks",
            python_script_file="/scale.py",
            python_workdir="/wd",
        )

    def test_dispatches_one_subprocess_per_cluster(self):
        """N clusters → N Popen calls, each carrying that cluster's role + kubeconfig."""
        clusters = [
            {"role": "mesh-1", "kubeconfig": "/home/.kube/mesh-1.config"},
            {"role": "mesh-2", "kubeconfig": "/home/.kube/mesh-2.config"},
            {"role": "mesh-3", "kubeconfig": "/home/.kube/mesh-3.config"},
        ]
        cf = self._write_clusters(clusters)
        try:
            _FakePopen.reset(wait_seconds=0)
            with patch.object(clustermesh_scale_module.subprocess, "Popen", _FakePopen):
                rc = self._call_execute_parallel(cf)
            self.assertEqual(rc, 0)
            self.assertEqual(len(_FakePopen.instances), 3)
            # Each invocation passes role + kubeconfig in the bash worker arg
            # vector. args layout: ["bash", worker_script, role, kubeconfig,
            # report_dir, cl2_image, cl2_config_dir, cl2_config_file, provider,
            # python_script_file, python_workdir]
            roles_seen = {p.args[2] for p in _FakePopen.instances}
            self.assertEqual(roles_seen, {"mesh-1", "mesh-2", "mesh-3"})
            for p in _FakePopen.instances:
                role = p.args[2]
                self.assertEqual(p.args[3], f"/home/.kube/{role}.config")
                # report_dir is base/role
                self.assertEqual(p.args[4], f"/r/{role}")
        finally:
            os.remove(cf)

    def test_all_zero_exit_codes_yield_overall_success(self):
        """If every per-cluster worker exits 0, execute_parallel returns 0."""
        clusters = [
            {"role": "mesh-1", "kubeconfig": "/k1"},
            {"role": "mesh-2", "kubeconfig": "/k2"},
        ]
        cf = self._write_clusters(clusters)
        try:
            _FakePopen.reset(wait_seconds=0, default_exit=0)
            with patch.object(clustermesh_scale_module.subprocess, "Popen", _FakePopen):
                rc = self._call_execute_parallel(cf)
            self.assertEqual(rc, 0)
        finally:
            os.remove(cf)

    def test_any_nonzero_exit_yields_overall_failure(self):
        """If ANY per-cluster worker exits non-zero, execute_parallel returns 1.

        Mirrors the sequential bash behavior (`if failures > 0; exit 1`) so
        the AzDO step's pass/fail signal is unchanged from before parallel
        fan-out. Other clusters still complete (no early cancellation).
        """
        clusters = [
            {"role": "mesh-1", "kubeconfig": "/k1"},
            {"role": "mesh-2", "kubeconfig": "/k2"},
            {"role": "mesh-3", "kubeconfig": "/k3"},
        ]
        cf = self._write_clusters(clusters)
        try:
            _FakePopen.reset(
                wait_seconds=0,
                role_config={
                    "mesh-1": ([], 0),
                    "mesh-2": ([], 1),  # this one fails
                    "mesh-3": ([], 0),
                },
            )
            with patch.object(clustermesh_scale_module.subprocess, "Popen", _FakePopen):
                rc = self._call_execute_parallel(cf)
            self.assertEqual(rc, 1)
            # All three workers ran — failure of one does NOT cancel the others.
            self.assertEqual(len(_FakePopen.instances), 3)
        finally:
            os.remove(cf)

    def test_respects_max_concurrent_bound(self):
        """No more than max_concurrent workers are in-flight simultaneously.

        Uses a barrier-free approach: each FakePopen sleeps in wait(); we
        observe the running max_active count maintained inside FakePopen.
        Asserts max_active <= max_concurrent regardless of timing — no
        ordering or wall-clock assertion (which would be flaky under CI load).
        """
        clusters = [{"role": f"mesh-{i}", "kubeconfig": f"/k{i}"} for i in range(8)]
        cf = self._write_clusters(clusters)
        try:
            _FakePopen.reset(wait_seconds=0.05)  # 50ms per "CL2 run"
            with patch.object(clustermesh_scale_module.subprocess, "Popen", _FakePopen):
                rc = self._call_execute_parallel(cf, max_concurrent=3)
            self.assertEqual(rc, 0)
            self.assertEqual(len(_FakePopen.instances), 8)
            # The bound is the contract: never more than 3 concurrent CL2
            # docker containers from this orchestrator at once.
            self.assertLessEqual(_FakePopen.max_active, 3)
            # Sanity: with 8 work items and 50ms each, we WILL see >1 in
            # flight — otherwise the test would pass trivially with a
            # single-threaded executor.
            self.assertGreater(_FakePopen.max_active, 1)
        finally:
            os.remove(cf)

    def test_prefixes_role_but_preserves_vso_service_messages(self):
        """Worker stdout lines get [role] prefix; ##vso AzDO messages stay verbatim.

        AzDO recognizes ##vso[...] service messages only at column 0 — a
        [role] prefix would silently drop the structured annotation
        (warnings, errors, set-variable). Regression-guard: if the prefix
        logic ever changes, this test breaks loudly.
        """
        clusters = [{"role": "mesh-1", "kubeconfig": "/k1"}]
        cf = self._write_clusters(clusters)
        try:
            _FakePopen.reset(
                wait_seconds=0,
                role_config={
                    "mesh-1": ([
                        "hello world\n",
                        "##vso[task.logissue type=warning;]something\n",
                        "more text\n",
                    ], 0),
                },
            )
            buf = io.StringIO()
            with patch.object(clustermesh_scale_module.subprocess, "Popen", _FakePopen):
                with redirect_stdout(buf):
                    rc = self._call_execute_parallel(cf)
            self.assertEqual(rc, 0)
            captured = buf.getvalue()
            # Non-vso lines are prefixed with [role].
            self.assertIn("[mesh-1] hello world", captured)
            self.assertIn("[mesh-1] more text", captured)
            # vso line MUST NOT be prefixed.
            self.assertIn("##vso[task.logissue type=warning;]something", captured)
            self.assertNotIn("[mesh-1] ##vso", captured)
        finally:
            os.remove(cf)

    def test_empty_clusters_file_raises(self):
        """A clusters file with [] is invalid — fail fast, don't silently no-op."""
        cf = self._write_clusters([])
        try:
            with self.assertRaises(ValueError):
                self._call_execute_parallel(cf)
        finally:
            os.remove(cf)

    def test_cluster_missing_kubeconfig_raises(self):
        """Each cluster object must carry both 'role' and 'kubeconfig'."""
        cf = self._write_clusters([{"role": "mesh-1"}])
        try:
            with self.assertRaises(ValueError):
                self._call_execute_parallel(cf)
        finally:
            os.remove(cf)

    def test_max_concurrent_zero_raises(self):
        """max_concurrent < 1 is meaningless and would deadlock the executor."""
        cf = self._write_clusters([{"role": "mesh-1", "kubeconfig": "/k1"}])
        try:
            with self.assertRaises(ValueError):
                self._call_execute_parallel(cf, max_concurrent=0)
        finally:
            os.remove(cf)

    def test_extra_fields_in_cluster_object_are_ignored(self):
        """Pipeline writes name/rg/kubeconfig/role; execute_parallel must tolerate extras.

        Same JSON file is consumed by collect.yml (which uses name/rg/role),
        so execute_parallel must NOT reject the additional fields.
        """
        clusters = [
            {"role": "mesh-1", "kubeconfig": "/k1", "name": "aks-1", "rg": "rg-1"},
            {"role": "mesh-2", "kubeconfig": "/k2", "name": "aks-2", "rg": "rg-2"},
        ]
        cf = self._write_clusters(clusters)
        try:
            _FakePopen.reset(wait_seconds=0)
            with patch.object(clustermesh_scale_module.subprocess, "Popen", _FakePopen):
                rc = self._call_execute_parallel(cf)
            self.assertEqual(rc, 0)
            self.assertEqual(len(_FakePopen.instances), 2)
        finally:
            os.remove(cf)


if __name__ == "__main__":
    unittest.main()
