#!/usr/bin/env python3
"""
Unit tests for AWS NodePoolCRUD class
"""

import os
import unittest
from unittest import mock
from crud.aws.node_pool_crud import NodePoolCRUD


class TestAWSNodePoolCRUD(unittest.TestCase):
    """Tests for the AWS NodePoolCRUD class"""

    def setUp(self):
        """Set up test environment"""
        # Setup mock EKSClient
        self.eks_client_patcher = mock.patch("crud.aws.node_pool_crud.EKSClient")
        mock_eks_client_cls = self.eks_client_patcher.start()
        self.mock_eks_client = mock_eks_client_cls.return_value
        self.mock_eks_client.get_cluster_name.return_value = "fake-cluster"

        # Create test directory for result files
        self.test_result_dir = "/tmp/test_results_aws"
        os.makedirs(self.test_result_dir, exist_ok=True)

        # Setup NodePoolCRUD client
        self.node_pool_crud = NodePoolCRUD(
            cluster_name="fake-cluster",
            region="us-west-2",
            kube_config_file=None,
            result_dir=self.test_result_dir,
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
        instance_types = ["t3.medium"]
        node_count = 3

        # Mock successful response
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": instance_types,
            "scalingConfig": {"desiredSize": node_count}
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_types[0],  # Use vm_size parameter for cloud-agnostic interface
            node_count=node_count
        )

        # Verify
        self.assertIsNotNone(result)
        self.assertEqual(result["nodegroupName"], node_group_name)
        self.mock_eks_client.create_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            instance_types=instance_types,
            node_count=node_count,
            gpu_node_pool=False,
            subnet_ids=None,
            node_role_arn=None,
            ami_type=None,
            capacity_type="ON_DEMAND",
            disk_size=20,
        )

    def test_create_node_group_gpu_enabled(self):
        """Test creating a GPU-enabled node group"""
        # Setup
        node_group_name = "gpu-nodegroup"
        instance_types = ["p3.2xlarge"]
        node_count = 2

        # Mock successful response
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": instance_types,
            "scalingConfig": {"desiredSize": node_count}
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_types[0],  # Use vm_size parameter for cloud-agnostic interface
            node_count=node_count,
            gpu_node_pool=True
        )

        # Verify
        self.assertIsNotNone(result)
        self.mock_eks_client.create_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            instance_types=instance_types,
            node_count=node_count,
            gpu_node_pool=True,
            subnet_ids=None,
            node_role_arn=None,
            ami_type=None,
            capacity_type="ON_DEMAND",
            disk_size=20,
        )

    def test_create_node_group_failure(self):
        """Test node group creation failure"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_types = ["t3.medium"]
        node_count = 3

        # Mock failure
        self.mock_eks_client.create_node_group.side_effect = Exception("EKS API Error")

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_types[0],
            node_count=node_count
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
            "scalingConfig": {"desiredSize": target_count}
        }
        self.mock_eks_client.scale_node_group.return_value = mock_scaled_node_group

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_group_name,
            node_count=target_count
        )

        # Verify
        self.assertIsNotNone(result)
        self.assertEqual(result["scalingConfig"]["desiredSize"], target_count)
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
            "scalingConfig": {"desiredSize": target_count}
        }
        self.mock_eks_client.scale_node_group.return_value = mock_scaled_node_group

        # Execute
        result = self.node_pool_crud.scale_node_pool(
            node_pool_name=node_group_name,
            node_count=target_count,
            progressive=True,
            scale_step_size=scale_step_size
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
            node_pool_name=node_group_name,
            node_count=target_count
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
        instance_types = ["t3.medium"]
        node_count = 2
        target_count = 4

        # Mock all successful operations
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": instance_types,
            "scalingConfig": {"desiredSize": node_count}
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group
        self.mock_eks_client.scale_node_group.return_value = mock_node_group
        self.mock_eks_client.delete_node_group.return_value = True

        # Mock time.sleep to speed up tests
        with mock.patch("crud.aws.node_pool_crud.time.sleep"):
            # Execute
            result = self.node_pool_crud.all(
                node_pool_name=node_group_name,
                vm_size=instance_types[0],  # Use vm_size parameter for cloud-agnostic interface
                node_count=node_count,
                target_count=target_count,
                step_wait_time=1  # Reduce wait time for tests
            )

        # Verify
        self.assertTrue(result)
        
        # Verify all operations were called
        self.mock_eks_client.create_node_group.assert_called_once()
        self.assertEqual(self.mock_eks_client.scale_node_group.call_count, 2)  # scale up and down
        self.mock_eks_client.delete_node_group.assert_called_once()

    def test_all_operations_create_failure(self):
        """Test all operations when create fails"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_types = ["t3.medium"]
        node_count = 2
        target_count = 4

        # Mock create failure
        self.mock_eks_client.create_node_group.side_effect = Exception("Create failed")

        # Execute
        result = self.node_pool_crud.all(
            node_pool_name=node_group_name,
            vm_size=instance_types[0],  # Use vm_size parameter for cloud-agnostic interface
            node_count=node_count,
            target_count=target_count,
            step_wait_time=1
        )

        # Verify
        self.assertFalse(result)
        
        # Verify only create was called
        self.mock_eks_client.create_node_group.assert_called_once()
        self.mock_eks_client.scale_node_group.assert_not_called()
        self.mock_eks_client.delete_node_group.assert_not_called()

    def test_string_instance_type_conversion(self):
        """Test that string instance types are converted to list"""
        # Setup
        node_group_name = "test-nodegroup"
        instance_type = "t3.medium"  # Single string instead of list
        node_count = 3

        # Mock successful response
        mock_node_group = {
            "nodegroupName": node_group_name,
            "status": "ACTIVE",
            "instanceTypes": [instance_type],
            "scalingConfig": {"desiredSize": node_count}
        }
        self.mock_eks_client.create_node_group.return_value = mock_node_group

        # Execute
        result = self.node_pool_crud.create_node_pool(
            node_pool_name=node_group_name,
            vm_size=instance_type,  # Pass as string using vm_size parameter
            node_count=node_count
        )

        # Verify
        self.assertIsNotNone(result)
        # Verify that string was converted to list when passed to EKS client
        self.mock_eks_client.create_node_group.assert_called_once_with(
            node_group_name=node_group_name,
            instance_types=[instance_type],  # Should be converted to list
            node_count=node_count,
            gpu_node_pool=False,
            subnet_ids=None,
            node_role_arn=None,
            ami_type=None,
            capacity_type="ON_DEMAND",
            disk_size=20,
        )


if __name__ == "__main__":
    unittest.main()
