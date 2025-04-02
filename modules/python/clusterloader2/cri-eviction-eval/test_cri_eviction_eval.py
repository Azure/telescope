import unittest
from unittest.mock import patch, MagicMock
from cluster_controller import ClusterController, KubeletConfig
from cl2_configurator import WorkloadConfig, CL2Configurator
from data_type import NodeResourceConfig

class TestClusterController(unittest.TestCase):

    @patch('cri_eviction_eval.KubernetesClient')
    def test_validate(self, MockKubernetesClient):
        mock_client = MockKubernetesClient.return_value
        mock_client.get_nodes.return_value = [MagicMock(metadata=MagicMock(name="node1"))]

        cluster_controller = ClusterController(mock_client, node_label="test-label")
        cluster_controller.validate(node_count=1)

        self.assertEqual(cluster_controller.node_count, 1)
        self.assertEqual(len(cluster_controller.nodes), 1)

    @patch('cri_eviction_eval.KubernetesClient')
    def test_reconfigure_kubelet(self, MockKubernetesClient):
        mock_client = MockKubernetesClient.return_value
        cluster_controller = ClusterController(mock_client, node_label="test-label")

        kubelet_config = KubeletConfig(eviction_hard_memory="500Mi")
        cluster_controller.reconfigure_kubelet(kubelet_config)

        mock_client.create_daemonset.assert_called_once()

    @patch('cri_eviction_eval.KubernetesClient')
    def test_generate_kubelet_reconfig_daemonset(self, MockKubernetesClient):
        mock_client = MockKubernetesClient.return_value
        cluster_controller = ClusterController(mock_client, node_label="test-label")

        kubelet_config = KubeletConfig(eviction_hard_memory="500Mi")
        KubeletConfig.set_default_config("100Mi")
        daemonset_yaml = cluster_controller.generate_kubelet_reconfig_daemonset(kubelet_config)

        self.assertIn("kubelet-config-updater", daemonset_yaml)

    @patch('cri_eviction_eval.KubernetesClient')
    def test_get_system_pods_allocated_resources(self, MockKubernetesClient):
        mock_client = MockKubernetesClient.return_value
        # mock_client.get_pods_by_namespace.return_value = [MagicMock(spec=MagicMock(containers=[MagicMock(resources=MagicMock(requests={"cpu": "100m", "memory": "200Mi"}))]))]

        cluster_controller = ClusterController(mock_client, node_label="test-label")
        cluster_controller.nodes = [MagicMock(metadata=MagicMock(name="node1"))]

        resources = cluster_controller.get_system_pods_allocated_resources()
        #
        # self.assertEqual(resources.cpu_milli, 100)
        # self.assertEqual(resources.memory_ki, 200 * 1024)

    @patch('cri_eviction_eval.KubernetesClient')
    def test_get_node_available_resource(self, MockKubernetesClient):
        mock_client = MockKubernetesClient.return_value
        cluster_controller = ClusterController(mock_client, node_label="test-label")
        cluster_controller.nodes = [MagicMock(status=MagicMock(allocatable=MagicMock(cpu="1000m", memory="1000000Ki")))]

        resources = cluster_controller.get_node_available_resource()

        self.assertEqual(resources.cpu_milli, 1000)
        self.assertEqual(resources.memory_ki, 1000000)

    @patch('cri_eviction_eval.KubernetesClient')
    def test_populate_node_resources(self, MockKubernetesClient):
        mock_client = MockKubernetesClient.return_value
        cluster_controller = ClusterController(mock_client, node_label="test-label")
        cluster_controller.nodes = [MagicMock(metadata=MagicMock(name="node1"), status=MagicMock(allocatable=MagicMock(cpu="1000m", memory="1000000Ki")))]

        node_resources = cluster_controller.populate_node_resources()

        self.assertIsInstance(node_resources, NodeResourceConfig)
        self.assertIsNotNone(node_resources.system_allocated_resources)
        self.assertIsNotNone(node_resources.node_allocatable_resources)
        self.assertIsNotNone(node_resources.remaining_resources)

    @patch('cri_eviction_eval.open', new_callable=unittest.mock.mock_open)
    def test_export_cl2_override(self,  mock_open):
        eviction_eval = CL2Configurator(max_pods=10, timeout_seconds=300, provider="aws")

        workload_config = WorkloadConfig(load_type="memory", load_duration_seconds = 300, pod_request_resource = MagicMock(memory_ki=1024, cpu_milli=500), load_resource = MagicMock(memory_ki=2048, cpu_milli=1000))
        eviction_eval.workload_config = workload_config

        # mock_open.assert_called_once_with("override_file.yaml", 'w', encoding='utf-8')
        # print the content of the file to standard output

        handle = mock_open()
        # handle.write.assert_called()
        for call in handle.write.call_args_list:
            print(call[0][0])


if __name__ == '__main__':
    unittest.main()