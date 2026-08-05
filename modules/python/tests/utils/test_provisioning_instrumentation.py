#!/usr/bin/env python3
"""
Unit tests for provisioning_instrumentation module
"""

import unittest
from unittest import mock

from azure.core.exceptions import HttpResponseError

from utils.provisioning_instrumentation import (
    begin_create_or_update_with_retry,
    instrument_nodepool_provisioning,
)


class TestInstrumentNodepoolProvisioning(unittest.TestCase):
    """Tests for instrument_nodepool_provisioning"""

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_records_timing_metadata(self, mock_time):
        """Both node_readiness_time and command_execution_time are stored"""
        mock_time.time.side_effect = [100, 140, 130]

        op = mock.MagicMock()
        arm_callable = mock.MagicMock(return_value=False)
        ready_nodes = [mock.MagicMock()]
        k8s_callable = mock.MagicMock(return_value=ready_nodes)

        result = instrument_nodepool_provisioning(
            node_pool_name="pool1",
            cluster_name="cluster1",
            op=op,
            arm_callable=arm_callable,
            k8s_wait_callable=k8s_callable,
        )

        self.assertEqual(result, ready_nodes)
        op.add_metadata.assert_any_call("node_readiness_time", 30)
        op.add_metadata.assert_any_call("command_execution_time", 40)
        op.add_metadata.assert_any_call("retry_occurred", False)

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_retry_occurred_true(self, mock_time):
        """retry_occurred=True is stored when arm_callable returns True"""
        mock_time.time.side_effect = [100, 160, 150]

        op = mock.MagicMock()
        arm_callable = mock.MagicMock(return_value=True)
        k8s_callable = mock.MagicMock(return_value=[mock.MagicMock()])

        instrument_nodepool_provisioning(
            node_pool_name="pool1",
            cluster_name="cluster1",
            op=op,
            arm_callable=arm_callable,
            k8s_wait_callable=k8s_callable,
        )

        op.add_metadata.assert_any_call("retry_occurred", True)

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
                cluster_name="cluster1",
                op=op,
                arm_callable=arm_callable,
                k8s_wait_callable=k8s_callable,
            )
        self.assertIn("ARM failed", str(ctx.exception))

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_k8s_failure_raises(self, mock_time):
        """K8s failure is raised when ARM succeeds"""
        mock_time.time.side_effect = [100, 110, 110]

        op = mock.MagicMock()
        arm_callable = mock.MagicMock(return_value=False)
        k8s_callable = mock.MagicMock(side_effect=RuntimeError("K8s timeout"))

        with self.assertRaises(RuntimeError) as ctx:
            instrument_nodepool_provisioning(
                node_pool_name="pool1",
                cluster_name="cluster1",
                op=op,
                arm_callable=arm_callable,
                k8s_wait_callable=k8s_callable,
            )
        self.assertIn("K8s timeout", str(ctx.exception))


class TestBeginCreateOrUpdateWithRetry(unittest.TestCase):
    """Tests for begin_create_or_update_with_retry"""

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_succeeds_first_attempt(self, mock_time):
        """Returns False (no retry) on first-attempt success"""
        mock_time.sleep = mock.MagicMock()

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

        self.assertFalse(result)
        sdk_client.agent_pools.begin_create_or_update.assert_called_once()

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_retries_on_operation_not_allowed(self, mock_time):
        """Returns True (retry occurred) after transient OperationNotAllowed"""
        mock_time.sleep = mock.MagicMock()

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
            retry_wait=0,
        )

        self.assertTrue(result)
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

        with self.assertRaises(HttpResponseError):
            begin_create_or_update_with_retry(
                aks_sdk_client=sdk_client,
                resource_group="rg",
                cluster_name="cluster1",
                node_pool_name="pool1",
                parameters={},
            )
        sdk_client.agent_pools.begin_create_or_update.assert_called_once()

    @mock.patch("utils.provisioning_instrumentation.time")
    def test_timeout_raises(self, mock_time):
        """TimeoutError raised when poller exceeds timeout"""
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
                timeout=0,
            )


if __name__ == "__main__":
    unittest.main()
