"""
Unit tests for AWS NodePoolCRUD class
"""

import os
import unittest
from unittest import mock
from crud.aws.node_pool_crud import NodePoolCRUD


class TestAWSNodePoolCRUD(unittest.TestCase):  # pylint: disable=too-many-public-methods
    """Tests for the AWS NodePoolCRUD class"""

    def setUp(self):
        """Set up test environment"""
        # Setup mock EKSClient
        self.eks_client_patcher = mock.patch("crud.aws.node_pool_crud.EKSClient")
        mock_eks_client_cls = self.eks_client_patcher.start()
        self.mock_eks_client = mock_eks_client_cls.return_value

        # Create test directory for result files
        self.test_result_dir = "/tmp/test_results_aws"
        os.makedirs(self.test_result_dir, exist_ok=True)

        # Setup NodePoolCRUD client with updated constructor
        self.node_pool_crud = NodePoolCRUD(
            run_id="test-run-id",
            kube_config_file=None,
            result_dir=self.test_result_dir,
            step_timeout=600,
            capacity_type="ON_DEMAND",
        )

    def tearDown(self):
        """Clean up after tests"""
        # Stop patches
        self.eks_client_patcher.stop()

        try:
            os.rmdir(self.test_result_dir)
        except OSError:
            pass

    def test_create_node_group_success(self):
        """Test successful node group creation"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"
        node_count = 3

        # Mock successful response
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": [instance_type],
            "scalingConfig": {"desiredSize": node_count},
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_type,
            node_count=node_count,
        )

        # Verify
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        if isinstance(result, dict):
            self.assertEqual(result["nodegroupName"], node_group_name)  # pylint: disable=unsubscriptable-object
        self.mock_eks_client.create_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            instance_type=instance_type,
            node_count=node_count,
            gpu_node_group=False,
            capacity_type="ON_DEMAND",
        )

    def test_create_node_group_gpu_enabled(self):
        """Test creating a GPU-enabled node group"""
        # Setup
        node_group_name = "gpu-nodegroup"
        instance_type = "p3.2xlarge"
        node_count = 2

        # Mock successful response
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": [instance_type],
            "scalingConfig": {"desiredSize": node_count},
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_type,
            node_count=node_count,
            gpu_node_pool=True,
        )

        # Verify
        self.assertIsNotNone(result)
        self.mock_eks_client.create_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            instance_type=instance_type,
            node_count=node_count,
            gpu_node_group=True,
            capacity_type="ON_DEMAND",
        )

    def test_create_node_group_failure(self):
        """Test node group creation failure"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"
        node_count = 3

        # Mock failure
        self.mock_eks_client.create_node_group.side_effect = Exception("EKS API Error")

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_type,
            node_count=node_count,
        )

        # Verify
        self.assertFalse(result)

    def test_scale_node_group_success(self):
        """Test successful node group scaling"""
        # Setup
        node_group_name = "test-nodegroup"
        target_count = 5

        # Mock successful response
        mock_scaled_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "scalingConfig": {"desiredSize": target_count},
        }
        self.mock_eks_client.scale_node_group.return_value = mock_scaled_node_group

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_group_name, node_count=target_count
        )

        # Verify
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        if isinstance(result, dict):
            self.assertEqual(result["scalingConfig"]["desiredSize"], target_count)  # pylint: disable=unsubscriptable-object
        self.mock_eks_client.scale_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            node_count=target_count,
            gpu_node_group=False,
            progressive=False,
            scale_step_size=1,
        )

    def test_scale_node_group_progressive(self):
        """Test progressive node group scaling"""
        # Setup
        node_group_name = "test-nodegroup"
        target_count = 5
        scale_step_size = 2

        # Mock successful response
        mock_scaled_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "scalingConfig": {"desiredSize": target_count},
        }
        self.mock_eks_client.scale_node_group.return_value = mock_scaled_node_group

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_group_name,
            node_count=target_count,
            progressive=True,
            scale_step_size=scale_step_size,
        )

        # Verify
        self.assertIsNotNone(result)
        self.mock_eks_client.scale_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            node_count=target_count,
            gpu_node_group=False,
            progressive=True,
            scale_step_size=scale_step_size,
        )

    def test_scale_node_group_failure(self):
        """Test node group scaling failure"""
        # Setup
        node_group_name = "test-nodegroup"
        target_count = 5

        # Mock failure
        self.mock_eks_client.scale_node_group.side_effect = Exception("EKS API Error")

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_group_name, node_count=target_count
        )

        # Verify
        self.assertFalse(result)

    def test_delete_node_group_success(self):
        """Test successful node group deletion"""
        # Setup
        node_group_name = "test-nodegroup"

        # Mock successful response
        self.mock_eks_client.delete_node_group.return_value = True

        # Execute
        result = self.node_pool_crud.delete_node_pool(node_pool_name=node_group_name)

        # Verify
        self.assertTrue(result)
        self.mock_eks_client.delete_node_group.assert_called_once_with(
            node_group_name=node_group_name
        )

    def test_delete_node_group_failure(self):
        """Test node group deletion failure"""
        # Setup
        node_group_name = "test-nodegroup"

        # Mock failure
        self.mock_eks_client.delete_node_group.side_effect = Exception("EKS API Error")

        # Execute
        result = self.node_pool_crud.delete_node_pool(node_pool_name=node_group_name)

        # Verify
        self.assertFalse(result)

    def test_all_operations_success(self):
        """Test successful execution of all operations"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"
        node_count = 2
        target_count = 4

        # Mock all successful operations
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": [instance_type],
            "scalingConfig": {"desiredSize": node_count},
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group
        self.mock_eks_client.scale_node_group.return_value = mock_node_group
        self.mock_eks_client.delete_node_group.return_value = True

        # Mock time.sleep to speed up tests
        with mock.patch("crud.aws.node_pool_crud.time.sleep"):
            # Execute
            result = self.node_pool_crud.all(
                node_pool_name=node_group_name,
                vm_size=instance_type,
                node_count=node_count,
                target_count=target_count,
                step_wait_time=1,  # Reduce wait time for tests
            )

        # Verify
        self.assertTrue(result)

        # Verify all operations were called
        self.mock_eks_client.create_node_group.assert_called_once()
        self.assertEqual(
            self.mock_eks_client.scale_node_group.call_count, 2
        )  # scale up and down
        self.mock_eks_client.delete_node_group.assert_called_once()

    def test_all_operations_create_failure(self):
        """Test all operations when create fails"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"
        node_count = 2
        target_count = 4

        # Mock create failure
        self.mock_eks_client.create_node_group.return_value = False

        # Execute
        result = self.node_pool_crud.all(
            node_pool_name=node_group_name,
            vm_size=instance_type,
            node_count=node_count,
            target_count=target_count,
            step_wait_time=1,
        )

        # Verify
        self.assertFalse(result)

        # Verify only create was called
        self.mock_eks_client.create_node_group.assert_called_once()
        self.mock_eks_client.scale_node_group.assert_not_called()
        self.mock_eks_client.delete_node_group.assert_not_called()

    def test_all_operations_create_exception(self):
        """Test all operations when create throws an exception"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"
        node_count = 2
        target_count = 4

        # Mock create exception
        self.mock_eks_client.create_node_group.side_effect = Exception("Create failed")

        # Execute
        result = self.node_pool_crud.all(
            node_pool_name=node_group_name,
            vm_size=instance_type,
            node_count=node_count,
            target_count=target_count,
            step_wait_time=1,
        )

        # Verify
        self.assertFalse(result)

        # Verify create was called but returned False due to exception handling
        self.mock_eks_client.create_node_group.assert_called_once()
        # No further operations should be called since create failed
        self.mock_eks_client.scale_node_group.assert_not_called()
        self.mock_eks_client.delete_node_group.assert_not_called()

    def test_string_instance_type_conversion(self):
        """Test that string instance types are handled correctly"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"  # Single string
        node_count = 3

        # Mock successful response
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": [instance_type],
            "scalingConfig": {"desiredSize": node_count},
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_type,  # Pass as string
            node_count=node_count,
        )

        # Verify
        self.assertIsNotNone(result)
        # Verify that string was passed correctly to EKS client
        self.mock_eks_client.create_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            instance_type=instance_type,
            node_count=node_count,
            gpu_node_group=False,
            capacity_type="ON_DEMAND",
        )

    def test_create_node_pool_with_custom_capacity_type(self):
        """Test creating node pool with custom capacity type"""
        # Setup
        node_group_name = "spot-nodegroup"
        instance_type = "t3.medium"
        node_count = 2

        # Create node pool CRUD with SPOT capacity type
        node_pool_crud = NodePoolCRUD(
            run_id="test-run",
            capacity_type="SPOT",
            result_dir=self.test_result_dir,
        )

        # Mock successful response
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": [instance_type],
            "scalingConfig": {"desiredSize": node_count},
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group

        # Execute
        result = node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_type,
            node_count=node_count,
        )

        # Verify
        self.assertIsNotNone(result)
        self.mock_eks_client.create_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            instance_type=instance_type,
            node_count=node_count,
            gpu_node_group=False,
            capacity_type="SPOT",
        )

    def test_scale_node_pool_with_gpu(self):
        """Test scaling a GPU-enabled node pool"""
        # Setup
        node_group_name = "gpu-nodegroup"
        target_count = 3

        # Mock successful response
        mock_scaled_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "scalingConfig": {"desiredSize": target_count},
        }
        self.mock_eks_client.scale_node_group.return_value = mock_scaled_node_group

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_group_name,
            node_count=target_count,
            gpu_node_pool=True,
        )

        # Verify
        self.assertIsNotNone(result)
        self.mock_eks_client.scale_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            node_count=target_count,
            gpu_node_group=True,
            progressive=False,
            scale_step_size=1,
        )

    def test_all_operations_scale_failure_continues_to_delete(self):
        """Test all operations when scale fails but deletion still happens"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"
        node_count = 2
        target_count = 4

        # Mock create success, scale failure, delete success
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": [instance_type],
            "scalingConfig": {"desiredSize": node_count},
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group
        self.mock_eks_client.scale_node_group.side_effect = [
            Exception("Scale up failed"),  # First scale (up) fails
            mock_node_group,  # Second scale (down) succeeds
        ]
        self.mock_eks_client.delete_node_group.return_value = True

        # Mock time.sleep to speed up tests
        with mock.patch("crud.aws.node_pool_crud.time.sleep"):
            # Execute
            result = self.node_pool_crud.all(
                node_pool_name=node_group_name,
                vm_size=instance_type,
                node_count=node_count,
                target_count=target_count,
                step_wait_time=1,
            )

        # Verify - should return False due to scale failure but delete should still be called
        self.assertFalse(result)
        self.mock_eks_client.create_node_group.assert_called_once()
        self.assertEqual(self.mock_eks_client.scale_node_group.call_count, 2)
        self.mock_eks_client.delete_node_group.assert_called_once()

    def test_all_operations_exception_handling(self):
        """Test all operations with exception during execution"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"
        node_count = 2
        target_count = 4

        # Mock create to raise an unexpected exception
        self.mock_eks_client.create_node_group.side_effect = RuntimeError(
            "Unexpected error"
        )

        # Execute
        result = self.node_pool_crud.all(
            node_pool_name=node_group_name,
            vm_size=instance_type,
            node_count=node_count,
            target_count=target_count,
        )

        # Verify
        self.assertFalse(result)

    def test_scale_node_pool_returns_none(self):
        """Test scale node pool when EKS client returns None"""
        # Setup
        node_group_name = "test-nodegroup"
        target_count = 5

        # Mock None response from EKS client
        self.mock_eks_client.scale_node_group.return_value = None

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_group_name,
            node_count=target_count,
        )

        # Verify - should return None (not False)
        self.assertIsNone(result)

    def test_all_operations_with_progressive_scaling(self):
        """Test all operations with progressive scaling enabled"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"
        node_count = 1
        target_count = 5
        scale_step_size = 2

        # Mock all successful operations
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": [instance_type],
            "scalingConfig": {"desiredSize": node_count},
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group
        self.mock_eks_client.scale_node_group.return_value = mock_node_group
        self.mock_eks_client.delete_node_group.return_value = True

        # Mock time.sleep to speed up tests
        with mock.patch("crud.aws.node_pool_crud.time.sleep"):
            # Execute
            result = self.node_pool_crud.all(
                node_pool_name=node_group_name,
                vm_size=instance_type,
                node_count=node_count,
                target_count=target_count,
                progressive=True,
                scale_step_size=scale_step_size,
                step_wait_time=1,
            )

        # Verify
        self.assertTrue(result)

        # Verify progressive scaling was used
        scale_calls = self.mock_eks_client.scale_node_group.call_args_list
        self.assertEqual(len(scale_calls), 2)  # scale up and down

        # Check that progressive=True was passed
        for call in scale_calls:
            self.assertTrue(call[1]["progressive"])
            self.assertEqual(call[1]["scale_step_size"], scale_step_size)


if __name__ == "__main__":
    unittest.main()
