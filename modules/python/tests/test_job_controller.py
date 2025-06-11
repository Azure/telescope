import json
import os
import tempfile
import unittest
from unittest.mock import patch

from clusterloader2.job_controller.job_controller import JobSchedulingBenchmark


class TestJobSchedulingBenchmark(unittest.TestCase):
    def test_configure_clusterloader2(self):
        # Create a temporary file for the override file
        fd, tmp_path = tempfile.mkstemp()
        try:
            benchmark = JobSchedulingBenchmark(
                node_count=3,
                operation_timeout="10m",
                cl2_override_file=tmp_path,
                job_count=1000,
                job_throughput=50,
            )
            benchmark.configure_clusterloader2()
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("CL2_NODES: 3", content)
            self.assertIn("CL2_OPERATION_TIMEOUT: 10m", content)
            self.assertIn("CL2_JOBS: 1000", content)
            self.assertIn("CL2_LOAD_TEST_THROUGHPUT: 50", content)
        finally:
            os.close(fd)
            os.remove(tmp_path)

    @patch("clients.kubernetes_client.KubernetesClient.wait_for_nodes_ready")
    def test_validate_clusterloader2(self, mock_wait_for_nodes_ready):
        benchmark = JobSchedulingBenchmark(
            node_count=2,
            operation_timeout="5m",
            label="role=worker",
        )
        benchmark.validate_clusterloader2()
        mock_wait_for_nodes_ready.assert_called_once_with(2, "5m", "role=worker")

    @patch("clusterloader2.job_controller.job_controller.run_cl2_command")
    def test_execute_clusterloader2(self, mock_run_cl2_command):
        benchmark = JobSchedulingBenchmark(
            kubeconfig="kubeconfig.yaml",
            cl2_image="cl2-image",
            cl2_config_dir="config_dir",
            cl2_report_dir="report_dir",
            provider="aws",
            cl2_config_file="config.yaml",
            prometheus_enabled=True,
            scrape_containerd=True,
        )
        benchmark.execute_clusterloader2()
        mock_run_cl2_command.assert_called_once_with(
            "kubeconfig.yaml",
            "cl2-image",
            "config_dir",
            "report_dir",
            "aws",
            cl2_config_file="config.yaml",
            overrides=True,
            enable_prometheus=True,
            scrape_containerd=True,
        )

    @patch("clusterloader2.job_controller.job_controller.parse_xml_to_json")
    @patch("clusterloader2.job_controller.job_controller.process_cl2_reports")
    def test_collect_clusterloader2(
        self, mock_process_cl2_reports, mock_parse_xml_to_json
    ):
        # Setup mock return values
        mock_parse_xml_to_json.return_value = json.dumps(
            {"testsuites": [{"failures": 0}]}
        )
        mock_process_cl2_reports.return_value = "mock_content"

        fd, tmp_path = tempfile.mkstemp()
        try:
            benchmark = JobSchedulingBenchmark(
                cl2_report_dir="report_dir",
                cloud_info=json.dumps({"cloud": "aws"}),
                run_id="run123",
                run_url="http://example.com/run123",
                result_file=tmp_path,
                test_type="unit-test",
                start_timestamp="2024-06-11T12:00:00Z",
                node_count=3,
                job_count=1000,
                job_throughput=50,
            )
            benchmark.collect_clusterloader2()
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, "mock_content")
        finally:
            os.close(fd)
            os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
