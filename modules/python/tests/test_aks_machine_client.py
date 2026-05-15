#!/usr/bin/env python3
"""Unit tests for AKSMachineClient (subclass of AKSClient).

All public methods open an ``OperationContext`` (patched here) and write the
result file via ``Operation.save_to_file`` on context exit. Tests verify:
- success path completes without raising and enriches ``op.add_metadata`` with
  the right keys
- failure path raises (so the OperationContext records ``success=False``)

Only ``create_machine_agentpool`` has a full implementation on this scaffolding
PR; ``scale_machine`` and the ``_get_machine_name_prefix`` naming helper raise
``NotImplementedError`` and will be tested in a follow-up PR.
"""
# pylint: disable=protected-access
# Tests intentionally exercise private helpers directly; the leading underscore
# is conventional rather than semantic privacy.
import tempfile
import unittest
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
        """PUT 200 + Succeeded poll → returns; metadata enriched."""
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
        """PUT non-2xx \u2192 RuntimeError propagates out of with-block."""
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
        """PUT OK but provisioning never reaches Succeeded \u2192 RuntimeError."""
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_make_request.return_value = mock_resp

        with self.assertRaises(RuntimeError):
            self.client.create_machine_agentpool(
                agentpool_name="apool", vm_size="Standard_D2_v3"
            )

    # ---- scale_machine: stubbed on this PR ----

    def test_scale_machine_raises_not_implemented(self):
        """scale_machine is a stub on this PR; subsequent PR will implement it."""
        with self.assertRaises(NotImplementedError):
            self.client.scale_machine(
                agentpool_name="apool", vm_size="Standard_D2_v3",
                scale_machine_count=2,
            )

    # ---- _get_machine_name_prefix: stubbed on this PR ----

    def test_get_machine_name_prefix_raises_not_implemented(self):
        """_get_machine_name_prefix is a stub on this PR; lands with the scale path."""
        with self.assertRaises(NotImplementedError):
            AKSMachineClient._get_machine_name_prefix(1000)


if __name__ == "__main__":
    unittest.main()
