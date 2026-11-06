"""VirtualMachines node-pool tests for AKSClient."""

import unittest
from unittest import mock

from clients.aks_client import AKSClient
from utils.provisioning_instrumentation import begin_create_or_update_with_retry


class TestAKSClientVirtualMachines(unittest.TestCase):
    """Validate VirtualMachines create and progressive scale orchestration."""

    def setUp(self):
        self.container_client_patcher = mock.patch(
            "clients.aks_client.ContainerServiceClient"
        )
        self.kubernetes_client_patcher = mock.patch(
            "clients.aks_client.KubernetesClient"
        )
        self.operation_context_patcher = mock.patch("crud.operation.OperationContext")

        mock_container_client = self.container_client_patcher.start()
        self.mock_kubernetes_client = self.kubernetes_client_patcher.start()
        self.mock_operation_context = self.operation_context_patcher.start()
        self.mock_credential = mock.MagicMock()

        self.mock_agent_pools = mock_container_client.return_value.agent_pools
        self.mock_operation_context.return_value.__enter__.return_value = mock.MagicMock()
        self.aks_client = AKSClient(
            subscription_id="fake-subscription-id",
            resource_group="fake-resource-group",
            cluster_name="fake-cluster",
            credential=self.mock_credential,
            result_dir="/tmp/test-results",
        )
        self.aks_client.get_cluster_data = mock.MagicMock(
            return_value={"name": "fake-cluster"}
        )

    def tearDown(self):
        self.operation_context_patcher.stop()
        self.container_client_patcher.stop()
        self.kubernetes_client_patcher.stop()

    @mock.patch("utils.azure_node_pool_cli.subprocess.run")
    def test_create_virtual_machines_node_pool(
        self, mock_subprocess_run
    ):
        self.aks_client.operation_timeout_minutes = 40
        mock_created_node_pool = mock.MagicMock()
        mock_created_node_pool.as_dict.return_value = {"name": "test-pool"}
        self.aks_client.get_node_pool = mock.MagicMock(
            return_value=mock_created_node_pool
        )
        mock_subprocess_run.return_value = mock.MagicMock(
            returncode=0, stdout="", stderr=""
        )

        self.aks_client.k8s_client.wait_for_nodes_ready.return_value = []

        result = self.aks_client.create_node_pool(
            node_pool_name="test-pool",
            vm_size="Standard_D2s_v3",
            node_count=2,
            node_pool_type="VirtualMachines",
        )

        self.assertTrue(result)
        command = mock_subprocess_run.call_args.args[0]
        self.assertIn("--vm-set-type", command)
        self.assertIn("VirtualMachines", command)
        self.assertIn("--vm-sizes", command)
        self.assertIn("Standard_D2s_v3", command)
        self.assertEqual(mock_subprocess_run.call_args.kwargs["timeout"], 2400)
        self.mock_kubernetes_client.return_value.wait_for_nodes_ready.assert_called_once_with(
            node_count=2,
            operation_timeout_in_minutes=40,
            label_selector="agentpool=test-pool",
        )
        operation = self.mock_operation_context.return_value.__enter__.return_value
        operation.add_metadata.assert_any_call("retry_occurred", False)

    @mock.patch("utils.azure_node_pool_cli.subprocess.run")
    @mock.patch("clients.aks_client.time")
    def test_progressive_scale_virtual_machines_node_pool(
        self, mock_time, mock_subprocess_run
    ):
        self.aks_client.operation_timeout_minutes = 40
        mock_time.sleep = mock.MagicMock()
        mock_subprocess_run.return_value = mock.MagicMock(
            returncode=0, stdout="", stderr=""
        )
        mock_node_pool = mock.MagicMock()
        mock_node_pool.virtual_machines_profile = {
            "scale": {
                "manual": [{"size": "Standard_D2s_v3", "count": 1}]
            }
        }
        mock_node_pool.as_dict.return_value = {
            "virtual_machines_profile": mock_node_pool.virtual_machines_profile
        }
        self.aks_client.get_node_pool = mock.MagicMock(return_value=mock_node_pool)

        self.aks_client.k8s_client.wait_for_nodes_ready.return_value = []

        result = self.aks_client.scale_node_pool(
            node_pool_name="test-pool",
            node_count=3,
            progressive=True,
            scale_step_size=1,
            node_pool_type="VirtualMachines",
        )

        self.assertTrue(result)
        self.assertEqual(
            [call.args[0][-1] for call in mock_subprocess_run.call_args_list],
            ["2", "3"],
        )
        self.assertTrue(all(
            call.kwargs["timeout"] == 2400 for call in mock_subprocess_run.call_args_list
        ))

    @mock.patch("utils.azure_node_pool_cli.subprocess.run")
    def test_direct_scale_virtual_machines_uses_real_instrumentation(self, mock_run):
        """Scale up and down must satisfy the shared timing result contract."""
        self.aks_client.operation_timeout_minutes = 40
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        node_pool = mock.MagicMock()
        node_pool.virtual_machines_profile = {
            "scale": {"manual": [{"size": "Standard_D2s_v3", "count": 1}]}
        }
        self.aks_client.get_node_pool = mock.Mock(return_value=node_pool)
        self.aks_client.k8s_client.wait_for_nodes_ready.return_value = []

        for target in (2, 0):
            with self.subTest(target=target):
                self.assertTrue(self.aks_client.scale_node_pool(
                    node_pool_name="test-pool",
                    node_count=target,
                    node_pool_type="VirtualMachines",
                ))
                self.assertEqual(mock_run.call_args.args[0][-1], str(target))
                self.assertEqual(mock_run.call_args.kwargs["timeout"], 2400)

    @mock.patch("utils.azure_node_pool_cli.subprocess.run")
    def test_create_preserves_readiness_failure(self, mock_run):
        """A successful CLI must not hide a Kubernetes readiness failure."""
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        self.aks_client.k8s_client.wait_for_nodes_ready.side_effect = RuntimeError(
            "readiness timed out"
        )

        with self.assertRaisesRegex(RuntimeError, "readiness timed out"):
            self.aks_client.create_node_pool(
                node_pool_name="test-pool",
                vm_size="Standard_D2s_v3",
                node_count=2,
                node_pool_type="VirtualMachines",
            )

    @mock.patch("utils.provisioning_instrumentation.time.sleep")
    def test_default_sdk_preserves_historical_arm_allowance(self, mock_sleep):
        """Ready nodes must not shorten ARM's historical 30-minute allowance."""
        self.assertEqual(self.aks_client.operation_timeout_minutes, 10)
        self.mock_agent_pools.begin_create_or_update.return_value.done.side_effect = (
            [False] * 21 + [True]
        )
        self.aks_client.get_node_pool = mock.MagicMock()
        self.aks_client.k8s_client.wait_for_nodes_ready.return_value = []

        self.assertTrue(self.aks_client.create_node_pool(
            node_pool_name="test-pool", vm_size="Standard_D2s_v3", node_count=1,
        ))

        self.assertEqual(mock_sleep.call_count, 21)
        self.mock_kubernetes_client.return_value.wait_for_nodes_ready.assert_called_once_with(
            node_count=1, operation_timeout_in_minutes=10,
            label_selector="agentpool=test-pool",
        )

    @mock.patch(
        "utils.azure_node_pool_cli.begin_create_or_update_with_retry",
        wraps=begin_create_or_update_with_retry,
    )
    @mock.patch("clients.aks_client.time.sleep")
    @mock.patch("utils.azure_node_pool_cli.subprocess.run")
    def test_arm_timeout_only_extends_existing_allowance(self, mock_run, _sleep, mock_sdk):
        """Both pool types retain old ARM limits across all provisioning paths."""
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        self.mock_agent_pools.begin_create_or_update.return_value.done.return_value = True
        self.aks_client.k8s_client.wait_for_nodes_ready.return_value = []
        node_pool = mock.MagicMock()
        node_pool.count = 1
        node_pool.vm_size = "Standard_D2s_v3"
        node_pool.virtual_machines_profile = {
            "scale": {"manual": [{"size": "Standard_D2s_v3", "count": 1}]}
        }
        self.aks_client.get_node_pool = mock.Mock(return_value=node_pool)

        for minutes, expected in ((1, 1800), (10, 1800), (30, 1800), (40, 2400)):
            self.aks_client.operation_timeout_minutes = minutes
            for pool_type in ("VirtualMachines", "VirtualMachineScaleSets"):
                for action in ("create", "scale-up", "scale-down", "progressive"):
                    with self.subTest(minutes=minutes, pool_type=pool_type, action=action):
                        if action == "create":
                            result = self.aks_client.create_node_pool(
                                node_pool_name="test-pool", vm_size="Standard_D2s_v3",
                                node_count=1, node_pool_type=pool_type,
                            )
                        else:
                            result = self.aks_client.scale_node_pool(
                                node_pool_name="test-pool",
                                node_count={"scale-up": 2, "scale-down": 0, "progressive": 3}[action],
                                progressive=action == "progressive",
                                scale_step_size=1, node_pool_type=pool_type,
                            )
                        self.assertTrue(result)
                        arm = mock_run if pool_type == "VirtualMachines" else mock_sdk
                        self.assertEqual(arm.call_args.kwargs["timeout"], expected)
                        readiness = self.mock_kubernetes_client.return_value.wait_for_nodes_ready
                        self.assertEqual(
                            readiness.call_args.kwargs["operation_timeout_in_minutes"],
                            minutes,
                        )


if __name__ == "__main__":
    unittest.main()
