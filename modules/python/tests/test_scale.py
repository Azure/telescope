import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from clusterloader2.scale.scale import (
    configure_clusterloader2,
    execute_clusterloader2,
    collect_clusterloader2,
    main,
)


class TestConfigureScale(unittest.TestCase):
    """Test cases for configure_clusterloader2 function"""

    def test_basic_configuration(self):
        """Test basic configuration with default parameters"""
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name

        try:
            configure_clusterloader2(
                fortio_servers_per_deployment=15,
                fortio_clients_per_deployment=15,
                fortio_client_queries_per_second=1500,
                fortio_client_connections=50,
                fortio_namespaces=1,
                fortio_deployments_per_namespace=1000,
                network_policies_per_namespace=100,
                generate_container_network_logs=False,
                label_traffic_pods=False,
                override_file=tmp_path,
            )

            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Assert Prometheus config
            self.assertIn("CL2_PROMETHEUS_TOLERATE_MASTER: true", content)
            self.assertIn("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 100.0", content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true", content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true", content)

            # Assert Fortio config
            self.assertIn("CL2_FORTIO_SERVERS_PER_DEPLOYMENT: 15", content)
            self.assertIn("CL2_FORTIO_CLIENTS_PER_DEPLOYMENT: 15", content)
            self.assertIn("CL2_FORTIO_CLIENT_QUERIES_PER_SECOND: 1500", content)
            self.assertIn("CL2_FORTIO_CLIENT_CONNECTIONS: 50", content)
            self.assertIn("CL2_FORTIO_NAMESPACES: 1", content)
            self.assertIn("CL2_FORTIO_DEPLOYMENTS_PER_NAMESPACE: 1000", content)

            # Assert network policies and flags
            self.assertIn("CL2_NETWORK_POLICIES_PER_NAMESPACE: 100", content)
            self.assertIn("CL2_GENERATE_CONTAINER_NETWORK_LOGS: False", content)
            self.assertIn("CL2_LABEL_TRAFFIC_PODS: False", content)
        finally:
            os.remove(tmp_path)

    def test_configuration_with_container_network_logs(self):
        """Test configuration with Container Network Logs enabled"""
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name

        try:
            configure_clusterloader2(
                fortio_servers_per_deployment=10,
                fortio_clients_per_deployment=10,
                fortio_client_queries_per_second=1000,
                fortio_client_connections=25,
                fortio_namespaces=5,
                fortio_deployments_per_namespace=100,
                network_policies_per_namespace=50,
                generate_container_network_logs=True,
                label_traffic_pods=True,
                override_file=tmp_path,
            )

            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("CL2_GENERATE_CONTAINER_NETWORK_LOGS: True", content)
            self.assertIn("CL2_LABEL_TRAFFIC_PODS: True", content)
        finally:
            os.remove(tmp_path)


class TestExecuteScale(unittest.TestCase):
    """Test cases for execute_clusterloader2 function"""

    @patch("clusterloader2.scale.scale.run_cl2_command")
    def test_execute_calls_run_cl2_command(self, mock_run_cl2):
        """Test that execute_clusterloader2 calls run_cl2_command with correct params"""
        execute_clusterloader2(
            cl2_image="ghcr.io/azure/clusterloader2:v20250513",
            cl2_config_dir="/path/to/config",
            cl2_report_dir="/path/to/report",
            cl2_config_file="config.yaml",
            kubeconfig="/path/to/kubeconfig",
            provider="aks",
            scrape_containerd=False,
        )

        mock_run_cl2.assert_called_once_with(
            "/path/to/kubeconfig",
            "ghcr.io/azure/clusterloader2:v20250513",
            "/path/to/config",
            "/path/to/report",
            "aks",
            cl2_config_file="config.yaml",
            overrides=True,
            enable_prometheus=True,
            scrape_containerd=False,
            tear_down_prometheus=True,
            scrape_kubelets=True,
            scrape_ksm=True,
            scrape_metrics_server=True,
        )


class TestCollectScale(unittest.TestCase):
    """Test cases for collect_clusterloader2 function"""

    def test_collect_creates_result_file(self):
        """Test that collect_clusterloader2 creates result file with correct structure"""
        cl2_report_dir = os.path.join(
            os.path.dirname(__file__), "mock_data", "scale", "report"
        )
        result_file = tempfile.mktemp(suffix=".jsonl")

        try:
            collect_clusterloader2(
                cl2_report_dir=cl2_report_dir,
                cloud_info=json.dumps({"cloud": "azure", "region": "eastus2"}),
                run_id="test-run-123",
                run_url="http://example.com/run123",
                result_file=result_file,
                test_type="unit-test",
                start_timestamp="2025-03-04T05:00:00Z",
                observability_tool="cnl",
                repository="https://github.com/microsoft/retina",
                repository_ref="main",
                fortio_servers_per_deployment=15,
                fortio_clients_per_deployment=15,
                fortio_client_queries_per_second=1500,
                fortio_client_connections=50,
                fortio_namespaces=1,
                fortio_deployments_per_namespace=1000,
                network_policies_per_namespace=100,
                generate_container_network_logs=True,
                label_traffic_pods=False,
                trigger_reason="Manual",
            )

            self.assertTrue(os.path.exists(result_file))
            with open(result_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Result should contain JSONL lines
            self.assertTrue(len(content) > 0)

            # Parse the first line and verify structure
            lines = content.strip().split("\n")
            if lines and lines[0]:
                result = json.loads(lines[0])
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["run_id"], "test-run-123")
                self.assertEqual(result["test_type"], "unit-test")
                self.assertEqual(result["observability_tool"], "cnl")
                self.assertIn("test_details", result)
                self.assertEqual(result["test_details"]["traffic_generator"], "fortio")
                self.assertEqual(result["test_details"]["traffic_namespaces"], 1)
                self.assertEqual(result["test_details"]["network_policies"], 100)
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)

    def test_collect_calculates_traffic_pods(self):
        """Test that traffic_pods is calculated correctly"""
        cl2_report_dir = os.path.join(
            os.path.dirname(__file__), "mock_data", "scale", "report"
        )
        result_file = tempfile.mktemp(suffix=".jsonl")

        try:
            # 5 namespaces * 10 deployments * (3 servers + 3 clients) = 300 pods
            collect_clusterloader2(
                cl2_report_dir=cl2_report_dir,
                cloud_info=json.dumps({"cloud": "azure"}),
                run_id="test-run",
                run_url="http://example.com",
                result_file=result_file,
                test_type="unit-test",
                start_timestamp="2025-03-04T05:00:00Z",
                observability_tool="cnl",
                repository="",
                repository_ref="",
                fortio_servers_per_deployment=3,
                fortio_clients_per_deployment=3,
                fortio_client_queries_per_second=100,
                fortio_client_connections=10,
                fortio_namespaces=5,
                fortio_deployments_per_namespace=10,
                network_policies_per_namespace=0,
            )

            with open(result_file, "r", encoding="utf-8") as f:
                content = f.read()

            lines = content.strip().split("\n")
            if lines and lines[0]:
                result = json.loads(lines[0])
                # 5 * 10 * (3 + 3) = 300
                self.assertEqual(result["test_details"]["traffic_pods"], 300)
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)


class TestMainArgumentParsing(unittest.TestCase):
    """Test cases for main() argument parsing"""

    @patch("clusterloader2.scale.scale.configure_clusterloader2")
    def test_configure_command_parsing(self, mock_configure):
        """Test that configure command parses arguments correctly"""
        test_args = [
            "scale.py",
            "configure",
            "--fortio-servers-per-deployment", "15",
            "--fortio-clients-per-deployment", "15",
            "--fortio-client-queries-per-second", "1500",
            "--fortio-client-connections", "50",
            "--fortio-namespaces", "1",
            "--fortio-deployments-per-namespace", "1000",
            "--network-policies-per-namespace", "100",
            "--generate-container-network-logs", "True",
            "--label_traffic_pods", "False",
            "--cl2_override_file", "/tmp/overrides.yaml",
        ]

        with patch.object(sys, "argv", test_args):
            main()

        mock_configure.assert_called_once_with(
            15, 15, 1500, 50, 1, 1000, 100, True, False, "/tmp/overrides.yaml"
        )

    @patch("clusterloader2.scale.scale.execute_clusterloader2")
    def test_execute_command_parsing(self, mock_execute):
        """Test that execute command parses arguments correctly"""
        test_args = [
            "scale.py",
            "execute",
            "--cl2-image", "ghcr.io/azure/clusterloader2:v20250513",
            "--cl2-config-dir", "/path/to/config",
            "--cl2-report-dir", "/path/to/report",
            "--cl2-config-file", "config.yaml",
            "--kubeconfig", "/path/to/kubeconfig",
            "--provider", "aks",
            "--scrape-containerd", "False",
        ]

        with patch.object(sys, "argv", test_args):
            main()

        mock_execute.assert_called_once_with(
            "ghcr.io/azure/clusterloader2:v20250513",
            "/path/to/config",
            "/path/to/report",
            "config.yaml",
            "/path/to/kubeconfig",
            "aks",
            False,
        )


if __name__ == "__main__":
    unittest.main()
