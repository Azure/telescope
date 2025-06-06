#!/usr/bin/env python3
"""
Unit tests for crud/main.py module (functions beyond collect_benchmark_results)
"""

import unittest
from unittest import mock
import os
import tempfile
import shutil

from crud.main import get_node_pool_crud_class, handle_node_pool_operation, main


class TestNodePoolCRUDFunctions(unittest.TestCase):
    """Tests for the node pool CRUD functions in main.py"""

    def setUp(self):
        """Set up test environment"""
        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()
        self.old_environ = dict(os.environ)

    def tearDown(self):
        """Clean up after tests"""
        # Remove temp directory
        shutil.rmtree(self.test_dir)
        # Restore environment
        os.environ.clear()
        os.environ.update(self.old_environ)

    def test_get_node_pool_crud_class_azure(self):
        """Test retrieving Azure NodePoolCRUD class"""
        cls = get_node_pool_crud_class("azure")
        self.assertEqual(cls.__name__, "NodePoolCRUD")

    def test_get_node_pool_crud_class_unsupported(self):
        """Test retrieving NodePoolCRUD class for unsupported provider"""
        with self.assertRaises(ValueError) as context:
            get_node_pool_crud_class("unsupported")
        self.assertIn("Unsupported cloud provider", str(context.exception))

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_create(self, mock_azure_crud):
        """Test handle_node_pool_operation for create command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "create"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 3
        mock_args.gpu_node_pool = False

        # Configure mock to return success
        mock_azure_crud.create_node_pool.return_value = True

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.create_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            vm_size="Standard_D2s_v3",
            node_count=3,
            gpu_node_pool=False,
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_scale(self, mock_azure_crud):
        """Test handle_node_pool_operation for scale command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.node_pool_name = "test-np"
        mock_args.target_count = 5
        mock_args.progressive = False
        mock_args.scale_step_size = 1
        mock_args.gpu_node_pool = False

        # Configure mock to return success
        mock_azure_crud.scale_node_pool.return_value = True

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.scale_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            node_count=5,
            progressive=False,
            scale_step_size=1,
            gpu_node_pool=False,
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_delete(self, mock_azure_crud):
        """Test handle_node_pool_operation for delete command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "delete"
        mock_args.node_pool_name = "test-np"

        # Configure mock to return success
        mock_azure_crud.delete_node_pool.return_value = True

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.delete_node_pool.assert_called_once_with(
            node_pool_name="test-np"
        )

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_unknown_command(
        self, mock_azure_crud, mock_logger
    ):
        """Test handle_node_pool_operation with unknown command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "unknown"

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 1)  # 1 means error
        mock_logger.error.assert_called_with("Unsupported command: unknown")

    @mock.patch("crud.main.logger")
    @mock.patch("argparse.ArgumentParser")
    def test_main_exception(self, mock_parser_class, mock_logger):
        """Test main function with exception handling"""
        # Setup to raise exception
        mock_parser = mock.MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse_args.side_effect = ValueError("Test error")

        # Execute
        with mock.patch("sys.argv", ["crud.py", "--cloud", "azure", "create"]):
            with mock.patch("sys.exit") as mock_exit:
                main()
                # Verify exit was called with error code
                mock_exit.assert_called_once_with(1)

        # Verify error was logged
        mock_logger.critical.assert_called()


if __name__ == "__main__":
    unittest.main()
