import unittest
from unittest.mock import patch, MagicMock
from clusterloader2.autoscale.autoscale import (
    warmup_deployment_for_karpeneter,
    cleanup_warmup_deployment_for_karpeneter,
    _get_daemonsets_pods_allocated_resources,
    calculate_cpu_request_for_clusterloader2,
    override_config_clusterloader2,
    execute_clusterloader2,
    collect_clusterloader2,
)

class TestClusterLoaderFunctions(unittest.TestCase):

    @patch('subprocess.run')
    def test_warmup_deployment_for_karpeneter(self, mock_run):
        cl2_config_dir = '/mock/path'
        warmup_deployment_for_karpeneter(cl2_config_dir)
        mock_run.assert_called_once_with(["kubectl", "apply", "-f", f"{cl2_config_dir}/warmup_deployment.yaml"], check=True)

    @patch('subprocess.run')
    def test_cleanup_warmup_deployment_for_karpeneter(self, mock_run):
        cl2_config_dir = '/mock/path'
        cleanup_warmup_deployment_for_karpeneter(cl2_config_dir)
        mock_run.assert_any_call(["kubectl", "delete", "-f", f"{cl2_config_dir}/warmup_deployment.yaml"], check=True)
        mock_run.assert_any_call(["kubectl", "delete", "nodeclaims", "--all"], check=True)

    @patch('clients.kubernetes_client.KubernetesClient')
    def test_get_daemonsets_pods_allocated_resources(self, mock_client):
        # Create a mock client
        mock_client = MagicMock()
        
        # Create two mock pods with different CPU requests
        mock_pod1 = MagicMock()
        mock_pod1.metadata.name = "test-pod-1"
        mock_container1 = MagicMock()
        mock_container1.name = "test-container-1"
        mock_container1.resources.requests = {"cpu": "200m"}
        mock_pod1.spec.containers = [mock_container1]

        mock_pod2 = MagicMock()
        mock_pod2.metadata.name = "test-pod-2"
        mock_container2 = MagicMock()
        mock_container2.name = "test-container-2"
        mock_container2.resources.requests = {"cpu": "300m"}
        mock_pod2.spec.containers = [mock_container2]

        # Set the return value of the mock client
        mock_client.get_pods_by_namespace.return_value = [mock_pod1, mock_pod2]

        # Call the function under test
        cpu_request = _get_daemonsets_pods_allocated_resources(mock_client, "node1")

        # Assert the expected CPU request is sum of both
        self.assertEqual(cpu_request, 500)

    @patch('clients.kubernetes_client.KubernetesClient')
    @patch('clusterloader2.autoscale.autoscale._get_daemonsets_pods_allocated_resources')
    @patch('clusterloader2.autoscale.autoscale.cleanup_warmup_deployment_for_karpeneter')
    @patch('time.sleep')
    def test_calculate_cpu_request_with_warmup(self, mock_sleep, mock_cleanup, mock_get_allocated_resources, mock_k8s_client):
        # Mock the Kubernetes client and its methods
        mock_node = MagicMock()
        mock_node.status.allocatable = {"cpu": "2000m"}
        mock_node.metadata.name = "test-node"
        mock_k8s_client.return_value.get_ready_nodes.return_value = [mock_node]
        
        # Mock the allocated CPU resources
        mock_get_allocated_resources.return_value = 100
        
        # Call the function under test
        cpu_request = calculate_cpu_request_for_clusterloader2('label_selector', 1, 1, 'true', '/mock/path')
        
        # Assert the CPU request calculation
        self.assertEqual(cpu_request, 1900)  # 2000m - 100m (allocated) - 100m (warmup)

        # Assert cleanup is called
        mock_cleanup.assert_called_once_with('/mock/path')

    # @patch('clients.kubernetes_client.KubernetesClient')
    # @patch('time.sleep')
    # def test_calculate_cpu_request_for_clusterloader2(self, mock_sleep, mock_client):
    #     mock_node = MagicMock(status=MagicMock(allocatable={"cpu": "2000m"}), metadata=MagicMock(name='metadata', spec=['name']))
    #     mock_client.return_value.get_ready_nodes.return_value = [mock_node]
    #     mock_client.return_value.get_pods_by_namespace.return_value = []

    #     result = calculate_cpu_request_for_clusterloader2('label_selector', 1, 1, 'true', '/mock/path')
    #     self.assertEqual(result, 1900)  # 2000m - 100m for warmup deployment

    # @patch('builtins.open', new_callable=unittest.mock.mock_open)
    # def test_override_config_clusterloader2(self, mock_open):
    #     override_config_clusterloader2(100, 1, 1, '5m', '5m', 1, 'label_selector', 'node_selector', 'override_file', 'true', '/mock/path')
    #     mock_open.assert_called_once_with('override_file', 'w', encoding='utf-8')
    #     handle = mock_open()
    #     handle.write.assert_any_call('CL2_DEPLOYMENT_CPU: 1900m\n')  # Adjust based on actual logic

if __name__ == '__main__':
    unittest.main()