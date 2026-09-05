#!/usr/bin/env python3
"""
Unit tests for provisioning_instrumentation module
"""

import unittest
from unittest import mock

from azure.core.exceptions import HttpResponseError

from utils.provisioning_instrumentation import (
    RETRY_WAIT_SECONDS,
    begin_create_or_update_with_retry,
    instrument_nodepool_provisioning,
)


class TestInstrumentNodepoolProvisioning(unittest.TestCase):
    """Tests for instrument_nodepool_provisioning.

    These drive the concurrent ARM/K8s ThreadPoolExecutor with a shared mocked
    ``time.time()`` side_effect list, and rely on ARM-thread-first scheduling: the
    ARM thread must consume its post-callable ``time.time()`` before the K8s thread
    (values ordered arm_done then ready). This is not guaranteed by the runtime --
    the mocked callables are instant so the ARM thread usually finishes within one
    GIL slice, but if these ever flake, replace the positional side_effect with a
    caller-keyed ``time.time`` stub instead of a shared list.
    """

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_records_timing_metadata(self, mock_time):
        """Timings are measured from the ARM accept; no wait when accepted immediately."""
        # start=100, arm done=140, nodes ready=130; ARM accepted at 100 (no retry).
        mock_time.time.side_effect = [100, 140, 130]

        op = mock.MagicMock()
        arm_callable = mock.MagicMock(return_value=(100, False))  # (command_start, retry_occurred)
        ready_nodes = [mock.MagicMock()]
        k8s_callable = mock.MagicMock(return_value=ready_nodes)

        result = instrument_nodepool_provisioning(
            node_pool_name="pool1",
            op=op,
            arm_callable=arm_callable,
            k8s_wait_callable=k8s_callable,
        )

        # command_execution_time = 140 - 100 = 40; node_readiness = 130 - 100 = 30
        self.assertEqual(result, ready_nodes)
        op.add_metadata.assert_any_call("node_readiness_time", 30)
        op.add_metadata.assert_any_call("command_execution_time", 40)
        op.add_metadata.assert_any_call("retry_occurred", False)
        # Operation.end() (not instrument) owns in_progress_wait_seconds.
        op.exclude_time.assert_called_once_with(0)

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_in_progress_wait_excluded_from_timings(self, mock_time):
        """Pre-accept queue-wait is excluded from the op duration and both timings."""
        # start=100, accepted attempt starts at 130 (30s queue-wait), arm done=160, ready=150.
        mock_time.time.side_effect = [100, 160, 150]

        op = mock.MagicMock()
        arm_callable = mock.MagicMock(return_value=(130, True))  # (command_start, retry_occurred)
        k8s_callable = mock.MagicMock(return_value=[mock.MagicMock()])

        instrument_nodepool_provisioning(
            node_pool_name="pool1",
            op=op,
            arm_callable=arm_callable,
            k8s_wait_callable=k8s_callable,
        )

        # measured from accepted-attempt start (130): command = 160-130 = 30; readiness = 150-130 = 20
        op.add_metadata.assert_any_call("command_execution_time", 30)
        op.add_metadata.assert_any_call("node_readiness_time", 20)
        op.add_metadata.assert_any_call("retry_occurred", True)
        # 30s of pre-accept wait is fed to the op; Operation.end() records it.
        op.exclude_time.assert_called_once_with(30)

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_arm_failure_raises(self, mock_time):
        """ARM failure is raised even if K8s succeeds"""
        mock_time.time.side_effect = [100, 110, 110]

        op = mock.MagicMock()
        arm_callable = mock.MagicMock(side_effect=RuntimeError("ARM failed"))
        k8s_callable = mock.MagicMock(return_value=[mock.MagicMock()])

        with self.assertRaises(RuntimeError) as ctx:
            instrument_nodepool_provisioning(
                node_pool_name="pool1",
                op=op,
                arm_callable=arm_callable,
                k8s_wait_callable=k8s_callable,
            )
        self.assertIn("ARM failed", str(ctx.exception))

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_k8s_failure_raises_still_excludes_queue_wait(self, mock_time):
        """K8s failure re-raises, but the pre-accept queue-wait is still excluded."""
        # start=100, ARM accepted at 130 (30s queue-wait) then succeeds; K8s fails.
        mock_time.time.side_effect = [100, 160, 150]

        op = mock.MagicMock()
        arm_callable = mock.MagicMock(return_value=(130, True))
        k8s_callable = mock.MagicMock(side_effect=RuntimeError("K8s timeout"))

        with self.assertRaises(RuntimeError) as ctx:
            instrument_nodepool_provisioning(
                node_pool_name="pool1",
                op=op,
                arm_callable=arm_callable,
                k8s_wait_callable=k8s_callable,
            )
        self.assertIn("K8s timeout", str(ctx.exception))
        # 30s of queue-wait (command_start 130 - start 100) excluded before re-raise.
        op.exclude_time.assert_called_once_with(30)

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_arm_accept_then_fail_excludes_attached_queue_wait(self, mock_time):
        """ARM accepted-then-failed: the attached accept time is excluded on failure."""
        mock_time.time.side_effect = [100, 160, 150]

        op = mock.MagicMock()
        # arm_callable raises, but carries the accepted attempt's start (130).
        arm_err = RuntimeError("provisioning failed")
        arm_err.request_started_at = 130
        arm_callable = mock.MagicMock(side_effect=arm_err)
        k8s_callable = mock.MagicMock(return_value=[mock.MagicMock()])

        with self.assertRaises(RuntimeError) as ctx:
            instrument_nodepool_provisioning(
                node_pool_name="pool1",
                op=op,
                arm_callable=arm_callable,
                k8s_wait_callable=k8s_callable,
            )
        self.assertIn("provisioning failed", str(ctx.exception))
        op.exclude_time.assert_called_once_with(30)


class TestBeginCreateOrUpdateWithRetry(unittest.TestCase):
    """Tests for begin_create_or_update_with_retry"""

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_succeeds_first_attempt(self, mock_time):
        """Returns (request_started_at, False) on first-attempt success"""
        mock_time.sleep = mock.MagicMock()
        mock_time.time.return_value = 500  # accepted attempt start

        mock_poller = mock.MagicMock()
        mock_poller.done.return_value = True
        sdk_client = mock.MagicMock()
        sdk_client.agent_pools.begin_create_or_update.return_value = mock_poller

        result = begin_create_or_update_with_retry(
            aks_sdk_client=sdk_client,
            resource_group="rg",
            cluster_name="cluster1",
            node_pool_name="pool1",
            parameters={},
        )

        self.assertEqual(result, (500, False))
        sdk_client.agent_pools.begin_create_or_update.assert_called_once()

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_retries_on_operation_not_allowed(self, mock_time):
        """Returns (request_started_at, True) after a transient OperationNotAllowed"""
        mock_time.sleep = mock.MagicMock()
        mock_time.time.return_value = 500  # accepted attempt start (the retry)

        error = HttpResponseError(message="OperationNotAllowed")
        error.error = mock.MagicMock()
        error.error.code = "OperationNotAllowed"

        mock_poller = mock.MagicMock()
        mock_poller.done.return_value = True

        sdk_client = mock.MagicMock()
        sdk_client.agent_pools.begin_create_or_update.side_effect = [
            error,
            mock_poller,
        ]

        result = begin_create_or_update_with_retry(
            aks_sdk_client=sdk_client,
            resource_group="rg",
            cluster_name="cluster1",
            node_pool_name="pool1",
            parameters={},
        )

        # Accepted on the 2nd attempt; retry_occurred flagged True.
        self.assertEqual(result, (500, True))
        mock_time.sleep.assert_called_once_with(RETRY_WAIT_SECONDS)
        self.assertEqual(sdk_client.agent_pools.begin_create_or_update.call_count, 2)

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_raises_non_retryable_error(self, mock_time):
        """Non-retryable HttpResponseError is raised immediately"""
        mock_time.sleep = mock.MagicMock()

        error = HttpResponseError(message="Forbidden")
        error.error = mock.MagicMock()
        error.error.code = "Forbidden"

        sdk_client = mock.MagicMock()
        sdk_client.agent_pools.begin_create_or_update.side_effect = error

        with self.assertRaises(HttpResponseError) as ctx:
            begin_create_or_update_with_retry(
                aks_sdk_client=sdk_client,
                resource_group="rg",
                cluster_name="cluster1",
                node_pool_name="pool1",
                parameters={},
            )
        sdk_client.agent_pools.begin_create_or_update.assert_called_once()
        # Non-retryable failure is real ARM latency, not queue-wait: no timing
        # anchor is attached, so the caller excludes nothing.
        self.assertIsNone(getattr(ctx.exception, "request_started_at", None))

    @mock.patch("utils.provisioning_instrumentation.TIMEOUT_SECONDS", 0)
    @mock.patch("utils.provisioning_instrumentation.time")
    def test_timeout_raises(self, mock_time):
        """TimeoutError raised when poller exceeds TIMEOUT_SECONDS"""
        mock_time.sleep = mock.MagicMock()

        mock_poller = mock.MagicMock()
        mock_poller.done.return_value = False
        mock_poller.result.return_value = None

        sdk_client = mock.MagicMock()
        sdk_client.agent_pools.begin_create_or_update.return_value = mock_poller

        with self.assertRaises(TimeoutError):
            begin_create_or_update_with_retry(
                aks_sdk_client=sdk_client,
                resource_group="rg",
                cluster_name="cluster1",
                node_pool_name="pool1",
                parameters={},
            )

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_post_accept_failure_attaches_request_started_at(self, mock_time):
        """An accepted op that then fails carries the accept time on the exception."""
        mock_time.time.return_value = 500
        mock_time.sleep = mock.MagicMock()

        poller = mock.MagicMock()
        poller.done.return_value = True
        poller.result.side_effect = RuntimeError("provisioning failed")
        sdk_client = mock.MagicMock()
        sdk_client.agent_pools.begin_create_or_update.return_value = poller

        with self.assertRaises(RuntimeError) as ctx:
            begin_create_or_update_with_retry(
                aks_sdk_client=sdk_client,
                resource_group="rg",
                cluster_name="cluster1",
                node_pool_name="pool1",
                parameters={},
            )
        # The accepted attempt's start is attached so the caller can exclude it.
        self.assertEqual(getattr(ctx.exception, "request_started_at", None), 500)

    @mock.patch("utils.provisioning_instrumentation.MAX_RETRIES", 3)
    @mock.patch("utils.provisioning_instrumentation.time")
    def test_exhausted_budget_reraises_last_error(self, mock_time):
        """Every attempt OperationNotAllowed -> the last attempt re-raises it."""
        mock_time.sleep = mock.MagicMock()

        error = HttpResponseError(message="OperationNotAllowed")
        error.error = mock.MagicMock()
        error.error.code = "OperationNotAllowed"

        sdk_client = mock.MagicMock()
        sdk_client.agent_pools.begin_create_or_update.side_effect = error

        with self.assertRaises(HttpResponseError):
            begin_create_or_update_with_retry(
                aks_sdk_client=sdk_client,
                resource_group="rg",
                cluster_name="cluster1",
                node_pool_name="pool1",
                parameters={},
            )
        # All 3 attempts made; the last one (no retry left) re-raises.
        self.assertEqual(sdk_client.agent_pools.begin_create_or_update.call_count, 3)

    @mock.patch("utils.provisioning_instrumentation.MAX_RETRIES", 3)
    @mock.patch("utils.provisioning_instrumentation.time")
    def test_terminal_rejection_attaches_timing_anchor(self, mock_time):
        """A never-admitted op anchors the exclusion at the give-up time."""
        mock_time.sleep = mock.MagicMock()
        mock_time.time.return_value = 900  # give-up timestamp

        error = HttpResponseError(message="OperationNotAllowed")
        error.error = mock.MagicMock()
        error.error.code = "OperationNotAllowed"

        sdk_client = mock.MagicMock()
        sdk_client.agent_pools.begin_create_or_update.side_effect = error

        with self.assertRaises(HttpResponseError) as ctx:
            begin_create_or_update_with_retry(
                aks_sdk_client=sdk_client,
                resource_group="rg",
                cluster_name="cluster1",
                node_pool_name="pool1",
                parameters={},
            )
        # Timing anchor attached so the caller excludes the rejected-attempt wait.
        self.assertEqual(getattr(ctx.exception, "request_started_at", None), 900)

    @mock.patch("utils.provisioning_instrumentation.MAX_RETRIES", 0)
    def test_zero_max_retries_raises_runtime_error(self):
        """MAX_RETRIES=0 makes no attempt and raises RuntimeError (guards None return)."""
        sdk_client = mock.MagicMock()
        with self.assertRaises(RuntimeError) as ctx:
            begin_create_or_update_with_retry(
                aks_sdk_client=sdk_client,
                resource_group="rg",
                cluster_name="cluster1",
                node_pool_name="pool1",
                parameters={},
            )
        self.assertIn("exhausted", str(ctx.exception))
        sdk_client.agent_pools.begin_create_or_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
