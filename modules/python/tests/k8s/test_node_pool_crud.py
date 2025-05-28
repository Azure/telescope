#!/usr/bin/env python3
"""
Unit tests for NodePoolCRUD class
"""
import os
import sys
import unittest
from unittest import mock
from k8s.azure.node_pool_crud import NodePoolCRUD


# Add the python directory to the path to import modules correctly
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


class TestNodePoolCRUD(unittest.TestCase):
    """Tests for the NodePoolCRUD class"""

    def setUp(self):
        """Set up test environment"""
        # Setup mock AKSClient
        self.aks_client_patcher = mock.patch("k8s.azure.node_pool_crud.AKSClient")
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
        self.mock_aks_client.get_node_pool.assert_called_once_with(node_pool_name)
        self.mock_aks_client.scale_node_pool.assert_called_once_with(
            node_pool_name=node_pool_name,
            node_count=node_count,
            operation_type="scale_up",
            gpu_node_pool=False,
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
        self.mock_aks_client.get_node_pool.assert_called_once_with(node_pool_name)
        self.mock_aks_client.scale_node_pool.assert_called_once_with(
            node_pool_name=node_pool_name,
            node_count=node_count,
            operation_type="scale_down",
            gpu_node_pool=False,
        )

    def test_scale_node_pool_no_change(self):
        """Test scaling a node pool when no change is needed"""
        # Setup
        node_pool_name = "test-pool"
        node_count = 3

        mock_node_pool = mock.MagicMock()
        mock_node_pool.count = 3  # Current count = target count
        self.mock_aks_client.get_node_pool.return_value = mock_node_pool

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_pool_name, node_count=node_count
        )

        # Verify
        self.assertEqual(result, mock_node_pool)  # Should return current pool unchanged
        self.mock_aks_client.get_node_pool.assert_called_once_with(node_pool_name)
        self.mock_aks_client.scale_node_pool.assert_not_called()

    def test_scale_node_pool_progressive(self):
        """Test progressive scaling of a node pool"""
        # Setup
        node_pool_name = "test-pool"
        current_count = 1
        target_count = 5
        scale_step_size = 2

        mock_node_pool = mock.MagicMock()
        mock_node_pool.count = current_count
        self.mock_aks_client.get_node_pool.return_value = mock_node_pool

        # Setup mocks for _progressive_scale
        # pylint: disable=protected-access
        self.node_pool_crud._progressive_scale = mock.MagicMock(return_value=True)

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_pool_name,
            node_count=target_count,
            progressive=True,
            scale_step_size=scale_step_size,
        )

        # Verify
        self.assertTrue(result)
        self.mock_aks_client.get_node_pool.assert_called_once_with(node_pool_name)
        # pylint: disable=protected-access
        self.node_pool_crud._progressive_scale.assert_called_once_with(
            node_pool_name=node_pool_name,
            current_count=current_count,
            target_count=target_count,
            scale_step_size=scale_step_size,
            operation_type="scale_up",
            gpu_node_pool=False,
        )

    @mock.patch("k8s.azure.node_pool_crud.time")
    def test_progressive_scale_up(self, mock_time):
        """Test the _progressive_scale method for scaling up"""
        # Setup
        node_pool_name = "test-pool"
        current_count = 1
        target_count = 5
        scale_step_size = 2

        self.mock_aks_client.scale_node_pool.return_value = True

        # Execute
        # pylint: disable=protected-access
        result = self.node_pool_crud._progressive_scale(
            node_pool_name=node_pool_name,
            current_count=current_count,
            target_count=target_count,
            scale_step_size=scale_step_size,
        )

        # Verify
        self.assertTrue(result)

        # Should have scaled to 3, then 5
        expected_calls = [
            mock.call(
                node_pool_name=node_pool_name,
                node_count=3,
                operation_type="scale_up",
                gpu_node_pool=False,
            ),
            mock.call(
                node_pool_name=node_pool_name,
                node_count=5,
                operation_type="scale_up",
                gpu_node_pool=False,
            ),
        ]
        self.assertEqual(
            self.mock_aks_client.scale_node_pool.call_args_list, expected_calls
        )
        self.assertEqual(mock_time.sleep.call_count, 1)

    @mock.patch("k8s.azure.node_pool_crud.time")
    def test_progressive_scale_down(self, mock_time):
        """Test the _progressive_scale method for scaling down"""
        # Setup
        node_pool_name = "test-pool"
        current_count = 5
        target_count = 1
        scale_step_size = 2

        self.mock_aks_client.scale_node_pool.return_value = True

        # Execute
        # pylint: disable=protected-access
        result = self.node_pool_crud._progressive_scale(
            node_pool_name=node_pool_name,
            current_count=current_count,
            target_count=target_count,
            scale_step_size=scale_step_size,
        )

        # Verify
        self.assertTrue(result)

        # Should have scaled to 3, then 1
        expected_calls = [
            mock.call(
                node_pool_name=node_pool_name,
                node_count=3,
                operation_type="scale_down",
                gpu_node_pool=False,
            ),
            mock.call(
                node_pool_name=node_pool_name,
                node_count=1,
                operation_type="scale_down",
                gpu_node_pool=False,
            ),
        ]
        self.assertEqual(
            self.mock_aks_client.scale_node_pool.call_args_list, expected_calls
        )
        self.assertEqual(mock_time.sleep.call_count, 1)

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

    @mock.patch("k8s.azure.node_pool_crud.time")
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


if __name__ == "__main__":
    unittest.main()
