import unittest
from unittest.mock import patch, MagicMock
from cluster_controller import KubeletConfig, ClusterController

class TestKubeletConfig(unittest.TestCase):
    @patch('cluster_controller.KubernetesClient')
    def setUp(self, MockKubernetesClient):
        self.kubelet_config = KubeletConfig(eviction_hard_memory="100Mi")
        self.default_kubelet_config = KubeletConfig(eviction_hard_memory="100Mi")
        mock_client = MockKubernetesClient.return_value
        mock_client.create_daemonset = MagicMock()

        # Mock KubernetesClient and its methods
        mock_client = MockKubernetesClient.return_value
        # return node in the format of a Kubernetes node object, which has format {name: "node1", metadata: {name: {}}}
        mock_client.get_nodes.return_value =  [MagicMock(metadata=MagicMock(name="node1"), status=MagicMock(allocatable=MagicMock(cpu="1000m", memory="1000000Ki")))]
        mock_client.get_pods_by_namespace.return_value = [MagicMock(metadata=MagicMock(name="pod1"))]

        self.mock_client = mock_client

# test clustercontroller class to reconfigure kubelet when the kubelet config is different from the default config

    def test_reconfigure_kubelet(self):
        cluster_controller = ClusterController(self.mock_client, node_label="test-label")

        KubeletConfig.set_default_config("100Mi")
        cluster_controller.reconfigure_kubelet(KubeletConfig("750Mi"))

        self.mock_client.create_daemonset.assert_called_once()
        self.assertIn("kube-system", self.mock_client.create_daemonset.call_args[0])
        self.assertIn("test-label", self.mock_client.create_daemonset.call_args[0][1])

    def test_generate_kubelet_reconfig_daemonset(self):
        KubeletConfig.set_default_config("100Mi")
        current_kubelet_config = KubeletConfig("750Mi")
        cluster_controller = ClusterController(self.mock_client, node_label="test-label")
        daemonset_yaml = cluster_controller.generate_kubelet_reconfig_daemonset(current_kubelet_config)
        # print the generated yaml to standard output
        print(daemonset_yaml)

        self.assertIn("kubelet-config-updater", daemonset_yaml)
        self.assertIn("test-label", daemonset_yaml)
        self.assertIn("memory\.available<750Mi", daemonset_yaml)

if __name__ == '__main__':
    unittest.main()