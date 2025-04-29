import json
import os
import unittest
from unittest.mock import mock_open, patch

from clusterloader2.default.cli import (collect_clusterloader2,
                                        configure_clusterloader2,
                                        execute_clusterloader2,
                                        validate_clusterloader2)


class TestCLI(unittest.TestCase):

    # Test for configure_clusterloader2
    @patch("builtins.open", new_callable=mock_open)
    def test_configure_clusterloader2(self, mock_open_file):
        # Arrange
        mock_write = mock_open_file.return_value.write
        mock_read = mock_open_file.return_value.read
        mock_read.return_value = "Mocked file content"

        mock_data = {
            "cpu_per_node": 2,
            "node_count": 100,
            "node_per_step": 10,
            "max_pods": 40,
            "repeats": 1,
            "operation_timeout": "15m",
            "provider": "azure",
            "cilium_enabled": False,
            "scrape_containerd": False,
            "service_test": True,
            "cnp_test": False,
            "ccnp_test": False,
            "num_cnps": 0,
            "num_ccnps": 0,
            "dualstack": False,
            "cl2_override_file": "overrides.yaml",
            "workload_type": "job",
            "job_count": 1000,
            "job_parallelism": 1,
            "job_completions": 1,
            "job_throughput": 1000,
        }

        # Act
        configure_clusterloader2(**mock_data)

        # Assert
        # Verify that the file was opened for writing
        mock_open_file.assert_any_call(
            mock_data["cl2_override_file"], "w", encoding="utf-8"
        )
        # Verify that the file was opened for reading (if applicable)
        mock_open_file.assert_any_call(
            mock_data["cl2_override_file"], "r", encoding="utf-8"
        )

        # Verify the content written to the file
        mock_write.assert_any_call("CL2_NODES: 100\n")
        mock_write.assert_any_call("CL2_OPERATION_TIMEOUT: 15m\n")
        mock_write.assert_any_call("CL2_JOBS: 1000\n")
        mock_write.assert_any_call("CL2_LOAD_TEST_THROUGHPUT: 1000\n")

    @patch(
        "clients.kubernetes_client.KubernetesClient.get_ready_nodes",
        return_value=["node1", "node2"],
    )
    @patch(
        "clients.kubernetes_client.KubernetesClient.__init__", return_value=None
    )
    def test_validate_clusterloader2(
        self, mock_kubernetes_client_init, mock_get_ready_nodes
    ):
        # Arrange
        node_count = 2  # Expected number of ready nodes
        operation_timeout_in_minutes = 5

        # Act
        validate_clusterloader2(node_count, operation_timeout_in_minutes)

        # Assert: verify if get_ready_nodes was called
        mock_get_ready_nodes.assert_called_once()
        mock_kubernetes_client_init.assert_called_once()
        self.assertEqual(mock_get_ready_nodes.return_value, ["node1", "node2"])

    @patch("clusterloader2.default.cli.run_cl2_command")
    @patch("clusterloader2.utils.DockerClient")
    def test_execute_clusterloader2(self, mock_docker_client, mock_run_cl2_command):
        # Arrange
        mock_run_cl2_command.return_value = "Command executed successfully"
        mock_docker_client.return_value = (
            mock_docker_client  # Mock DockerClient instance
        )

        mock_data = {
            "cl2_image": "cl2-image",
            "cl2_config_dir": "/path/to/config",
            "cl2_report_dir": "/path/to/reports",
            "cl2_config_file": "/path/to/config.yaml",
            "kubeconfig": "/path/to/kubeconfig",
            "provider": "aws",
            "scrape_containerd": False,
            "prometheus_enabled": False,
        }

        # Act
        execute_clusterloader2(**mock_data)

        # Assert
        mock_run_cl2_command.assert_called_once()

    @patch("clusterloader2.default.cli.parse_xml_to_json")
    @patch("os.makedirs")
    @patch("os.listdir", return_value=["junit.xml"])
    @patch("builtins.open", new_callable=mock_open)
    def test_collect_clusterloader2(
        self, mock_open_file, mock_listdir, mock_makedirs, mock_parse_xml_to_json
    ):
        # Arrange
        mock_parse_xml_to_json.return_value = json.dumps(
            {"testsuites": [{"failures": 0, "testcases": []}]}
        )  # Simulate a valid parsed XML structure

        # Mock the open call for the report file separately
        mock_report_file = mock_open(read_data="Mocked XML content").return_value
        mock_open_file.side_effect = lambda file, mode, encoding=None: (
            mock_report_file
            if file == "/path/to/reports/junit.xml"
            else mock_open_file.return_value
        )

        mock_data = {
            "cpu_per_node": 2,
            "node_count": 100,
            "max_pods": 40,
            "repeats": 1,
            "cl2_report_dir": "/path/to/reports",
            "cloud_info": '{"cloud": "aws"}',
            "run_id": None,
            "run_url": None,
            "service_test": True,
            "cnp_test": False,
            "ccnp_test": False,
            "result_file": "/path/to/results.json",
            "test_type": None,
            "start_timestamp": "2025-04-23T12:00:00Z",
            "workload_type": "pod",
            "job_count": None,
            "job_parallelism": None,
            "job_completions": None,
            "job_throughput": None,
        }

        # Act
        collect_clusterloader2(**mock_data)

        # Assert
        mock_makedirs.assert_called_once_with("/path/to", exist_ok=True)
        mock_open_file.assert_any_call(mock_data["result_file"], "w", encoding="utf-8")
        mock_parse_xml_to_json.assert_called_once_with(
            os.path.join(mock_data["cl2_report_dir"], "junit.xml"), indent=2
        )
        mock_listdir.assert_called_once_with(mock_data["cl2_report_dir"])


if __name__ == "__main__":
    unittest.main()
