#!/usr/bin/env python3
"""Unit tests for AKSMachineClient (subclass of AKSClient).

All public methods open an ``OperationContext`` (patched here) and write the
result file via ``Operation.save_to_file`` on context exit. Tests verify:
- success path completes without raising and enriches ``op.add_metadata`` with
  the right keys
- failure path raises (so the OperationContext records ``success=False``)

This revision adds tests for the non-batch scale path. The batch dispatch
(``use_batch_api=True``) is asserted to raise ``NotImplementedError`` until
the follow-up PR lands.
"""
# pylint: disable=protected-access
# Tests intentionally exercise private helpers directly; the leading underscore
# is conventional rather than semantic privacy.
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
    @mock.patch.object(AKSMachineClient, "_create_single_machine")
    def test_scale_machine_partial_landing_raises(
        self, mock_create, _mock_wait_ap, mock_wait_ready
    ):
        """Non-batch path: if fewer machines land than requested,
        scale_machine raises RuntimeError before returning."""
        # Two PUTs requested, first lands, second fails.
        mock_create.side_effect = [True, False]
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

        with self.assertRaises(RuntimeError):
            self.client.scale_machine(
                agentpool_name="apool",
                vm_size="Standard_D2_v3",
                scale_machine_count=2,
                machine_workers=1,
            )

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

    def test_scale_machine_batch_path_raises_not_implemented(self):
        """The use_batch_api=True branch is stubbed until the follow-up PR."""
        with self.assertRaises(NotImplementedError):
            self.client.scale_machine(
                agentpool_name="apool",
                vm_size="Standard_D2_v3",
                scale_machine_count=2,
                use_batch_api=True,
            )

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


if __name__ == "__main__":
    unittest.main()
