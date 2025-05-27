#!/usr/bin/env python3
"""
Unit tests for AKSClient class
"""

import os
import json
import sys
import unittest
from unittest import mock

from azure.core.exceptions import HttpResponseError

# Add the python directory to the path to import modules correctly
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
# pylint: disable=wrong-import-position
from clients.aks_client import AKSClient


class TestAKSClient(unittest.TestCase):
    """Tests for the AKSClient class"""

    def setUp(self):
        """Set up test environment"""
        # Create patches
        self.cs_client_patcher = mock.patch("clients.aks_client.ContainerServiceClient")
        self.mi_cred_patcher = mock.patch(
            "clients.aks_client.ManagedIdentityCredential"
        )
        self.k8s_client_patcher = mock.patch("clients.aks_client.KubernetesClient")

        # Start patches
        mock_cs_client = self.cs_client_patcher.start()
        mock_mi_cred = self.mi_cred_patcher.start()
        mock_k8s_client = self.k8s_client_patcher.start()

        # Setup mock credential
        self.mock_credential = mock_mi_cred.return_value

        # Setup mock container service client
        self.mock_aks_client = mock_cs_client.return_value
        self.mock_agent_pools = mock.MagicMock()
        self.mock_aks_client.agent_pools = self.mock_agent_pools
        self.mock_managed_clusters = mock.MagicMock()
        self.mock_aks_client.managed_clusters = self.mock_managed_clusters

        # Setup mock kubernetes client
        self.mock_k8s = mock_k8s_client.return_value

        # Create test directory for result files
        self.test_result_dir = "/tmp/test_results"
        os.makedirs(self.test_result_dir, exist_ok=True)

        # Setup AKS client
        self.aks_client = AKSClient(
            subscription_id="fake-subscription-id",
            resource_group="fake-resource-group",
            cluster_name="fake-cluster",
            use_managed_identity=True,
            result_dir=self.test_result_dir,
        )

        # Set VM size for metrics testing
        self.aks_client.vm_size = "Standard_DS2_v2"

    def tearDown(self):
        """Clean up after tests"""
        # Remove test result files
        for file in os.listdir(self.test_result_dir):
            if file.startswith("azure_"):
                os.remove(os.path.join(self.test_result_dir, file))

        try:
            os.rmdir(self.test_result_dir)
        except OSError:
            pass

    def test_get_cluster_name_provided(self):
        """Test get_cluster_name when name is already provided"""
        self.assertEqual(self.aks_client.get_cluster_name(), "fake-cluster")

    def test_get_cluster_name_from_api(self):
        """Test get_cluster_name retrieves from API when not provided"""
        # Setup
        self.aks_client.cluster_name = None
        mock_cluster = mock.MagicMock()
        mock_cluster.name = "discovered-cluster"
        self.mock_managed_clusters.list_by_resource_group.return_value = [mock_cluster]

        # Execute
        result = self.aks_client.get_cluster_name()

        # Verify
        self.assertEqual(result, "discovered-cluster")
        self.mock_managed_clusters.list_by_resource_group.assert_called_once_with(
            "fake-resource-group"
        )

    def test_get_cluster_name_no_clusters(self):
        """Test get_cluster_name when no clusters are found"""
        # Setup
        self.aks_client.cluster_name = None
        self.mock_managed_clusters.list_by_resource_group.return_value = []

        # Execute and verify
        with self.assertRaises(ValueError):
            self.aks_client.get_cluster_name()

        self.mock_managed_clusters.list_by_resource_group.assert_called_once_with(
            "fake-resource-group"
        )

    def test_get_cluster_data(self):
        """Test get_cluster_data retrieves cluster information"""
        # Setup
        mock_cluster = mock.MagicMock()
        mock_cluster.as_dict.return_value = {
            "name": "fake-cluster",
            "location": "eastus",
        }
        self.mock_managed_clusters.get.return_value = mock_cluster

        # Execute
        result = self.aks_client.get_cluster_data()

        # Verify
        self.assertEqual(result, {"name": "fake-cluster", "location": "eastus"})
        self.mock_managed_clusters.get.assert_called_once_with(
            resource_group_name="fake-resource-group", resource_name="fake-cluster"
        )

    def test_get_node_pool(self):
        """Test get_node_pool retrieves a specific node pool"""
        # Setup
        mock_node_pool = mock.MagicMock()
        mock_node_pool.name = "test-pool"
        self.mock_agent_pools.get.return_value = mock_node_pool

        # Execute
        result = self.aks_client.get_node_pool("test-pool")

        # Verify
        self.assertEqual(result, mock_node_pool)
        self.mock_agent_pools.get.assert_called_once_with(
            resource_group_name="fake-resource-group",
            resource_name="fake-cluster",
            agent_pool_name="test-pool",
        )

    @mock.patch("clients.aks_client.time")
    def test_create_node_pool_success(self, mock_time):
        """Test successful node pool creation"""
        # Setup
        node_pool_name = "test-pool"
        vm_size = "Standard_DS2_v2"
        node_count = 2

        mock_time.time.side_effect = [100, 150]  # Start and end times

        mock_operation = mock.MagicMock()
        self.mock_agent_pools.begin_create_or_update.return_value = mock_operation

        ready_nodes = [mock.MagicMock(), mock.MagicMock()]
        self.mock_k8s.wait_for_nodes_ready.return_value = ready_nodes

        # Execute
        result = self.aks_client.create_node_pool(
            node_pool_name=node_pool_name,
            vm_size=vm_size,
            node_count=node_count,
            gpu_node_pool=False,
        )

        # Verify
        self.assertTrue(result)
        self.mock_agent_pools.begin_create_or_update.assert_called_once()
        self.mock_k8s.wait_for_nodes_ready.assert_called_once_with(
            node_count=node_count,
            operation_timeout_in_minutes=10,
            label_selector=f"agentpool={node_pool_name}",
        )

        # Check that metrics recording happened
        self.assertIn("_record_metrics", self.aks_client.__class__.__dict__)

    @mock.patch("clients.aks_client.time")
    def test_create_node_pool_gpu(self, mock_time):
        """Test creating a GPU node pool with driver verification"""
        # Setup
        node_pool_name = "gpu-pool"
        vm_size = "Standard_NC6s_v3"  # GPU VM size
        node_count = 1

        mock_time.time.side_effect = [100, 150]  # Start and end times

        mock_operation = mock.MagicMock()
        self.mock_agent_pools.begin_create_or_update.return_value = mock_operation

        ready_nodes = [mock.MagicMock()]
        self.mock_k8s.wait_for_nodes_ready.return_value = ready_nodes

        # Add nvidia-smi verification mock
        self.mock_k8s.verify_nvidia_smi_on_node = mock.MagicMock(
            return_value="GPU 0: Tesla V100"
        )

        # Execute
        result = self.aks_client.create_node_pool(
            node_pool_name=node_pool_name,
            vm_size=vm_size,
            node_count=node_count,
            gpu_node_pool=True,
        )

        # Verify
        self.assertTrue(result)
        self.mock_agent_pools.begin_create_or_update.assert_called_once()
        self.mock_k8s.wait_for_nodes_ready.assert_called_once_with(
            node_count=node_count,
            operation_timeout_in_minutes=10,
            label_selector=f"agentpool={node_pool_name}",
        )

        # Check that NVIDIA verification was performed
        self.mock_k8s.verify_nvidia_smi_on_node.assert_called_once_with(ready_nodes)

    @mock.patch("clients.aks_client.time")
    def test_scale_node_pool_up(self, mock_time):
        """Test scaling a node pool up"""
        # Setup
        node_pool_name = "test-pool"
        node_count = 3

        mock_time.time.side_effect = [100, 150]  # Start and end times

        mock_node_pool = mock.MagicMock()
        mock_node_pool.count = 1  # Current count
        mock_node_pool.vm_size = "Standard_DS2_v2"
        self.mock_agent_pools.get.return_value = mock_node_pool

        mock_operation = mock.MagicMock()
        self.mock_agent_pools.begin_create_or_update.return_value = mock_operation

        ready_nodes = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        self.mock_k8s.wait_for_nodes_ready.return_value = ready_nodes

        # Execute
        result = self.aks_client.scale_node_pool(
            node_pool_name=node_pool_name, node_count=node_count
        )

        # Verify
        self.assertTrue(result)
        self.mock_agent_pools.begin_create_or_update.assert_called_once()
        self.mock_k8s.wait_for_nodes_ready.assert_called_once_with(
            node_count=node_count,
            operation_timeout_in_minutes=10,
            label_selector=f"agentpool={node_pool_name}",
        )
        self.assertEqual(mock_node_pool.count, node_count)

    @mock.patch("clients.aks_client.time")
    def test_scale_node_pool_down(self, mock_time):
        """Test scaling a node pool down"""
        # Setup
        node_pool_name = "test-pool"
        node_count = 1

        mock_time.time.side_effect = [100, 150]  # Start and end times

        mock_node_pool = mock.MagicMock()
        mock_node_pool.count = 3  # Current count
        mock_node_pool.vm_size = "Standard_DS2_v2"
        self.mock_agent_pools.get.return_value = mock_node_pool

        mock_operation = mock.MagicMock()
        self.mock_agent_pools.begin_create_or_update.return_value = mock_operation

        ready_nodes = [mock.MagicMock()]
        self.mock_k8s.wait_for_nodes_ready.return_value = ready_nodes

        # Execute
        result = self.aks_client.scale_node_pool(
            node_pool_name=node_pool_name, node_count=node_count
        )

        # Verify
        self.assertTrue(result)
        self.mock_agent_pools.begin_create_or_update.assert_called_once()
        self.mock_k8s.wait_for_nodes_ready.assert_called_once_with(
            node_count=node_count,
            operation_timeout_in_minutes=10,
            label_selector=f"agentpool={node_pool_name}",
        )
        self.assertEqual(mock_node_pool.count, node_count)

    @mock.patch("clients.aks_client.time")
    def test_delete_node_pool(self, mock_time):
        """Test deleting a node pool"""
        # Setup
        node_pool_name = "test-pool"

        mock_time.time.side_effect = [100, 150]  # Start and end times

        mock_node_pool = mock.MagicMock()
        mock_node_pool.vm_size = "Standard_DS2_v2"
        self.mock_agent_pools.get.return_value = mock_node_pool

        mock_operation = mock.MagicMock()
        self.mock_agent_pools.begin_delete.return_value = mock_operation

        # Execute
        result = self.aks_client.delete_node_pool(node_pool_name=node_pool_name)

        # Verify
        self.assertTrue(result)
        self.mock_agent_pools.begin_delete.assert_called_once_with(
            resource_group_name="fake-resource-group",
            resource_name="fake-cluster",
            agent_pool_name=node_pool_name,
        )
        mock_operation.result.assert_called_once()

    def test_record_metrics(self):
        """Test the _record_metrics method for operation data capture"""
        # Setup
        operation = "create_node_pool"
        node_pool_name = "test-pool"
        duration = 50.0
        success = True
        node_count = 3

        self.mock_managed_clusters.get.side_effect = HttpResponseError(
            message="Not found"
        )

        # Execute
        # pylint: disable=protected-access
        self.aks_client._record_metrics(
            operation=operation,
            node_pool_name=node_pool_name,
            duration=duration,
            success=success,
            node_count=node_count,
        )

        # Verify - check that a file was created
        files = [
            f
            for f in os.listdir(self.test_result_dir)
            if f.startswith("azure_create_node_pool_")
        ]
        self.assertEqual(len(files), 1)

        # Verify the content of the file
        with open(
            os.path.join(self.test_result_dir, files[0]), "r", encoding="utf-8"
        ) as f:
            data = json.load(f)

        self.assertEqual(data["operation_info"]["operation"], operation)
        self.assertEqual(data["operation_info"]["duration_seconds"], duration)
        self.assertEqual(data["operation_info"]["success"], success)
        self.assertEqual(data["operation_info"]["node_pool_name"], node_pool_name)
        self.assertEqual(data["operation_info"]["node_count"], node_count)
        self.assertEqual(data["operation_info"]["vm_size"], "Standard_DS2_v2")


if __name__ == "__main__":
    unittest.main()
