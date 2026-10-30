"""
Unit tests for crud/main.py module (functions beyond collect_benchmark_results)
"""
# pylint: disable=too-many-lines

import unittest
from unittest import mock
import argparse
import os
import tempfile
import shutil
import json

from crud.main import (
    _build_operation_info,
    get_node_pool_crud_class,
    handle_node_pool_operation,
    handle_workload_operations,
    main,
    check_for_progressive_scaling,
    collect_benchmark_results,
    handle_node_pool_all,
)


class TestBuildOperationInfo(unittest.TestCase):
    """Tests for the ADX compatibility adapter."""

    def test_preserves_canonical_names_and_maps_legacy_names(self):
        """Canonical names remain available while ADX receives legacy names."""
        expected_names = {
            "create_node_pool": "create_agent_pool",
            "scale_up": "scale_agent_pool",
            "scale_down": "clean_agent_pool",
            "delete_node_pool": "delete_agent_pool",
            "create_pods": "create_pods",
            "create_statefulset": "create_statefulset",
            "create_jobs": "create_jobs",
        }

        for canonical_name, legacy_name in expected_names.items():
            with self.subTest(canonical_name=canonical_name):
                operation_info = _build_operation_info(
                    {
                        "operation_info": {
                            "name": canonical_name,
                            "duration": 12.5,
                            "success": True,
                            "metadata": {},
                        }
                    }
                )

                self.assertEqual(operation_info["canonical_name"], canonical_name)
                self.assertEqual(operation_info["name"], legacy_name)
                self.assertEqual(operation_info["duration"], 12.5)
                self.assertEqual(operation_info["time"], 12.5)
                self.assertTrue(operation_info["success"])
                self.assertTrue(operation_info["succeeded"])

    def test_preserves_failure_and_workload_metadata(self):
        """Failure state and workload metadata survive compatibility mapping."""
        metadata = {"workload_count": 3, "successful_workloads": 2}

        operation_info = _build_operation_info(
            {
                "operation_info": {
                    "name": "create_pods",
                    "duration": 30.0,
                    "success": False,
                    "error_message": "Created 2/3 Deployment(s)",
                    "metadata": metadata,
                }
            }
        )

        self.assertFalse(operation_info["success"])
        self.assertFalse(operation_info["succeeded"])
        self.assertEqual(operation_info["error_message"], "Created 2/3 Deployment(s)")
        self.assertEqual(operation_info["data"], metadata)

    def test_preserves_node_pool_metadata_without_mutating_source(self):
        """Node timings and cluster data are aliases of canonical metadata."""
        metadata = {
            "command_execution_time": 45.0,
            "node_readiness_time": 75.0,
            "cluster_info": {"nodeImageVersion": "AKSUbuntu-2204gen2"},
        }
        source = {
            "operation_info": {
                "name": "scale_down",
                "success": False,
                "duration": 120.0,
                "metadata": metadata,
                "error_message": "readiness timed out",
            }
        }
        original = json.loads(json.dumps(source))

        operation_info = _build_operation_info(source)

        self.assertEqual(source, original)
        self.assertEqual(operation_info["name"], "clean_agent_pool")
        self.assertEqual(operation_info["command_execution_time"], 45.0)
        self.assertEqual(operation_info["node_readiness_time"], 75.0)
        self.assertEqual(json.loads(operation_info["data"]), metadata["cluster_info"])
        self.assertEqual(operation_info["metadata"], metadata)
        self.assertFalse(operation_info["succeeded"])

    def test_preserves_unmapped_operations(self):
        """Other canonical operations remain collectable without legacy renaming."""
        operation_info = _build_operation_info(
            {"operation_info": {"name": "create_machines", "success": True}}
        )

        self.assertEqual(operation_info["name"], "create_machines")
        self.assertEqual(operation_info["canonical_name"], "create_machines")
        self.assertEqual(operation_info["data"], {})


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

    def test_get_node_pool_crud_class_aws(self):
        """Test retrieving AWS NodePoolCRUD class"""
        cls = get_node_pool_crud_class("aws")
        self.assertEqual(cls.__name__, "NodePoolCRUD")

    def test_get_node_pool_crud_class_gcp_not_implemented(self):
        """Test retrieving GCP NodePoolCRUD class (not implemented)"""
        with self.assertRaises(ValueError) as context:
            get_node_pool_crud_class("gcp")
        self.assertIn(
            "GCP NodePoolCRUD implementation not yet available", str(context.exception)
        )

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
        mock_args.cloud = "azure"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 3
        mock_args.node_pool_type = "VirtualMachines"
        mock_args.gpu_node_pool = False
        mock_args.enable_managed_gpu = False

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
            node_pool_type="VirtualMachines",
            gpu_node_pool=False,
            enable_managed_gpu=False,
            gpu_instance_profile=mock_args.gpu_instance_profile,
            gpu_mig_strategy=mock_args.gpu_mig_strategy,
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_scale(self, mock_azure_crud):
        """Test handle_node_pool_operation for scale command with progressive scaling"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.cloud = "azure"
        mock_args.node_pool_name = "test-np"
        mock_args.target_count = 5
        mock_args.node_pool_type = "VirtualMachines"
        mock_args.scale_step_size = (
            1  # scale_step_size != target_count, so progressive=True
        )
        mock_args.gpu_node_pool = False
        mock_args.enable_managed_gpu = False

        # Configure mock to return success
        mock_azure_crud.scale_node_pool.return_value = True

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.scale_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            node_count=5,
            node_pool_type="VirtualMachines",
            progressive=True,  # Should be True because scale_step_size != target_count
            scale_step_size=1,
            gpu_node_pool=False,
            enable_managed_gpu=False,
            gpu_instance_profile=mock_args.gpu_instance_profile,
            gpu_mig_strategy=mock_args.gpu_mig_strategy,
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_scale_non_progressive(self, mock_azure_crud):
        """Test handle_node_pool_operation for scale command without progressive scaling"""
        # Setup - when scale_step_size equals target_count, progressive should be False
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.cloud = "azure"
        mock_args.node_pool_name = "test-np"
        mock_args.target_count = 3
        mock_args.node_pool_type = "VirtualMachineScaleSets"
        mock_args.scale_step_size = (
            3  # scale_step_size == target_count, so progressive=False
        )
        mock_args.gpu_node_pool = False
        mock_args.enable_managed_gpu = False

        # Configure mock to return success
        mock_azure_crud.scale_node_pool.return_value = True

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.scale_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            node_count=3,
            node_pool_type="VirtualMachineScaleSets",
            progressive=False,  # Should be False because scale_step_size == target_count
            scale_step_size=3,
            gpu_node_pool=False,
            enable_managed_gpu=False,
            gpu_instance_profile=mock_args.gpu_instance_profile,
            gpu_mig_strategy=mock_args.gpu_mig_strategy,
        )

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_scale_fails_returns_error(
        self, mock_azure_crud, mock_logger
    ):
        """Test handle_node_pool_operation when scale up fails but continues execution.

        This test verifies that when scale_node_pool returns False (e.g., some nodes
        failed to scale but the operation completed), the function correctly returns
        exit code 1 to indicate failure while allowing the calling code to continue.
        """
        # Setup - progressive scaling where operation fails
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.cloud = "azure"
        mock_args.node_pool_name = "test-np"
        mock_args.target_count = 10
        mock_args.node_pool_type = "VirtualMachineScaleSets"
        mock_args.scale_step_size = 2  # Progressive scaling
        mock_args.gpu_node_pool = False
        mock_args.enable_managed_gpu = False

        # Configure mock to return False (scale failed but didn't raise exception)
        mock_azure_crud.scale_node_pool.return_value = False

        # Execute
        result = handle_node_pool_operation(mock_azure_crud, mock_args)

        # Verify - operation failed but returned gracefully (no exception)
        self.assertEqual(result, 1)  # 1 means failure
        mock_azure_crud.scale_node_pool.assert_called_once_with(
            node_pool_name="test-np",
            node_count=10,
            node_pool_type="VirtualMachineScaleSets",
            progressive=True,
            scale_step_size=2,
            gpu_node_pool=False,
            enable_managed_gpu=False,
            gpu_instance_profile=mock_args.gpu_instance_profile,
            gpu_mig_strategy=mock_args.gpu_mig_strategy,
        )
        mock_logger.error.assert_called_with("Operation 'scale' failed")

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
        mock_args.cloud = "azure"
        mock_args.node_pool_name = "test-np"
        mock_args.vm_size = "Standard_D2s_v3"
        mock_args.node_count = 1
        mock_args.target_count = 3
        mock_args.node_pool_type = "VirtualMachines"
        mock_args.scale_step_size = 1
        mock_args.gpu_node_pool = True
        mock_args.enable_managed_gpu = False
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
            node_pool_type="VirtualMachines",
            progressive=True,  # Should be True because scale_step_size != target_count
            scale_step_size=1,
            gpu_node_pool=True,
            enable_managed_gpu=False,
            step_wait_time=30,
            gpu_instance_profile=mock_args.gpu_instance_profile,
            gpu_mig_strategy=mock_args.gpu_mig_strategy,
        )

    def test_handle_node_pool_operation_scale_aws_omits_mig_kwargs(self):
        """AWS scale must not receive Azure-only MIG kwargs (the AWS CRUD rejects them)."""
        mock_args = mock.MagicMock()
        mock_args.command = "scale"
        mock_args.cloud = "aws"
        mock_args.node_pool_name = "test-np"
        mock_args.target_count = 5
        mock_args.scale_step_size = 1
        mock_args.gpu_node_pool = False
        mock_args.enable_managed_gpu = False

        mock_crud = mock.MagicMock()
        mock_crud.scale_node_pool.return_value = True

        result = handle_node_pool_operation(mock_crud, mock_args)

        self.assertEqual(result, 0)
        call_kwargs = mock_crud.scale_node_pool.call_args.kwargs
        self.assertNotIn("gpu_instance_profile", call_kwargs)
        self.assertNotIn("gpu_mig_strategy", call_kwargs)
        self.assertNotIn("node_pool_type", call_kwargs)
        self.assertNotIn("vm_size", call_kwargs)

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_node_pool_operation_failure(self, mock_azure_crud):
        """Test handle_node_pool_operation when operation fails"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "create"
        mock_args.cloud = "azure"
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
        mock_args.cloud = "azure"
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
        """Test collect command passes explicit pipeline context."""
        mock_collect_func.return_value = 0

        test_args = [
            "crud.py",
            "collect",
            "--legacy-output",
            "--result-dir",
            "/tmp/results",
            "--result-file",
            "/tmp/results/final.json",
            "--run-id",
            "run-123",
            "--run-url",
            "https://example.com/run/123",
            "--region",
            "eastus",
            "--cloud-info",
            '{"cloud":"azure"}',
            "--scale-node-count",
            "10",
        ]
        with mock.patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                main()

        collect_args = mock_collect_func.call_args.args[0]
        self.assertTrue(collect_args.legacy_output)
        self.assertEqual(collect_args.result_dir, "/tmp/results")
        self.assertEqual(collect_args.result_file, "/tmp/results/final.json")
        self.assertEqual(collect_args.run_id, "run-123")
        self.assertEqual(collect_args.region, "eastus")
        self.assertEqual(collect_args.scale_node_count, "10")
        self.assertEqual(cm.exception.code, 0)

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_workload_operations_create_deployment_success(self, mock_azure_crud):
        """Test handle_workload_operations for successful deployment creation"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "deployment"
        mock_args.node_pool_name = "test-nodepool"
        mock_args.replicas = 5
        mock_args.manifest_dir = "/path/to/manifests"
        mock_args.count = 3
        mock_args.label_selector = "app=nginx-container"

        # Configure mock to return success
        mock_azure_crud.create_deployment.return_value = True

        # Execute
        result = handle_workload_operations(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.create_deployment.assert_called_once_with(
            node_pool_name="test-nodepool",
            replicas=5,
            manifest_dir="/path/to/manifests",
            number_of_deployments=3,
            label_selector="app=nginx-container"
        )

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_workload_operations_failure(self, mock_azure_crud):
        """Test handle_workload_operations when operation fails"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "deployment"
        mock_args.node_pool_name = "test-nodepool"
        mock_args.replicas = 5
        mock_args.manifest_dir = "/path/to/manifests"
        mock_args.count = 3

        # Configure mock to return failure
        mock_azure_crud.create_deployment.return_value = False

        # Execute
        result = handle_workload_operations(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 1)  # 1 means failure

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_workload_operations_exception(self, mock_azure_crud, mock_logger):
        """Test handle_workload_operations with exception during operation"""
        # Setup
        mock_args = mock.MagicMock()
        mock_args.command = "deployment"
        mock_args.node_pool_name = "test-nodepool"
        mock_args.replicas = 5
        mock_args.manifest_dir = "/path/to/manifests"
        mock_args.count = 3

        # Configure mock to raise exception
        mock_azure_crud.create_deployment.side_effect = ValueError("Test error")

        # Execute
        result = handle_workload_operations(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 1)  # 1 means error
        mock_logger.error.assert_called_with(
            "Error during 'deployment' operation: Test error"
        )

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_workload_operations_partial_success(self, mock_azure_crud, mock_logger):
        """Test handle_workload_operations when deployment returns partial success (False).

        The create_deployment method returns False when some deployments succeed but
        not all of them (partial success). This tests that handle_workload_operations
        correctly treats this as a failure and returns exit code 1.
        """
        # Setup - simulate a partial success scenario where create_deployment
        # returns False (e.g., 2 out of 3 deployments succeeded)
        mock_args = mock.MagicMock()
        mock_args.command = "deployment"
        mock_args.node_pool_name = "test-nodepool"
        mock_args.replicas = 5
        mock_args.manifest_dir = "/path/to/manifests"
        mock_args.count = 3  # Requesting 3 deployments
        mock_args.label_selector = "app=nginx-container"

        # Configure mock to return False (partial success - some deployments
        # succeeded but not all, which is still considered a failure)
        mock_azure_crud.create_deployment.return_value = False

        # Execute
        result = handle_workload_operations(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 1)  # 1 means failure (partial success is still failure)
        mock_azure_crud.create_deployment.assert_called_once_with(
            node_pool_name="test-nodepool",
            replicas=5,
            manifest_dir="/path/to/manifests",
            number_of_deployments=3,
            label_selector="app=nginx-container"
        )
        # Verify the error was logged for the failed operation
        mock_logger.error.assert_called_with("Operation 'deployment' failed")

    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_handle_workload_operations_multiple_deployments_success(self, mock_azure_crud):
        """Test handle_workload_operations with multiple deployments all succeeding.

        This test verifies that when create_deployment is called with multiple
        deployments (number_of_deployments > 1) and all deployments succeed,
        the function returns success (exit code 0).
        """
        # Setup - configure for multiple deployments
        mock_args = mock.MagicMock()
        mock_args.command = "deployment"
        mock_args.node_pool_name = "test-nodepool"
        mock_args.replicas = 10
        mock_args.manifest_dir = "/path/to/manifests"
        mock_args.count = 5  # Multiple deployments
        mock_args.label_selector = "app=nginx-container"

        # Configure mock to return True (all deployments succeeded)
        mock_azure_crud.create_deployment.return_value = True

        # Execute
        result = handle_workload_operations(mock_azure_crud, mock_args)

        # Verify
        self.assertEqual(result, 0)  # 0 means success
        mock_azure_crud.create_deployment.assert_called_once_with(
            node_pool_name="test-nodepool",
            replicas=10,
            manifest_dir="/path/to/manifests",
            number_of_deployments=5,
            label_selector="app=nginx-container"
        )


class TestCollectBenchmarkResults(unittest.TestCase):
    """Tests for the collect_benchmark_results function"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.old_environ = dict(os.environ)
        self.env_vars = {
            "RESULT_DIR": self.test_dir,
            "RUN_URL": "https://example.com/run/123",
            "RUN_ID": "test-run-123",
            "REGION": "eastus",
        }
        self.legacy_args = argparse.Namespace(legacy_output=True)

    def tearDown(self):
        """Clean up after tests"""
        shutil.rmtree(self.test_dir)
        os.environ.clear()
        os.environ.update(self.old_environ)

    def _set_env(self, **values):
        """Configure collector environment values for a test."""
        self.env_vars.update(values)
        os.environ.update(self.env_vars)

    def _write_operation(self, name, filename=None, **values):
        """Write one canonical operation fixture and return its path."""
        operation = {"name": name, "success": True, "metadata": {}}
        operation.update(values)
        path = os.path.join(self.test_dir, filename or f"{name}.json")
        with open(path, "w", encoding="utf-8") as result_file:
            json.dump({"operation_info": operation}, result_file)
        return path

    def _read_rows(self):
        """Read final JSONL rows from the default output file."""
        with open(
            os.path.join(self.test_dir, "results.json"), "r", encoding="utf-8"
        ) as results_file:
            return [json.loads(line) for line in results_file]

    def _assert_failed_collection_preserves_output(self, args):
        results_path = os.path.join(self.test_dir, "results.json")
        with open(results_path, "w", encoding="utf-8") as results_file:
            results_file.write("previous-valid-output\n")
        original_files = sorted(os.listdir(self.test_dir))

        with self.assertLogs("crud.main", level="ERROR"):
            self.assertEqual(collect_benchmark_results(args), 1)

        with open(results_path, encoding="utf-8") as results_file:
            self.assertEqual(results_file.read(), "previous-valid-output\n")
        self.assertEqual(sorted(os.listdir(self.test_dir)), original_files)

    @mock.patch("crud.main.glob.glob")
    @mock.patch("crud.main.datetime")
    def test_collect_benchmark_results_success(self, mock_datetime, mock_glob):
        """Test successful collection of benchmark results"""
        self._set_env()
        test_file1 = self._write_operation("create_node_pool", "test1.json")
        test_file2 = self._write_operation("scale_up", "test2.json")
        mock_glob.return_value = [test_file1, test_file2]
        # Mock datetime.now(timezone.utc).strftime() properly
        mock_datetime_instance = mock.MagicMock()
        mock_datetime_instance.strftime.return_value = "2023-01-01T00:00:00Z"
        mock_datetime.now.return_value = mock_datetime_instance

        self.assertEqual(collect_benchmark_results(), 0)
        self.assertEqual(len(self._read_rows()), 2)

    def test_collect_benchmark_results_preserves_workload_operations(self):
        """Test aggregate workload records are collected as distinct rows."""
        self._set_env()

        operation_names = ["create_pods", "create_statefulset", "create_jobs"]
        for operation_name in operation_names:
            self._write_operation(
                operation_name,
                cloud="azure",
                duration=10.0,
                metadata={"workload_type": operation_name},
                unit="seconds",
            )

        self.assertEqual(collect_benchmark_results(), 0)
        rows = self._read_rows()

        self.assertEqual(len(rows), 3)
        collected_names = {
            json.loads(row["operation_info"])["name"] for row in rows
        }
        self.assertEqual(collected_names, set(operation_names))
        for row in rows:
            self.assertEqual(row["region"], "eastus")
            self.assertEqual(row["run_id"], "test-run-123")
            self.assertEqual(row["run_url"], "https://example.com/run/123")

    def test_collect_benchmark_results_emits_scale_up_compatibility_row(self):
        """Scale-up rows retain canonical data and legacy ADX fields."""
        self._set_env(
            CLOUD_INFO='{"cloud":"azure","aks_name":"test-cluster"}',
            VM_SIZE="Standard_D4s_v5",
            NODE_POOL_NAME="np1",
            CREATE_NODE_COUNT="1",
            SCALE_NODE_COUNT="10",
            NODE_POOL_TYPE="VirtualMachineScaleSets",
            NODE_POOL_NUMBER="1",
            BATCH_SIZE="1",
            WORKLOAD_TEST_SETTING="PodSetting=10*10*1200",
        )
        self._write_operation(
            "scale_up",
            filename="azure_scale_up.json",
            cloud="azure",
            start_timestamp="2026-10-09T12:00:00Z",
            end_timestamp="2026-10-09T12:02:00Z",
            duration=120.0,
            error_message=None,
            error_traceback=None,
            metadata={
                "command_execution_time": 45.0,
                "node_readiness_time": 75.0,
                "cluster_info": {"nodeImageVersion": "AKSUbuntu-2204gen2"},
            },
            unit="seconds",
        )

        self.assertEqual(collect_benchmark_results(self.legacy_args), 0)
        row = self._read_rows()[0]
        operation_info = json.loads(row["operation_info"])

        self.assertEqual(operation_info["name"], "scale_agent_pool")
        self.assertEqual(operation_info["canonical_name"], "scale_up")
        self.assertTrue(operation_info["success"])
        self.assertTrue(operation_info["succeeded"])
        self.assertEqual(operation_info["duration"], 120.0)
        self.assertEqual(operation_info["command_execution_time"], 45.0)
        self.assertEqual(operation_info["node_readiness_time"], 75.0)
        self.assertEqual(
            json.loads(operation_info["data"]), {"nodeImageVersion": "AKSUbuntu-2204gen2"}
        )
        self.assertEqual(json.loads(row["cloud_info"])["cloud"], "azure")
        self.assertEqual(json.loads(row["aks_data"])["scale_node_count"], 10)
        self.assertEqual(json.loads(row["aks_data"])["create_node_count"], 1)
        self.assertEqual(json.loads(row["aks_data"])["batch_size"], 1)
        self.assertEqual(json.loads(row["aks_data"])["node_pool_number"], "1")

    @mock.patch("crud.main.glob.glob")
    def test_collect_benchmark_results_skip_results_json(self, mock_glob):
        """Test that results.json is skipped during collection"""
        self._set_env()
        test_file = self._write_operation("create_pods", "test.json")
        results_file = os.path.join(self.test_dir, "results.json")
        with open(results_file, "w", encoding="utf-8") as f:
            f.write("existing content\n")

        mock_glob.return_value = [test_file, results_file]
        self.assertEqual(collect_benchmark_results(), 0)

        with open(results_file, "r", encoding="utf-8") as f:
            rows = f.readlines()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0], "existing content\n")

    @mock.patch("crud.main.glob.glob")
    def test_collect_benchmark_results_no_files(self, mock_glob):
        """Test collection when no JSON files are found"""
        self._set_env()
        mock_glob.return_value = []
        self.assertEqual(collect_benchmark_results(), 0)
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, "results.json")))

    def test_collect_benchmark_results_preserves_default_schema_and_append(self):
        """Default collection retains the original row shape and operation data."""
        self._set_env(CLOUD_INFO='{"cloud":"azure"}', SCALE_NODE_COUNT="10")
        source = self._write_operation("scale_up", duration=12.5)
        with open(source, encoding="utf-8") as source_file:
            original = json.load(source_file)["operation_info"]

        self.assertEqual(collect_benchmark_results(), 0)
        self.assertEqual(collect_benchmark_results(), 0)

        rows = self._read_rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(
                set(row), {"timestamp", "region", "operation_info", "run_id", "run_url"}
            )
            self.assertEqual(json.loads(row["operation_info"]), original)

    @mock.patch("crud.main.glob.glob")
    def test_collect_benchmark_results_preserves_default_source_order(self, mock_glob):
        """Default collection retains the original file-enumeration order."""
        self._set_env()
        mock_glob.return_value = [
            self._write_operation("scale_up", filename="z-scale.json"),
            self._write_operation("create_pods", filename="a-workload.json"),
        ]

        self.assertEqual(collect_benchmark_results(), 0)

        self.assertEqual(
            [json.loads(row["operation_info"])["name"] for row in self._read_rows()],
            ["scale_up", "create_pods"],
        )

    def test_collect_benchmark_results_is_idempotent(self):
        """Legacy reruns replace output and exclude default or custom output files."""
        self._set_env()
        self._write_operation("create_pods", duration=10.0)

        for filename in ("results.json", "final.json"):
            with self.subTest(filename=filename):
                result_file = os.path.join(self.test_dir, filename)
                args = argparse.Namespace(result_file=result_file, legacy_output=True)
                self.assertEqual(collect_benchmark_results(args), 0)
                self.assertEqual(collect_benchmark_results(args), 0)
                with open(result_file, encoding="utf-8") as results_file:
                    self.assertEqual(len([json.loads(line) for line in results_file]), 1)
                os.remove(result_file)

    def test_collect_benchmark_results_publishes_failed_operation(self):
        """A failed scale operation remains a failed legacy result after publishing."""
        self._set_env()
        self._write_operation(
            "scale_up", success=False, duration=600,
            error_message="readiness timed out",
        )

        self.assertEqual(collect_benchmark_results(self.legacy_args), 0)
        rows = self._read_rows()
        self.assertEqual(len(rows), 1)
        operation = json.loads(rows[0]["operation_info"])
        self.assertEqual(operation["name"], "scale_agent_pool")
        self.assertEqual(operation["canonical_name"], "scale_up")
        self.assertFalse(operation["success"])
        self.assertFalse(operation["succeeded"])
        self.assertEqual(operation["time"], 600)
        self.assertEqual(operation["error_message"], "readiness timed out")

    def test_collect_benchmark_results_cli_overrides_environment(self):
        """Explicit arguments win while omitted arguments use the environment."""
        self._set_env(VM_SIZE="Standard_D4s_v5")
        self._write_operation("create_pods", duration=10.0)
        result_file = os.path.join(self.test_dir, "published", "final.json")
        args = argparse.Namespace(
            legacy_output=True,
            result_file=result_file,
            run_id="cli-run",
            region="westus2",
            cloud_info='{"cloud":"azure","aks_name":"test-cluster"}',
            scale_node_count="10",
        )

        self.assertEqual(collect_benchmark_results(args), 0)
        self.assertEqual(collect_benchmark_results(args), 0)

        with open(result_file, encoding="utf-8") as results_file:
            rows = [json.loads(line) for line in results_file]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], "cli-run")
        self.assertEqual(rows[0]["region"], "westus2")
        self.assertEqual(rows[0]["run_url"], self.env_vars["RUN_URL"])
        self.assertEqual(json.loads(rows[0]["cloud_info"])["aks_name"], "test-cluster")
        self.assertEqual(json.loads(rows[0]["aks_data"])["vm_size"], "Standard_D4s_v5")
        self.assertEqual(json.loads(rows[0]["aks_data"])["scale_node_count"], 10)

    def test_collect_benchmark_results_requires_context(self):
        """Missing required context reports the specific missing value."""
        for name in self.env_vars:
            with self.subTest(name=name):
                with mock.patch.dict(os.environ, self.env_vars, clear=True):
                    del os.environ[name]
                    with self.assertRaisesRegex(RuntimeError, name):
                        collect_benchmark_results()

    def test_collect_benchmark_results_rejects_invalid_legacy_counts(self):
        """Invalid numeric pipeline context must not produce a successful row."""
        self._set_env(SCALE_NODE_COUNT="not-a-number")
        self._write_operation("scale_up", duration=10.0)

        with self.assertLogs("crud.main", level="ERROR"):
            self.assertEqual(collect_benchmark_results(self.legacy_args), 1)

        self.assertFalse(os.path.exists(os.path.join(self.test_dir, "results.json")))

    def test_collect_benchmark_results_reports_unreadable_source(self):
        """A missing source is logged rather than producing partial output."""
        self._set_env()
        self._write_operation("create_pods")

        with mock.patch("crud.main.open", side_effect=FileNotFoundError("source removed")):
            with self.assertLogs("crud.main", level="ERROR"):
                self.assertEqual(collect_benchmark_results(self.legacy_args), 1)
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, "results.json")))

    def test_legacy_collection_rejects_invalid_source_directory(self):
        """Missing or non-directory sources cannot erase published results."""
        self._set_env()
        source_file = self._write_operation("create_pods")
        for source in (os.path.join(self.test_dir, "missing"), source_file):
            with self.subTest(source=source):
                args = argparse.Namespace(
                    legacy_output=True, result_dir=source,
                    result_file=os.path.join(self.test_dir, "results.json"),
                )
                self._assert_failed_collection_preserves_output(args)

    @mock.patch("crud.main.os.scandir", side_effect=PermissionError("access denied"))
    def test_legacy_collection_rejects_unreadable_directory(self, _scandir):
        """Directory enumeration failures are logged without replacing output."""
        self._set_env()
        self._assert_failed_collection_preserves_output(self.legacy_args)

    def test_default_collection_preserves_missing_directory_behavior(self):
        """Default collection remains a successful no-op for a missing source."""
        self._set_env(RESULT_DIR=os.path.join(self.test_dir, "missing"))
        self.assertEqual(collect_benchmark_results(), 0)
        self.assertFalse(os.path.exists(self.env_vars["RESULT_DIR"]))

    def test_legacy_collection_preserves_source_filter_and_order(self):
        """Legacy enumeration sorts visible JSON sources and skips hidden ones."""
        self._set_env()
        self._write_operation("scale_up", filename="z-scale.json")
        self._write_operation("create_pods", filename="a-workload.json")
        self._write_operation("hidden", filename=".ignored.json")
        self.assertEqual(collect_benchmark_results(self.legacy_args), 0)
        self.assertEqual(
            [json.loads(row["operation_info"])["canonical_name"] for row in self._read_rows()],
            ["create_pods", "scale_up"],
        )

    def test_collect_benchmark_results_rejects_invalid_operation_shapes(self):
        """Invalid source data is logged without replacing valid published rows."""
        self._set_env()
        invalid_contents = {
            "list root": [],
            "null root": None,
            "missing operation": {},
            "list operation": {"operation_info": []},
            "string operation": {"operation_info": "invalid"},
            "list name": {"operation_info": {"name": [], "success": True}},
            "blank name": {"operation_info": {"name": " ", "success": True}},
            "missing success": {"operation_info": {"name": "create_pods"}},
            "string success": {"operation_info": {"name": "create_pods", "success": "false"}},
            "list metadata": {
                "operation_info": {"name": "create_pods", "success": True, "metadata": []}
            },
        }
        self._write_operation("create_pods", filename="a-valid.json")
        for case, content in invalid_contents.items():
            with self.subTest(case=case):
                with open(
                    os.path.join(self.test_dir, "invalid.json"), "w", encoding="utf-8"
                ) as invalid_file:
                    json.dump(content, invalid_file)
                self._assert_failed_collection_preserves_output(self.legacy_args)

    @mock.patch("crud.main.os.replace", side_effect=OSError("publish failed"))
    def test_collect_benchmark_results_preserves_output_on_publish_failure(self, _replace):
        """An output failure leaves the previous file intact and cleans staging."""
        self._set_env()
        self._write_operation("create_pods", duration=10.0)
        self._assert_failed_collection_preserves_output(self.legacy_args)

    def test_collect_benchmark_results_rejects_malformed_json(self):
        """Malformed operation files fail collection before output is replaced."""
        self._set_env()
        with open(
            os.path.join(self.test_dir, "malformed.json"), "w", encoding="utf-8"
        ) as malformed_file:
            malformed_file.write("{")
        self._assert_failed_collection_preserves_output(None)


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

    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_operation_returns_none(
        self,
        mock_azure_crud_class,
        mock_operation_context,  # pylint: disable=unused-argument
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

        # Operation should complete successfully (no exit call in normal flow)

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_operation_returns_boolean_false(
        self,
        mock_azure_crud_class,
        mock_operation_context,  # pylint: disable=unused-argument
        mock_logger,  # pylint: disable=unused-argument
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
            with self.assertRaises(SystemExit) as context:
                main()

        self.assertEqual(context.exception.code, 1)
        mock_logger.error.assert_called_with("Operation failed with exit code: 1")

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

    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_gpu_node_pool_enabled(
        self, mock_azure_crud_class, mock_operation_context
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

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_gpu_verification_fails(
        self, mock_azure_crud_class, mock_operation_context, mock_logger
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
        # Verify error was logged
        mock_logger.error.assert_any_call("GPU device plugin verification failed")

    @mock.patch("crud.main.AWSNodePoolCRUD")
    def test_main_complete_create_operation_aws(self, mock_aws_crud_class):
        """Test complete create operation flow with AWS"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_aws_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = True

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "aws",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "t3.medium",
            "--node-count",
            "2",
        ]

        with mock.patch("sys.argv", test_args):
            main()  # Use the imported main function

        # Verify
        mock_aws_crud_class.assert_called_once()
        mock_node_pool_crud.create_node_pool.assert_called_once()

    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AWSNodePoolCRUD")
    def test_main_gpu_node_pool_enabled_aws(
        self, mock_aws_crud_class, mock_operation_context
    ):
        """Test main function with GPU node pool enabled for AWS"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_k8s_client = mock.MagicMock()
        mock_eks_client = mock.MagicMock()
        mock_eks_client.k8s_client = mock_k8s_client
        mock_node_pool_crud.eks_client = mock_eks_client

        mock_aws_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = True
        mock_k8s_client.verify_gpu_device_plugin.return_value = True

        # Setup operation context mock
        mock_op = mock.MagicMock()
        mock_operation_context.return_value.__enter__.return_value = mock_op

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "aws",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "gpu-pool",
            "--vm-size",
            "p3.2xlarge",
            "--gpu-node-pool",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        # Verify GPU device plugin was installed and verified
        mock_k8s_client.install_gpu_device_plugin.assert_called_once()
        mock_k8s_client.verify_gpu_device_plugin.assert_called_once()

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AWSNodePoolCRUD")
    def test_main_gpu_verification_fails_aws(
        self, mock_aws_crud_class, mock_operation_context, mock_logger
    ):
        """Test main function when GPU verification fails for AWS"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_k8s_client = mock.MagicMock()
        mock_eks_client = mock.MagicMock()
        mock_eks_client.k8s_client = mock_k8s_client
        mock_node_pool_crud.eks_client = mock_eks_client

        mock_aws_crud_class.return_value = mock_node_pool_crud
        mock_k8s_client.verify_gpu_device_plugin.return_value = False

        # Setup operation context mock
        mock_op = mock.MagicMock()
        mock_operation_context.return_value.__enter__.return_value = mock_op

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "aws",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "gpu-pool",
            "--vm-size",
            "p3.2xlarge",
            "--gpu-node-pool",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        # Verify GPU verification failed and operation was marked as failed
        mock_k8s_client.verify_gpu_device_plugin.assert_called_once()
        self.assertFalse(mock_op.success)
        # Verify error was logged
        mock_logger.error.assert_any_call("GPU device plugin verification failed")

    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AWSNodePoolCRUD")
    def test_main_aws_initialization_with_capacity_type(
        self, mock_aws_crud_class, mock_operation_context  # pylint: disable=unused-argument
    ):
        """Test main function AWS initialization with capacity type"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_aws_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = True

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "aws",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "spot-pool",
            "--vm-size",
            "t3.medium",
            "--capacity-type",
            "SPOT",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        # Verify AWS NodePoolCRUD was initialized with correct parameters
        call_args = mock_aws_crud_class.call_args[1]
        self.assertEqual(call_args["run_id"], "test-run")
        self.assertEqual(call_args["capacity_type"], "SPOT")

    @mock.patch("crud.main.logger")
    def test_main_unsupported_cloud_provider(self, mock_logger):
        """Test main function with unsupported cloud provider"""
        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "oracle",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "small",
        ]

        with mock.patch("sys.argv", test_args):
            with mock.patch("sys.exit") as mock_exit:
                main()

        # Verify error was logged and exit was called
        mock_logger.critical.assert_called()
        mock_exit.assert_called_with(1)

    @mock.patch("crud.main.AWSNodePoolCRUD")
    def test_main_all_operations_aws(self, mock_aws_crud_class):
        """Test main function with all operations for AWS"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_aws_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.all.return_value = True

        test_args = [
            "crud.py",
            "all",
            "--cloud",
            "aws",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "t3.medium",
            "--node-count",
            "1",
            "--target-count",
            "3",
            "--scale-step-size",
            "1",
            "--step-wait-time",
            "30",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        # Verify all method was called with correct parameters
        mock_node_pool_crud.all.assert_called_once()
        call_args = mock_node_pool_crud.all.call_args[1]
        self.assertEqual(call_args["node_pool_name"], "test-pool")
        self.assertEqual(call_args["vm_size"], "t3.medium")
        self.assertEqual(call_args["node_count"], 1)
        self.assertEqual(call_args["target_count"], 3)
        self.assertTrue(call_args["progressive"])
        self.assertEqual(call_args["scale_step_size"], 1)
        self.assertEqual(call_args["step_wait_time"], 30)


class TestMainParameterValidation(unittest.TestCase):
    """Tests for parameter validation in main function"""

    @mock.patch("sys.exit")
    def test_main_missing_node_pool_name_create(self, mock_exit):
        """Test main function validation when node-pool-name is missing for create"""
        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--vm-size",
            "Standard_D2s_v3",
        ]

        with mock.patch("sys.argv", test_args):
            # argparse will handle this and call sys.exit
            main()

        # argparse handles the validation and exits
        mock_exit.assert_called()

    @mock.patch("sys.exit")
    def test_main_missing_vm_size_create(self, mock_exit):
        """Test main function validation when vm-size is missing for create"""
        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
        ]

        with mock.patch("sys.argv", test_args):
            # argparse will handle this and call sys.exit
            main()

        # argparse handles the validation and exits
        mock_exit.assert_called()

    @mock.patch("sys.exit")
    def test_main_missing_target_count_scale(self, mock_exit):
        """Test main function validation when target-count is missing for scale"""
        test_args = [
            "crud.py",
            "scale",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
        ]

        with mock.patch("sys.argv", test_args):
            # argparse will handle this and call sys.exit
            main()

        # argparse handles the validation and exits
        mock_exit.assert_called()

    @mock.patch("sys.exit")
    def test_main_missing_vm_size_all(self, mock_exit):
        """Test main function validation when vm-size is missing for all command"""
        test_args = [
            "crud.py",
            "all",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--node-count",
            "1",
            "--target-count",
            "3",
        ]

        with mock.patch("sys.argv", test_args):
            # argparse will handle this and call sys.exit
            main()

        # argparse handles the validation and exits
        mock_exit.assert_called()

    @mock.patch("sys.exit")
    def test_main_missing_node_count_all(self, mock_exit):
        """Test main function validation when node-count is missing for all command"""
        test_args = [
            "crud.py",
            "all",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "Standard_D2s_v3",
            "--target-count",
            "3",
        ]

        with mock.patch("sys.argv", test_args):
            # argparse will handle this and call sys.exit
            main()

        # argparse handles the validation and exits
        mock_exit.assert_called()

    @mock.patch("sys.exit")
    def test_main_missing_target_count_all(self, mock_exit):
        """Test main function validation when target-count is missing for all command"""
        test_args = [
            "crud.py",
            "all",
            "--cloud",
            "azure",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "Standard_D2s_v3",
            "--node-count",
            "1",
        ]

        with mock.patch("sys.argv", test_args):
            # argparse will handle this and call sys.exit
            main()

        # argparse handles the validation and exits
        mock_exit.assert_called()

    @mock.patch("sys.exit")
    @mock.patch("crud.main.logger")
    def test_main_aws_initialization_error(self, mock_logger, mock_exit):
        """Test main function when GCP NodePoolCRUD initialization is not implemented"""
        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "gcp",  # This should trigger the 'not implemented' path
            "--run-id",
            "test-run",
            "--node-pool-name",
            "test-pool",
            "--vm-size",
            "n1-standard-1",
        ]

        with mock.patch("sys.argv", test_args):
            main()

        # Should log critical error and exit
        mock_logger.critical.assert_called()
        mock_exit.assert_called_with(1)

    @mock.patch("crud.main.OperationContext")
    @mock.patch("crud.main.AWSNodePoolCRUD")
    def test_main_k8s_client_not_available_aws(self, mock_aws_crud_class, mock_operation_context):
        """Test main function when k8s client is not available for AWS GPU setup"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_eks_client = mock.MagicMock()
        mock_eks_client.k8s_client = None  # k8s client not available
        mock_node_pool_crud.eks_client = mock_eks_client

        mock_aws_crud_class.return_value = mock_node_pool_crud
        mock_node_pool_crud.create_node_pool.return_value = True

        # Setup operation context mock to prevent file generation - use a no-op context manager
        mock_context_manager = mock.MagicMock()
        mock_context_manager.__enter__ = mock.MagicMock(return_value=mock_context_manager)
        mock_context_manager.__exit__ = mock.MagicMock(return_value=None)
        mock_operation_context.return_value = mock_context_manager

        test_args = [
            "crud.py",
            "create",
            "--cloud",
            "aws",
            "--run-id",
            "test-run",
            "--node-pool-name",
            "gpu-pool",
            "--vm-size",
            "p3.2xlarge",
            "--gpu-node-pool",
        ]

        with mock.patch("sys.argv", test_args):
            with mock.patch("crud.main.logger") as mock_logger:
                main()

        # Should log warning about k8s client not available
        mock_logger.warning.assert_called_with(
            "Kubernetes client not available - skipping GPU plugin installation"
        )


class TestMainErrorHandlingEdgeCases(unittest.TestCase):
    """Tests for edge cases in main function error handling"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests"""
        shutil.rmtree(self.test_dir)

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_operation_returns_explicit_exit_code(
        self, mock_azure_crud_class, mock_logger
    ):
        """Test main function when operation returns explicit exit code"""
        # Setup - simulate function returning explicit exit code (integer)
        mock_node_pool_crud = mock.MagicMock()
        mock_azure_crud_class.return_value = mock_node_pool_crud

        def mock_handle_operation(crud, args):  # pylint: disable=unused-argument
            return 42  # Return explicit exit code

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
            with mock.patch(
                "crud.main.handle_node_pool_operation", mock_handle_operation
            ):
                with self.assertRaises(SystemExit) as context:
                    main()

        self.assertEqual(context.exception.code, 42)
        mock_logger.error.assert_called_with("Operation failed with exit code: 42")

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_operation_returns_true(self, mock_azure_crud_class, mock_logger):
        """Test main function when operation returns True (success)"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_azure_crud_class.return_value = mock_node_pool_crud

        def mock_handle_operation(crud, args):  # pylint: disable=unused-argument
            return True  # Return boolean success

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
            with mock.patch(
                "crud.main.handle_node_pool_operation", mock_handle_operation
            ):
                main()

        # Should log success
        mock_logger.info.assert_called_with("Operation completed successfully")

    @mock.patch("crud.main.logger")
    @mock.patch("crud.main.AzureNodePoolCRUD")
    def test_main_operation_returns_false(self, mock_azure_crud_class, mock_logger):
        """Test main function when operation returns False (failure)"""
        # Setup
        mock_node_pool_crud = mock.MagicMock()
        mock_azure_crud_class.return_value = mock_node_pool_crud

        def mock_handle_operation(crud, args):  # pylint: disable=unused-argument
            return False  # Return boolean failure

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
            with mock.patch(
                "crud.main.handle_node_pool_operation", mock_handle_operation
            ):
                with self.assertRaises(SystemExit) as context:
                    main()

        self.assertEqual(context.exception.code, 1)
        mock_logger.error.assert_called_with("Operation failed with exit code: 1")


if __name__ == "__main__":
    unittest.main()
