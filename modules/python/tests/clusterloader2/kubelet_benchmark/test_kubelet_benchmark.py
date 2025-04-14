from unittest.mock import patch
import sys
import os
import unittest

from clusterloader2.kubelet_benchmark.kubelet_benchmark import override_clusterloader2_config, execute_clusterloader2, collect_clusterloader2
from clusterloader2.kubelet_benchmark.data_type import ResourceStressor
from clusterloader2.kubelet_benchmark.cluster_controller import KubeletConfig

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

class TestKubeletBenchmark(unittest.TestCase):

    @patch('clusterloader2.kubelet_benchmark.cluster_controller.ClusterController', autospec=True)
    @patch('clusterloader2.kubelet_benchmark.cl2_file_handler.CL2FileHandler', autospec=True)
    def test_override_clusterloader2_config_defaults(self, mock_file_handler, mock_cluster_controller):
        mock_cluster_controller = mock_cluster_controller.return_value
        mock_file_handler = mock_file_handler.return_value
        mock_file_handler.cl2_config_dir = "configs"
        mock_file_handler.cl2_report_dir = "results"

        resource_stressor = ResourceStressor("memory", "best_effort", "spike")

        override_clusterloader2_config(
            mock_cluster_controller,
            mock_file_handler,
            resource_stressor,
            node_count=10,
            max_pods=100,
            operation_timeout_seconds=300,
            provider="aws"
        )

        mock_cluster_controller.populate_nodes.assert_called_once_with(10)
        mock_cluster_controller.populate_node_resources.assert_called_once()
        mock_file_handler.export_cl2_override.assert_called_once()

    @patch('clusterloader2.kubelet_benchmark.kubelet_benchmark.run_cl2_command', autospec=True)
    @patch('clusterloader2.kubelet_benchmark.cluster_controller.ClusterController', autospec=True)
    @patch('clusterloader2.kubelet_benchmark.cl2_file_handler.CL2FileHandler', autospec=True)
    def test_execute_clusterloader2_defaults(self, mock_file_handler, mock_cluster_controller, mock_run_cl2_command):
        mock_cluster_controller = mock_cluster_controller.return_value
        mock_file_handler = mock_file_handler.return_value
        mock_file_handler.cl2_config_dir = "configs"
        mock_file_handler.cl2_report_dir = "results"

        kubelet_config = KubeletConfig("100Mi")

        execute_clusterloader2(
            mock_cluster_controller,
            mock_file_handler,
            kubelet_config,
            cl2_image="test-image",
            kubeconfig="~/.kube/config",
            provider="aws"
        )

        mock_cluster_controller.reconfigure_kubelet.assert_called_once_with(kubelet_config)
        mock_run_cl2_command.assert_called_once()

    @patch('clusterloader2.kubelet_benchmark.kubelet_benchmark.run_cl2_command', autospec=True)
    @patch('clusterloader2.kubelet_benchmark.cluster_controller.ClusterController', autospec=True)
    @patch('clusterloader2.kubelet_benchmark.cl2_file_handler.CL2FileHandler', autospec=True)
    def test_execute_clusterloader2_with_750mi_kubelet_config(self, mock_file_handler, mock_cluster_controller, mock_run_cl2_command):
        mock_cluster_controller = mock_cluster_controller.return_value
        mock_file_handler = mock_file_handler.return_value
        mock_file_handler.cl2_config_dir = "configs"
        mock_file_handler.cl2_report_dir = "results"

        kubelet_config = KubeletConfig("750Mi")

        execute_clusterloader2(
            mock_cluster_controller,
            mock_file_handler,
            kubelet_config,
            cl2_image="test-image",
            kubeconfig="~/.kube/config",
            provider="aws"
        )

        mock_cluster_controller.reconfigure_kubelet.assert_called_once_with(kubelet_config)
        mock_run_cl2_command.assert_called_once()

    @patch('clusterloader2.kubelet_benchmark.cluster_controller.ClusterController', autospec=True)
    @patch('clusterloader2.kubelet_benchmark.cl2_file_handler.CL2FileHandler', autospec=True)
    def test_collect_clusterloader2_defaults(self, mock_file_handler, mock_cluster_controller):
        mock_cluster_controller = mock_cluster_controller.return_value
        mock_file_handler = mock_file_handler.return_value
        mock_file_handler.cl2_config_dir = "configs"
        mock_file_handler.cl2_report_dir = "results"

        resource_stressor = ResourceStressor("memory", "best_effort", "spike")
        kubelet_config = KubeletConfig("100Mi")

        collect_clusterloader2(
            mock_cluster_controller,
            mock_file_handler,
            resource_stressor,
            node_count=10,
            max_pods=100,
            kubelet_config=kubelet_config,
            cloud_info="aws",
            run_id="test-run-id",
            run_url="http://test-url",
            output_test_file="/tmp/test-result.json"
        )

        mock_cluster_controller.verify_measurement.assert_called_once_with(10)
        mock_file_handler.load_junit_result.assert_called_once()
        mock_file_handler.parse_test_result.assert_called_once()

if __name__ == "__main__":
    unittest.main()
