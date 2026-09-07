#!/usr/bin/env python3
"""Unit tests for Machine-API 429 throttle-wait exclusion.

Covers the ``compute_throttle_delay`` critical-path attribution, per-chunk
backoff returned by ``_make_batch_request``, and the ``scale_machine`` exclusion
of throttle-wait from the operation duration / command time.
"""
# pylint: disable=protected-access
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from clients.aks_machine_client import AKSMachineClient
from utils.common import compute_throttle_delay


class TestComputeThrottleDelay(unittest.TestCase):
    """Tests for the compute_throttle_delay critical-path helper."""

    def test_empty_is_zero(self):
        """No chunks -> 0 delay."""
        self.assertEqual(compute_throttle_delay([]), 0.0)

    def test_single_chunk_backoff_counts(self):
        """A lone chunk's backoff fully delayed its own completion."""
        # finish=1005, backoff=5 -> throttle-free finish 1000 -> delay 5.
        self.assertEqual(compute_throttle_delay([(1005.0, 5.0)]), 5.0)

    def test_off_critical_path_backoff_excluded(self):
        """Backoff on a worker that is NOT last-to-finish does not delay command."""
        # Chunk A finishes last at 1005 with no backoff (critical path); chunk B
        # slept 5s but finished earlier at 1003. Removing B's throttle would not
        # move the makespan, so the throttle delay is 0 (Karen's concurrency case).
        self.assertEqual(
            compute_throttle_delay([(1005.0, 0.0), (1003.0, 5.0)]), 0.0
        )

    def test_critical_path_capped_by_runner_up(self):
        """Delay is capped by the next-latest throttle-free finish."""
        # Critical chunk finishes 1010 with 8s backoff (throttle-free 1002);
        # runner-up finishes 1005 with no backoff. Counterfactual makespan =
        # max(1002, 1005) = 1005, so delay = 1010 - 1005 = 5 (not the full 8).
        self.assertEqual(
            compute_throttle_delay([(1010.0, 8.0), (1005.0, 0.0)]), 5.0
        )

    def test_tie_finish_uses_least_throttled(self):
        """When two chunks finish together, the least-throttled bounds the delay."""
        # Both finish at 1000; throttle-free finishes are 990 and 997. Without
        # throttle the command still finishes at max(990, 997) = 997 -> delay 3.
        self.assertEqual(
            compute_throttle_delay([(1000.0, 10.0), (1000.0, 3.0)]), 3.0
        )

    def test_exact_tie(self):
        """Identical (finish, backoff) chunks -> delay equals the shared backoff."""
        self.assertEqual(
            compute_throttle_delay([(1000.0, 4.0), (1000.0, 4.0)]), 4.0
        )


class TestMachineThrottleExclusion(unittest.TestCase):
    """Tests that throttle backoff is recorded and excluded from timings."""

    def setUp(self):
        """Build the client WITHOUT running __init__ and stub only the attrs these
        tests touch (no mock.patch of clients.aks_client at all). Other tests in the
        suite mutate that module's SDK symbols / AKSClient.__init__, so constructing
        or patching through it is order-dependent; this avoids the dependency."""
        self._tmp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.mock_operation = mock.MagicMock()
        op_context = mock.MagicMock()
        op_context.return_value.__enter__.return_value = self.mock_operation
        op_context.return_value.__exit__.return_value = None
        self.mock_k8s = mock.MagicMock()

        self.client = AKSMachineClient.__new__(AKSMachineClient)
        self.client._session = mock.MagicMock()
        self.client.subscription_id = "fake-sub"
        self.client.resource_group = "fake-rg"
        self.client.result_dir = self._tmp_dir.name
        self.client.k8s_client = self.mock_k8s
        self.client._get_access_token = mock.MagicMock(return_value="token")
        self.client._get_operation_context = mock.MagicMock(return_value=op_context)
        self.client.get_cluster_name = mock.MagicMock(return_value="fake-cluster")
        self.client.get_cluster_data = mock.MagicMock(return_value={"name": "fake-cluster"})

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_make_batch_request_returns_backoff(self):
        """A 429-then-2xx returns the accumulated backoff seconds."""
        responses = [
            mock.MagicMock(status_code=429),
            mock.MagicMock(status_code=201),
        ]
        with mock.patch.object(
            self.client._session, "request", side_effect=responses,
        ), mock.patch("clients.aks_machine_client.time.sleep"):
            backoff = self.client._make_batch_request(
                "PUT", "https://fake/url", {}, timeout=30, batch_header_value="{}",
            )
        # One retry at the initial 1.0s backoff.
        self.assertEqual(backoff, 1.0)

    def test_make_batch_request_no_retry_returns_zero(self):
        """A first-attempt 2xx returns 0 backoff."""
        with mock.patch.object(
            self.client._session, "request",
            return_value=mock.MagicMock(status_code=201),
        ), mock.patch("clients.aks_machine_client.time.sleep"):
            backoff = self.client._make_batch_request(
                "PUT", "https://fake/url", {}, timeout=30, batch_header_value="{}",
            )
        self.assertEqual(backoff, 0.0)

    def test_make_batch_request_records_backoff_on_failure(self):
        """A chunk that exhausts its 429 retries still records its backoff (finally)."""
        request = SimpleNamespace(chunk_throttle=[], throttle_lock=mock.MagicMock())
        with mock.patch.object(
            self.client._session, "request",
            return_value=mock.MagicMock(status_code=429),
        ), mock.patch("clients.aks_machine_client.time.sleep"):
            with self.assertRaises(RuntimeError):
                self.client._make_batch_request(
                    "PUT", "https://fake/url", {}, timeout=30,
                    batch_header_value="{}", request=request,
                )
        # Recorded despite failure; backoff = 1+2+4+8 = 15s across the retry budget.
        self.assertEqual(len(request.chunk_throttle), 1)
        self.assertEqual(request.chunk_throttle[0][1], 15.0)

    def test_scale_machine_scopes_throttle_to_command_time(self):
        """Throttle adjusts command_execution_time only, NOT the operation duration."""
        def fake_batch(request, names):
            # Critical chunk finishes last (1005) with 5s backoff; an earlier chunk
            # (1003) also slept 5s but is off the critical path. Only the critical
            # chunk's backoff delayed the PUT makespan -> 5s throttle, not 10s.
            request.chunk_throttle.append((1005.0, 5.0))
            request.chunk_throttle.append((1003.0, 5.0))
            return names

        with mock.patch.object(
            AKSMachineClient, "_scale_machine_batch", side_effect=fake_batch,
        ), mock.patch.object(
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
                agent_pool_name="apool",
                vm_size="Standard_D2_v3",
                scale_machine_count=2,
                use_batch_api=True,
                machine_workers=2,
            )

        # Only the critical-path chunk's 5s backoff delayed the PUT makespan (not 10s).
        # It is removed from command_execution_time (fan-out ~instant -> wall - 5s
        # floors to 0) and recorded as throttle_wait_seconds, but the operation
        # duration is NOT adjusted (op.exclude_time is not called): the PUT-phase
        # critical path may not determine end-to-end completion.
        self.mock_operation.add_metadata.assert_any_call("command_execution_time", 0.0)
        self.mock_operation.add_metadata.assert_any_call("throttle_wait_seconds", 5.0)
        self.mock_operation.exclude_time.assert_not_called()


if __name__ == "__main__":
    unittest.main()
