#!/usr/bin/env python3
"""
Unit tests for NodePoolCRUD class
"""

import os
import unittest
from unittest import mock
from crud.azure.node_pool_crud import NodePoolCRUD


class TestAzureNodePoolCRUD(unittest.TestCase):
    """Tests for the NodePoolCRUD class"""

    def setUp(self):
        """Set up test environment"""
        # Setup mock AKSClient
        self.aks_client_patcher = mock.patch("crud.azure.node_pool_crud.AKSClient")
        mock_aks_client_cls = self.aks_client_patcher.start()
        self.mock_aks_client = mock_aks_client_cls.return_value
        self.mock_aks_client.get_cluster_name.return_value = "fake-cluster"

        # Create test directory for result files
        self.test_result_dir = "/tmp/test_results"
        os.makedirs(self.test_result_dir, exist_ok=True)

        # Setup NodePoolCRUD client
        self.node_pool_crud = NodePoolCRUD(
            resource_group="fake-resource-group",
            kube_config_file=None,
            result_dir=self.test_result_dir,
        )

    def tearDown(self):
        """Clean up after tests"""
        # Stop patches
        self.aks_client_patcher.stop()

        try:
            os.rmdir(self.test_result_dir)
        except OSError:
            pass

    def test_create_node_pool_success(self):
        """Test successful node pool creation"""
        # Setup
        node_pool_name = "test-pool"
        vm_size = "Standard_DS2_v2"
        node_count = 3

        self.mock_aks_client.create_node_pool.return_value = True

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_pool_name,
            vm_size=vm_size,
            node_count=node_count,
            gpu_node_pool=False,
        )

        # Verify
        self.assertTrue(result)
        self.mock_aks_client.create_node_pool.assert_called_once_with(
            node_pool_name=node_pool_name,
            vm_size=vm_size,
            node_count=node_count,
            gpu_node_pool=False,
        )

    def test_create_node_pool_failure(self):
        """Test node pool creation failure"""
        # Setup
        node_pool_name = "test-pool"
        vm_size = "Standard_DS2_v2"
        node_count = 3

        self.mock_aks_client.create_node_pool.side_effect = Exception("Creation failed")

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_pool_name, vm_size=vm_size, node_count=node_count
        )

        # Verify
        self.assertFalse(result)

    def test_scale_node_pool_up(self):
        """Test scaling a node pool up"""
        # Setup
        node_pool_name = "test-pool"
        node_count = 5

        mock_node_pool = mock.MagicMock()
        mock_node_pool.count = 3  # Current count
        self.mock_aks_client.get_node_pool.return_value = mock_node_pool

        self.mock_aks_client.scale_node_pool.return_value = True

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_pool_name, node_count=node_count
        )

        # Verify
        self.assertTrue(result)
        self.mock_aks_client.scale_node_pool.assert_called_once_with(
            node_pool_name=node_pool_name,
            node_count=node_count,
            gpu_node_pool=False,
            progressive=False,
            scale_step_size=1,
        )

    def test_scale_node_pool_down(self):
        """Test scaling a node pool down"""
        # Setup
        node_pool_name = "test-pool"
        node_count = 1

        mock_node_pool = mock.MagicMock()
        mock_node_pool.count = 3  # Current count
        self.mock_aks_client.get_node_pool.return_value = mock_node_pool

        self.mock_aks_client.scale_node_pool.return_value = True

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_pool_name, node_count=node_count
        )

        # Verify
        self.assertTrue(result)
        self.mock_aks_client.scale_node_pool.assert_called_once_with(
            node_pool_name=node_pool_name,
            node_count=node_count,
            gpu_node_pool=False,
            progressive=False,
            scale_step_size=1,
        )

    def test_delete_node_pool(self):
        """Test deleting a node pool"""
        # Setup
        node_pool_name = "test-pool"
        self.mock_aks_client.delete_node_pool.return_value = True

        # Execute
        result = self.node_pool_crud.delete_node_pool(node_pool_name)

        # Verify
        self.assertTrue(result)
        self.mock_aks_client.delete_node_pool.assert_called_once_with(
            node_pool_name=node_pool_name
        )

    def test_delete_node_pool_failure(self):
        """Test node pool deletion failure"""
        # Setup
        node_pool_name = "test-pool"
        self.mock_aks_client.delete_node_pool.side_effect = Exception("Deletion failed")

        # Execute
        result = self.node_pool_crud.delete_node_pool(node_pool_name)

        # Verify
        self.assertFalse(result)

    @mock.patch("crud.azure.node_pool_crud.time")
    def test_all_operations(self, mock_time):
        """Test the all method which performs all operations in sequence"""
        # Setup
        node_pool_name = "test-pool"
        vm_size = "Standard_DS2_v2"
        node_count = 1
        target_count = 3

        # Mock all the individual methods
        self.node_pool_crud.create_node_pool = mock.MagicMock(return_value=True)
        self.node_pool_crud.scale_node_pool = mock.MagicMock(return_value=True)
        self.node_pool_crud.delete_node_pool = mock.MagicMock(return_value=True)

        # Execute
        self.node_pool_crud.all(
            node_pool_name=node_pool_name,
            vm_size=vm_size,
            node_count=node_count,
            target_count=target_count,
            progressive=True,
            scale_step_size=1,
            gpu_node_pool=True,
        )

        # Verify
        self.node_pool_crud.create_node_pool.assert_called_once_with(
            node_pool_name=node_pool_name,
            vm_size=vm_size,
            node_count=node_count,
            gpu_node_pool=True,
        )

        # Should be called twice - once for scale up, once for scale down
        self.assertEqual(self.node_pool_crud.scale_node_pool.call_count, 2)

        # First call should be scale up to target_count
        scale_up_call = self.node_pool_crud.scale_node_pool.call_args_list[0]
        self.assertEqual(scale_up_call[1]["node_pool_name"], node_pool_name)
        self.assertEqual(scale_up_call[1]["node_count"], target_count)
        self.assertTrue(scale_up_call[1]["progressive"])
        self.assertEqual(scale_up_call[1]["scale_step_size"], 1)
        self.assertTrue(scale_up_call[1]["gpu_node_pool"])

        # Second call should be scale down to node_count
        scale_down_call = self.node_pool_crud.scale_node_pool.call_args_list[1]
        self.assertEqual(scale_down_call[1]["node_pool_name"], node_pool_name)
        self.assertEqual(scale_down_call[1]["node_count"], node_count)

        # Finally, should call delete
        self.node_pool_crud.delete_node_pool.assert_called_once_with(
            node_pool_name=node_pool_name
        )

        # Check time.sleep was called 3 times (between operations)
        self.assertEqual(mock_time.sleep.call_count, 3)

    @mock.patch("crud.azure.node_pool_crud.time")
    def test_all_create_returns_false_early_exit(self, mock_time):
        """Test that all() exits early when create returns False"""
        # Setup - mock create to fail
        self.node_pool_crud.create_node_pool = mock.MagicMock(return_value=False)
        self.node_pool_crud.scale_node_pool = mock.MagicMock(return_value=True)
        self.node_pool_crud.delete_node_pool = mock.MagicMock(return_value=True)

        # Execute
        result = self.node_pool_crud.all(
            node_pool_name="test-pool",
            vm_size="Standard_DS2_v2",
            node_count=1,
            target_count=3,
            progressive=True,
            scale_step_size=1,
        )

        # Verify - should return False
        self.assertFalse(result)

        # Verify create was called once
        self.node_pool_crud.create_node_pool.assert_called_once()

        # Verify scale and delete were NOT called (early exit)
        self.node_pool_crud.scale_node_pool.assert_not_called()
        self.node_pool_crud.delete_node_pool.assert_not_called()

        # Verify time.sleep was NOT called (no operations after create)
        mock_time.sleep.assert_not_called()

    @mock.patch("crud.azure.node_pool_crud.time")
    def test_all_scale_up_fails_continues(self, mock_time):
        """Test that all() continues to scale down and delete when scale up fails"""
        # Setup - create succeeds, scale_up fails, scale_down and delete succeed
        self.node_pool_crud.create_node_pool = mock.MagicMock(return_value=True)
        self.node_pool_crud.scale_node_pool = mock.MagicMock(
            side_effect=[False, True]  # scale_up fails, scale_down succeeds
        )
        self.node_pool_crud.delete_node_pool = mock.MagicMock(return_value=True)

        # Execute
        result = self.node_pool_crud.all(
            node_pool_name="test-pool",
            vm_size="Standard_DS2_v2",
            node_count=1,
            target_count=3,
            progressive=True,
            scale_step_size=1,
        )

        # Verify - should return False (scale_up failed)
        self.assertFalse(result)

        # Verify create was called once
        self.node_pool_crud.create_node_pool.assert_called_once()

        # Verify scale was called TWICE (scale_up failed, but scale_down still called)
        self.assertEqual(self.node_pool_crud.scale_node_pool.call_count, 2)

        # Verify delete was still called (cleanup continues despite scale_up failure)
        self.node_pool_crud.delete_node_pool.assert_called_once()

        # Verify time.sleep was called 3 times (between all operations)
        self.assertEqual(mock_time.sleep.call_count, 3)

    @mock.patch("crud.azure.node_pool_crud.time")
    def test_all_scale_down_fails_continues(self, mock_time):
        """Test that all() continues to delete when scale down fails"""
        # Setup - create and scale_up succeed, scale_down fails, delete succeeds
        self.node_pool_crud.create_node_pool = mock.MagicMock(return_value=True)
        self.node_pool_crud.scale_node_pool = mock.MagicMock(
            side_effect=[True, False]  # scale_up succeeds, scale_down fails
        )
        self.node_pool_crud.delete_node_pool = mock.MagicMock(return_value=True)

        # Execute
        result = self.node_pool_crud.all(
            node_pool_name="test-pool",
            vm_size="Standard_DS2_v2",
            node_count=1,
            target_count=3,
            progressive=True,
            scale_step_size=1,
        )

        # Verify - should return False (scale_down failed)
        self.assertFalse(result)

        # Verify create was called once
        self.node_pool_crud.create_node_pool.assert_called_once()

        # Verify scale was called TWICE (scale_up succeeded, scale_down failed)
        self.assertEqual(self.node_pool_crud.scale_node_pool.call_count, 2)

        # Verify delete was still called (cleanup continues despite scale_down failure)
        self.node_pool_crud.delete_node_pool.assert_called_once()

        # Verify time.sleep was called 3 times (between all operations)
        self.assertEqual(mock_time.sleep.call_count, 3)

    def test_create_deployment_success(self):
        """Test successful deployment creation"""
        # Setup
        mock_k8s_client = mock.MagicMock()
        self.mock_aks_client.k8s_client = mock_k8s_client
        # Must return a real string - yaml.safe_load_all(MagicMock()) causes an infinite loop
        mock_k8s_client.create_template.return_value = "apiVersion: apps/v1\nkind: Deployment\n"
        mock_k8s_client.wait_for_condition.return_value = True

        # Execute
        result = self.node_pool_crud.create_deployment(node_pool_name="test-pool")

        # Verify
        self.assertTrue(result)

    def test_create_deployment_failure(self):
        """Test deployment creation failure"""
        # Setup
        mock_k8s_client = mock.MagicMock()
        self.mock_aks_client.k8s_client = mock_k8s_client
        # Must return a real string - yaml.safe_load_all(MagicMock()) causes an infinite loop
        mock_k8s_client.create_template.return_value = "apiVersion: apps/v1\nkind: Deployment\n"
        mock_k8s_client.wait_for_condition.return_value = False

        # Execute
        result = self.node_pool_crud.create_deployment(node_pool_name="test-pool")

        # Verify
        self.assertFalse(result)

    def test_create_deployment_no_client(self):
        """Test deployment creation with no Kubernetes client"""
        # Setup
        self.mock_aks_client.k8s_client = None

        # Execute
        result = self.node_pool_crud.create_deployment(node_pool_name="test-pool")

        # Verify
        self.assertFalse(result)

    def test_create_deployment_partial_success(self):
        """Test deployment creation when some deployments succeed and others fail"""
        # Setup
        mock_k8s_client = mock.MagicMock()
        self.mock_aks_client.k8s_client = mock_k8s_client

        # Must return a real string - yaml.safe_load_all(MagicMock()) causes an infinite loop
        mock_k8s_client.create_template.return_value = "apiVersion: apps/v1\nkind: Deployment\n"

        # Simulate: deployment 1 succeeds, deployment 2 fails, deployment 3 succeeds
        # wait_for_condition returns True/False for each deployment
        mock_k8s_client.wait_for_condition.side_effect = [True, False, True]

        # Execute - request 3 deployments
        result = self.node_pool_crud.create_deployment(
            node_pool_name="test-pool",
            number_of_deployments=3,
            replicas=5
        )

        # Verify - should return False (not all deployments succeeded)
        self.assertFalse(result)

        # Verify wait_for_condition was called 3 times (once per deployment)
        self.assertEqual(mock_k8s_client.wait_for_condition.call_count, 3)

        # Verify create_template was called 3 times (attempted all deployments)
        self.assertEqual(mock_k8s_client.create_template.call_count, 3)

if __name__ == "__main__":
    unittest.main()
