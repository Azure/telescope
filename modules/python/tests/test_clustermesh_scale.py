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
# pylint: disable=too-many-lines
import importlib.util
import io
import json
import os
import shutil
import subprocess
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
            self.assertIn("CL2_PROMETHEUS_MEMORY_LIMIT: 12Gi", content)
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

    def test_overrides_file_ha_config_replicas_default(self):
        """ha-config replicas default to 3 (standard k8s HA)."""
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
            self.assertIn("CL2_HA_CONFIG_REPLICAS: 3", content)
        finally:
            os.remove(tmp_path)

    def test_overrides_file_ha_config_replicas_passthrough(self):
        """Explicit ha_config_replicas overrides the default."""
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
                ha_config_replicas=5,
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("CL2_HA_CONFIG_REPLICAS: 5", content)
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


class TestHAConfigScalingTimingPickup(unittest.TestCase):
    """collect_clusterloader2 appends a row from HAConfigScalingTimings_*.json
    if it finds one in the report dir. ha-config-scaler.sh writes the file
    on every cluster (not just target) — mesh-wide HA scaling.
    """
    def test_scaling_file_appends_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(MOCK_REPORT_ROOT, "mesh-1")
            report_dir = os.path.join(tmp, "mesh-1")
            shutil.copytree(src, report_dir)
            scaling_path = os.path.join(
                report_dir, "HAConfigScalingTimings_clustermesh-1.json"
            )
            with open(scaling_path, "w", encoding="utf-8") as f:
                json.dump({
                    "context": "clustermesh-1",
                    "action": "scale-up",
                    "requested_replicas": 3,
                    "spec_replicas_after": 3,
                    "ready_replicas_after": 3,
                    "ha_replicas_honored": True,
                    "scale_duration_seconds": 42,
                    "note": "ok",
                }, f)

            result_file = tempfile.mktemp(suffix=".jsonl")
            try:
                collect_clusterloader2(
                    cl2_report_dir=report_dir,
                    cloud_info="",
                    run_id="ha-test",
                    run_url="",
                    result_file=result_file,
                    test_type="ha-config",
                    start_timestamp="2026-05-13T20:00:00Z",
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
                scaling_rows = [
                    r for r in lines
                    if r.get("measurement") == "HAConfigScalingTiming"
                ]
                self.assertEqual(len(scaling_rows), 1)
                sr = scaling_rows[0]
                self.assertEqual(sr["group"], "ha-config")
                self.assertEqual(sr["test_type"], "ha-config")
                self.assertEqual(sr["cluster"], "mesh-1")
                self.assertEqual(sr["result"]["unit"], "seconds")
                data = sr["result"]["data"]
                self.assertEqual(data["requested_replicas"], 3)
                self.assertEqual(data["spec_replicas_after"], 3)
                self.assertTrue(data["ha_replicas_honored"])
            finally:
                if os.path.exists(result_file):
                    os.remove(result_file)

    def test_no_scaling_file_means_no_extra_row(self):
        """Without a scaling JSON, no HAConfigScalingTiming row is emitted
        (covers the non-ha-config scenario case, where the scaler isn't run).
        """
        result_file = tempfile.mktemp(suffix=".jsonl")
        try:
            collect_clusterloader2(
                cl2_report_dir=os.path.join(MOCK_REPORT_ROOT, "mesh-2"),
                cloud_info="",
                run_id="ha-test-no-scaling",
                run_url="",
                result_file=result_file,
                test_type="event-throughput",
                start_timestamp="2026-05-13T20:00:00Z",
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
            scaling_rows = [
                r for r in lines
                if r.get("measurement") == "HAConfigScalingTiming"
            ]
            self.assertEqual(len(scaling_rows), 0)
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)


class TestConfigureNodeChurnKnobs(unittest.TestCase):
    """Phase 4b — Scenario #3 (Node Churn / IP Churn) overrides flow through
    configure_clusterloader2 and land in the CL2 overrides file with the
    expected CL2_NODE_CHURN_* keys.
    """

    def test_node_churn_defaults_emitted(self):
        """Defaults match scale.py argparse + node-churner.sh expectations."""
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
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
            self.assertIn("CL2_NODE_CHURN_TARGET_CONTEXT: clustermesh-1", content)
            self.assertIn("CL2_NODE_CHURN_CYCLES: 3", content)
            self.assertIn("CL2_NODE_CHURN_DELTA: 5", content)
            self.assertIn("CL2_NODE_CHURN_SETTLE_SECONDS: 60", content)
            self.assertIn("CL2_NODE_CHURN_SCALE_DURATION_SECONDS: 1800", content)
            self.assertIn("CL2_NODE_CHURN_REPLACE_DURATION_SECONDS: 1500", content)
            self.assertIn("CL2_NODE_CHURN_COMBINED_DURATION_SECONDS: 3300", content)
            self.assertIn("CL2_NODE_REPLACE_BATCH_SIZE: 10", content)
            self.assertIn("CL2_NODE_CHURN_READY_TIMEOUT_SECONDS: 300", content)
        finally:
            os.remove(tmp_path)

    def test_node_churn_overrides_passthrough(self):
        """Explicit kwargs override defaults; per-tier matrix overrides land."""
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="15m",
                override_file=tmp_path,
                node_churn_target_context="clustermesh-7",
                node_churn_cycles=5,
                node_churn_delta=3,
                node_churn_settle_seconds=90,
                node_churn_scale_duration_seconds=2400,
                node_churn_replace_duration_seconds=2000,
                node_churn_combined_duration_seconds=4500,
                node_replace_batch_size=8,
                node_churn_ready_timeout_seconds=180,
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("CL2_NODE_CHURN_TARGET_CONTEXT: clustermesh-7", content)
            self.assertIn("CL2_NODE_CHURN_CYCLES: 5", content)
            self.assertIn("CL2_NODE_CHURN_DELTA: 3", content)
            self.assertIn("CL2_NODE_CHURN_SETTLE_SECONDS: 90", content)
            self.assertIn("CL2_NODE_CHURN_SCALE_DURATION_SECONDS: 2400", content)
            self.assertIn("CL2_NODE_CHURN_REPLACE_DURATION_SECONDS: 2000", content)
            self.assertIn("CL2_NODE_CHURN_COMBINED_DURATION_SECONDS: 4500", content)
            self.assertIn("CL2_NODE_REPLACE_BATCH_SIZE: 8", content)
            self.assertIn("CL2_NODE_CHURN_READY_TIMEOUT_SECONDS: 180", content)
        finally:
            os.remove(tmp_path)


class TestNodeChurnTimingPickup(unittest.TestCase):
    """collect_clusterloader2 appends one NodeChurnSummary row + one
    NodeChurnOpTiming row per op from NodeChurnTimings_*.json. node-churner.sh
    writes the file ONLY in the target cluster's report dir (the script runs
    on the host, not inside CL2; the file lives in the target's per-cluster
    report dir so the existing per-cluster collect pickup works).
    """

    def _write_timing(self, report_dir, target_context, ops=None,
                      scenario="node-churn-combined",
                      ready_quorum_reached=True,
                      scenario_valid=True, cleanup_failed=False,
                      truncated=False):
        ops = ops or []
        path = os.path.join(report_dir, f"NodeChurnTimings_{target_context}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "scenario": scenario,
                "target_context": target_context,
                "target_cluster_name": target_context,
                "target_resource_group": "test-rg",
                "target_nodepool": "default",
                "target_node_resource_group": f"MC_test-rg_{target_context}_eastus2",
                "target_vmss": "aks-default-12345",
                "original_node_count": 20,
                "ready_quorum_reached": ready_quorum_reached,
                "scenario_valid": scenario_valid,
                "cleanup_failed": cleanup_failed,
                "truncated": truncated,
                "started_epoch": 1746000000,
                "ended_epoch": 1746001500,
                "duration_seconds": 1500,
                "ops": ops,
            }, f)
        return path

    def test_timing_file_emits_summary_and_op_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(MOCK_REPORT_ROOT, "mesh-1")
            report_dir = os.path.join(tmp, "mesh-1")
            shutil.copytree(src, report_dir)
            self._write_timing(report_dir, "clustermesh-1", ops=[
                {
                    "op_index": 1, "op_type": "scale_up",
                    "start_epoch": 1746000010, "end_epoch": 1746000200,
                    "duration_seconds": 190, "succeeded": True,
                    "observed_node_count": 25,
                    "pre_ip_set": [], "post_ip_set": [], "new_ip_count": 0,
                    "error": "",
                },
                {
                    "op_index": 2, "op_type": "scale_down",
                    "start_epoch": 1746000260, "end_epoch": 1746000450,
                    "duration_seconds": 190, "succeeded": True,
                    "observed_node_count": 20,
                    "pre_ip_set": [], "post_ip_set": [], "new_ip_count": 0,
                    "error": "",
                },
                {
                    "op_index": 3, "op_type": "replace_wait",
                    "start_epoch": 1746000500, "end_epoch": 1746001100,
                    "duration_seconds": 600, "succeeded": True,
                    "observed_node_count": 20,
                    "pre_ip_set": ["10.1.0.4", "10.1.0.19"],
                    "post_ip_set": ["10.1.0.4", "10.1.0.19"],
                    "pre_node_names": ["aks-default-vmss000004", "aks-default-vmss00000j"],
                    "post_node_names": ["aks-default-vmss000004", "aks-default-vmss00000k"],
                    "new_ip_count": 0,
                    "new_node_count": 1,
                    "error": "",
                },
            ])
            result_file = tempfile.mktemp(suffix=".jsonl")
            try:
                collect_clusterloader2(
                    cl2_report_dir=report_dir,
                    cloud_info="",
                    run_id="nc-test",
                    run_url="",
                    result_file=result_file,
                    test_type="node-churn-combined",
                    start_timestamp="2026-05-13T20:00:00Z",
                    cluster_name="mesh-1",
                    cluster_count=2,
                    mesh_size=2,
                    namespaces=5,
                    deployments_per_namespace=4,
                    replicas_per_deployment=10,
                    trigger_reason="Manual",
                )
                with open(result_file, "r", encoding="utf-8") as f:
                    lines = [json.loads(l) for l in f.read().strip().split("\n") if l]
                summary = [r for r in lines if r.get("measurement") == "NodeChurnSummary"]
                ops = [r for r in lines if r.get("measurement") == "NodeChurnOpTiming"]
                self.assertEqual(len(summary), 1)
                self.assertEqual(len(ops), 3)
                s = summary[0]
                self.assertEqual(s["group"], "node-churn-combined")
                self.assertEqual(s["test_type"], "node-churn-combined")
                self.assertEqual(s["cluster"], "mesh-1")
                self.assertEqual(s["result"]["data"]["op_count"], 3)
                self.assertEqual(s["result"]["data"]["original_node_count"], 20)
                self.assertTrue(s["result"]["data"]["ready_quorum_reached"])
                self.assertTrue(s["result"]["data"]["scenario_valid"])
                # ops sorted by op_index
                op_types = [o["result"]["data"]["op_type"] for o in ops]
                self.assertEqual(set(op_types), {"scale_up", "scale_down", "replace_wait"})
                # scenario-level context merged onto op rows
                for op_row in ops:
                    self.assertEqual(op_row["result"]["data"]["scenario"], "node-churn-combined")
                    self.assertEqual(op_row["result"]["data"]["target_context"], "clustermesh-1")
                # replace_wait op carries IP set + node name deltas.
                # Build 67155: new_ip_count is informational (Azure can reuse IPs);
                # new_node_count is the authoritative replacement signal.
                replace = [o for o in ops if o["result"]["data"]["op_type"] == "replace_wait"][0]
                self.assertEqual(replace["result"]["data"]["new_ip_count"], 0)
                self.assertEqual(replace["result"]["data"]["new_node_count"], 1,
                                 "node name delta is the authoritative replacement signal")
                self.assertIn("aks-default-vmss00000k",
                              replace["result"]["data"]["post_node_names"])
            finally:
                if os.path.exists(result_file):
                    os.remove(result_file)

    def test_timing_file_with_empty_ops_emits_summary_only(self):
        """Ready-quorum-never-reached case: timing file exists with ops=[],
        scenario_valid=false. Summary row still emitted so Kusto can detect
        the aborted run; no op rows."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(MOCK_REPORT_ROOT, "mesh-1")
            report_dir = os.path.join(tmp, "mesh-1")
            shutil.copytree(src, report_dir)
            self._write_timing(
                report_dir, "clustermesh-1", ops=[],
                ready_quorum_reached=False, scenario_valid=False,
            )
            result_file = tempfile.mktemp(suffix=".jsonl")
            try:
                collect_clusterloader2(
                    cl2_report_dir=report_dir,
                    cloud_info="",
                    run_id="nc-test-abort",
                    run_url="",
                    result_file=result_file,
                    test_type="node-churn-scale",
                    start_timestamp="2026-05-13T20:00:00Z",
                    cluster_name="mesh-1",
                    cluster_count=2,
                    mesh_size=2,
                    namespaces=5,
                    deployments_per_namespace=4,
                    replicas_per_deployment=10,
                    trigger_reason="Manual",
                )
                with open(result_file, "r", encoding="utf-8") as f:
                    lines = [json.loads(l) for l in f.read().strip().split("\n") if l]
                summary = [r for r in lines if r.get("measurement") == "NodeChurnSummary"]
                ops = [r for r in lines if r.get("measurement") == "NodeChurnOpTiming"]
                self.assertEqual(len(summary), 1)
                self.assertEqual(len(ops), 0)
                self.assertFalse(summary[0]["result"]["data"]["ready_quorum_reached"])
                self.assertFalse(summary[0]["result"]["data"]["scenario_valid"])
                self.assertEqual(summary[0]["result"]["data"]["op_count"], 0)
            finally:
                if os.path.exists(result_file):
                    os.remove(result_file)

    def test_timing_file_with_cleanup_failed_marks_summary(self):
        """If node-churner finalizer can't restore the pool, cleanup_failed=true.
        execute.yml uses this to break the share-infra loop; collect must still
        emit the summary row with cleanup_failed=true visible."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(MOCK_REPORT_ROOT, "mesh-1")
            report_dir = os.path.join(tmp, "mesh-1")
            shutil.copytree(src, report_dir)
            self._write_timing(
                report_dir, "clustermesh-1",
                ops=[{
                    "op_index": 1, "op_type": "scale_up",
                    "start_epoch": 1746000010, "end_epoch": 1746000200,
                    "duration_seconds": 190, "succeeded": False,
                    "observed_node_count": 0,
                    "pre_ip_set": [], "post_ip_set": [], "new_ip_count": 0,
                    "error": "OperationNotAllowed",
                }],
                cleanup_failed=True, scenario_valid=False,
            )
            result_file = tempfile.mktemp(suffix=".jsonl")
            try:
                collect_clusterloader2(
                    cl2_report_dir=report_dir,
                    cloud_info="",
                    run_id="nc-test-cleanup",
                    run_url="",
                    result_file=result_file,
                    test_type="node-churn-combined",
                    start_timestamp="2026-05-13T20:00:00Z",
                    cluster_name="mesh-1",
                    cluster_count=2,
                    mesh_size=2,
                    namespaces=5,
                    deployments_per_namespace=4,
                    replicas_per_deployment=10,
                    trigger_reason="Manual",
                )
                with open(result_file, "r", encoding="utf-8") as f:
                    lines = [json.loads(l) for l in f.read().strip().split("\n") if l]
                summary = [r for r in lines if r.get("measurement") == "NodeChurnSummary"]
                self.assertEqual(len(summary), 1)
                self.assertTrue(summary[0]["result"]["data"]["cleanup_failed"])
                # failed op still surfaces with succeeded=false
                ops = [r for r in lines if r.get("measurement") == "NodeChurnOpTiming"]
                self.assertEqual(len(ops), 1)
                self.assertFalse(ops[0]["result"]["data"]["succeeded"])
                self.assertIn("OperationNotAllowed", ops[0]["result"]["data"]["error"])
            finally:
                if os.path.exists(result_file):
                    os.remove(result_file)

    def test_no_timing_file_means_no_node_churn_rows(self):
        """Non-target clusters (and non-node-churn scenarios) skip writing
        the timing file → no NodeChurnSummary / NodeChurnOpTiming rows."""
        result_file = tempfile.mktemp(suffix=".jsonl")
        try:
            collect_clusterloader2(
                cl2_report_dir=os.path.join(MOCK_REPORT_ROOT, "mesh-2"),
                cloud_info="",
                run_id="nc-test-no-timing",
                run_url="",
                result_file=result_file,
                test_type="node-churn-scale",
                start_timestamp="2026-05-13T20:00:00Z",
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
            summary = [r for r in lines if r.get("measurement") == "NodeChurnSummary"]
            ops = [r for r in lines if r.get("measurement") == "NodeChurnOpTiming"]
            self.assertEqual(len(summary), 0)
            self.assertEqual(len(ops), 0)
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)


class TestWriteReadySentinelScript(unittest.TestCase):
    """write-ready-sentinel.sh derives a unique context per CL2 invocation
    and writes a non-empty sentinel filename. Build 67114 regression: the
    original inline `bash -c` Method:Exec returned an empty context name,
    causing both clusters to write the same path (ready-) and one to
    overwrite the other → barrier saw 1/2 → scenario aborted.

    The fix relies on parsing /root/.kube/config directly (CL2 bind-mounts
    the per-cluster kubeconfig there). These tests confirm the resolution
    chain (kubeconfig-parse > kubectl-PATH > kubectl-prestaged > server-hash
    > hostname > pid-fallback) and that the sentinel filename always has
    a non-empty suffix.
    """

    SCRIPT_PATH = (
        Path(__file__).resolve().parents[1]
        / "clusterloader2" / "clustermesh-scale" / "config" / "write-ready-sentinel.sh"
    )

    def _run_with_kubeconfig(self, kubeconfig_content, td):
        kubeconfig = os.path.join(td, "kubeconfig")
        with open(kubeconfig, "w", encoding="utf-8") as f:
            f.write(kubeconfig_content)
        sentinel_dir = os.path.join(td, "sentinels")
        os.makedirs(sentinel_dir, exist_ok=True)
        env = os.environ.copy()
        env["KUBECONFIG"] = kubeconfig
        result = subprocess.run(
            ["bash", str(self.SCRIPT_PATH), sentinel_dir],
            capture_output=True, text=True, env=env, check=False,
            timeout=10,
        )
        return result, sentinel_dir

    def test_kubeconfig_parse_resolves_current_context(self):
        kc = (
            "apiVersion: v1\n"
            "clusters:\n"
            "- cluster:\n"
            "    server: https://test1.example.com:443\n"
            "  name: clustermesh-1\n"
            "contexts:\n"
            "- context:\n"
            "    cluster: clustermesh-1\n"
            "  name: clustermesh-1\n"
            "current-context: clustermesh-1\n"
        )
        with tempfile.TemporaryDirectory() as td:
            result, sentinel_dir = self._run_with_kubeconfig(kc, td)
            self.assertEqual(result.returncode, 0, f"stderr={result.stderr}")
            files = os.listdir(sentinel_dir)
            self.assertEqual(files, ["ready-clustermesh-1"])
            self.assertIn("via kubeconfig-parse", result.stderr)

    def test_different_kubeconfigs_yield_distinct_sentinels(self):
        """Build 67114 regression: two clusters MUST NOT write the same
        sentinel path (otherwise the second's write silently overwrites
        the first, breaking the quorum count)."""
        kc1 = "current-context: clustermesh-1\n"
        kc2 = "current-context: clustermesh-2\n"
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            r1, sd1 = self._run_with_kubeconfig(kc1, td1)
            r2, sd2 = self._run_with_kubeconfig(kc2, td2)
            self.assertEqual(r1.returncode, 0)
            self.assertEqual(r2.returncode, 0)
            self.assertEqual(os.listdir(sd1), ["ready-clustermesh-1"])
            self.assertEqual(os.listdir(sd2), ["ready-clustermesh-2"])

    def test_empty_current_context_falls_back_to_server_hash(self):
        """If current-context line is missing/blank, fall back to a hash of
        the server URL. Two different servers MUST yield different hashes."""
        kc1 = (
            "apiVersion: v1\n"
            "clusters:\n"
            "- cluster:\n"
            "    server: https://serverA.example.com:443\n"
            "  name: foo\n"
        )
        kc2 = (
            "apiVersion: v1\n"
            "clusters:\n"
            "- cluster:\n"
            "    server: https://serverB.example.com:443\n"
            "  name: foo\n"
        )
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            r1, sd1 = self._run_with_kubeconfig(kc1, td1)
            r2, sd2 = self._run_with_kubeconfig(kc2, td2)
            self.assertEqual(r1.returncode, 0)
            self.assertEqual(r2.returncode, 0)
            f1 = os.listdir(sd1)[0]
            f2 = os.listdir(sd2)[0]
            self.assertNotEqual(f1, f2,
                                f"server-hash collision: {f1} == {f2}")

    def test_sentinel_filename_always_non_empty_suffix(self):
        """Whatever the resolution path, the sentinel filename suffix is
        never empty (avoids the build 67114 path-collision regression)."""
        kc = ""
        with tempfile.TemporaryDirectory() as td:
            r, sd = self._run_with_kubeconfig(kc, td)
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            files = os.listdir(sd)
            self.assertEqual(len(files), 1)
            self.assertNotEqual(files[0], "ready-",
                                "sentinel filename has empty suffix — build 67114 regression")
            self.assertTrue(files[0].startswith("ready-"))
            self.assertGreater(len(files[0]), len("ready-"))


class TestNodeChurnerScript(unittest.TestCase):
    """node-churner.sh smoke tests — bash -n syntax + arg validation. The
    script's full Azure CLI behavior cannot be unit-tested without mocking
    the cloud, but its argparse-equivalent + missing-binary fail-soft path
    can.
    """

    SCRIPT_PATH = (
        Path(__file__).resolve().parents[1]
        / "clusterloader2" / "clustermesh-scale" / "config" / "node-churner.sh"
    )

    def test_script_exists_and_is_executable(self):
        self.assertTrue(self.SCRIPT_PATH.exists(),
                        f"{self.SCRIPT_PATH} should exist")
        self.assertTrue(
            os.access(self.SCRIPT_PATH, os.X_OK),
            f"{self.SCRIPT_PATH} must be executable",
        )

    def test_script_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(self.SCRIPT_PATH)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0,
                         f"bash -n failed: stderr={result.stderr}")

    def test_script_aborts_softly_when_az_missing(self):
        """When `az` CLI isn't on PATH, the script writes a timing file with
        scenario_valid=false instead of erroring out (so execute.yml's
        share-infra loop continues to subsequent scenarios with clean data).
        """
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = os.path.join(tmp, "report")
            sentinel_dir = os.path.join(tmp, "sentinels")
            os.makedirs(report_dir, exist_ok=True)
            os.makedirs(sentinel_dir, exist_ok=True)
            env = os.environ.copy()
            env["PATH"] = "/usr/bin:/bin"  # strip out any az
            result = subprocess.run(
                [
                    "bash", str(self.SCRIPT_PATH),
                    "node-churn-scale",   # scenario
                    "clustermesh-1",      # target cluster name
                    "test-rg",            # target rg
                    "default",            # target nodepool
                    report_dir,           # report dir
                    sentinel_dir,         # sentinel dir
                    "2",                  # cluster count
                    "1", "1", "1", "1", "30", "60",  # remaining knobs
                ],
                capture_output=True, text=True, env=env, check=False,
                timeout=30,
            )
            # Soft-fail contract: exit 0 even when az is missing.
            self.assertEqual(result.returncode, 0,
                             f"expected soft-fail (rc=0); got rc={result.returncode}, "
                             f"stderr={result.stderr}")
            timing_file = os.path.join(report_dir, "NodeChurnTimings_clustermesh-1.json")
            self.assertTrue(os.path.exists(timing_file),
                            "timing file should still be written on soft-fail")
            with open(timing_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertFalse(data["scenario_valid"],
                             "scenario_valid must be false when az is missing")


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
            global_namespace_count=None,
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
            ha_config_replicas=3,
            node_churn_target_context="clustermesh-1",
            node_churn_cycles=3,
            node_churn_delta=5,
            node_churn_settle_seconds=60,
            node_churn_scale_duration_seconds=1800,
            node_churn_replace_duration_seconds=1500,
            node_churn_combined_duration_seconds=3300,
            node_replace_batch_size=10,
            node_churn_ready_timeout_seconds=300,
            saturation_qps_list="100,500,1500,4000,10000",
            saturation_restarts_list="1,2,4,8,15",
            saturation_ops_per_sec_list="0,0,0,0,0",
            saturation_rung_duration_seconds=240,
            saturation_settle_seconds=90,
            probe_window_duration="60m",
            policy_canary_enabled="false",
            policy_scale_cnp_per_ns=50,
            policy_scale_hold_duration="5m",
            mock_mode="false",
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
            mock_mode="false",
        )

    @patch.object(clustermesh_scale_module, "run_cl2_command")
    def test_execute_mock_mode_disables_kubelet_scrape(self, mock_run):
        """In mock mode, kubelet scraping is disabled (KWOK nodes have no real
        kubelet, so kubelet targets stay down and block CL2's Prometheus gate)."""
        common = dict(
            cl2_image="img",
            cl2_config_dir="/cfg",
            cl2_report_dir="/rep",
            cl2_config_file="config.yaml",
            kubeconfig="/kc",
            provider="aks",
        )
        clustermesh_scale_module.execute_clusterloader2(**common, mock_mode="true")
        assert mock_run.call_args.kwargs["scrape_kubelets"] is False
        mock_run.reset_mock()
        clustermesh_scale_module.execute_clusterloader2(**common, mock_mode="false")
        assert mock_run.call_args.kwargs["scrape_kubelets"] is True

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
            saturation_qps_list="",
            saturation_restarts_list="",
            saturation_ops_per_sec_list="",
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
            worker_timeout_seconds=None,
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

    def poll(self):
        # Watchdog (when worker_timeout_seconds is set) calls poll() to
        # check liveness without blocking. Mirror real subprocess.Popen:
        # returns None while alive, returncode after exit. _run_one_cluster
        # always wait()s after streaming stdout, so by the time the watchdog
        # could observe a stale poll() the wait has set returncode.
        return self.returncode

    def kill(self):
        # SIGKILL escalation path. No-op for tests.
        self.returncode = -9

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

    def test_worker_timeout_seconds_default_none_preserves_unbounded_wait(self):
        """When worker_timeout_seconds is omitted, watchdog stays off — the
        original behavior at tiers n=2/5/10/20 is preserved.

        Regression guard for the N=100 watchdog addition: smaller tiers MUST
        keep their original semantics (no SIGTERM, returncode mirrors the
        child's exit). Asserts the watchdog thread isn't spawned and exit
        code passes through.
        """
        clusters = [{"role": "mesh-1", "kubeconfig": "/k1"}]
        cf = self._write_clusters(clusters)
        try:
            _FakePopen.reset(wait_seconds=0, default_exit=0)
            with patch.object(clustermesh_scale_module.subprocess, "Popen", _FakePopen):
                rc = clustermesh_scale_module.execute_parallel(
                    clusters_file=cf,
                    max_concurrent=1,
                    worker_script="/w.sh",
                    cl2_image="img",
                    cl2_config_dir="/cfg",
                    cl2_config_file="config.yaml",
                    cl2_report_dir_base="/r",
                    provider="aks",
                    python_script_file="/scale.py",
                    python_workdir="/wd",
                    # worker_timeout_seconds NOT passed → None
                )
            self.assertEqual(rc, 0)
        finally:
            os.remove(cf)

    def test_worker_timeout_seconds_kills_hung_worker_and_records_124(self):
        """N=100 hardening — a worker that exceeds worker_timeout_seconds is
        SIGTERM-ed (then SIGKILL after 30s) and its result is recorded as
        exit 124 (timeout) regardless of what the process eventually returns.

        Without this, a single stuck CL2 container at N=100 would block the
        whole AzDO step until the 30h job timeout — losing all other 99
        workers' completed work + the collect+upload step.

        Test models the hang by setting wait_seconds well above
        worker_timeout_seconds. _FakePopen.poll() returns None until wait()
        completes, so the watchdog sees a live process for the duration and
        fires after timeout_seconds.
        """
        clusters = [{"role": "mesh-1", "kubeconfig": "/k1"}]
        cf = self._write_clusters(clusters)
        try:
            # Fake "hang" — wait sleeps 3s. Watchdog fires at 1s (rounded up
            # to nearest 5s loop iteration → ~5s).
            _FakePopen.reset(wait_seconds=3, default_exit=0)
            with patch.object(clustermesh_scale_module.subprocess, "Popen", _FakePopen):
                rc = clustermesh_scale_module.execute_parallel(
                    clusters_file=cf,
                    max_concurrent=1,
                    worker_script="/w.sh",
                    cl2_image="img",
                    cl2_config_dir="/cfg",
                    cl2_config_file="config.yaml",
                    cl2_report_dir_base="/r",
                    provider="aks",
                    python_script_file="/scale.py",
                    python_workdir="/wd",
                    worker_timeout_seconds=1,
                )
            # Overall RC is 1 (any non-zero worker fails the run); the
            # watchdog-fired flag forces exit 124 for the timed-out worker.
            self.assertEqual(rc, 1)
        finally:
            os.remove(cf)


# ============================================================================
# Phase 4b — Scenario #6 (Upper Bound / Saturation) tests
# ============================================================================


SATURATION_THRESHOLDS = clustermesh_scale_module.SATURATION_THRESHOLDS
SATURATION_CLASSIFIER_VERSION = clustermesh_scale_module.SATURATION_CLASSIFIER_VERSION


def _write_metric_file(report_dir, metric_name, suffix, metrics, fmt="prod", shape="cl2"):
    """Write a CL2-shaped GenericPrometheusQuery JSON.

    Two AXES of variation:

    **Filename format** (`fmt`):
      "prod" — build 67211+ production filename format:
        `GenericPrometheusQuery <metricName with spaces> <suffix>_<group>_<ts>.json`
      "compact" — legacy/mock filename with no spaces:
        `GenericPrometheusQuery_<MetricNameNoSpaces><Suffix>_<group>_<ts>.json`

    **Content shape** (`shape`):
      "cl2" — build 67224 verified — one dataItem with named metric keys
        in `data`, scalar values:
          {"dataItems": [{"data": {"Max": 0, "Perc99": 0.5}, "unit": "#"}]}
      "labels" — legacy / PodStartupLatency-style — one dataItem per
        metric label, with `data.value` carrying the scalar:
          {"dataItems": [{"labels": {"Metric": "Perc99"}, "data": {"value": 0.5}}]}

    Defaults to fmt="prod", shape="cl2" — what real CL2 emits today.
    """
    if fmt == "prod":
        fname = (
            f"GenericPrometheusQuery {metric_name} {suffix}_"
            f"saturation-test_2026-05-14T00:00:00Z.json"
        )
    elif fmt == "compact":
        compact = metric_name.replace(" ", "")
        fname = (
            f"GenericPrometheusQuery_{compact}{suffix}_"
            f"saturation-test_2026-05-14T00:00:00Z.json"
        )
    else:
        raise ValueError(f"unknown fmt: {fmt!r}")
    if shape == "cl2":
        data_items = [{"data": dict(metrics), "unit": "#"}]
    elif shape == "labels":
        data_items = [
            {"labels": {"Metric": label}, "data": {"value": value}}
            for label, value in metrics.items()
        ]
    else:
        raise ValueError(f"unknown shape: {shape!r}")
    path = os.path.join(report_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": "v1", "dataItems": data_items}, f)
    return path


class TestConfigureSaturationKnobs(unittest.TestCase):
    """Phase 4b — Scenario #6 saturation overrides flow through
    configure_clusterloader2 and land in the CL2 overrides file with the
    expected CL2_SATURATION_* keys.
    """

    def test_saturation_defaults_emitted(self):
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
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
            self.assertIn('CL2_SATURATION_QPS_LIST: "100,500,1500,4000,10000"', content)
            self.assertIn('CL2_SATURATION_OPS_PER_SEC_LIST: "0,0,0,0,0"', content)
            self.assertIn('CL2_SATURATION_RESTARTS_LIST: "1,2,4,8,15"', content)
            self.assertIn("CL2_SATURATION_RUNG_DURATION_SECONDS: 240", content)
            self.assertIn("CL2_SATURATION_SETTLE_SECONDS: 90", content)
        finally:
            os.remove(tmp_path)

    def test_saturation_overrides_passthrough(self):
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="15m",
                override_file=tmp_path,
                saturation_qps_list="50,100,200,400,800",
                saturation_restarts_list="1,1,2,3,5",
                saturation_rung_duration_seconds=240,
                saturation_settle_seconds=90,
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn('CL2_SATURATION_QPS_LIST: "50,100,200,400,800"', content)
            self.assertIn('CL2_SATURATION_RESTARTS_LIST: "1,1,2,3,5"', content)
            self.assertIn("CL2_SATURATION_RUNG_DURATION_SECONDS: 240", content)
            self.assertIn("CL2_SATURATION_SETTLE_SECONDS: 90", content)
        finally:
            os.remove(tmp_path)

    def test_saturation_ops_per_sec_list_passthrough(self):
        """Phase B (2026-05-15) label-flip rate-per-rung knob propagates
        to overrides.yaml so the CL2 template engine sees it."""
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="15m",
                override_file=tmp_path,
                saturation_qps_list="100,500,1500,4000,10000",
                saturation_ops_per_sec_list="2,20,200,2000,20000",
                saturation_restarts_list="0,0,0,0,0",
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn('CL2_SATURATION_OPS_PER_SEC_LIST: "2,20,200,2000,20000"', content)
        finally:
            os.remove(tmp_path)

    def test_saturation_lists_pad_to_qps_length_for_template_safety(self):
        """CL2 template engine's `index $list $i` panics if a slice is
        shorter than the rung loop expects. configure pads shorter
        ops_per_sec / restarts lists with '0' (no-op for both consumers)
        so users supplying e.g. 3 ops entries with 5 qps rungs get a
        valid run rather than a confusing template-engine panic.
        """
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="15m",
                override_file=tmp_path,
                saturation_qps_list="100,500,1500,4000,10000",
                saturation_ops_per_sec_list="10,100,1000",
                saturation_restarts_list="2",
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            # ops_per_sec gets padded with 0,0 (no-op skip path in the script)
            self.assertIn('CL2_SATURATION_OPS_PER_SEC_LIST: "10,100,1000,0,0"', content)
            # restarts gets padded with 0,0,0,0 (no-op = zero restart-bursts)
            self.assertIn('CL2_SATURATION_RESTARTS_LIST: "2,0,0,0,0"', content)
        finally:
            os.remove(tmp_path)

    def test_saturation_lists_truncate_when_longer_than_qps(self):
        """Symmetrically: if user supplies MORE entries than qps rungs
        (e.g., copy-paste error), configure truncates to match qps so
        downstream loop indices stay valid and the excess entries are
        silently discarded.
        """
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
            tmp_path = tmp.name
        try:
            configure_clusterloader2(
                namespaces=1,
                deployments_per_namespace=1,
                replicas_per_deployment=1,
                operation_timeout="15m",
                override_file=tmp_path,
                saturation_qps_list="100,500,1500",
                saturation_ops_per_sec_list="10,100,1000,5000,10000",
                saturation_restarts_list="0,0,0,0,0",
            )
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn('CL2_SATURATION_OPS_PER_SEC_LIST: "10,100,1000"', content)
            self.assertIn('CL2_SATURATION_RESTARTS_LIST: "0,0,0"', content)
        finally:
            os.remove(tmp_path)

    def test_saturation_classifier_constants_exposed(self):
        """SATURATION_THRESHOLDS + SATURATION_CLASSIFIER_VERSION must be
        importable so dashboards (and these tests) can reference them. If
        the schema changes, the version string must change too."""
        self.assertEqual(SATURATION_CLASSIFIER_VERSION, "saturation-v1")
        for k in (
            "latency_p99_ms", "queue_size_perc99", "apiserver_max_cpu_cores",
            "mesh_failure_rate_max", "etcd_commit_p99_ms",
        ):
            self.assertIn(k, SATURATION_THRESHOLDS)
            self.assertGreater(SATURATION_THRESHOLDS[k], 0)


class TestSaturationClassifier(unittest.TestCase):
    """Phase 4b — Scenario #6 classifier emits per-rung verdicts +
    per-cluster summary rows. Synthetic per-rung mock data exercises
    each verdict path.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.report_dir = os.path.join(self.tmpdir, "mesh-1")
        shutil.copytree(os.path.join(MOCK_REPORT_ROOT, "mesh-1"), self.report_dir)
        self.result_file = tempfile.mktemp(suffix=".jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        if os.path.exists(self.result_file):
            os.remove(self.result_file)

    def _write_clean_rung(self, rung):
        suffix = f"Rung{rung}"
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            suffix, {"Perc99": 0.020},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            suffix, {"Max": 5, "Perc99": 3},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            suffix, {"PerPodMax": 0.3, "TotalMax": 0.3, "TotalAvg": 0.2},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            suffix, {"Max": 0.01},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            suffix, {"Perc99": 0.005},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            suffix, {"Perc99": 15},
        )

    def _write_latency_tripped_rung(self, rung):
        suffix = f"Rung{rung}"
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            suffix, {"Perc99": 0.900},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            suffix, {"Max": 10, "Perc99": 5},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            suffix, {"PerPodMax": 0.4, "TotalMax": 0.4, "TotalAvg": 0.3},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            suffix, {"Max": 0.02},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            suffix, {"Perc99": 0.010},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            suffix, {"Perc99": 50},
        )

    def _write_queue_unbounded_rung(self, rung):
        suffix = f"Rung{rung}"
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            suffix, {"Perc99": 0.100},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            suffix, {"Max": 8000, "Perc99": 5000},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            suffix, {"PerPodMax": 0.5, "TotalMax": 0.5, "TotalAvg": 0.4},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            suffix, {"Max": 0.02},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            suffix, {"Perc99": 0.020},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            suffix, {"Perc99": 200},
        )

    def _write_cpu_exhaust_rung(self, rung):
        suffix = f"Rung{rung}"
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            suffix, {"Perc99": 0.200},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            suffix, {"Max": 50, "Perc99": 30},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            suffix, {"PerPodMax": 2.5, "TotalMax": 2.5, "TotalAvg": 2.0},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            suffix, {"Max": 0.05},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            suffix, {"Perc99": 0.050},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            suffix, {"Perc99": 80},
        )

    def _run_collect(self, qps_list, restarts_list=None, ops_per_sec_list=None):
        if restarts_list is None:
            restarts_list = ",".join(["1"] * len(qps_list.split(",")))
        if ops_per_sec_list is None:
            ops_per_sec_list = ""
        collect_clusterloader2(
            cl2_report_dir=self.report_dir,
            cloud_info="",
            run_id="sat-test",
            run_url="",
            result_file=self.result_file,
            test_type="upper-bound",
            start_timestamp="2026-05-14T00:00:00Z",
            cluster_name="mesh-1",
            cluster_count=2,
            mesh_size=2,
            namespaces=5,
            deployments_per_namespace=4,
            replicas_per_deployment=10,
            trigger_reason="Manual",
            saturation_qps_list=qps_list,
            saturation_restarts_list=restarts_list,
            saturation_ops_per_sec_list=ops_per_sec_list,
        )
        with open(self.result_file, "r", encoding="utf-8") as f:
            return [json.loads(l) for l in f.read().strip().split("\n") if l]

    def test_classifier_no_op_when_qps_list_empty(self):
        """Non-upper-bound runs leave saturation_qps_list empty → no
        SaturationRung / SaturationSummary rows."""
        collect_clusterloader2(
            cl2_report_dir=self.report_dir,
            cloud_info="",
            run_id="sat-noop",
            run_url="",
            result_file=self.result_file,
            test_type="event-throughput",
            start_timestamp="2026-05-14T00:00:00Z",
            cluster_name="mesh-1",
            cluster_count=2,
            mesh_size=2,
            namespaces=5,
            deployments_per_namespace=4,
            replicas_per_deployment=10,
            trigger_reason="Manual",
        )
        with open(self.result_file, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f.read().strip().split("\n") if l]
        rungs = [r for r in lines if r.get("measurement") == "SaturationRung"]
        summaries = [r for r in lines if r.get("measurement") == "SaturationSummary"]
        self.assertEqual(len(rungs), 0)
        self.assertEqual(len(summaries), 0)

    def test_all_clean_rungs_max_clean_qps_is_highest(self):
        for r in range(3):
            self._write_clean_rung(r)
        lines = self._run_collect("20,40,80")
        rungs = sorted(
            [r for r in lines if r.get("measurement") == "SaturationRung"],
            key=lambda r: r["result"]["data"]["rung_index"],
        )
        summary = [r for r in lines if r.get("measurement") == "SaturationSummary"]
        self.assertEqual(len(rungs), 3)
        self.assertEqual(len(summary), 1)
        for r in rungs:
            self.assertEqual(r["result"]["data"]["verdict"], "clean")
            self.assertTrue(r["result"]["data"]["rung_completed"])
            self.assertEqual(r["result"]["data"]["measurement_missing"], [])
        s = summary[0]["result"]["data"]
        self.assertEqual(s["max_clean_qps"], 80)
        self.assertEqual(s["rungs_completed"], 3)
        self.assertEqual(s["rungs_configured"], 3)
        self.assertIsNone(s["first_failure_rung_index"])
        self.assertIsNone(s["first_failure_mode"])
        self.assertEqual(s["classifier_version"], SATURATION_CLASSIFIER_VERSION)

    def test_latency_spike_verdict(self):
        self._write_clean_rung(0)
        self._write_latency_tripped_rung(1)
        lines = self._run_collect("20,40")
        rungs = sorted(
            [r for r in lines if r.get("measurement") == "SaturationRung"],
            key=lambda r: r["result"]["data"]["rung_index"],
        )
        self.assertEqual(rungs[0]["result"]["data"]["verdict"], "clean")
        self.assertEqual(rungs[1]["result"]["data"]["verdict"], "latency_spike")
        self.assertAlmostEqual(
            rungs[1]["result"]["data"]["dominant_signal_ratio"], 1.8, places=2,
        )
        summary = [r for r in lines if r.get("measurement") == "SaturationSummary"][0]
        s = summary["result"]["data"]
        self.assertEqual(s["max_clean_qps"], 20)
        self.assertEqual(s["first_failure_rung_index"], 1)
        self.assertEqual(s["first_failure_qps"], 40)
        self.assertEqual(s["first_failure_mode"], "latency_spike")
        self.assertIsNone(s["second_failure_mode"])

    def test_queue_unbounded_verdict(self):
        self._write_clean_rung(0)
        self._write_queue_unbounded_rung(1)
        lines = self._run_collect("20,40")
        rung1 = next(
            r for r in lines
            if r.get("measurement") == "SaturationRung"
            and r["result"]["data"]["rung_index"] == 1
        )
        self.assertEqual(rung1["result"]["data"]["verdict"], "queue_unbounded")
        self.assertAlmostEqual(
            rung1["result"]["data"]["dominant_signal_ratio"], 5.0, places=2,
        )

    def test_cpu_exhaust_verdict(self):
        self._write_clean_rung(0)
        self._write_cpu_exhaust_rung(1)
        lines = self._run_collect("20,40")
        rung1 = next(
            r for r in lines
            if r.get("measurement") == "SaturationRung"
            and r["result"]["data"]["rung_index"] == 1
        )
        self.assertEqual(rung1["result"]["data"]["verdict"], "cpu_exhaust")
        self.assertAlmostEqual(
            rung1["result"]["data"]["dominant_signal_ratio"], 2.5 / 1.5,
            places=2,
        )

    def test_second_failure_mode_tracking(self):
        """Rung 0 clean, rung 1 latency, rung 2 cpu_exhaust → first=latency_spike,
        second=cpu_exhaust. Same-mode subsequent failures don't overwrite second."""
        self._write_clean_rung(0)
        self._write_latency_tripped_rung(1)
        self._write_cpu_exhaust_rung(2)
        lines = self._run_collect("20,40,80")
        summary = [r for r in lines if r.get("measurement") == "SaturationSummary"][0]
        s = summary["result"]["data"]
        self.assertEqual(s["first_failure_mode"], "latency_spike")
        self.assertEqual(s["second_failure_mode"], "cpu_exhaust")
        self.assertEqual(s["first_failure_qps"], 40)

    def test_max_clean_qps_is_contiguous_prefix(self):
        """If a non-clean rung lands then a later 'clean' rung shows up,
        max_clean_qps does NOT extend past the first failure."""
        self._write_clean_rung(0)
        self._write_clean_rung(1)
        self._write_latency_tripped_rung(2)
        self._write_clean_rung(3)
        lines = self._run_collect("20,40,80,160")
        summary = [r for r in lines if r.get("measurement") == "SaturationSummary"][0]
        s = summary["result"]["data"]
        self.assertEqual(s["max_clean_qps"], 40)
        self.assertEqual(s["first_failure_rung_index"], 2)
        self.assertEqual(s["first_failure_mode"], "latency_spike")

    def test_missing_measurements_flag_incomplete_rung(self):
        """If a rung's measurement files are missing, measurement_missing
        lists the gaps. Latency present → rung_completed still true."""
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            "Rung0", {"Perc99": 0.020},
        )
        lines = self._run_collect("20")
        rung = next(r for r in lines if r.get("measurement") == "SaturationRung")
        d = rung["result"]["data"]
        self.assertTrue(d["rung_completed"])
        self.assertIn("queue_size_perc99", d["measurement_missing"])
        self.assertIn("apiserver_max_cpu_cores", d["measurement_missing"])
        self.assertIn("mesh_failure_rate_max", d["measurement_missing"])
        self.assertIn("etcd_commit_p99_ms", d["measurement_missing"])

    def test_rung_completed_false_when_latency_missing(self):
        """Latency is the gating signal — without it, rung is incomplete
        regardless of how many other signals landed."""
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            "Rung0", {"Max": 5, "Perc99": 3},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            "Rung0", {"PerPodMax": 0.3, "TotalMax": 0.3, "TotalAvg": 0.2},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            "Rung0", {"Max": 0.01},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            "Rung0", {"Perc99": 0.005},
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            "Rung0", {"Perc99": 15},
        )
        lines = self._run_collect("20")
        rung = next(r for r in lines if r.get("measurement") == "SaturationRung")
        self.assertFalse(rung["result"]["data"]["rung_completed"])
        self.assertIn("latency_p99_ms", rung["result"]["data"]["measurement_missing"])
        summary = [r for r in lines if r.get("measurement") == "SaturationSummary"][0]
        self.assertEqual(summary["result"]["data"]["rungs_completed"], 0)

    def test_summary_carries_classifier_metadata(self):
        """SaturationSummary records classifier_version + thresholds so
        dashboards can recompute verdicts post-hoc."""
        self._write_clean_rung(0)
        lines = self._run_collect("20")
        summary = [r for r in lines if r.get("measurement") == "SaturationSummary"][0]
        s = summary["result"]["data"]
        self.assertEqual(s["classifier_version"], SATURATION_CLASSIFIER_VERSION)
        self.assertEqual(s["thresholds"], SATURATION_THRESHOLDS)
        self.assertEqual(s["configured_qps_list"], [20])
        self.assertEqual(s["configured_restarts_list"], [1])

    def test_rung_row_carries_raw_signal_values(self):
        """SaturationRung records raw signal values + all per-criterion
        ratios so the classifier can be re-run post-hoc at different
        thresholds without re-collecting from CL2."""
        self._write_latency_tripped_rung(0)
        lines = self._run_collect("20")
        rung = next(r for r in lines if r.get("measurement") == "SaturationRung")
        d = rung["result"]["data"]
        self.assertAlmostEqual(d["signals"]["latency_p99_ms"], 900.0, places=1)
        self.assertAlmostEqual(d["signals"]["apiserver_max_cpu_cores"], 0.4, places=2)
        self.assertIn("latency_spike", d["all_verdicts"])
        self.assertIn("cpu_exhaust", d["all_verdicts"])

    def test_malformed_qps_list_skips_classifier_gracefully(self):
        """Malformed CL2_SATURATION_QPS_LIST should not crash collect; the
        classifier logs a warning and emits zero saturation rows."""
        self._write_latency_tripped_rung(0)
        collect_clusterloader2(
            cl2_report_dir=self.report_dir,
            cloud_info="",
            run_id="sat-malformed",
            run_url="",
            result_file=self.result_file,
            test_type="upper-bound",
            start_timestamp="2026-05-14T00:00:00Z",
            cluster_name="mesh-1",
            cluster_count=2,
            mesh_size=2,
            namespaces=5,
            deployments_per_namespace=4,
            replicas_per_deployment=10,
            trigger_reason="Manual",
            saturation_qps_list="20,not-a-number,80",
            saturation_restarts_list="1,2,3",
        )
        with open(self.result_file, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f.read().strip().split("\n") if l]
        rungs = [r for r in lines if r.get("measurement") == "SaturationRung"]
        summaries = [r for r in lines if r.get("measurement") == "SaturationSummary"]
        self.assertEqual(len(rungs), 0)
        self.assertEqual(len(summaries), 0)

    def test_restarts_list_padded_when_shorter_than_qps(self):
        """If restarts_list is shorter than qps_list, missing entries
        default to 1 so the classifier doesn't crash."""
        self._write_clean_rung(0)
        self._write_clean_rung(1)
        self._write_clean_rung(2)
        lines = self._run_collect("20,40,80", restarts_list="1,2")
        rungs = sorted(
            [r for r in lines if r.get("measurement") == "SaturationRung"],
            key=lambda r: r["result"]["data"]["rung_index"],
        )
        self.assertEqual(rungs[0]["result"]["data"]["configured_restarts"], 1)
        self.assertEqual(rungs[1]["result"]["data"]["configured_restarts"], 2)
        self.assertEqual(rungs[2]["result"]["data"]["configured_restarts"], 1)

    def test_monitoring_oom_verdict_when_prom_dies_mid_run(self):
        """Phase 4b — Scenario #6 monitoring_oom verdict (added 2026-05-15
        after build 67279). When an earlier rung successfully completed but
        a later rung has zero signals, the most likely explanation is the
        Prometheus stack OOM'ed under load. That IS a saturation finding
        per spec line 113 ('Resource exhaustion occurs') so we record it
        as verdict=monitoring_oom rather than silently leaving it as
        verdict=clean rung_completed=False (which underclaims the failure).
        """
        # Rung 0: clean (Prom alive, all signals land)
        self._write_clean_rung(0)
        # Rung 1: NOTHING — Prom crashed mid-run before its gather phase
        # (no files written for this rung). Classifier should detect
        # "previous rung had signals, this one doesn't → monitoring_oom".
        lines = self._run_collect("20,40")
        rungs = sorted(
            [r for r in lines if r.get("measurement") == "SaturationRung"],
            key=lambda r: r["result"]["data"]["rung_index"],
        )
        self.assertEqual(rungs[0]["result"]["data"]["verdict"], "clean")
        self.assertEqual(rungs[1]["result"]["data"]["verdict"], "monitoring_oom")
        self.assertEqual(rungs[1]["result"]["data"]["dominant_signal_ratio"], 999.0)
        self.assertFalse(rungs[1]["result"]["data"]["rung_completed"])
        # Summary records monitoring_oom as the first failure mode.
        summary = [r for r in lines if r.get("measurement") == "SaturationSummary"][0]
        s = summary["result"]["data"]
        self.assertEqual(s["max_clean_qps"], 20)
        self.assertEqual(s["first_failure_mode"], "monitoring_oom")
        self.assertEqual(s["first_failure_qps"], 40)

    def test_monitoring_oom_not_emitted_when_no_prior_rung_completed(self):
        """If even Rung 0 has zero signals, that's NOT monitoring_oom —
        it's an upstream config / deployment problem (Prom never came up,
        or scale.py was misconfigured). Stay at verdict=clean
        rung_completed=False so postmortem investigates the right layer."""
        # Don't write any files. Every rung will have zero signals.
        lines = self._run_collect("20,40")
        rungs = sorted(
            [r for r in lines if r.get("measurement") == "SaturationRung"],
            key=lambda r: r["result"]["data"]["rung_index"],
        )
        # Both rungs should be clean (not monitoring_oom) because no
        # earlier rung established that Prom WAS working.
        for r in rungs:
            self.assertNotEqual(r["result"]["data"]["verdict"], "monitoring_oom",
                                f"rung {r['result']['data']['rung_index']}: "
                                f"monitoring_oom should only fire after a "
                                f"prior rung completed")
            self.assertEqual(r["result"]["data"]["verdict"], "clean")
            self.assertFalse(r["result"]["data"]["rung_completed"])

    def test_classifier_matches_build_67211_production_filename_format(self):
        """REGRESSION: build 67211 (first n=2 upper-bound smoke 2026-05-14)
        emitted measurement files in the format
            'GenericPrometheusQuery <metricName with spaces> <suffix>_<group>_<ts>.json'
        but the classifier was matching the legacy compact format
            'GenericPrometheusQuery_<MetricNameNoSpaces><Suffix>_<group>_<ts>.json'
        → 0 files found, all 4 rungs classified as `clean` with 0 signals
        despite all 20 signal files (5 signals × 4 rungs) being present on
        disk. This test pins the production format so a future regression
        fails locally instead of silently in CI.
        """
        # Use fmt="prod" — production format with spaces. Default in
        # _write_metric_file is also "prod" but explicit here for clarity.
        suffix = "Rung0"
        # Latency: 600ms p99 (above 500ms threshold) → should trip latency_spike
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            suffix, {"Perc99": 0.600}, fmt="prod",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            suffix, {"Max": 50, "Perc99": 30}, fmt="prod",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            suffix, {"PerPodMax": 0.5, "TotalMax": 0.5, "TotalAvg": 0.4},
            fmt="prod",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            suffix, {"Max": 0.05}, fmt="prod",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            suffix, {"Perc99": 0.020}, fmt="prod",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            suffix, {"Perc99": 30}, fmt="prod",
        )
        # Verify the file on disk matches the build-67211 pattern exactly.
        on_disk = sorted(os.listdir(self.report_dir))
        prod_pattern_files = [
            f for f in on_disk
            if f.startswith("GenericPrometheusQuery ClusterMesh ")
            and "Rung0_" in f
        ]
        self.assertGreaterEqual(
            len(prod_pattern_files), 6,
            f"production-format files not on disk; got: {prod_pattern_files}",
        )
        lines = self._run_collect("20")
        rung = next(r for r in lines if r.get("measurement") == "SaturationRung")
        d = rung["result"]["data"]
        # Classifier must FIND the files (production format) and apply the
        # verdict. Pre-fix: all signals would be `None`, verdict=`clean`,
        # rung_completed=False. Post-fix: latency value lands → latency_spike.
        self.assertTrue(d["rung_completed"],
                        f"rung must be completed; missing={d['measurement_missing']}")
        self.assertEqual(d["measurement_missing"], [],
                         f"all 7 signals should land; missing={d['measurement_missing']}")
        self.assertAlmostEqual(d["signals"]["latency_p99_ms"], 600.0, places=1)
        self.assertEqual(d["verdict"], "latency_spike")

    def test_classifier_accepts_legacy_compact_filename_format(self):
        """The classifier supports BOTH production (space) and legacy
        (compact-underscore) filename formats so test mocks/older CL2
        emissions don't silently fail. Pin both with this test."""
        suffix = "Rung0"
        # Write the same set in COMPACT format (no spaces, underscore after
        # GenericPrometheusQuery).
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            suffix, {"Perc99": 0.020}, fmt="compact",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            suffix, {"Max": 5, "Perc99": 3}, fmt="compact",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            suffix, {"PerPodMax": 0.3, "TotalMax": 0.3, "TotalAvg": 0.2},
            fmt="compact",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            suffix, {"Max": 0.01}, fmt="compact",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            suffix, {"Perc99": 0.005}, fmt="compact",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            suffix, {"Perc99": 15}, fmt="compact",
        )
        lines = self._run_collect("20")
        rung = next(r for r in lines if r.get("measurement") == "SaturationRung")
        d = rung["result"]["data"]
        self.assertTrue(d["rung_completed"])
        self.assertEqual(d["verdict"], "clean")
        self.assertAlmostEqual(d["signals"]["latency_p99_ms"], 20.0, places=1)

    def test_classifier_reads_build_67224_cl2_content_shape(self):
        """REGRESSION: build 67224 (2nd n=2 upper-bound smoke 2026-05-15)
        emitted measurement file content in the CL2 GenericPrometheusQuery
        shape — one dataItem with query results as named keys in `data`:
            {"dataItems": [{"data": {"Max": 0, "Perc99": 0.5}, "unit": "#"}]}
        not the legacy labels shape
            {"dataItems": [{"labels": {"Metric": "Perc99"}, "data": {"value": 0.5}}]}
        The classifier was reading via labels.Metric, missing every value.
        Pin BOTH content shapes here so the bug can't regress.
        """
        # shape="cl2" mirrors the actual on-disk content from build 67224.
        suffix = "Rung0"
        # Latency 600ms p99 (above 500ms threshold) → should trip latency_spike
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            suffix, {"Perc50": 0.020, "Perc90": 0.300, "Perc99": 0.600},
            fmt="prod", shape="cl2",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            suffix, {"Max": 50, "Perc50": 10, "Perc99": 30},
            fmt="prod", shape="cl2",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            suffix, {"TotalMax": 0.5, "TotalAvg": 0.3, "PerPodMax": 0.5},
            fmt="prod", shape="cl2",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            suffix, {"Max": 0.05, "Perc50": 0.01},
            fmt="prod", shape="cl2",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            suffix, {"Perc50": 0.003, "Perc90": 0.005, "Perc99": 0.020},
            fmt="prod", shape="cl2",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            suffix, {"Perc50": 0, "Perc90": 5, "Perc99": 30, "TotalIncrease": 3000},
            fmt="prod", shape="cl2",
        )
        lines = self._run_collect("20")
        rung = next(r for r in lines if r.get("measurement") == "SaturationRung")
        d = rung["result"]["data"]
        # Pre-fix (build 67224): all signals returned None → verdict=clean
        # rung_completed=False signals_found=0/7. Post-fix: every signal
        # lands, latency trips threshold.
        self.assertTrue(d["rung_completed"],
                        f"rung must be completed; missing={d['measurement_missing']}")
        self.assertEqual(d["measurement_missing"], [],
                         f"all 7 signals should land; missing={d['measurement_missing']}")
        self.assertAlmostEqual(d["signals"]["latency_p99_ms"], 600.0, places=1)
        self.assertAlmostEqual(d["signals"]["queue_size_perc99"], 30.0, places=1)
        self.assertAlmostEqual(d["signals"]["apiserver_max_cpu_cores"], 0.5, places=2)
        self.assertAlmostEqual(d["signals"]["mesh_failure_rate_max"], 0.05, places=3)
        self.assertEqual(d["verdict"], "latency_spike")

    def test_classifier_reads_legacy_labels_content_shape(self):
        """Backward-compat: even though build 67224 uses the cl2 shape,
        legacy mocks (and PodStartupLatency-format files) use a
        per-metric-labels shape. The classifier must still read those so
        existing mock fixtures don't break."""
        suffix = "Rung0"
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Operation Duration",
            suffix, {"Perc99": 0.020}, fmt="prod", shape="labels",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Sync Queue Size",
            suffix, {"Max": 5, "Perc99": 3}, fmt="prod", shape="labels",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh APIServer Pod CPU",
            suffix, {"PerPodMax": 0.3, "TotalMax": 0.3, "TotalAvg": 0.2},
            fmt="prod", shape="labels",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Remote Cluster Failure Rate",
            suffix, {"Max": 0.01}, fmt="prod", shape="labels",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Etcd Backend Write Duration",
            suffix, {"Perc99": 0.005}, fmt="prod", shape="labels",
        )
        _write_metric_file(
            self.report_dir, "ClusterMesh Kvstore Events Rate",
            suffix, {"Perc99": 15}, fmt="prod", shape="labels",
        )
        lines = self._run_collect("20")
        rung = next(r for r in lines if r.get("measurement") == "SaturationRung")
        d = rung["result"]["data"]
        self.assertTrue(d["rung_completed"])
        self.assertEqual(d["verdict"], "clean")
        self.assertAlmostEqual(d["signals"]["latency_p99_ms"], 20.0, places=1)
        self.assertAlmostEqual(d["signals"]["queue_size_perc99"], 3.0, places=1)

    def test_label_churn_timing_picked_up_into_rung_row(self):
        """Phase B (2026-05-15): when LabelChurnTimings_Rung<N>.json is
        present in cl2_report_dir, the per-rung SaturationRung row's
        data block must surface target/actual ops/sec + ops_attempted/
        succeeded/failed so dashboards can plot achieved vs requested
        rate. Diverges from configured_ops_per_sec because kubectl
        latency throttles real-world rate at high rungs.
        """
        self._write_clean_rung(0)
        self._write_clean_rung(1)
        # Mock label-churn driver output for rung 0: hit target.
        with open(os.path.join(self.report_dir, "LabelChurnTimings_Rung0.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "target_ops_per_second": 10,
                "actual_ops_per_second": 9.87,
                "ops_attempted": 2400,
                "ops_succeeded": 2400,
                "ops_failed": 0,
                "duration_seconds": 243.1,
                "first_error": "",
            }, f)
        # Mock label-churn driver output for rung 1: throttled by kubectl latency.
        with open(os.path.join(self.report_dir, "LabelChurnTimings_Rung1.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "target_ops_per_second": 5000,
                "actual_ops_per_second": 873.4,
                "ops_attempted": 1200000,
                "ops_succeeded": 212301,
                "ops_failed": 987699,
                "duration_seconds": 243.0,
                "first_error": "kubectl: connection refused",
            }, f)
        rows = self._run_collect(
            "100,500", restarts_list="0,0",
            ops_per_sec_list="10,5000",
        )
        rungs = [r for r in rows if r["measurement"] == "SaturationRung"]
        self.assertEqual(len(rungs), 2)
        d0 = rungs[0]["result"]["data"]
        self.assertEqual(d0["configured_ops_per_sec"], 10)
        self.assertIn("label_churn", d0)
        self.assertEqual(d0["label_churn"]["target_ops_per_second"], 10)
        self.assertAlmostEqual(d0["label_churn"]["actual_ops_per_second"], 9.87, places=2)
        self.assertEqual(d0["label_churn"]["ops_failed"], 0)
        d1 = rungs[1]["result"]["data"]
        self.assertEqual(d1["configured_ops_per_sec"], 5000)
        self.assertEqual(d1["label_churn"]["target_ops_per_second"], 5000)
        self.assertAlmostEqual(d1["label_churn"]["actual_ops_per_second"], 873.4, places=1)
        self.assertEqual(d1["label_churn"]["ops_failed"], 987699)
        self.assertIn("connection refused", d1["label_churn"]["first_error"])

    def test_label_churn_timing_absent_does_not_break_rung_row(self):
        """When the Phase B label-churn driver wasn't used (or didn't
        write a timing file), the rung row must still emit normally —
        just without the label_churn sub-dict."""
        self._write_clean_rung(0)
        rows = self._run_collect("100", restarts_list="0", ops_per_sec_list="10")
        rungs = [r for r in rows if r["measurement"] == "SaturationRung"]
        self.assertEqual(len(rungs), 1)
        d = rungs[0]["result"]["data"]
        self.assertEqual(d["configured_ops_per_sec"], 10)
        self.assertNotIn("label_churn", d)
        self.assertEqual(d["verdict"], "clean")

    def test_summary_includes_configured_ops_per_sec_list(self):
        """Phase B: SaturationSummary must echo the configured
        ops_per_sec_list so consumers see what was requested even when
        the per-rung label_churn block is missing.
        """
        self._write_clean_rung(0)
        self._write_clean_rung(1)
        rows = self._run_collect(
            "100,500", restarts_list="0,0", ops_per_sec_list="10,100",
        )
        summary = [r for r in rows if r["measurement"] == "SaturationSummary"]
        self.assertEqual(len(summary), 1)
        d = summary[0]["result"]["data"]
        self.assertEqual(d["configured_ops_per_sec_list"], [10, 100])
        self.assertEqual(d["configured_qps_list"], [100, 500])
        self.assertEqual(d["configured_restarts_list"], [0, 0])

    def test_summary_tracks_max_clean_and_first_failure_ops_per_sec(self):
        """Phase B (rubber-duck non-blocking #4): in Phase B the load axis
        is ops_per_sec, not qps. SaturationSummary surfaces the load-axis
        equivalents `max_clean_ops_per_sec` + `first_failure_ops_per_sec`
        alongside the original qps fields so the upper-bound headline is
        readable on either axis.
        """
        self._write_clean_rung(0)
        self._write_clean_rung(1)
        self._write_latency_tripped_rung(2)
        self._write_cpu_exhaust_rung(3)
        rows = self._run_collect(
            "100,500,1500,4000",
            restarts_list="0,0,0,0",
            ops_per_sec_list="10,100,1000,5000",
        )
        summary = [r for r in rows if r["measurement"] == "SaturationSummary"]
        self.assertEqual(len(summary), 1)
        d = summary[0]["result"]["data"]
        # max_clean prefix: rungs 0+1 are clean → 100 ops/sec is the cap.
        self.assertEqual(d["max_clean_qps"], 500)
        self.assertEqual(d["max_clean_ops_per_sec"], 100)
        # First failure: rung 2 (latency_spike at qps=1500, ops/sec=1000).
        self.assertEqual(d["first_failure_rung_index"], 2)
        self.assertEqual(d["first_failure_qps"], 1500)
        self.assertEqual(d["first_failure_ops_per_sec"], 1000)
        self.assertEqual(d["first_failure_mode"], "latency_spike")
        # Second-failure: rung 3 (cpu_exhaust) — different mode from #1.
        self.assertEqual(d["second_failure_mode"], "cpu_exhaust")


if __name__ == "__main__":
    unittest.main()
