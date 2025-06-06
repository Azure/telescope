#!/usr/bin/env python3
"""
Unit tests for crud/main.py module (functions beyond collect_benchmark_results)
"""

import unittest
from unittest import mock
import os
import tempfile
import argparse
import shutil

from crud.main import (
    get_node_pool_crud_class,
    handle_node_pool_operation,
    main
)


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
        mock_args.enable_auto_scaling = False
        mock_args.min_count = None
        mock_args.max_count = None
        mock_args.labels = None
        mock_args.taints = None
        mock_args.mode = None
        
        mock_azure_crud.create_node_pool.return_value = {"status": "success"}
        
        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)
        
        # Verify
        self.assertEqual(result, {"status": "success"})
        mock_azure_crud.create_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            vm_size="Standard_D2s_v3",
            node_count=3,
            enable_auto_scaling=False,
            min_count=None,
            max_count=None,
            labels=None,
            taints=None,
            mode=None
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_scale(self, mock_azure_crud):
        """Test handle_node_pool_operation for scale command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.node_pool_name = "test-np"
        mock_args.node_count = 5
        
        mock_azure_crud.scale_node_pool.return_value = {"status": "success"}
        
        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)
        
        # Verify
        self.assertEqual(result, {"status": "success"})
        mock_azure_crud.scale_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            node_count=5
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_delete(self, mock_azure_crud):
        """Test handle_node_pool_operation for delete command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "delete"
        mock_args.node_pool_name = "test-np"
        
        mock_azure_crud.delete_node_pool.return_value = {"status": "success"}
        
        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)
        
        # Verify
        self.assertEqual(result, {"status": "success"})
        mock_azure_crud.delete_node_pool.assert_called_once_with(
            node_pool_name="test-np"
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_unknown_command(self, mock_azure_crud):
        """Test handle_node_pool_operation with unknown command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "unknown"
        
        # Execute and verify
        with self.assertRaises(ValueError) as context:
            handle_node_pool_operation(mock_azure_crud, mock_args)
        
        self.assertIn("Invalid command", str(context.exception))

    def test_validate_args_create_command(self):
        """Test validating arguments for create command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "create"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 3
        
        # Execute (should not raise exception)
        validate_args(mock_args)

    def test_validate_args_missing_required(self):
        """Test validating arguments with missing required fields"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "create"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = None  # Missing required field
        mock_args.node_count = 3
        
        # Execute and verify
        with self.assertRaises(ValueError) as context:
            validate_args(mock_args)
        
        self.assertIn("Required argument 'vm_size' is missing", str(context.exception))

    def test_validate_args_auto_scale_missing_min_max(self):
        """Test validating auto-scaling args with missing min/max count"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "create"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 3
        mock_args.enable_auto_scaling = True
        mock_args.min_count = None  # Missing required for auto-scaling
        mock_args.max_count = None  # Missing required for auto-scaling
        
        # Execute and verify
        with self.assertRaises(ValueError) as context:
            validate_args(mock_args)
        
        self.assertIn("min_count and max_count must be specified", str(context.exception))

    def test_setup_cli_args(self):
        """Test setting up CLI argument parser"""
        parser = setup_cli_args()
        self.assertIsInstance(parser, argparse.ArgumentParser)
        
        # Test parsing basic create command
        args = parser.parse_args([
            "--cloud", "azure", 
            "create", 
            "--node-pool-name", "test-np", 
            "--vm-size", "Standard_D2s_v3", 
            "--node-count", "3"
        ])
        
        self.assertEqual(args.cloud, "azure")
        self.assertEqual(args.command, "create")
        self.assertEqual(args.node_pool_name, "test-np")
        self.assertEqual(args.vm_size, "Standard_D2s_v3")
        self.assertEqual(args.node_count, 3)

    @mock.patch("crud.main.handle_node_pool_operation")
    @mock.patch("crud.main.get_node_pool_crud_class")
    @mock.patch("crud.main.setup_cli_args")
    def test_main_success(self, mock_setup_cli, mock_get_class, mock_handle_op):
        """Test main function with successful execution"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.cloud = "azure"
        mock_args.command = "create"
        mock_args.result_dir = self.test_dir
        
        mock_setup_cli.return_value.parse_args.return_value = mock_args
        mock_crud_class = mock.MagicMock()
        mock_get_class.return_value = mock_crud_class
        mock_handle_op.return_value = {"status": "success"}
        
        # Execute
        with mock.patch("sys.argv", ["crud.py", "--cloud", "azure", "create"]):
            main()
        
        # Verify
        mock_setup_cli.assert_called_once()
        mock_get_class.assert_called_once_with("azure")
        mock_handle_op.assert_called_once()
        
        # Check if result file was created
        result_files = [f for f in os.listdir(self.test_dir) if f.endswith('.json')]
        self.assertEqual(len(result_files), 1)

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.setup_cli_args")
    def test_main_exception(self, mock_setup_cli, mock_logger):
        """Test main function with exception handling"""
        # Setup to raise exception
        mock_setup_cli.return_value.parse_args.side_effect = ValueError("Test error")
        
        # Execute
        with mock.patch("sys.argv", ["crud.py", "--cloud", "azure", "create"]):
            with self.assertRaises(SystemExit):
                main()
        
        # Verify error was logged
        mock_logger.error.assert_called()


if __name__ == "__main__":
    unittest.main()
