"""CLI integration tests for Azure-specific CRUD options."""

import unittest
from unittest import mock

from crud.main import main


class TestMainAzureOptions(unittest.TestCase):
    """Validate option ownership across CRUD and machine commands."""

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_complete_create_operation(self, mock_azure_crud_class):
        mock_node_pool_crud = mock.MagicMock()
        mock_azure_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = True
        test_args = [
            "crud.py", "create", "--cloud", "azure", "--run-id", "test-run",
            "--cluster-name", "test-cluster", "--exclude-managed-identity",
            "--node-pool-name", "test-pool", "--node-pool-type",
            "VirtualMachines", "--vm-size", "Standard_D2s_v3", "--node-count", "2",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        client_kwargs = mock_azure_crud_class.call_args.kwargs
        self.assertEqual(client_kwargs["cluster_name"], "test-cluster")
        self.assertTrue(client_kwargs["exclude_managed_identity"])
        create_kwargs = mock_node_pool_crud.create_node_pool.call_args.kwargs
        self.assertEqual(create_kwargs["node_pool_type"], "VirtualMachines")

    def test_main_machine_command_rejects_node_pool_azure_options(self):
        test_args = [
            "crud.py", "create-machine", "--cloud", "azure", "--run-id", "test-run",
            "--node-pool-name", "test-pool", "--vm-size", "Standard_D2s_v3",
            "--cluster-name", "test-cluster",
        ]

        with mock.patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as context:
                main()

        self.assertEqual(context.exception.code, 2)

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_delete_does_not_require_node_pool_type(
        self, mock_azure_crud_class
    ):
        mock_node_pool_crud = mock.MagicMock()
        mock_azure_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.delete_node_pool.return_value = True
        test_args = [
            "crud.py", "delete", "--cloud", "azure", "--run-id", "test-run",
            "--cluster-name", "test-cluster", "--exclude-managed-identity",
            "--node-pool-name", "test-pool",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        mock_node_pool_crud.delete_node_pool.assert_called_once_with(
            node_pool_name="test-pool"
        )

    def test_main_aws_rejects_azure_only_options(self):
        test_args = [
            "crud.py", "create", "--cloud", "aws", "--run-id", "test-run",
            "--node-pool-name", "test-pool", "--vm-size", "m6i.2xlarge",
            "--exclude-managed-identity", "--node-pool-type", "VirtualMachines",
        ]

        with mock.patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as context:
                main()

        self.assertEqual(context.exception.code, 2)

    def test_main_workload_rejects_node_pool_type(self):
        test_args = [
            "crud.py", "deployment", "--cloud", "azure", "--run-id", "test-run",
            "--node-pool-name", "test-pool", "--node-pool-type", "VirtualMachines",
        ]

        with mock.patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as context:
                main()

        self.assertEqual(context.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
