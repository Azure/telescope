#!/usr/bin/env python3
"""Unit tests for AKSMachineClient (subclass of AKSClient).

All public methods open an ``OperationContext`` (patched here) and write the
result file via ``Operation.save_to_file`` on context exit. Tests verify:
- success path completes without raising and enriches ``op.add_metadata`` with
  the right keys
- failure path raises (so the OperationContext records ``success=False``)

This revision adds tests for both scale paths (non-batch individual PUTs and
the BatchPutMachine-headered chunked path) plus the batch-path helpers
``_scale_machine_batch``, ``_create_batch_machines``, and
``_make_batch_request``.
"""
# pylint: disable=protected-access
# Tests intentionally exercise private helpers directly; the leading underscore
# is conventional rather than semantic privacy.
import itertools
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from clients.aks_machine_client import AKSMachineClient


class TestAKSMachineClient(unittest.TestCase):
    """Tests for the AKSMachineClient class."""

    def setUp(self):
        """Patch all upstream Azure SDK and OperationContext seams."""
        self.cs_client_patcher = mock.patch(
            "clients.aks_client.ContainerServiceClient"
        )
        self.mi_cred_patcher = mock.patch(
            "clients.aks_client.ManagedIdentityCredential"
        )
        self.k8s_client_patcher = mock.patch("clients.aks_client.KubernetesClient")
        self.operation_context_getter_patcher = mock.patch(
            "clients.aks_machine_client.AKSMachineClient._get_operation_context"
        )

        self.cs_client_patcher.start()
        self.mi_cred_patcher.start()
        mock_k8s_class = self.k8s_client_patcher.start()
        mock_get_operation_context = self.operation_context_getter_patcher.start()
        self.mock_operation_context = mock.MagicMock()
        mock_get_operation_context.return_value = self.mock_operation_context

        self.mock_k8s = mock_k8s_class.return_value
        self.mock_operation = mock.MagicMock()
        self.mock_operation_context.return_value.__enter__.return_value = (
            self.mock_operation
        )
        self.mock_operation_context.return_value.__exit__.return_value = None

        # Hermetic per-test temp dir avoids cross-platform /tmp assumptions
        # and parallel-run collisions. ``with`` doesn't fit the setUp/tearDown
        # lifecycle, so we explicitly cleanup() in tearDown.
        self._tmp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.test_result_dir = self._tmp_dir.name

        self.client = AKSMachineClient(
            subscription_id="fake-sub",
            resource_group="fake-rg",
            cluster_name="fake-cluster",
            use_managed_identity=True,
            result_dir=self.test_result_dir,
        )

        # Stub inherited helpers that the Machine methods enrich metadata with.
        self.client.get_cluster_name = mock.MagicMock(return_value="fake-cluster")
        self.client.get_cluster_data = mock.MagicMock(
            return_value={"name": "fake-cluster"}
        )
        fake_pool = mock.MagicMock()
        fake_pool.as_dict.return_value = {"name": "fake-pool"}
        self.client.get_node_pool = mock.MagicMock(return_value=fake_pool)

    def tearDown(self):
        mock.patch.stopall()
        self._tmp_dir.cleanup()

    # ---- create_machine_agentpool ----

    @mock.patch.object(AKSMachineClient, "_wait_for_agentpool_provisioning",
                       return_value=True)
    @mock.patch.object(AKSMachineClient, "make_request")
    def test_create_machine_agentpool_success(self, mock_make_request, _mock_wait):
        """PUT 200 + Succeeded poll -> returns; metadata enriched."""
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_make_request.return_value = mock_resp

        self.client.create_machine_agentpool(
            agentpool_name="apool", vm_size="Standard_D2_v3"
        )

        mock_make_request.assert_called_once()
        call_args = mock_make_request.call_args
        self.assertEqual(call_args.args[0], "PUT")
        self.assertEqual(call_args.kwargs["data"], {"properties": {"mode": "Machines"}})
        metadata_keys = {
            call.args[0] for call in self.mock_operation.add_metadata.call_args_list
        }
        self.assertIn("agentpool_info", metadata_keys)
        self.assertIn("cluster_info", metadata_keys)

    @mock.patch.object(AKSMachineClient, "make_request")
    def test_create_machine_agentpool_put_failure_raises(self, mock_make_request):
        """PUT non-2xx -> RuntimeError propagates out of with-block."""
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "boom"
        mock_make_request.return_value = mock_resp

        with self.assertRaises(RuntimeError):
            self.client.create_machine_agentpool(
                agentpool_name="apool", vm_size="Standard_D2_v3"
            )

    @mock.patch.object(AKSMachineClient, "_wait_for_agentpool_provisioning",
                       return_value=False)
    @mock.patch.object(AKSMachineClient, "make_request")
    def test_create_machine_agentpool_provisioning_timeout_raises(
        self, mock_make_request, _mock_wait
    ):
        """PUT OK but provisioning never reaches Succeeded -> RuntimeError."""
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_make_request.return_value = mock_resp

        with self.assertRaises(RuntimeError):
            self.client.create_machine_agentpool(
                agentpool_name="apool", vm_size="Standard_D2_v3"
            )

    # ---- _get_machine_name_prefix ----

    def test_get_machine_name_prefix_small(self):
        """Counts < 1000 emit literal scale<N>."""
        self.assertEqual(AKSMachineClient._get_machine_name_prefix(1), "scale1")
        self.assertEqual(AKSMachineClient._get_machine_name_prefix(500), "scale500")

    def test_get_machine_name_prefix_thousand_multiples(self):
        """Multiples of 1000 collapse to scale<N>k for stable Kusto keys."""
        self.assertEqual(AKSMachineClient._get_machine_name_prefix(1000), "scale1k")
        self.assertEqual(AKSMachineClient._get_machine_name_prefix(2000), "scale2k")

    def test_get_machine_name_prefix_non_multiple_thousand(self):
        """Non-multiple-of-1000 counts >= 1000 stay literal."""
        self.assertEqual(AKSMachineClient._get_machine_name_prefix(1500), "scale1500")

    # ---- scale_machine: non-batch path ----

    @mock.patch.object(AKSMachineClient, "_wait_for_machine_node_readiness")
    @mock.patch.object(AKSMachineClient, "_wait_for_agentpool_provisioning",
                       return_value=True)
    @mock.patch.object(AKSMachineClient, "_create_single_machine", return_value=True)
    def test_scale_machine_non_batch_success(
        self, _mock_create, _mock_wait_ap, mock_wait_ready
    ):
        """Non-batch path: all PUTs land, agentpool Succeeded, P100 success ->
        returns and metadata is enriched with the expected keys."""
        mock_wait_ready.return_value = {
            f"P{p}": {
                "target_nodes": 2,
                "elapsed_time_seconds": 10.0,
                "percentage": p,
                "success": True,
            }
            for p in (50, 70, 90, 99, 100)
        }
        self.mock_k8s.get_ready_nodes.return_value = []

        self.client.scale_machine(
            agentpool_name="apool",
            vm_size="Standard_D2_v3",
            scale_machine_count=2,
            machine_workers=2,
        )

        metadata_keys = {
            call.args[0] for call in self.mock_operation.add_metadata.call_args_list
        }
        self.assertIn("successful_machines", metadata_keys)
        self.assertIn("percentile_node_readiness_times", metadata_keys)
        self.assertIn("node_readiness_time", metadata_keys)
        self.assertIn("cluster_info", metadata_keys)

    @mock.patch.object(AKSMachineClient, "_wait_for_machine_node_readiness")
    @mock.patch.object(AKSMachineClient, "_wait_for_agentpool_provisioning",
                       return_value=True)
    @mock.patch.object(AKSMachineClient, "_create_single_machine", return_value=True)
    def test_scale_machine_p99_met_p100_missed_does_not_raise(
        self, _mock_create, _mock_wait_ap, mock_wait_ready
    ):
        """Gate is P99, not P100. A straggler tail (P99 success, P100 miss) is
        logged as a warning but must NOT raise; the full envelope -- including
        the failed P100 entry -- is still emitted to metadata for trending."""
        envelope = {
            f"P{p}": {
                "target_nodes": 2,
                "elapsed_time_seconds": 10.0,
                "percentage": p,
                "success": True,
            }
            for p in (50, 70, 90, 99)
        }
        envelope["P100"] = {
            "target_nodes": 2,
            "elapsed_time_seconds": None,
            "percentage": 100,
            "success": False,
        }
        mock_wait_ready.return_value = envelope
        self.mock_k8s.get_ready_nodes.return_value = []

        # Must not raise.
        self.client.scale_machine(
            agentpool_name="apool",
            vm_size="Standard_D2_v3",
            scale_machine_count=2,
            machine_workers=2,
        )

        metadata = {
            call.args[0]: call.args[1]
            for call in self.mock_operation.add_metadata.call_args_list
        }
        self.assertIn("percentile_node_readiness_times", metadata)
        # Full envelope including the failed P100 is preserved for Kusto.
        emitted = metadata["percentile_node_readiness_times"]
        self.assertFalse(emitted["P100"]["success"])
        self.assertIsNone(emitted["P100"]["elapsed_time_seconds"])
        self.assertTrue(emitted["P99"]["success"])
        # node_readiness_time falls back to 0.0 when P100 elapsed is None.
        self.assertEqual(metadata["node_readiness_time"], 0.0)

    @mock.patch.object(AKSMachineClient, "_wait_for_machine_node_readiness")
    @mock.patch.object(AKSMachineClient, "_wait_for_agentpool_provisioning",
                       return_value=True)
    @mock.patch.object(AKSMachineClient, "_create_single_machine", return_value=True)
    def test_scale_machine_p99_missed_raises(
        self, _mock_create, _mock_wait_ap, mock_wait_ready
    ):
        """If P99 is missed, scale_machine raises RuntimeError naming P99."""
        envelope = {
            f"P{p}": {
                "target_nodes": 2,
                "elapsed_time_seconds": 10.0,
                "percentage": p,
                "success": True,
            }
            for p in (50, 70, 90)
        }
        for p in (99, 100):
            envelope[f"P{p}"] = {
                "target_nodes": 2,
                "elapsed_time_seconds": None,
                "percentage": p,
                "success": False,
            }
        mock_wait_ready.return_value = envelope
        self.mock_k8s.get_ready_nodes.return_value = []

        with self.assertRaises(RuntimeError) as ctx:
            self.client.scale_machine(
                agentpool_name="apool",
                vm_size="Standard_D2_v3",
                scale_machine_count=2,
                machine_workers=2,
            )
        self.assertIn("P99", str(ctx.exception))

    @mock.patch.object(AKSMachineClient, "_wait_for_machine_node_readiness")
    @mock.patch.object(AKSMachineClient, "_wait_for_agentpool_provisioning",
                       return_value=True)
    @mock.patch.object(AKSMachineClient, "_create_single_machine")
    def test_scale_machine_partial_landing_raises(
        self, mock_create, mock_wait_ap, mock_wait_ready
    ):
        """Non-batch path: if fewer machines land than requested,
        scale_machine raises RuntimeError BEFORE waiting on agentpool
        provisioning or node readiness -- otherwise the recorded percentile
        envelope and node_readiness_time describe a smaller target than
        requested."""
        # Two PUTs requested, first lands, second fails.
        mock_create.side_effect = [True, False]
        self.mock_k8s.get_ready_nodes.return_value = []

        with self.assertRaises(RuntimeError):
            self.client.scale_machine(
                agentpool_name="apool",
                vm_size="Standard_D2_v3",
                scale_machine_count=2,
                machine_workers=1,
            )

        # Fail-fast: neither the agentpool wait nor the readiness wait should
        # have been reached.
        mock_wait_ap.assert_not_called()
        mock_wait_ready.assert_not_called()
        # successful_machines metadata IS recorded so operators can see which
        # PUTs landed; downstream readiness/cluster_info metadata is not.
        metadata_keys = {
            call.args[0] for call in self.mock_operation.add_metadata.call_args_list
        }
        self.assertIn("successful_machines", metadata_keys)
        self.assertNotIn("percentile_node_readiness_times", metadata_keys)
        self.assertNotIn("node_readiness_time", metadata_keys)
        self.assertNotIn("cluster_info", metadata_keys)

    @mock.patch.object(AKSMachineClient, "_wait_for_machine_node_readiness")
    @mock.patch.object(AKSMachineClient, "_wait_for_agentpool_provisioning",
                       return_value=True)
    @mock.patch.object(AKSMachineClient, "_create_single_machine", return_value=True)
    def test_scale_machine_passes_baseline_count_to_readiness(
        self, _mock_create, _mock_wait_ap, mock_wait_ready
    ):
        """baseline_count snapshot is forwarded to _wait_for_machine_node_readiness."""
        # Three pre-existing labeled Ready nodes.
        self.mock_k8s.get_ready_nodes.return_value = [object(), object(), object()]
        mock_wait_ready.return_value = {
            f"P{p}": {
                "target_nodes": 4,
                "elapsed_time_seconds": 10.0,
                "percentage": p,
                "success": True,
            }
            for p in (50, 70, 90, 99, 100)
        }

        self.client.scale_machine(
            agentpool_name="apool",
            vm_size="Standard_D2_v3",
            scale_machine_count=1,
            machine_workers=1,
        )

        mock_wait_ready.assert_called_once()
        self.assertEqual(mock_wait_ready.call_args.kwargs["baseline_count"], 3)
        self.assertEqual(mock_wait_ready.call_args.kwargs["expected_count"], 1)

    def test_scale_machine_batch_path_dispatches_to_batch(self):
        """The use_batch_api=True branch calls _scale_machine_batch (not _individually)
        and records command_execution_time in operation metadata."""
        names = [f"scale2-machine-{i+1}" for i in range(2)]
        with mock.patch.object(
            AKSMachineClient,
            "_scale_machine_batch",
            return_value=names,
        ) as mock_batch, mock.patch.object(
            AKSMachineClient, "_scale_machine_individually"
        ) as mock_individual, mock.patch.object(
            AKSMachineClient, "_wait_for_agentpool_provisioning", return_value=True
        ), mock.patch.object(
            AKSMachineClient,
            "_wait_for_machine_node_readiness",
            return_value={
                f"P{p}": {
                    "target_nodes": 2,
                    "elapsed_time_seconds": 12.0,
                    "percentage": p,
                    "success": True,
                }
                for p in (50, 70, 90, 99, 100)
            },
        ):
            self.mock_k8s.get_ready_nodes.return_value = []
            self.client.scale_machine(
                agentpool_name="apool",
                vm_size="Standard_D2_v3",
                scale_machine_count=2,
                use_batch_api=True,
                machine_workers=2,
            )
        mock_batch.assert_called_once()
        mock_individual.assert_not_called()
        # command_execution_time must be added to operation metadata.
        added_keys = {
            call.args[0] for call in self.mock_operation.add_metadata.call_args_list
        }
        self.assertIn("command_execution_time", added_keys)

    # ---- _create_single_machine ----

    @mock.patch.object(AKSMachineClient, "make_request")
    def test_create_single_machine_2xx_returns_true(self, mock_make_request):
        """Any 200/201/202 response counts as a successful PUT."""
        request = SimpleNamespace(
            agentpool_name="apool",
            cluster_name="fake-cluster",
            resource_group="fake-rg",
            vm_size="Standard_D2_v3",
            timeout=60,
        )
        for code in (200, 201, 202):
            with self.subTest(status=code):
                mock_resp = mock.MagicMock()
                mock_resp.status_code = code
                mock_make_request.return_value = mock_resp
                self.assertTrue(
                    self.client._create_single_machine("m1", request)
                )

    @mock.patch.object(AKSMachineClient, "make_request")
    def test_create_single_machine_non_2xx_returns_false(self, mock_make_request):
        """Non-2xx responses are logged and return False (never raise)."""
        request = SimpleNamespace(
            agentpool_name="apool",
            cluster_name="fake-cluster",
            resource_group="fake-rg",
            vm_size="Standard_D2_v3",
            timeout=60,
        )
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "boom"
        mock_make_request.return_value = mock_resp
        self.assertFalse(self.client._create_single_machine("m1", request))

    # ---- _wait_for_machine_node_readiness ----

    def _make_readiness_envelope(self, ready_counts):
        """Helper: drive _wait_for_machine_node_readiness with a scripted
        sequence of get_ready_nodes results.

        ``ready_counts`` is an iterable of ints; each item is the integer
        returned by len(get_ready_nodes(...)) on each poll. ``time.sleep`` is
        patched out and ``time.time`` is advanced 1s per call so the loop's
        elapsed-time bookkeeping is deterministic.
        """
        self.mock_k8s.get_ready_nodes.side_effect = [
            [object()] * c for c in ready_counts
        ]
        # time.time() is called multiple times per iteration (start, deadline
        # check, elapsed). Use a long monotonic sequence and let StopIteration
        # be impossible by repeating the last value with itertools.chain.
        tick = itertools.chain(
            iter([float(i) for i in range(0, 1000)]),
            itertools.repeat(1000.0),
        )

        def fake_time():
            return next(tick)

        return fake_time

    def test_wait_readiness_ceil_rounding_target_total_3(self):
        """target_total=3 with baseline=0 expected=3 -> percentile targets use
        math.ceil: P50=2, P70=3, P90=3, P99=3, P100=3 (P100 always equals
        target_total)."""
        fake_time = self._make_readiness_envelope(
            # 0 ready -> 1 -> 2 -> 3 ready: at 3 ready all targets met.
            [0, 1, 2, 3]
        )
        with mock.patch("clients.aks_machine_client.time.sleep"), \
             mock.patch("clients.aks_machine_client.time.time", side_effect=fake_time):
            env = self.client._wait_for_machine_node_readiness(
                agentpool_name="apool",
                expected_count=3,
                timeout=600,
                baseline_count=0,
            )
        self.assertEqual(env["P50"]["target_nodes"], 2)
        self.assertEqual(env["P70"]["target_nodes"], 3)
        self.assertEqual(env["P90"]["target_nodes"], 3)
        self.assertEqual(env["P99"]["target_nodes"], 3)
        # P100 == target_total invariant: ceil(1.0 * 3) == 3.
        self.assertEqual(env["P100"]["target_nodes"], 3)
        for p in (50, 70, 90, 99, 100):
            self.assertTrue(env[f"P{p}"]["success"])

    def test_wait_readiness_baseline_clamp(self):
        """When baseline_count is large relative to expected, the clamp
        baseline_count+1 dominates: every percentile target == baseline+1 so
        pre-existing nodes alone can never satisfy any threshold."""
        # baseline=10, expected=1 -> target_total=11. ceil-based percentile
        # targets would be P50=6, P70=8, P90=10, P99=11, P100=11, but the
        # baseline+1 clamp (11) overrides P50/P70/P90 (and meets P99/P100).
        fake_time = self._make_readiness_envelope([10, 11])
        with mock.patch("clients.aks_machine_client.time.sleep"), \
             mock.patch("clients.aks_machine_client.time.time", side_effect=fake_time):
            env = self.client._wait_for_machine_node_readiness(
                agentpool_name="apool",
                expected_count=1,
                timeout=600,
                baseline_count=10,
            )
        for p in (50, 70, 90, 99, 100):
            self.assertEqual(env[f"P{p}"]["target_nodes"], 11)
            self.assertTrue(env[f"P{p}"]["success"])

    def test_wait_readiness_no_target_met_returns_failure_envelope(self):
        """No percentile target met within the deadline -> envelope with
        success=False, elapsed_time_seconds=None, target_nodes preserved."""
        # Always 0 ready; time.time eventually crosses the deadline.
        self.mock_k8s.get_ready_nodes.return_value = []
        # Force the loop to exit immediately: start=0, every subsequent call
        # returns 1000.0 which is past the deadline of start+timeout=10.
        time_seq = iter([0.0, 1000.0, 1000.0, 1000.0])
        with mock.patch("clients.aks_machine_client.time.sleep"), \
             mock.patch("clients.aks_machine_client.time.time",
                        side_effect=lambda: next(time_seq, 1000.0)):
            env = self.client._wait_for_machine_node_readiness(
                agentpool_name="apool",
                expected_count=3,
                timeout=10,
                baseline_count=0,
            )
        for p in (50, 70, 90, 99, 100):
            self.assertFalse(env[f"P{p}"]["success"])
            self.assertIsNone(env[f"P{p}"]["elapsed_time_seconds"])
        # target_nodes still reflects what we were aiming for so operators can
        # see "we wanted 3, got 0".
        self.assertEqual(env["P100"]["target_nodes"], 3)
        self.assertEqual(env["P50"]["target_nodes"], 2)

    def test_wait_readiness_partial_timeout(self):
        """Some percentiles hit, then deadline elapses -> hit percentiles have
        success=True with elapsed_time_seconds; missed percentiles have
        success=False with elapsed_time_seconds=None. Crucially the
        'all became ready' summary log does NOT fire."""
        # target_total=3 (baseline=0, expected=3). Sequence: ready=0,1,2 then
        # deadline crosses before reaching 3.
        ready_seq = iter([[], [object()], [object()] * 2, [object()] * 2])
        self.mock_k8s.get_ready_nodes.side_effect = lambda label_selector: next(
            ready_seq, [object()] * 2
        )
        # The function calls time.time() ~3 times per loop iteration plus once
        # for `start`. Provide a long monotonic sequence so P50 (target=2) is
        # met while well under the 100s deadline, then jump past it.
        ticks = itertools.chain(
            iter([0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 200.0, 200.0]),
            itertools.repeat(200.0),
        )
        with mock.patch("clients.aks_machine_client.time.sleep"), \
             mock.patch("clients.aks_machine_client.time.time",
                        side_effect=lambda: next(ticks)), \
             mock.patch("clients.aks_machine_client.logger") as mock_logger:
            env = self.client._wait_for_machine_node_readiness(
                agentpool_name="apool",
                expected_count=3,
                timeout=100,
                baseline_count=0,
            )
        # P50 (target=2) was hit; P70/P90/P99/P100 (target=3) were not.
        self.assertTrue(env["P50"]["success"])
        self.assertIsNotNone(env["P50"]["elapsed_time_seconds"])
        for p in (70, 90, 99, 100):
            self.assertFalse(env[f"P{p}"]["success"])
            self.assertIsNone(env[f"P{p}"]["elapsed_time_seconds"])
        # The unconditional "All target nodes became ready" log must NOT fire
        # on partial completion; a partial-readiness warning takes its place.
        info_msgs = [
            c.args[0] for c in mock_logger.info.call_args_list if c.args
        ]
        warning_msgs = [
            c.args[0] for c in mock_logger.warning.call_args_list if c.args
        ]
        self.assertFalse(
            any("All target nodes became ready" in m for m in info_msgs),
            f"unexpected all-ready log on partial completion: {info_msgs}",
        )
        self.assertTrue(
            any("Partial readiness" in m for m in warning_msgs),
            f"expected partial-readiness warning, got: {warning_msgs}",
        )

    def test_wait_readiness_expected_count_zero_short_circuits(self):
        """expected_count<=0 -> empty envelope, no Kubernetes calls."""
        env = self.client._wait_for_machine_node_readiness(
            agentpool_name="apool",
            expected_count=0,
            timeout=600,
            baseline_count=0,
        )
        for p in (50, 70, 90, 99, 100):
            self.assertFalse(env[f"P{p}"]["success"])
            self.assertEqual(env[f"P{p}"]["target_nodes"], 0)
        self.mock_k8s.get_ready_nodes.assert_not_called()

    def test_wait_readiness_no_k8s_client_short_circuits(self):
        """k8s_client is None -> empty envelope, no polling."""
        self.client.k8s_client = None
        env = self.client._wait_for_machine_node_readiness(
            agentpool_name="apool",
            expected_count=5,
            timeout=600,
            baseline_count=0,
        )
        for p in (50, 70, 90, 99, 100):
            self.assertFalse(env[f"P{p}"]["success"])
            self.assertEqual(env[f"P{p}"]["target_nodes"], 0)

    # ---- _scale_machine_batch ----

    def test_scale_machine_batch_partitions_and_aggregates(self):
        """Names sharded across machine_workers; all successful slices aggregated."""
        request = SimpleNamespace(
            agentpool_name="apool",
            cluster_name="fake-cluster",
            resource_group="fake-rg",
            vm_size="Standard_D2_v3",
            timeout=60,
            machine_workers=2,
        )
        names = ["m-1", "m-2", "m-3", "m-4"]
        with mock.patch.object(
            AKSMachineClient,
            "_create_batch_machines",
            side_effect=lambda req, chunk, worker_id: list(chunk),
        ) as mock_create_batch:
            successful = self.client._scale_machine_batch(request, names)
        self.assertEqual(set(successful), set(names))
        # 2 workers, each handling per_worker = 4 // 2 = 2 names
        self.assertEqual(mock_create_batch.call_count, 2)

    def test_scale_machine_batch_per_worker_failure_isolated(self):
        """One worker raising does not poison the other worker's success list."""
        request = SimpleNamespace(
            agentpool_name="apool",
            cluster_name="fake-cluster",
            resource_group="fake-rg",
            vm_size="Standard_D2_v3",
            timeout=60,
            machine_workers=2,
        )
        names = ["m-1", "m-2", "m-3", "m-4"]
        counter = itertools.count()

        def fake_create(req, chunk, worker_id):  # pylint: disable=unused-argument
            if next(counter) == 0:
                raise RuntimeError("first worker boom")
            return list(chunk)

        with mock.patch.object(
            AKSMachineClient, "_create_batch_machines", side_effect=fake_create
        ):
            successful = self.client._scale_machine_batch(request, names)
        # Exactly one worker's slice survives.
        self.assertEqual(len(successful), 2)

    def test_scale_machine_batch_rejects_non_exact_multiple(self):
        """scale_machine_count must be an exact multiple of machine_workers."""
        request = SimpleNamespace(
            agentpool_name="apool",
            cluster_name="fake-cluster",
            resource_group="fake-rg",
            vm_size="Standard_D2_v3",
            timeout=60,
            machine_workers=3,
        )
        names = ["m-1", "m-2", "m-3", "m-4"]  # 4 not divisible by 3
        with self.assertRaises(ValueError):
            self.client._scale_machine_batch(request, names)

    # ---- _create_batch_machines ----

    def test_create_batch_machines_empty_chunk_returns_empty(self):
        """Empty chunk -> early return, no HTTP call."""
        request = SimpleNamespace(
            agentpool_name="apool",
            cluster_name="fake-cluster",
            resource_group="fake-rg",
            vm_size="Standard_D2_v3",
            timeout=60,
        )
        with mock.patch.object(
            AKSMachineClient, "_make_batch_request"
        ) as mock_make_batch:
            result = self.client._create_batch_machines(request, [], 0)
        self.assertEqual(result, [])
        mock_make_batch.assert_not_called()

    def test_create_batch_machines_header_shape(self):
        """BatchPutMachine header carries vmSkus envelope + batchMachines
        using machineName (NOT name) keys for the *additional* machines only."""
        request = SimpleNamespace(
            agentpool_name="apool",
            cluster_name="fake-cluster",
            resource_group="fake-rg",
            vm_size="Standard_D2_v3",
            timeout=60,
        )
        with mock.patch.object(
            AKSMachineClient, "_make_batch_request"
        ) as mock_make_batch:
            result = self.client._create_batch_machines(
                request, ["m-1", "m-2", "m-3"], chunk_idx=0
            )
        self.assertEqual(result, ["m-1", "m-2", "m-3"])
        mock_make_batch.assert_called_once()
        # Inspect the batch_header_value kwarg.
        import json as _json  # pylint: disable=import-outside-toplevel
        kwargs = mock_make_batch.call_args.kwargs
        header_value = kwargs["batch_header_value"]
        parsed = _json.loads(header_value)
        # vmSkus is wrapped in {"value": [...]}
        self.assertIn("vmSkus", parsed)
        self.assertIn("value", parsed["vmSkus"])
        self.assertEqual(len(parsed["vmSkus"]["value"]), 1)
        self.assertEqual(
            parsed["vmSkus"]["value"][0]["name"], "Standard_D2_v3"
        )
        # First machine of chunk is created from the URL+body; only the rest
        # appear in batchMachines.
        self.assertEqual(
            parsed["batchMachines"],
            [{"machineName": "m-2"}, {"machineName": "m-3"}],
        )

    # ---- _make_batch_request ----

    def test_make_batch_request_2xx_returns(self):
        """2xx response returns without raising; one HTTP call made."""
        with mock.patch.object(
            self.client._session, "request"
        ) as mock_request:
            mock_request.return_value.status_code = 200
            self.client._make_batch_request(
                "PUT",
                "https://fake/url",
                {"k": "v"},
                timeout=30,
                batch_header_value="{}",
            )
        mock_request.assert_called_once()

    def test_make_batch_request_non_2xx_non_429_raises(self):
        """500 -> RuntimeError, no retry."""
        with mock.patch.object(
            self.client._session, "request"
        ) as mock_request:
            mock_request.return_value.status_code = 500
            mock_request.return_value.text = "boom"
            with self.assertRaises(RuntimeError):
                self.client._make_batch_request(
                    "PUT",
                    "https://fake/url",
                    {},
                    timeout=30,
                    batch_header_value="{}",
                )
        self.assertEqual(mock_request.call_count, 1)

    def test_make_batch_request_429_then_success(self):
        """429 then 2xx (201) -> succeeds after 1 retry."""
        responses = [
            mock.MagicMock(status_code=429),
            mock.MagicMock(status_code=201),
        ]
        with mock.patch.object(
            self.client._session, "request", side_effect=responses,
        ) as mock_request, mock.patch(
            "clients.aks_machine_client.time.sleep"
        ):
            self.client._make_batch_request(
                "PUT",
                "https://fake/url",
                {},
                timeout=30,
                batch_header_value="{}",
            )
        self.assertEqual(mock_request.call_count, 2)

    def test_make_batch_request_429_exhausted_raises(self):
        """429 across the full retry budget -> RuntimeError."""
        with mock.patch.object(
            self.client._session, "request"
        ) as mock_request, mock.patch(
            "clients.aks_machine_client.time.sleep"
        ):
            mock_request.return_value.status_code = 429
            mock_request.return_value.text = "rate limited"
            with self.assertRaises(RuntimeError):
                self.client._make_batch_request(
                    "PUT",
                    "https://fake/url",
                    {},
                    timeout=30,
                    batch_header_value="{}",
                )
        # _BATCH_429_MAX_RETRIES == 5 total attempts (no extra initial call)
        self.assertEqual(mock_request.call_count, 5)

    # ---- Session connection pool ----

    def test_session_https_adapter_pool_sized_for_workers(self):
        """Session mounts a sized HTTPAdapter so the per-host connection pool
        can hold one warm connection per worker thread, preventing the
        ``Connection pool is full, discarding connection`` urllib3 warning
        when machine_workers exceeds urllib3's default pool_maxsize=10."""
        # pylint: disable=import-outside-toplevel,protected-access
        from clients.aks_machine_client import _HTTPS_POOL_SIZE
        adapter = self.client._session.get_adapter("https://management.azure.com")
        self.assertGreaterEqual(_HTTPS_POOL_SIZE, 50)  # covers 50-worker individual path
        self.assertEqual(adapter._pool_connections, _HTTPS_POOL_SIZE)
        self.assertEqual(adapter._pool_maxsize, _HTTPS_POOL_SIZE)


if __name__ == "__main__":
    unittest.main()
