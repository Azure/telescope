import json
import os
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from clusterloader2.large_cluster.large_cluster import (
    calculate_config,
    LargeCluster,
    Cl2DefaultConfigConstants,
)


class TestLargeCluster(unittest.TestCase):

    """Comprehensive test class for all large_cluster.py functions"""

    def setUp(self):
        """Set up test fixtures for each test"""
        #pylint: disable=consider-using-with
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, mode='w+', encoding='utf-8')
        self.temp_path = self.temp_file.name
        self.temp_file.close()

        self.large_cluster = LargeCluster()

        self.test_params = {
            "cpu_per_node": 4,
            "node_count": 20,
            "pods_per_node": 10,
            "repeats": 3,
            "cloud_info": json.dumps({"cloud": "test_cloud"}),
            "run_id": "test_run_123",
            "run_url": "http://example.com/run123"
        }

    def tearDown(self):
        """Clean up temporary files after each test"""
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    # ==================== calculate_config() Tests ====================

    def test_calculate_config_small_aws_cluster(self):
        """Test AWS small cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=2, node_count=10, provider="aws", pods_per_node=10
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 10)
        expected_cpu = (2 * 1000 * Cl2DefaultConfigConstants.CPU_CAPACITY["aws"]) // 10
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_medium_aws_cluster(self):
        """Test AWS medium cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=4, node_count=50, provider="aws", pods_per_node=20
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 50)
        expected_cpu = (4 * 1000 * Cl2DefaultConfigConstants.CPU_CAPACITY["aws"]) // 20
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_large_aws_cluster(self):
        """Test AWS large cluster configuration with namespace limit"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=8, node_count=150, provider="aws", pods_per_node=30
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, Cl2DefaultConfigConstants.DEFAULT_NODES_PER_NAMESPACE)  # Should be capped at 100
        expected_cpu = (8 * 1000 * Cl2DefaultConfigConstants.CPU_CAPACITY["aws"]) // 30
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_small_azure_cluster(self):
        """Test Azure small cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=2, node_count=10, provider="azure", pods_per_node=10
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 10)
        expected_cpu = (2 * 1000 * Cl2DefaultConfigConstants.CPU_CAPACITY["azure"]) // 10
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_medium_azure_cluster(self):
        """Test Azure medium cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=4, node_count=50, provider="azure", pods_per_node=20
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 50)
        expected_cpu = (4 * 1000 * Cl2DefaultConfigConstants.CPU_CAPACITY["azure"]) // 20
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_large_azure_cluster(self):
        """Test Azure large cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=8, node_count=150, provider="azure", pods_per_node=30
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, Cl2DefaultConfigConstants.DEFAULT_NODES_PER_NAMESPACE)
        expected_cpu = (8 * 1000 * Cl2DefaultConfigConstants.CPU_CAPACITY["azure"]) // 30
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_small_aks_cluster(self):
        """Test AKS small cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=2, node_count=10, provider="aks", pods_per_node=10
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 10)
        expected_cpu = (2 * 1000 * Cl2DefaultConfigConstants.CPU_CAPACITY["aks"]) // 10
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_edge_case_min_cpu(self):
        """Test edge case with minimum CPU request limit"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=1, node_count=5, provider="aws", pods_per_node=100
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 5)
        self.assertEqual(cpu_request, 9.0)

    def test_calculate_config_edge_case_high_pods(self):
        """Test edge case with high pod count"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=16, node_count=200, provider="azure", pods_per_node=50
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, Cl2DefaultConfigConstants.DEFAULT_NODES_PER_NAMESPACE)
        expected_cpu = (16 * 1000 * Cl2DefaultConfigConstants.CPU_CAPACITY["azure"]) // 50
        self.assertEqual(cpu_request, int(expected_cpu))

    # ==================== self.large_cluster.configure() Tests ====================

    def test_configure_clusterloader2_basic_aws_config(self):
        """Test basic AWS configuration"""
        config = self.large_cluster.configure(
            cpu_per_node=4, node_count=20, node_per_step=5,
            pods_per_node=10, repeats=3, operation_timeout="30m",
            provider="aws", cilium_enabled=False,
            scrape_containerd=False
        )

        self.assertEqual(config["CL2_NODES"], 20)
        self.assertEqual(config["CL2_NODES_PER_STEP"], 5)
        self.assertEqual(config["CL2_STEPS"], 4)  # 20 // 5
        self.assertEqual(config["CL2_PODS_PER_NODE"], 10)
        self.assertEqual(config["CL2_REPEATS"], 3)
        self.assertEqual(config["CL2_OPERATION_TIMEOUT"], "30m")
        self.assertNotIn("CL2_CILIUM_METRICS_ENABLED", config)
        self.assertNotIn("CL2_SCRAPE_CONTAINERD", config)

    def test_configure_clusterloader2_basic_azure_config(self):
        """Test basic Azure configuration"""
        config = self.large_cluster.configure(
            cpu_per_node=4, node_count=20, node_per_step=5,
            pods_per_node=10, repeats=3, operation_timeout="30m",
            provider="azure", cilium_enabled=False,
            scrape_containerd=False
        )

        self.assertEqual(config["CL2_NODES"], 20)
        self.assertEqual(config["CL2_LOAD_TEST_THROUGHPUT"], 100)

    def test_configure_clusterloader2_cilium_enabled(self):
        """Test configuration with Cilium enabled"""
        config = self.large_cluster.configure(
            cpu_per_node=4, node_count=50, node_per_step=10,
            pods_per_node=15, repeats=5, operation_timeout="45m",
            provider="azure", cilium_enabled=True,
            scrape_containerd=False
        )

        self.assertEqual(config["CL2_CILIUM_METRICS_ENABLED"], "true")
        self.assertEqual(config["CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR"], "true")
        self.assertEqual(config["CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT"], "true")
        self.assertEqual(config["CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL"], "30s")

    def test_configure_clusterloader2_containerd_scraping(self):
        """Test configuration with containerd scraping enabled"""
        config = self.large_cluster.configure(
            cpu_per_node=8, node_count=100, node_per_step=20,
            pods_per_node=20, repeats=2, operation_timeout="60m",
            provider="aws", cilium_enabled=False,
            scrape_containerd=True
        )

        self.assertEqual(config["CL2_SCRAPE_CONTAINERD"], "true")
        self.assertEqual(config["CONTAINERD_SCRAPE_INTERVAL"], "5m")

    def test_configure_clusterloader2_all_features_enabled(self):
        """Test configuration with all features enabled"""
        config = self.large_cluster.configure(
            cpu_per_node=8, node_count=100, node_per_step=25,
            pods_per_node=25, repeats=4, operation_timeout="90m",
            provider="azure", cilium_enabled=True,
            scrape_containerd=True
        )

        # Check all features are present
        self.assertEqual(config["CL2_CILIUM_METRICS_ENABLED"], "true")
        self.assertEqual(config["CL2_SCRAPE_CONTAINERD"], "true")
        self.assertEqual(config["CL2_STEPS"], 4)  # 100 // 25

    def test_configure_clusterloader2_large_scale(self):
        """Test large scale configuration"""
        config = self.large_cluster.configure(
            cpu_per_node=16, node_count=500, node_per_step=50,
            pods_per_node=30, repeats=1, operation_timeout="120m",
            provider="aws", cilium_enabled=False,
            scrape_containerd=False
        )

        self.assertEqual(config["CL2_NODES"], 500)
        self.assertEqual(config["CL2_STEPS"], 10)  # 500 // 50
        self.assertEqual(config["CL2_OPERATION_TIMEOUT"], "120m")

    def test_configure_clusterloader2_single_step(self):
        """Test single step configuration"""
        config = self.large_cluster.configure(
            cpu_per_node=2, node_count=10, node_per_step=10,
            pods_per_node=5, repeats=1, operation_timeout="15m",
            provider="azure", cilium_enabled=False,
            scrape_containerd=False
        )

        self.assertEqual(config["CL2_STEPS"], 1)  # 10 // 10

    # ==================== self.large_cluster.validate() Tests ====================

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_successful_validation(self, mock_kube_client_class):
        """Test successful node validation"""
        mock_kube_client = MagicMock()
        mock_kube_client_class.return_value = mock_kube_client

        self.large_cluster.validate(node_count=20, operation_timeout_in_minute=30)

        mock_kube_client_class.assert_called_once()
        mock_kube_client.wait_for_nodes_ready.assert_called_once_with(
            node_count=20,
            operation_timeout_in_minutes=30
        )

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_large_cluster(self, mock_kube_client_class):
        """Test validation of large cluster"""
        mock_kube_client = MagicMock()
        mock_kube_client_class.return_value = mock_kube_client

        self.large_cluster.validate(node_count=500, operation_timeout_in_minute=120)

        mock_kube_client.wait_for_nodes_ready.assert_called_once_with(
            node_count=500,
            operation_timeout_in_minutes=120
        )

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_small_cluster(self, mock_kube_client_class):
        """Test validation of small cluster"""
        mock_kube_client = MagicMock()
        mock_kube_client_class.return_value = mock_kube_client

        self.large_cluster.validate(node_count=3, operation_timeout_in_minute=10)

        mock_kube_client.wait_for_nodes_ready.assert_called_once_with(
            node_count=3,
            operation_timeout_in_minutes=10
        )

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_default_timeout(self, mock_kube_client_class):
        """Test validation with default timeout"""
        mock_kube_client = MagicMock()
        mock_kube_client_class.return_value = mock_kube_client

        self.large_cluster.validate(node_count=50, operation_timeout_in_minute=600)

        mock_kube_client.wait_for_nodes_ready.assert_called_once_with(
            node_count=50,
            operation_timeout_in_minutes=600
        )

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_timeout_exception(self, mock_kube_client_class):
        """Test validation when timeout occurs"""
        mock_kube_client = MagicMock()
        mock_kube_client_class.return_value = mock_kube_client
        mock_kube_client.wait_for_nodes_ready.side_effect = Exception("Timeout waiting for nodes")

        with self.assertRaises(Exception) as context:
            self.large_cluster.validate(node_count=100, operation_timeout_in_minute=5)

        self.assertIn("Timeout waiting for nodes", str(context.exception))
        mock_kube_client.wait_for_nodes_ready.assert_called_once_with(
            node_count=100,
            operation_timeout_in_minutes=5
        )

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_kubernetes_client_error(self, mock_kube_client_class):
        """Test validation when KubernetesClient initialization fails"""
        mock_kube_client_class.side_effect = Exception("Failed to initialize KubernetesClient")

        with self.assertRaises(Exception) as context:
            self.large_cluster.validate(node_count=20, operation_timeout_in_minute=30)

        self.assertIn("Failed to initialize KubernetesClient", str(context.exception))

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_wait_for_nodes_connection_error(self, mock_kube_client_class):
        """Test validation when connection to cluster fails"""
        mock_kube_client = MagicMock()
        mock_kube_client_class.return_value = mock_kube_client
        mock_kube_client.wait_for_nodes_ready.side_effect = Exception("Connection refused")

        with self.assertRaises(Exception) as context:
            self.large_cluster.validate(node_count=10, operation_timeout_in_minute=15)

        self.assertIn("Connection refused", str(context.exception))

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_zero_nodes(self, mock_kube_client_class):
        """Test validation with zero nodes (edge case)"""
        mock_kube_client = MagicMock()
        mock_kube_client_class.return_value = mock_kube_client

        self.large_cluster.validate(node_count=0, operation_timeout_in_minute=5)

        mock_kube_client.wait_for_nodes_ready.assert_called_once_with(
            node_count=0,
            operation_timeout_in_minutes=5
        )

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_negative_timeout(self, mock_kube_client_class):
        """Test validation with negative timeout (edge case)"""
        mock_kube_client = MagicMock()
        mock_kube_client_class.return_value = mock_kube_client

        self.large_cluster.validate(node_count=5, operation_timeout_in_minute=-10)

        mock_kube_client.wait_for_nodes_ready.assert_called_once_with(
            node_count=5,
            operation_timeout_in_minutes=-10
        )

class IgnoredTests(unittest.TestCase):
    # ==================== self.large_cluster.execute() Tests ====================

    @patch('clusterloader2.large_cluster.large_cluster.run_cl2_command')
    def test_execute_clusterloader2_basic_aws_execution(self, mock_run_cl2_command):
        """Test basic AWS execution"""
        self.large_cluster.execute(
            cl2_image="k8s.io/perf-tests/clusterloader2:latest",
            cl2_config_dir="/test/config",
            cl2_report_dir="/test/report",
            cl2_config_file="config.yaml",
            kubeconfig="/test/kubeconfig",
            provider="aws",
            scrape_containerd=False
        )

        mock_run_cl2_command.assert_called_once_with(
            "/test/kubeconfig",
            "k8s.io/perf-tests/clusterloader2:latest",
            "/test/config",
            "/test/report",
            "aws",
            cl2_config_file="config.yaml",
            overrides=True,
            enable_prometheus=True,
            scrape_containerd=False
        )

    @patch('clusterloader2.large_cluster.large_cluster.run_cl2_command')
    def test_execute_clusterloader2_basic_azure_execution(self, mock_run_cl2_command):
        """Test basic Azure execution"""
        self.large_cluster.execute(
            cl2_image="k8s.io/perf-tests/clusterloader2:v1.2.3",
            cl2_config_dir="/azure/config",
            cl2_report_dir="/azure/report",
            cl2_config_file="azure-config.yaml",
            kubeconfig="/azure/kubeconfig",
            provider="azure",
            scrape_containerd=False
        )

        mock_run_cl2_command.assert_called_once_with(
            "/azure/kubeconfig",
            "k8s.io/perf-tests/clusterloader2:v1.2.3",
            "/azure/config",
            "/azure/report",
            "azure",
            cl2_config_file="azure-config.yaml",
            overrides=True,
            enable_prometheus=True,
            scrape_containerd=False
        )

    @patch('clusterloader2.large_cluster.large_cluster.run_cl2_command')
    def test_execute_clusterloader2_with_containerd_scraping(self, mock_run_cl2_command):
        """Test execution with containerd scraping"""
        self.large_cluster.execute(
            cl2_image="custom/cl2:latest",
            cl2_config_dir="/custom/config",
            cl2_report_dir="/custom/report",
            cl2_config_file="custom-config.yaml",
            kubeconfig="/custom/kubeconfig",
            provider="aws",
            scrape_containerd=True
        )

        mock_run_cl2_command.assert_called_once_with(
            "/custom/kubeconfig",
            "custom/cl2:latest",
            "/custom/config",
            "/custom/report",
            "aws",
            cl2_config_file="custom-config.yaml",
            overrides=True,
            enable_prometheus=True,
            scrape_containerd=True
        )

    @patch('clusterloader2.large_cluster.large_cluster.run_cl2_command')
    def test_execute_clusterloader2_custom_image(self, mock_run_cl2_command):
        """Test execution with custom image"""
        self.large_cluster.execute(
            cl2_image="private-registry/cl2:dev",
            cl2_config_dir="/dev/config",
            cl2_report_dir="/dev/report",
            cl2_config_file="dev-config.yaml",
            kubeconfig="/dev/kubeconfig",
            provider="azure",
            scrape_containerd=False
        )

        mock_run_cl2_command.assert_called_once_with(
            "/dev/kubeconfig",
            "private-registry/cl2:dev",
            "/dev/config",
            "/dev/report",
            "azure",
            cl2_config_file="dev-config.yaml",
            overrides=True,
            enable_prometheus=True,
            scrape_containerd=False
        )

    # ==================== self.large_cluster.collect() Tests ====================

    def create_mock_junit_xml(self, temp_dir, failures=0):
        """Helper to create mock junit.xml file"""
        junit_path = os.path.join(temp_dir, "junit.xml")
        with open(junit_path, 'w', encoding='utf-8') as f:
            f.write(f"""<?xml version="1.0"?>
<testsuites>
    <testsuite name="test" failures="{failures}">
        <testcase name="case1" time="1.0"></testcase>
    </testsuite>
</testsuites>""")
        return junit_path

    def create_mock_measurement_file(self, temp_dir, filename, has_data_items=True, empty_items=False):
        """Helper to create mock measurement files"""
        file_path = os.path.join(temp_dir, filename)
        if has_data_items:
            if empty_items:
                data = {"dataItems": []}
            else:
                data = {"dataItems": [{"value": 123, "timestamp": "2025-01-01T00:00:00Z"}]}
        else:
            data = {"value": 456, "timestamp": "2025-01-01T00:00:00Z"}

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return file_path

    @patch('clusterloader2.large_cluster.large_cluster.parse_xml_to_json')
    @patch('clusterloader2.large_cluster.large_cluster.get_measurement')
    def test_collect_clusterloader2_successful_test(self, mock_get_measurement, mock_parse_xml):
        """Test successful test scenario"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock parse_xml_to_json
            mock_parse_xml.return_value = json.dumps({
                "testsuites": [{"failures": 0}]
            })

            # Create measurement file
            self.create_mock_measurement_file(temp_dir, "measurement1.json")
            mock_get_measurement.return_value = ("test_measurement", "test_group")

            result_file = os.path.join(temp_dir, "result.json")

            self.large_cluster.collect(
                cl2_report_dir=temp_dir,
                result_file=result_file,
                **self.test_params
            )

            # Verify result file is created
            self.assertTrue(os.path.exists(result_file))

            # Verify content
            with open(result_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.assertIn('"status": "success"', content)
                self.assertIn('"test_measurement"', content)

    @patch('clusterloader2.large_cluster.large_cluster.parse_xml_to_json')
    @patch('clusterloader2.large_cluster.large_cluster.get_measurement')
    def test_collect_clusterloader2_failed_test(self, mock_get_measurement, mock_parse_xml):
        """Test failed test scenario"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock parse_xml_to_json with failures
            mock_parse_xml.return_value = json.dumps({
                "testsuites": [{"failures": 2}]
            })

            # Create measurement file
            self.create_mock_measurement_file(temp_dir, "measurement1.json")
            mock_get_measurement.return_value = ("test_measurement", "test_group")

            result_file = os.path.join(temp_dir, "result.json")

            self.large_cluster.collect(
                cl2_report_dir=temp_dir,
                result_file=result_file,
                **self.test_params
            )

            # Verify result file contains failure status
            with open(result_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.assertIn('"status": "failure"', content)

    @patch('clusterloader2.large_cluster.large_cluster.parse_xml_to_json')
    @patch('clusterloader2.large_cluster.large_cluster.get_measurement')
    def test_collect_clusterloader2_no_data_items(self, mock_get_measurement, mock_parse_xml):
        """Test scenario with empty data items"""
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_parse_xml.return_value = json.dumps({
                "testsuites": [{"failures": 0}]
            })

            # Create measurement file with empty dataItems
            self.create_mock_measurement_file(temp_dir, "measurement1.json",
                                              has_data_items=True, empty_items=True)
            mock_get_measurement.return_value = ("test_measurement", "test_group")

            result_file = os.path.join(temp_dir, "result.json")

            self.large_cluster.collect(
                cl2_report_dir=temp_dir,
                result_file=result_file,
                **self.test_params
            )

            # Result file should be created but with minimal content
            self.assertTrue(os.path.exists(result_file))

    @patch('clusterloader2.large_cluster.large_cluster.parse_xml_to_json')
    @patch('clusterloader2.large_cluster.large_cluster.get_measurement')
    def test_collect_clusterloader2_multiple_measurements(self, mock_get_measurement, mock_parse_xml):
        """Test scenario with multiple measurement files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_parse_xml.return_value = json.dumps({
                "testsuites": [{"failures": 0}]
            })

            # Create multiple measurement files
            self.create_mock_measurement_file(temp_dir, "measurement1.json")
            self.create_mock_measurement_file(temp_dir, "measurement2.json")

            mock_get_measurement.side_effect = [
                ("measurement1", "group1"),
                ("measurement2", "group2")
            ]

            result_file = os.path.join(temp_dir, "result.json")

            self.large_cluster.collect(
                cl2_report_dir=temp_dir,
                result_file=result_file,
                **self.test_params
            )

            # Verify multiple entries in result file
            with open(result_file, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.strip().split('\n')
                self.assertGreaterEqual(len(lines), 2)  # At least 2 JSON objects

    def test_collect_clusterloader2_missing_junit_xml(self):
        """Test scenario with missing junit.xml file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "result.json")

            with self.assertRaises(Exception):
                self.large_cluster.collect(
                    cl2_report_dir=temp_dir,
                    result_file=result_file,
                    **self.test_params
                )

    @patch('clusterloader2.large_cluster.large_cluster.parse_xml_to_json')
    def test_collect_clusterloader2_empty_testsuites(self, mock_parse_xml):
        """Test scenario with empty testsuites array"""
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_parse_xml.return_value = json.dumps({
                "testsuites": []
            })

            result_file = os.path.join(temp_dir, "result.json")

            with self.assertRaises(Exception) as context:
                self.large_cluster.collect(
                    cl2_report_dir=temp_dir,
                    result_file=result_file,
                    **self.test_params
                )

            self.assertIn("No testsuites found", str(context.exception))

    def test_collect_clusterloader2_malformed_junit_xml(self):
        """Test handling of malformed junit.xml file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create malformed junit.xml
            junit_path = os.path.join(temp_dir, "junit.xml")
            with open(junit_path, 'w', encoding='utf-8') as f:
                f.write("<testsuites><testsuite name='test' failures='0'><testcase name='case1'></testsuite>")  # Missing closing tags

            result_file = os.path.join(temp_dir, "result.json")

            with self.assertRaises(Exception):
                self.large_cluster.collect(
                    cl2_report_dir=temp_dir,
                    result_file=result_file,
                    **self.test_params
                )

    @patch('clusterloader2.large_cluster.large_cluster.parse_xml_to_json')
    def test_collect_clusterloader2_invalid_json_structure_junit_xml(self, mock_parse_xml):
        """Test handling of junit.xml that creates invalid JSON"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Simulate parse_xml_to_json returning invalid JSON
            mock_parse_xml.return_value = '{"testsuites": invalid_json}'

            result_file = os.path.join(temp_dir, "result.json")

            with self.assertRaises(Exception):
                self.large_cluster.collect(
                    cl2_report_dir=temp_dir,
                    result_file=result_file,
                    **self.test_params
                )

    def test_collect_clusterloader2_corrupted_junit_xml(self):
        """Test handling of corrupted/truncated junit.xml file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            junit_path = os.path.join(temp_dir, "junit.xml")
            with open(junit_path, 'wb') as f:
                # Write some corrupted binary data
                f.write(b'\x00\x01\x02\x03invalid_xml_content\xff\xfe')

            result_file = os.path.join(temp_dir, "result.json")

            with self.assertRaises(Exception):
                self.large_cluster.collect(
                    cl2_report_dir=temp_dir,
                    result_file=result_file,
                    **self.test_params
                )

    def test_collect_clusterloader2_empty_junit_xml(self):
        """Test handling of empty junit.xml file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            junit_path = os.path.join(temp_dir, "junit.xml")
            with open(junit_path, 'w', encoding='utf-8') as f:
                f.write("")  # Empty file

            result_file = os.path.join(temp_dir, "result.json")

            with self.assertRaises(Exception):
                self.large_cluster.collect(
                    cl2_report_dir=temp_dir,
                    result_file=result_file,
                    **self.test_params
                )

    # ==================== self.large_cluster.main() Tests ====================

    @patch('clusterloader2.large_cluster.large_cluster.configure_clusterloader2')
    @patch('sys.argv', ['large_cluster.py', 'configure', '4', '20', '5', '10', '3', '30m',
                        'aws', 'False', 'False', '/tmp/override.yaml'])
    def test_main_configure_command(self, mock_configure):
        """Test configure command parsing"""
        self.large_cluster.main()

        mock_configure.assert_called_once_with(
            4, 20, 5, 10, 3, '30m', 'aws', False, False, '/tmp/override.yaml'
        )

    @patch('clusterloader2.large_cluster.large_cluster.validate_clusterloader2')
    @patch('sys.argv', ['large_cluster.py', 'validate', '20', '600'])
    def test_main_validate_command(self, mock_validate):
        """Test validate command parsing"""
        self.large_cluster.main()

        mock_validate.assert_called_once_with(20, 600)

    @patch('clusterloader2.large_cluster.large_cluster.execute_clusterloader2')
    @patch('sys.argv', ['large_cluster.py', 'execute', 'cl2:latest', '/config', '/report',
                        'config.yaml', '/kubeconfig', 'aws', 'False'])
    def test_main_execute_command(self, mock_execute):
        """Test execute command parsing"""
        self.large_cluster.main()

        mock_execute.assert_called_once_with(
            'cl2:latest', '/config', '/report', 'config.yaml', '/kubeconfig', 'aws', False
        )

    @patch('clusterloader2.large_cluster.large_cluster.collect_clusterloader2')
    @patch('sys.argv', ['large_cluster.py', 'collect', '4', '20', '10', '3', '/report',
                        '{"cloud":"test"}', 'run123', 'http://example.com', '/result.json'])
    def test_main_collect_command(self, mock_collect):
        """Test collect command parsing"""
        self.large_cluster.main()

        mock_collect.assert_called_once_with(
            4, 20, 10, 3, '/report', '{"cloud":"test"}', 'run123', 'http://example.com', '/result.json'
        )


if __name__ == "__main__":
    unittest.main()
