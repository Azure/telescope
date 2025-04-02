import unittest
from unittest.mock import patch, MagicMock
from eviction_eval import EvictionEval, NodeConfig, WorkloadConfig

class TestEvictionEval(unittest.TestCase):

    @patch('eviction_eval.KubernetesClient')
    def test_generate_cl2_override(self, MockKubernetesClient):
        # Mock KubernetesClient and its methods
        mock_client = MockKubernetesClient.return_value
        # return node in the format of a Kubernetes node object, which has format {name: "node1", metadata: {name: {}}}

        mock_client.get_nodes.return_value =  [MagicMock(metadata=MagicMock(name="node1"), status=MagicMock(allocatable=MagicMock(cpu="1000m", memory="1000000Ki")))]
        mock_client.get_pods_by_namespace.return_value = [MagicMock(metadata=MagicMock(name="pod1"))]
        node_config = NodeConfig(node_label="test-label", node_count=1)
        node_config.validate(mock_client)
        node_config.populate_node_resources(mock_client)

        eviction_eval = EvictionEval(max_pods=10, timeout_seconds=300, provider="aks")
        eviction_eval.generate_cl2_override(node_config, load_type="memory")

        self.assertIsNotNone(eviction_eval.workload_config)
        self.assertEqual(eviction_eval.workload_config.load_type, "memory")

    @patch('eviction_eval.open', new_callable=unittest.mock.mock_open)
    def test_export_cl2_override(self, mock_open):
        node_config = NodeConfig(node_label="test-label", node_count=1)
        workload_config = WorkloadConfig(load_type="memory")
        workload_config.load_duration_seconds = 300
        workload_config.pod_request_resource = MagicMock(memory_ki=1024, cpu_milli=500)
        workload_config.load_resource = MagicMock(memory_ki=2048, cpu_milli=1000)

        eviction_eval = EvictionEval(max_pods=10, timeout_seconds=300, provider="aws")
        eviction_eval.workload_config = workload_config

        eviction_eval.export_cl2_override(node_config, "override_file.yaml")

        mock_open.assert_called_once_with("override_file.yaml", 'w', encoding='utf-8')
        # print the content of the file to standard output

        handle = mock_open()
        handle.write.assert_called()
        for call in handle.write.call_args_list:
            print(call[0][0])


if __name__ == '__main__':
    unittest.main()
