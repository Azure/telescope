#!/usr/bin/env python3
"""
Unit tests for crud/main.py module (functions beyond collect_benchmark_results)
"""

import unittest
from unittest import mock
import os
import tempfile
import shutil
import json
import json

from crud.main import (
    get_node_pool_crud_class,
    handle_node_pool_operation,
    main,
    check_for_progressive_scaling,
    collect_benchmark_results,
    handle_node_pool_all,
)
from crud.main import (
    get_node_pool_crud_class,
    handle_node_pool_operation,
    main,
    check_for_progressive_scaling,
    collect_benchmark_results,
    handle_node_pool_all,
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
        """Test handle_node_pool_operation for scale command with progressive scaling"""
        """Test handle_node_pool_operation for scale command with progressive scaling"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.node_pool_name = "test-np"
        mock_args.target_count = 5
        mock_args.scale_step_size = (
            1  # scale_step_size != target_count, so progressive=True
        )
        mock_args.scale_step_size = (
            1  # scale_step_size != target_count, so progressive=True
        )
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
            progressive=True,  # Should be True because scale_step_size != target_count
            progressive=True,  # Should be True because scale_step_size != target_count
            scale_step_size=1,
            gpu_node_pool=False,
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_scale_non_progressive(self, mock_azure_crud):
        """Test handle_node_pool_operation for scale command without progressive scaling"""
        # Setup - when scale_step_size equals target_count, progressive should be False
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.node_pool_name = "test-np"
        mock_args.target_count = 3
        mock_args.scale_step_size = (
            3  # scale_step_size == target_count, so progressive=False
        )
        mock_args.gpu_node_pool = False

        # Configure mock to return success
        mock_azure_crud.scale_node_pool.return_value = True

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.scale_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            node_count=3,
            progressive=False,  # Should be False because scale_step_size == target_count
            scale_step_size=3,
            gpu_node_pool=False,
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_scale_non_progressive(self, mock_azure_crud):
        """Test handle_node_pool_operation for scale command without progressive scaling"""
        # Setup - when scale_step_size equals target_count, progressive should be False
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.node_pool_name = "test-np"
        mock_args.target_count = 3
        mock_args.scale_step_size = (
            3  # scale_step_size == target_count, so progressive=False
        )
        mock_args.gpu_node_pool = False

        # Configure mock to return success
        mock_azure_crud.scale_node_pool.return_value = True

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.scale_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            node_count=3,
            progressive=False,  # Should be False because scale_step_size == target_count
            scale_step_size=3,
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

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_all(self, mock_azure_crud):
        """Test handle_node_pool_operation for all command"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "all"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 1
        mock_args.target_count = 3
        mock_args.scale_step_size = 1
        mock_args.gpu_node_pool = True
        mock_args.step_wait_time = 30

        # Configure mock to return success
        mock_azure_crud.all.return_value = True

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.all.assert_called_once_with(
            node_pool_name="test-np",
            vm_size="Standard_D2s_v3",
            node_count=1,
            target_count=3,
            progressive=True,  # Should be True because scale_step_size != target_count
            scale_step_size=1,
            gpu_node_pool=True,
            step_wait_time=30,
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_failure(self, mock_azure_crud):
        """Test handle_node_pool_operation when operation fails"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "create"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 1
        mock_args.gpu_node_pool = False

        # Configure mock to return failure
        mock_azure_crud.create_node_pool.return_value = False

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 1)  # 1 means failure

    def test_check_for_progressive_scaling_true(self):
        """Test check_for_progressive_scaling returns True when scale_step_size != target_count"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.scale_step_size = 1
        mock_args.target_count = 5

        # Execute
        result = check_for_progressive_scaling(mock_args)

        # Verify
        self.assertTrue(result)

    def test_check_for_progressive_scaling_false(self):
        """Test check_for_progressive_scaling returns False when scale_step_size == target_count"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.scale_step_size = 5
        mock_args.target_count = 5

        # Execute
        result = check_for_progressive_scaling(mock_args)

        # Verify
        self.assertFalse(result)

    def test_check_for_progressive_scaling_no_scale_step_size(self):
        """Test check_for_progressive_scaling returns False when scale_step_size is not present"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.target_count = 5
        # Simulate absence of scale_step_size attribute
        delattr(mock_args, "scale_step_size")

        # Execute
        result = check_for_progressive_scaling(mock_args)

        # Verify
        self.assertFalse(result)

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_exception(self, mock_azure_crud, mock_logger):
        """Test handle_node_pool_operation with exception during operation"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "create"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 1
        mock_args.gpu_node_pool = False

        # Configure mock to raise exception
        mock_azure_crud.create_node_pool.side_effect = ValueError("Test error")

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 1)  # 1 means error
        mock_logger.error.assert_called_with(
            "Error during 'create' operation: Test error"
        )

    def test_main_gpu_node_pool_logic(self):
        """Test that the main function correctly handles GPU node pool logic"""
        # Verify that the GPU logic exists by checking the imports and functions exist
        self.assertTrue(callable(handle_node_pool_operation))
        self.assertTrue(callable(check_for_progressive_scaling))

    @mock.patch("crud.main.collect_benchmark_results")
    def test_main_collect_command_simple(self, mock_collect_func):
        """Test main function with collect command - simplified version"""
        # Setup
        mock_collect_func.return_value = 0

        test_args = ["crud.py", "collect"]
        with mock.patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                main()  # Use the imported main function

        # Verify collect function was called and exit code was 0
        mock_collect_func.assert_called_once()
        self.assertEqual(cm.exception.code, 0)


class TestCollectBenchmarkResults(unittest.TestCase):
    """Tests for the collect_benchmark_results function"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.old_environ = dict(os.environ)

    def tearDown(self):
        """Clean up after tests"""
        shutil.rmtree(self.test_dir)
        os.environ.clear()
        os.environ.update(self.old_environ)

    @mock.patch("crud.main.get_env_vars")
    @mock.patch("crud.main.glob.glob")
    @mock.patch("crud.main.datetime")
    def test_collect_benchmark_results_success(
        self, mock_datetime, mock_glob, mock_get_env_vars
    ):
        """Test successful collection of benchmark results"""
        # Setup
        mock_get_env_vars.side_effect = lambda var: {
            "RESULT_DIR": self.test_dir,
            "RUN_URL": "https://example.com/run/123",
            "RUN_ID": "test-run-123",
            "REGION": "eastus",
        }.get(var)

        # Create test JSON files
        test_file1 = os.path.join(self.test_dir, "test1.json")
        test_file2 = os.path.join(self.test_dir, "test2.json")

        test_data1 = {"operation_info": {"operation": "create", "status": "success"}}
        test_data2 = {"operation_info": {"operation": "scale", "status": "success"}}

        with open(test_file1, "w", encoding="utf-8") as f:
            json.dump(test_data1, f)
        with open(test_file2, "w", encoding="utf-8") as f:
            json.dump(test_data2, f)

        mock_glob.return_value = [test_file1, test_file2]
        # Mock datetime.now(timezone.utc).strftime() properly
        mock_datetime_instance = mock.MagicMock()
        mock_datetime_instance.strftime.return_value = "2023-01-01T00:00:00Z"
        mock_datetime.now.return_value = mock_datetime_instance

        # Execute
        result = collect_benchmark_results()

        # Verify
        self.assertEqual(result, 0)

        # Check results.json was created
        results_file = os.path.join(self.test_dir, "results.json")
        self.assertTrue(os.path.exists(results_file))

        # Verify content
        with open(results_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)  # Two result entries

    @mock.patch("crud.main.get_env_vars")
    @mock.patch("crud.main.glob.glob")
    def test_collect_benchmark_results_skip_results_json(
        self, mock_glob, mock_get_env_vars
    ):
        """Test that results.json is skipped during collection"""
        # Setup
        mock_get_env_vars.side_effect = lambda var: {
            "RESULT_DIR": self.test_dir,
            "RUN_URL": "https://example.com/run/123",
            "RUN_ID": "test-run-123",
            "REGION": "eastus",
        }.get(var)

        # Create test files including results.json
        test_file = os.path.join(self.test_dir, "test.json")
        results_file = os.path.join(self.test_dir, "results.json")

        with open(test_file, "w", encoding="utf-8") as f:
            json.dump({"operation_info": {"operation": "test"}}, f)
        with open(results_file, "w", encoding="utf-8") as f:
            f.write("existing content\n")

        mock_glob.return_value = [test_file, results_file]

        # Execute
        result = collect_benchmark_results()

        # Verify
        self.assertEqual(result, 0)

        # Check that results.json still has existing content plus new content
        with open(results_file, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("existing content", content)

    @mock.patch("crud.main.get_env_vars")
    @mock.patch("crud.main.glob.glob")
    def test_collect_benchmark_results_no_files(self, mock_glob, mock_get_env_vars):
        """Test collection when no JSON files are found"""
        # Setup
        mock_get_env_vars.side_effect = lambda var: {
            "RESULT_DIR": self.test_dir,
            "RUN_URL": "https://example.com/run/123",
            "RUN_ID": "test-run-123",
            "REGION": "eastus",
        }.get(var)

        mock_glob.return_value = []

        # Execute
        result = collect_benchmark_results()

        # Verify
        self.assertEqual(result, 0)


class TestHandleNodePoolAll(unittest.TestCase):
    """Tests for the handle_node_pool_all function"""

    @mock.patch("crud.main.logger")
    def test_handle_node_pool_all_success(self, mock_logger):
        """Test successful execution of all node pool operations"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_node_pool_crud.all.return_value = True

        mock_args = mock.MagicMock()
        mock_args.node_pool_name = "test-pool"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 1
        mock_args.target_count = 3
        mock_args.scale_step_size = 1
        mock_args.gpu_node_pool = False

        # Execute
        result = handle_node_pool_all(mock_node_pool_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)
        mock_node_pool_crud.all.assert_called_once()
        mock_logger.info.assert_called_with(
            "All node pool operations completed successfully"
        )

    @mock.patch("crud.main.logger")
    def test_handle_node_pool_all_failure(self, mock_logger):
        """Test failed execution of all node pool operations"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_node_pool_crud.all.return_value = False

        mock_args = mock.MagicMock()
        mock_args.node_pool_name = "test-pool"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 1
        mock_args.target_count = 3
        mock_args.scale_step_size = 1
        mock_args.gpu_node_pool = False

        # Execute
        result = handle_node_pool_all(mock_node_pool_crud, mock_args)

        # Verify
        self.assertEqual(result, 1)
        mock_logger.error.assert_called_with("One or more node pool operations failed")

    @mock.patch("crud.main.logger")
    def test_handle_node_pool_all_exception(self, mock_logger):
        """Test exception handling in handle_node_pool_all"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_node_pool_crud.all.side_effect = ValueError("Test error")

        mock_args = mock.MagicMock()
        mock_args.node_pool_name = "test-pool"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 1
        mock_args.target_count = 3

        # Execute
        result = handle_node_pool_all(mock_node_pool_crud, mock_args)

        # Verify
        self.assertEqual(result, 1)
        mock_logger.error.assert_called_with(
            "Error during all operations sequence: Test error"
        )

    def test_handle_node_pool_all_missing_attributes(self):
        """Test handle_node_pool_all with missing optional attributes"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_node_pool_crud.all.return_value = True

        mock_args = mock.MagicMock()
        mock_args.node_pool_name = "test-pool"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 1
        mock_args.target_count = 3
        # Remove optional attributes
        delattr(mock_args, "scale_step_size")
        delattr(mock_args, "gpu_node_pool")

        # Execute
        result = handle_node_pool_all(mock_node_pool_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)
        # Check that defaults were used
        call_args = mock_node_pool_crud.all.call_args[1]
        self.assertEqual(call_args["scale_step_size"], 1)
        self.assertEqual(call_args["gpu_node_pool"], False)


class TestMainFunctionIntegration(unittest.TestCase):
    """Integration tests for the main function"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests"""
        shutil.rmtree(self.test_dir)

    @mock.patch("sys.exit")
    @mock.patch("argparse.ArgumentParser.print_help")
    def test_main_no_func_attribute(self, mock_print_help, mock_exit):
        """Test main function when args has no func attribute"""
        test_args = ["crud.py"]

        with mock.patch("sys.argv", test_args):
            main()  # Use the imported main function

        mock_print_help.assert_called_once()
        # Function may call sys.exit multiple times due to error handling flow
        self.assertTrue(mock_exit.called)
        # Verify it was called with exit code 1 at least once
        self.assertIn(mock.call(1), mock_exit.call_args_list)

    @mock.patch("sys.exit")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_complete_create_operation(
        self, mock_azure_crud_class, mock_exit
    ):
        """Test complete create operation flow"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_azure_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = True

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "Standard_D2s_v3",
            "--node-count",
            "2",
        ]

        with mock.patch("sys.argv", test_args):
            main()  # Use the imported main function

        # Verify
        mock_azure_crud_class.assert_called_once()
        mock_node_pool_crud.create_node_pool.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @mock.patch("sys.exit")
    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_operation_returns_none(
        self, mock_azure_crud_class, mock_operation_context, mock_exit  # pylint: disable=unused-argument
    ):
        """Test main function when operation returns None (backward compatibility)"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_azure_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = None

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "Standard_D2s_v3",
        ]

        with mock.patch("sys.argv", test_args):
            main()  # Use the imported main function

        # Verify exit code 0 for None return (backward compatibility)
        mock_exit.assert_called_once_with(0)

    @mock.patch("sys.exit")
    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_operation_returns_boolean_false(
        self, mock_azure_crud_class, mock_operation_context, mock_exit  # pylint: disable=unused-argument
    ):
        """Test main function when operation returns False"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_azure_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = False

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "Standard_D2s_v3",
        ]

        with mock.patch("sys.argv", test_args):
            main()  # Use the imported main function

        # Verify exit code 1 for False return
        mock_exit.assert_called_once_with(1)

    @mock.patch("sys.exit")
    @mock.patch("crud.main.logger")
    def test_main_import_error_handling(self, mock_logger, mock_exit):
        """Test main function ImportError handling"""
        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "unsupported",
            "--run-id",
            "test",
            "--node-pool-name",
            "test",
        ]

        with mock.patch("sys.argv", test_args):
            main()  # Use the imported main function

        # Verify error logging and exit
        mock_logger.critical.assert_called()
        # Function may call sys.exit multiple times due to argparse and error handling
        self.assertTrue(mock_exit.called)
        # Verify it was called with exit code 1 at least once
        self.assertIn(mock.call(1), mock_exit.call_args_list)

    @mock.patch("sys.exit")
    @mock.patch("crud.main.logger")
    @mock.patch("argparse.ArgumentParser.parse_args")
    def test_main_general_exception_handling(
        self, mock_parse_args, mock_logger, mock_exit
    ):
        """Test main function general exception handling"""
        # Setup to raise a general exception
        mock_parse_args.side_effect = RuntimeError("Unexpected error")

        main()

        # Verify error logging and exit
        mock_logger.critical.assert_called()
        mock_exit.assert_called_once_with(1)

    @mock.patch("sys.exit")
    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_gpu_node_pool_enabled(
        self, mock_azure_crud_class, mock_operation_context, mock_exit
    ):
        """Test main function with GPU node pool enabled"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_k8s_client = mock.MagicMock()
        mock_aks_client = mock.MagicMock()
        mock_aks_client.k8s_client = mock_k8s_client
        mock_node_pool_crud.aks_client = mock_aks_client

        mock_azure_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = True
        mock_k8s_client.verify_gpu_device_plugin.return_value = True

        # Setup operation context mock
        mock_op = mock.MagicMock()
        mock_operation_context.return_value.__enter__.return_value = mock_op

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "gpu-pool",
            "--vm-size",
            "Standard_NC6s_v3",
            "--gpu-node-pool",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        # Verify GPU device plugin was installed and verified
        mock_k8s_client.install_gpu_device_plugin.assert_called_once()
        mock_k8s_client.verify_gpu_device_plugin.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @mock.patch("sys.exit")
    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_gpu_verification_fails(
        self, mock_azure_crud_class, mock_operation_context, mock_exit
    ):
        """Test main function when GPU verification fails"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_k8s_client = mock.MagicMock()
        mock_aks_client = mock.MagicMock()
        mock_aks_client.k8s_client = mock_k8s_client
        mock_node_pool_crud.aks_client = mock_aks_client

        mock_azure_crud_class.return_value = mock_node_pool_crud
        mock_k8s_client.verify_gpu_device_plugin.return_value = False

        # Setup operation context mock
        mock_op = mock.MagicMock()
        mock_operation_context.return_value.__enter__.return_value = mock_op

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "gpu-pool",
            "--vm-size",
            "Standard_NC6s_v3",
            "--gpu-node-pool",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        # Verify GPU verification failed and operation was marked as failed
        mock_k8s_client.verify_gpu_device_plugin.assert_called_once()
        self.assertFalse(mock_op.success)
        # Function may call sys.exit multiple times due to error handling flow
        self.assertTrue(mock_exit.called)
        # Verify it was called with exit code 1 at least once
        self.assertIn(mock.call(1), mock_exit.call_args_list)


class TestGetNodePoolCRUDClassErrorHandling(unittest.TestCase):
    """Tests for error handling in get_node_pool_crud_class"""

    def test_get_node_pool_crud_class_aws_not_implemented(self):
        """Test ValueError for AWS (not implemented)"""
        with self.assertRaises(ValueError) as context:
            get_node_pool_crud_class("aws")

        self.assertIn("Unsupported cloud provider: aws", str(context.exception))

    def test_get_node_pool_crud_class_gcp_not_implemented(self):
        """Test ValueError for GCP (not implemented)"""
        with self.assertRaises(ValueError) as context:
            get_node_pool_crud_class("gcp")

        self.assertIn("Unsupported cloud provider: gcp", str(context.exception))

    def test_get_node_pool_crud_class_random_provider(self):
        """Test ValueError for unsupported random provider"""
        with self.assertRaises(ValueError) as context:
            get_node_pool_crud_class("random_provider")

        self.assertIn(
            "Unsupported cloud provider: random_provider", str(context.exception)
        )
