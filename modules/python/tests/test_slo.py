import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Setup path for the module under test
test_dir = os.path.dirname(os.path.abspath(__file__))
modules_dir = os.path.abspath(os.path.join(test_dir, '..'))
if modules_dir not in sys.path:
    sys.path.insert(0, modules_dir)

# Mock modules before importing the module under test
sys.modules['docker'] = MagicMock()
sys.modules['clients.docker_client'] = MagicMock()
sys.modules['clients.kubernetes_client'] = MagicMock()
sys.modules['kubernetes'] = MagicMock()
sys.modules['kubernetes.client'] = MagicMock()
sys.modules['kubernetes.config'] = MagicMock()
sys.modules['utils.logger_config'] = MagicMock()
sys.modules['utils.logger_config'].get_logger = MagicMock()
sys.modules['utils.logger_config'].setup_logging = MagicMock()

# Import the module under test
# pylint: disable=wrong-import-position
from clusterloader2.slo.slo import (
    calculate_config, execute_clusterloader2, main,
    CPU_REQUEST_LIMIT_MILLI, DEFAULT_NODES_PER_NAMESPACE, DEFAULT_PODS_PER_NODE
)

class TestSlo(unittest.TestCase):
    """Tests for the slo.py module. These tests use mocks to avoid external dependencies."""

    def test_calculate_config_default(self):
        """Test calculate_config with default parameters"""
        cpu_per_node = 4
        node_count = 10
        max_pods = 110
        provider = "azure"
        service_test = False
        cnp_test = False
        ccnp_test = False

        throughput, nodes_per_namespace, pods_per_node, cpu_request = calculate_config(
            cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test
        )

        # Verify default calculations
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, min(node_count, DEFAULT_NODES_PER_NAMESPACE))
        self.assertEqual(pods_per_node, DEFAULT_PODS_PER_NODE)
        expected_cpu_request = max(
            (cpu_per_node * 1000 * 0.87) // DEFAULT_PODS_PER_NODE,
            CPU_REQUEST_LIMIT_MILLI
        )
        self.assertEqual(cpu_request, expected_cpu_request)

    def test_calculate_config_service_test(self):
        """Test calculate_config with service_test=True"""
        cpu_per_node = 4
        node_count = 10
        max_pods = 110
        provider = "azure"
        service_test = True
        cnp_test = False
        ccnp_test = False

        _, _, pods_per_node, cpu_request = calculate_config(
            cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test
        )

        # Verify service_test affects pods_per_node
        self.assertEqual(pods_per_node, max_pods)
        expected_cpu_request = max(
            (cpu_per_node * 1000 * 0.87) // max_pods,
            CPU_REQUEST_LIMIT_MILLI
        )
        self.assertEqual(cpu_request, expected_cpu_request)

    def test_calculate_config_cnp_test(self):
        """Test calculate_config with cnp_test=True"""
        cpu_per_node = 4
        node_count = 10
        max_pods = 110
        provider = "azure"
        service_test = False
        cnp_test = True
        ccnp_test = False

        _, _, pods_per_node, cpu_request = calculate_config(
            cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test
        )

        # Verify cnp_test affects pods_per_node
        self.assertEqual(pods_per_node, max_pods)
        expected_cpu_request = max(
            (cpu_per_node * 1000 * 0.87) // max_pods,
            CPU_REQUEST_LIMIT_MILLI
        )
        self.assertEqual(cpu_request, expected_cpu_request)

    def test_calculate_config_ccnp_test(self):
        """Test calculate_config with ccnp_test=True"""
        cpu_per_node = 4
        node_count = 10
        max_pods = 110
        provider = "aws"  # Using AWS provider to test different CPU_CAPACITY
        service_test = False
        cnp_test = False
        ccnp_test = True

        _, _, pods_per_node, cpu_request = calculate_config(
            cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test
        )

        # Verify ccnp_test affects pods_per_node
        self.assertEqual(pods_per_node, max_pods)
        expected_cpu_request = max(
            (cpu_per_node * 1000 * 0.94) // max_pods,  # AWS capacity is 0.94
            CPU_REQUEST_LIMIT_MILLI
        )
        self.assertEqual(cpu_request, expected_cpu_request)

    @patch("clusterloader2.slo.slo.run_cl2_command")
    def test_execute_clusterloader2(self, mock_run_cl2_command):
        """Test execute_clusterloader2 function"""
        cl2_image = "test-image:latest"
        cl2_config_dir = "/tmp/config"
        cl2_report_dir = "/tmp/report"
        cl2_config_file = "test-config.yaml"
        kubeconfig = "/tmp/kubeconfig"
        provider = "azure"
        scrape_containerd = True

        # Call the function
        execute_clusterloader2(
            cl2_image, cl2_config_dir, cl2_report_dir, cl2_config_file,
            kubeconfig, provider, scrape_containerd
        )

        # Verify run_cl2_command was called with correct parameters
        mock_run_cl2_command.assert_called_once_with(
            kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider,
            cl2_config_file=cl2_config_file, overrides=True, enable_prometheus=True,
            scrape_containerd=scrape_containerd
        )

    @patch("clusterloader2.slo.slo.configure_clusterloader2")
    def test_main_configure(self, mock_configure):
        """Test main function with configure command"""
        test_args = [
            "main.py", "configure",
            "4", "10", "5", "110", "3", "10m", "azure",
            "False", "False", "False", "False", "False",
            "0", "0", "False", "/tmp/override.yaml"
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_configure.assert_called_once_with(
                4, 10, 5, 110, 3, "10m", "azure", False, False, False, False, False, 0, 0, False, "/tmp/override.yaml"
            )

    @patch("clusterloader2.slo.slo.validate_clusterloader2")
    def test_main_validate(self, mock_validate):
        """Test main function with validate command"""
        test_args = ["main.py", "validate", "10", "600"]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_validate.assert_called_once_with(10, 600)

    @patch("clusterloader2.slo.slo.execute_clusterloader2")
    def test_main_execute(self, mock_execute):
        """Test main function with execute command"""
        test_args = [
            "main.py", "execute",
            "test-image:latest", "/tmp/config", "/tmp/report", "config.yaml",
            "/tmp/kubeconfig", "azure", "True"
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_execute.assert_called_once_with(
                "test-image:latest", "/tmp/config", "/tmp/report", "config.yaml",
                "/tmp/kubeconfig", "azure", True
            )

    @patch("clusterloader2.slo.slo.collect_clusterloader2")
    def test_main_collect(self, mock_collect):
        """Test main function with collect command"""
        test_args = [
            "main.py", "collect",
            "4", "10", "110", "3", "/tmp/report",
            '{"cloud":"azure"}', "test-run-123", "http://example.com/run/123",
            "False", "False", "False",
            "/tmp/results/output.json", "test-type", "2023-01-01T00:00:00Z"
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_collect.assert_called_once_with(
                4, 10, 110, 3, "/tmp/report",
                '{"cloud":"azure"}', "test-run-123", "http://example.com/run/123",
                False, False, False,
                "/tmp/results/output.json", "test-type", "2023-01-01T00:00:00Z"
            )


if __name__ == '__main__':
    unittest.main()
