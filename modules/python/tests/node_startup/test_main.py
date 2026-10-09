"""Iteration loop: per-iteration filtering, deadline, settle wait, inputs, output file (plan 6a, 9.10)."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from clients.kubernetes_client import KubernetesClient
from node_startup import main
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, kubernetes_client
from tests.node_startup.test_record import AKS_CLUSTER
from tests.node_startup.test_validation import VALID_MEASUREMENT

NOW = 1_800_000_000


def valid_result(iteration):
    return {
        "measurement": {**VALID_MEASUREMENT, "node_name": f"aks-userpool-vmss00000{iteration}", "latencies": {}},
        "environment": {"defender_sensor_present": False},
        "existing_nodes": {scenarios.EXISTING_NODE},
    }


class FakeClock:
    """time.time() stand-in that advances by `step` seconds per call."""

    def __init__(self, step=0):
        self.now = NOW
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


class RunTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.directory.cleanup)
        self.cluster_file = os.path.join(self.directory.name, "aks.json")
        with open(self.cluster_file, "w", encoding="utf-8") as file:
            json.dump(AKS_CLUSTER, file)
        self.records_file = os.path.join(self.directory.name, "records.jsonl")
        self.api = FakeCoreV1Api()
        settle = mock.patch("node_startup.probe.wait_for_pool_settled")
        self.settle = settle.start()
        self.addCleanup(settle.stop)

    def args(self, *extra):
        return main.parse_args([
            "--scenario", "managed-cilium",
            "--provisioner", "cluster-autoscaler",
            "--cluster-info-file", self.cluster_file,
            "--node-pool-name", "userpool",
            "--node-label-key", "agentpool",
            "--cni-daemonset-label", scenarios.CILIUM_LABEL,
            "--cni-blocking-taint", scenarios.CILIUM_TAINT,
            "--supplementary-cni-pod", "azure_cns=k8s-app=azure-cns",
            "--probe-namespace", scenarios.PROBE_NAMESPACE,
            "--iterations", "5",
            "--iteration-cooldown-seconds", "240",
            "--step-timeout-seconds", "600",
            "--deadline-epoch-seconds", str(NOW + 3600),
            "--uses-default-settings", "true",
            "--records-file", self.records_file,
            *extra,
        ])

    def run_with(self, outcomes, args=None, clock=None):
        """Run main.run with measure_iteration returning/raising `outcomes` in order."""
        sleep = mock.Mock()
        stdout = io.StringIO()
        with mock.patch("node_startup.main.measure_iteration", side_effect=outcomes) as measure, \
                contextlib.redirect_stdout(stdout):
            exit_code = main.run(args or self.args(), kubernetes_client(KubernetesClient, self.api),
                                 clock=clock or FakeClock(), sleep=sleep)
        return exit_code, measure, sleep, stdout.getvalue()

    def records(self):
        with open(self.records_file, encoding="utf-8") as file:
            return [json.loads(line) for line in file]

    def test_all_valid(self):
        exit_code, measure, sleep, stdout = self.run_with([valid_result(i) for i in range(1, 6)])
        self.assertEqual(exit_code, 0)
        self.assertEqual([r["iteration"] for r in self.records()], [1, 2, 3, 4, 5])
        self.assertEqual({r["valid_iterations"] for r in self.records()}, {5})
        self.assertEqual(stdout, "")
        self.assertEqual(sleep.call_args_list, [mock.call(240)] * 4)
        self.assertEqual(measure.call_args_list[0].kwargs["pod_name"], "latency-probe-1")
        self.assertEqual(measure.call_args_list[0].kwargs["operation_timeout_in_minutes"], 10)
        self.assertEqual(measure.call_args_list[0].kwargs["supplementary_cni_pods"], {"azure_cns": "k8s-app=azure-cns"})
        self.assertEqual(self.api.created_namespaces, [scenarios.PROBE_NAMESPACE])

    def test_failed_iteration_is_dropped_and_others_uploaded(self):
        outcomes = [valid_result(1), valid_result(2), RuntimeError("probe never ran"), valid_result(4),
                    valid_result(5)]
        exit_code, measure, _, stdout = self.run_with(outcomes)
        self.assertEqual(exit_code, 0)
        self.assertEqual(measure.call_count, 5)
        self.assertEqual([r["iteration"] for r in self.records()], [1, 2, 4, 5])
        self.assertEqual({r["valid_iterations"] for r in self.records()}, {4})
        self.assertEqual({r["total_iterations"] for r in self.records()}, {5})
        self.settle.assert_called_once()
        self.assertIn("iteration 3 failed: probe never ran", stdout)
        self.assertIn("##vso[task.complete result=SucceededWithIssues;]", stdout)

    def test_invalid_iterations_are_dropped(self):
        missing = valid_result(2)
        missing["measurement"]["cni_taint_cleared"] = None
        reused = valid_result(1)
        exit_code, _, _, stdout = self.run_with([valid_result(1), missing, reused, valid_result(4), valid_result(5)])
        self.assertEqual(exit_code, 0)
        self.assertEqual([r["iteration"] for r in self.records()], [1, 4, 5])
        self.assertIn("iteration 2 invalid: missing cni_taint_cleared", stdout)
        self.assertIn("iteration 3 invalid: node aks-userpool-vmss000001 already used", stdout)
        self.settle.assert_not_called()

    def test_no_valid_iteration_writes_nothing(self):
        exit_code, _, _, _ = self.run_with([RuntimeError("boom")] * 5)
        self.assertEqual(exit_code, 1)
        self.assertFalse(os.path.exists(self.records_file))

    def test_deadline_skips_remaining_iterations(self):
        # Each clock() call advances 10 minutes; the deadline is an hour away, so only 2 iterations start.
        exit_code, measure, _, stdout = self.run_with([valid_result(1), valid_result(2)], clock=FakeClock(step=600))
        self.assertEqual(exit_code, 0)
        self.assertEqual(measure.call_count, 2)
        self.assertEqual([r["total_iterations"] for r in self.records()], [5, 5])
        self.assertIn("iteration 3 skipped: deadline passed", stdout)

    def test_cooldown_that_would_end_past_the_deadline_is_skipped(self):
        # Deadline is 10 minutes away; a 240 s cooldown fits once, then not again.
        args = self.args("--deadline-epoch-seconds", str(NOW + 600))
        exit_code, measure, sleep, stdout = self.run_with([valid_result(1), valid_result(2)], args=args,
                                                          clock=FakeClock(step=60))
        self.assertEqual(exit_code, 0)
        self.assertEqual(measure.call_count, 2)
        self.assertEqual(sleep.call_args_list, [mock.call(240)])
        self.assertIn("iteration 3 skipped: deadline passed", stdout)
        self.assertIn("iteration 5 skipped: deadline passed", stdout)

    def test_settle_wait_errors_do_not_lose_valid_iterations(self):
        self.settle.side_effect = RuntimeError("API server unavailable")
        exit_code, _, _, _ = self.run_with([valid_result(1), RuntimeError("boom"), valid_result(3),
                                            valid_result(4), valid_result(5)])
        self.assertEqual(exit_code, 0)
        self.assertEqual([r["iteration"] for r in self.records()], [1, 3, 4, 5])

    def test_settle_wait_is_capped_at_the_deadline_and_skipped_after_the_last_iteration(self):
        args = self.args("--deadline-epoch-seconds", str(NOW + 300), "--iteration-cooldown-seconds", "0",
                         "--iterations", "2")
        self.run_with([RuntimeError("boom"), RuntimeError("boom")], args=args)
        self.settle.assert_called_once()
        self.assertLessEqual(self.settle.call_args.kwargs["timeout_seconds"], 300)

    def test_overrides_are_recorded(self):
        args = self.args("--iterations", "7", "--iteration-cooldown-seconds", "120",
                         "--uses-default-settings", "false")
        self.run_with([valid_result(i) for i in range(1, 8)], args=args)
        first = self.records()[0]
        self.assertEqual(first["total_iterations"], 7)
        self.assertEqual(first["config"]["iteration_cooldown_seconds"], 120)
        self.assertFalse(first["config"]["uses_default_settings"])

    def test_record_contents(self):
        self.run_with([valid_result(i) for i in range(1, 6)])
        first = self.records()[0]
        self.assertEqual(first["scenario"], "managed-cilium")
        self.assertEqual(first["cluster"]["network_dataplane"], "cilium")
        self.assertEqual(first["config"]["cni_readiness_signal"], "cni_pod_ready")
        self.assertEqual(first["config"]["probe_namespace"], scenarios.PROBE_NAMESPACE)
        self.assertEqual(first["measurement"]["iteration"], 1)
        self.assertEqual(first["measurement"]["total_iterations"], 5)
        self.assertTrue(first["operation"]["success"])

    def test_karpenter_pools_skip_the_settle_wait(self):
        args = self.args("--node-label-key", "karpenter.sh/nodepool")
        self.run_with([RuntimeError("boom"), valid_result(2), valid_result(3), valid_result(4), valid_result(5)],
                      args=args)
        self.settle.assert_not_called()


class ParseArgsTest(unittest.TestCase):
    REQUIRED = [
        "--scenario", "s", "--provisioner", "p", "--cluster-info-file", "f", "--node-pool-name", "n",
        "--node-label-key", "agentpool", "--probe-namespace", "ns", "--step-timeout-seconds", "600",
        "--deadline-epoch-seconds", "1", "--records-file", "r",
    ]

    def parse(self, *extra):
        with contextlib.redirect_stderr(io.StringIO()):
            return main.parse_args(self.REQUIRED + list(extra))

    def test_invalid_values_are_rejected(self):
        for extra in (
            ["--iterations", "0", "--iteration-cooldown-seconds", "0", "--uses-default-settings", "true"],
            ["--iterations", "5", "--iteration-cooldown-seconds", "-1", "--uses-default-settings", "true"],
            ["--iterations", "5", "--iteration-cooldown-seconds", "0", "--uses-default-settings", "maybe"],
            ["--iterations", "5", "--iteration-cooldown-seconds", "0", "--uses-default-settings", "true",
             "--supplementary-cni-pod", "no-selector"],
        ):
            with self.subTest(extra=extra), self.assertRaises(SystemExit):
                self.parse(*extra)

    def test_ado_boolean_rendering(self):
        args = self.parse("--iterations", "5", "--iteration-cooldown-seconds", "0", "--uses-default-settings", "True")
        self.assertTrue(args.uses_default_settings)


if __name__ == "__main__":
    unittest.main()
