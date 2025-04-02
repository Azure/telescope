import unittest
from unittest.mock import patch, MagicMock
from kubelet_configurator import KubeletConfig

class TestKubeletConfig(unittest.TestCase):

    @patch('kubelet_configurator.KubernetesClient')
    def test_reconfigure_kubelet(self, MockKubernetesClient):
        mock_client = MockKubernetesClient.return_value
        mock_client.create_daemonset = MagicMock()

        KubeletConfig.default_config = KubeletConfig("100Mi")
        kubelet_config = KubeletConfig("750Mi")
        kubelet_config.reconfigure_kubelet(mock_client, "test-label")

        mock_client.create_daemonset.assert_called_once()
        self.assertIn("kube-system", mock_client.create_daemonset.call_args[0])
        self.assertIn("test-label", mock_client.create_daemonset.call_args[0][1])

    def test_generate_kubelet_reconfig_daemonset(self):
        KubeletConfig.default_config = KubeletConfig("100Mi")
        kubelet_config = KubeletConfig("750Mi")
        daemonset_yaml = kubelet_config.generate_kubelet_reconfig_daemonset("test-label")
        # print the generated yaml to standard output
        print(daemonset_yaml)

        self.assertIn("kubelet-config-updater", daemonset_yaml)
        self.assertIn("test-label", daemonset_yaml)
        self.assertIn("memory\.available<750Mi", daemonset_yaml)

if __name__ == '__main__':
    unittest.main()