from unittest.mock import MagicMock, patch
import sys
import os
import unittest

from clusterloader2.kubelet_benchmark.kubelet_benchmark import override_clusterloader2_config, execute_clusterloader2, collect_clusterloader2
from clusterloader2.kubelet_benchmark.data_type import ResourceStressor
from clusterloader2.kubelet_benchmark.cluster_controller import KubeletConfig

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

class TestKubeletBenchmark(unittest.TestCase):

    @patch('clusterloader2.kubelet_benchmark.kubelet_benchmark.run_cl2_command', autospec=True)
    @patch('clusterloader2.kubelet_benchmark.cluster_controller.ClusterController', autospec=True)
    @patch('clusterloader2.kubelet_benchmark.cl2_file_handler.CL2FileHandler', autospec=True)
    def setUp(self, MockFileHandler, MockClusterController, MockRunCl2Command):
        self.mock_cluster_controller = MockClusterController.return_value
        self.mock_file_handler = MockFileHandler.return_value
        self.mock_run_cl2_command = MockRunCl2Command
        self.mock_run_cl2_command.side_effect = lambda *args, **kwargs: print(f"run_cl2_command called with args: {args}, kwargs: {kwargs}")
        self.mock_cluster_controller.kubernetes_client = MagicMock()  # Mock out the Kubernetes client
        self.mock_cluster_controller.docker_client = MagicMock()  # Mock out the Docker client
        self.mock_cluster_controller.docker_client.side_effect = lambda *args, **kwargs: print(f"docker_client called with args: {args}, kwargs: {kwargs}")
        self.mock_file_handler.cl2_config_dir = "configs"
        self.mock_file_handler.cl2_report_dir = "results"

    def test_override_clusterloader2_config_defaults(self):
        resource_stressor = ResourceStressor("memory", "best_effort", "spike")

        override_clusterloader2_config(
            self.mock_cluster_controller,
            self.mock_file_handler,
            resource_stressor,
            node_count=10,
            max_pods=100,
            operation_timeout_seconds=300,
            provider="aws"
        )

        self.mock_cluster_controller.populate_nodes.assert_called_once_with(10)
        self.mock_cluster_controller.populate_node_resources.assert_called_once()
        self.mock_file_handler.export_cl2_override.assert_called_once()

    @patch('clusterloader2.kubelet_benchmark.kubelet_benchmark.run_cl2_command', autospec=True)
    def test_execute_clusterloader2_defaults(self, mock_run_cl2_command):
        kubelet_config = KubeletConfig("100Mi")

        execute_clusterloader2(
            self.mock_cluster_controller,
            self.mock_file_handler,
            kubelet_config,
            cl2_image="test-image",
            kubeconfig="~/.kube/config",
            provider="aws"
        )

        self.mock_cluster_controller.reconfigure_kubelet.assert_called_once_with(kubelet_config)
        mock_run_cl2_command.assert_called_once()

    @patch('clusterloader2.kubelet_benchmark.kubelet_benchmark.run_cl2_command', autospec=True)
    def test_execute_clusterloader2_with_750mi_kubelet_config(self, mock_run_cl2_command):
        kubelet_config = KubeletConfig("750Mi")

        execute_clusterloader2(
            self.mock_cluster_controller,
            self.mock_file_handler,
            kubelet_config,
            cl2_image="test-image",
            kubeconfig="~/.kube/config",
            provider="aws"
        )
        mock_run_cl2_command.assert_called_once()
        self.mock_cluster_controller.reconfigure_kubelet.assert_called_once_with(kubelet_config)

    def test_collect_clusterloader2_defaults(self):
        resource_stressor = ResourceStressor("memory", "best_effort", "spike")
        kubelet_config = KubeletConfig("100Mi")

        collect_clusterloader2(
            self.mock_cluster_controller,
            self.mock_file_handler,
            resource_stressor,
            node_count=10,
            max_pods=100,
            kubelet_config=kubelet_config,
            cloud_info="aws",
            run_id="test-run-id",
            run_url="http://test-url",
            output_test_file="/tmp/test-result.json"
        )

        self.mock_cluster_controller.verify_measurement.assert_called_once_with(10)
        self.mock_file_handler.load_junit_result.assert_called_once()
        self.mock_file_handler.parse_test_result.assert_called_once()


if __name__ == "__main__":
    unittest.main()
