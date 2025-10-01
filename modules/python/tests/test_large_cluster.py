import json
import os
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from clusterloader2.large_cluster.large_cluster import (
    calculate_config,
    configure_clusterloader2,
    validate_clusterloader2,
    execute_clusterloader2,
    collect_clusterloader2,
    main,
    DEFAULT_NODES_PER_NAMESPACE,
    CPU_CAPACITY,
)


class TestLargeCluster(unittest.TestCase):
    """Comprehensive test class for all large_cluster.py functions"""

    def setUp(self):
        """Set up test fixtures for each test"""
        #pylint: disable=consider-using-with
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, mode='w+', encoding='utf-8')
        self.temp_path = self.temp_file.name
        self.temp_file.close()

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
        expected_cpu = (2 * 1000 * CPU_CAPACITY["aws"]) // 10
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_medium_aws_cluster(self):
        """Test AWS medium cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=4, node_count=50, provider="aws", pods_per_node=20
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 50)
        expected_cpu = (4 * 1000 * CPU_CAPACITY["aws"]) // 20
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_large_aws_cluster(self):
        """Test AWS large cluster configuration with namespace limit"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=8, node_count=150, provider="aws", pods_per_node=30
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, DEFAULT_NODES_PER_NAMESPACE)  # Should be capped at 100
        expected_cpu = (8 * 1000 * CPU_CAPACITY["aws"]) // 30
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_small_azure_cluster(self):
        """Test Azure small cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=2, node_count=10, provider="azure", pods_per_node=10
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 10)
        expected_cpu = (2 * 1000 * CPU_CAPACITY["azure"]) // 10
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_medium_azure_cluster(self):
        """Test Azure medium cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=4, node_count=50, provider="azure", pods_per_node=20
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 50)
        expected_cpu = (4 * 1000 * CPU_CAPACITY["azure"]) // 20
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_large_azure_cluster(self):
        """Test Azure large cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=8, node_count=150, provider="azure", pods_per_node=30
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, DEFAULT_NODES_PER_NAMESPACE)
        expected_cpu = (8 * 1000 * CPU_CAPACITY["azure"]) // 30
        self.assertEqual(cpu_request, int(expected_cpu))

    def test_calculate_config_small_aks_cluster(self):
        """Test AKS small cluster configuration"""
        throughput, nodes_per_namespace, cpu_request = calculate_config(
            cpu_per_node=2, node_count=10, provider="aks", pods_per_node=10
        )
        self.assertEqual(throughput, 100)
        self.assertEqual(nodes_per_namespace, 10)
        expected_cpu = (2 * 1000 * CPU_CAPACITY["aks"]) // 10
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
        self.assertEqual(nodes_per_namespace, DEFAULT_NODES_PER_NAMESPACE)
        expected_cpu = (16 * 1000 * CPU_CAPACITY["azure"]) // 50
        self.assertEqual(cpu_request, int(expected_cpu))

    # ==================== configure_clusterloader2() Tests ====================

    def test_configure_clusterloader2_basic_aws_config(self):
        """Test basic AWS configuration"""
        configure_clusterloader2(
            cpu_per_node=4, node_count=20, node_per_step=5,
            pods_per_node=10, repeats=3, operation_timeout="30m",
            provider="aws", cilium_enabled=False,
            scrape_containerd=False, override_file=self.temp_path
        )

        with open(self.temp_path, "r", encoding='utf-8') as f:
            content = f.read()

        self.assertIn("CL2_NODES: 20", content)
        self.assertIn("CL2_NODES_PER_STEP: 5", content)
        self.assertIn("CL2_STEPS: 4", content)  # 20 // 5
        self.assertIn("CL2_PODS_PER_NODE: 10", content)
        self.assertIn("CL2_REPEATS: 3", content)
        self.assertIn("CL2_OPERATION_TIMEOUT: 30m", content)
        self.assertNotIn("CL2_CILIUM_METRICS_ENABLED", content)
        self.assertNotIn("CL2_SCRAPE_CONTAINERD", content)

    def test_configure_clusterloader2_basic_azure_config(self):
        """Test basic Azure configuration"""
        configure_clusterloader2(
            cpu_per_node=4, node_count=20, node_per_step=5,
            pods_per_node=10, repeats=3, operation_timeout="30m",
            provider="azure", cilium_enabled=False,
            scrape_containerd=False, override_file=self.temp_path
        )

        with open(self.temp_path, "r", encoding='utf-8') as f:
            content = f.read()

        self.assertIn("CL2_NODES: 20", content)
        self.assertIn("CL2_LOAD_TEST_THROUGHPUT: 100", content)

    def test_configure_clusterloader2_cilium_enabled(self):
        """Test configuration with Cilium enabled"""
        configure_clusterloader2(
            cpu_per_node=4, node_count=50, node_per_step=10,
            pods_per_node=15, repeats=5, operation_timeout="45m",
            provider="azure", cilium_enabled=True,
            scrape_containerd=False, override_file=self.temp_path
        )

        with open(self.temp_path, "r", encoding='utf-8') as f:
            content = f.read()

        self.assertIn("CL2_CILIUM_METRICS_ENABLED: true", content)
        self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true", content)
        self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true", content)
        self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL: 30s", content)

    def test_configure_clusterloader2_containerd_scraping(self):
        """Test configuration with containerd scraping enabled"""
        configure_clusterloader2(
            cpu_per_node=8, node_count=100, node_per_step=20,
            pods_per_node=20, repeats=2, operation_timeout="60m",
            provider="aws", cilium_enabled=False,
            scrape_containerd=True, override_file=self.temp_path
        )

        with open(self.temp_path, "r", encoding='utf-8') as f:
            content = f.read()

        self.assertIn("CL2_SCRAPE_CONTAINERD: true", content)
        self.assertIn("CONTAINERD_SCRAPE_INTERVAL: 5m", content)

    def test_configure_clusterloader2_all_features_enabled(self):
        """Test configuration with all features enabled"""
        configure_clusterloader2(
            cpu_per_node=8, node_count=100, node_per_step=25,
            pods_per_node=25, repeats=4, operation_timeout="90m",
            provider="azure", cilium_enabled=True,
            scrape_containerd=True, override_file=self.temp_path
        )

        with open(self.temp_path, "r", encoding='utf-8') as f:
            content = f.read()

        # Check all features are present
        self.assertIn("CL2_CILIUM_METRICS_ENABLED: true", content)
        self.assertIn("CL2_SCRAPE_CONTAINERD: true", content)
        self.assertIn("CL2_STEPS: 4", content)  # 100 // 25

    def test_configure_clusterloader2_large_scale(self):
        """Test large scale configuration"""
        configure_clusterloader2(
            cpu_per_node=16, node_count=500, node_per_step=50,
            pods_per_node=30, repeats=1, operation_timeout="120m",
            provider="aws", cilium_enabled=False,
            scrape_containerd=False, override_file=self.temp_path
        )

        with open(self.temp_path, "r", encoding='utf-8') as f:
            content = f.read()

        self.assertIn("CL2_NODES: 500", content)
        self.assertIn("CL2_STEPS: 10", content)  # 500 // 50
        self.assertIn("CL2_OPERATION_TIMEOUT: 120m", content)

    def test_configure_clusterloader2_single_step(self):
        """Test single step configuration"""
        configure_clusterloader2(
            cpu_per_node=2, node_count=10, node_per_step=10,
            pods_per_node=5, repeats=1, operation_timeout="15m",
            provider="azure", cilium_enabled=False,
            scrape_containerd=False, override_file=self.temp_path
        )

        with open(self.temp_path, "r", encoding='utf-8') as f:
            content = f.read()

        self.assertIn("CL2_STEPS: 1", content)  # 10 // 10

    # ==================== validate_clusterloader2() Tests ====================

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    @patch('clusterloader2.large_cluster.large_cluster.time.sleep')
    def test_validate_clusterloader2_immediate_success(self, mock_sleep, mock_kube_client_class):
        """Test immediate success scenario"""
        mock_kube_client = MagicMock()
        mock_kube_client.get_ready_nodes.return_value = ['node1', 'node2', 'node3', 'node4', 'node5']
        mock_kube_client_class.return_value = mock_kube_client

        # Should not raise exception
        validate_clusterloader2(node_count=5, operation_timeout_in_minutes=10)

        # Should call get_ready_nodes at least once
        mock_kube_client.get_ready_nodes.assert_called()
        # Should not sleep since nodes are ready immediately
        mock_sleep.assert_not_called()

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    @patch('clusterloader2.large_cluster.large_cluster.time.sleep')
    @patch('clusterloader2.large_cluster.large_cluster.time.time')
    def test_validate_clusterloader2_delayed_success(self, mock_time, mock_sleep, mock_kube_client_class):
        """Test delayed success scenario"""
        mock_kube_client = MagicMock()
        # Simulate gradual node readiness: 5 -> 8 -> 10
        mock_kube_client.get_ready_nodes.side_effect = [
            ['node1', 'node2', 'node3', 'node4', 'node5'],  # First call: 5 nodes
            ['node1', 'node2', 'node3', 'node4', 'node5', 'node6', 'node7', 'node8'],  # Second call: 8 nodes
            ['node1', 'node2', 'node3', 'node4', 'node5', 'node6', 'node7', 'node8', 'node9', 'node10']  # Third call: 10 nodes
        ]
        mock_kube_client_class.return_value = mock_kube_client

        # Mock time progression
        start_time = 1000
        mock_time.side_effect = [start_time, start_time + 60, start_time + 120, start_time + 180]  # Time progression

        validate_clusterloader2(node_count=10, operation_timeout_in_minutes=5)

        # Should call get_ready_nodes multiple times
        self.assertEqual(mock_kube_client.get_ready_nodes.call_count, 3)
        mock_sleep.assert_called()

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    @patch('clusterloader2.large_cluster.large_cluster.time.sleep')
    @patch('clusterloader2.large_cluster.large_cluster.time.time')
    def test_validate_clusterloader2_timeout_failure(self, mock_time, mock_sleep, mock_kube_client_class):
        """Test timeout failure scenario"""
        mock_kube_client = MagicMock()
        # Always return 15 nodes, never reaches 20
        mock_kube_client.get_ready_nodes.return_value = [f"node{i}" for i in range(15)]
        mock_kube_client_class.return_value = mock_kube_client

        # Mock timeout scenario
        start_time = 1000
        timeout_time = start_time + (2 * 60)  # 2 minutes timeout
        mock_time.side_effect = [start_time, timeout_time + 1]  # Exceed timeout

        with self.assertRaises(Exception) as context:
            validate_clusterloader2(node_count=20, operation_timeout_in_minutes=2)

            self.assertIn("Only 15 nodes are ready, expected 20 nodes!", str(context.exception))
        mock_sleep.assert_not_called()

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    @patch('clusterloader2.large_cluster.large_cluster.time.sleep')
    @patch('clusterloader2.large_cluster.large_cluster.time.time')
    def test_validate_clusterloader2_too_many_ready_nodes_failure(self, mock_time, mock_sleep, mock_kube_client_class):
        """Test there are more ready node than required"""
        mock_kube_client = MagicMock()
        # Always returns 5 ready nodes
        mock_kube_client.get_ready_nodes.return_value = [f"node{i}" for i in range(5)]
        mock_kube_client_class.return_value = mock_kube_client

        # Mock timeout scenario
        start_time = 1000
        mock_time.side_effect = start_time

        with self.assertRaises(Exception) as context:
            validate_clusterloader2(
                node_count=2,
                operation_timeout_in_minutes=2
            )

            self.assertIn(
                "Only 5 nodes are ready, expected 2 nodes!",
                str(context.exception)
            )

        mock_sleep.assert_not_called()

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_clusterloader2_single_node(self, mock_kube_client_class):
        """Test single node scenario"""
        mock_kube_client = MagicMock()
        mock_kube_client.get_ready_nodes.return_value = ['node1']
        mock_kube_client_class.return_value = mock_kube_client

        validate_clusterloader2(node_count=1, operation_timeout_in_minutes=5)

        mock_kube_client.get_ready_nodes.assert_called()

    @patch('clusterloader2.large_cluster.large_cluster.KubernetesClient')
    def test_validate_clusterloader2_zero_nodes(self, mock_kube_client_class):
        """Test zero nodes scenario"""
        mock_kube_client = MagicMock()
        mock_kube_client.get_ready_nodes.return_value = []
        mock_kube_client_class.return_value = mock_kube_client

        validate_clusterloader2(node_count=0, operation_timeout_in_minutes=5)

        mock_kube_client.get_ready_nodes.assert_called()

    # ==================== execute_clusterloader2() Tests ====================

    @patch('clusterloader2.large_cluster.large_cluster.run_cl2_command')
    def test_execute_clusterloader2_basic_aws_execution(self, mock_run_cl2_command):
        """Test basic AWS execution"""
        execute_clusterloader2(
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
        execute_clusterloader2(
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
        execute_clusterloader2(
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
        execute_clusterloader2(
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

    # ==================== collect_clusterloader2() Tests ====================

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

            collect_clusterloader2(
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

            collect_clusterloader2(
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

            collect_clusterloader2(
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

            collect_clusterloader2(
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
                collect_clusterloader2(
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
                collect_clusterloader2(
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
                collect_clusterloader2(
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
                collect_clusterloader2(
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
                collect_clusterloader2(
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
                collect_clusterloader2(
                    cl2_report_dir=temp_dir,
                    result_file=result_file,
                    **self.test_params
                )

    # ==================== main() Tests ====================

    @patch('clusterloader2.large_cluster.large_cluster.configure_clusterloader2')
    @patch('sys.argv', ['large_cluster.py', 'configure',
                        '--cpu_per_node', '4', '--node_count', '20', '--node_per_step', '5',
                        '--pods_per_node', '10', '--repeats', '3', '--operation_timeout', '30m',
                        '--provider', 'aws', '--cilium_enabled', 'False', '--scrape_containerd', 'False',
                        '--cl2_override_file', '/tmp/override.yaml'])
    def test_main_configure_command(self, mock_configure):
        """Test configure command parsing"""
        main()

        mock_configure.assert_called_once_with(
            4, 20, 5, 10, 3, '30m', 'aws', False, False, '/tmp/override.yaml'
        )

    @patch('clusterloader2.large_cluster.large_cluster.validate_clusterloader2')
    @patch('sys.argv', ['large_cluster.py', 'validate', '--node_count', '20', '--operation_timeout', '600'])
    def test_main_validate_command(self, mock_validate):
        """Test validate command parsing"""
        main()

        mock_validate.assert_called_once_with(20, 600)

    @patch('clusterloader2.large_cluster.large_cluster.execute_clusterloader2')
    @patch('sys.argv', ['large_cluster.py', 'execute',
                        '--cl2_image', 'cl2:latest', '--cl2_config_dir', '/config',
                        '--cl2_report_dir', '/report', '--cl2_config_file', 'config.yaml',
                        '--kubeconfig', '/kubeconfig', '--provider', 'aws', '--scrape_containerd', 'False'])
    def test_main_execute_command(self, mock_execute):
        """Test execute command parsing"""
        main()

        mock_execute.assert_called_once_with(
            'cl2:latest', '/config', '/report', 'config.yaml', '/kubeconfig', 'aws', False
        )

    @patch('clusterloader2.large_cluster.large_cluster.collect_clusterloader2')
    @patch('sys.argv', ['large_cluster.py', 'collect',
                        '--cpu_per_node', '4', '--node_count', '20', '--pods_per_node', '10',
                        '--repeats', '3', '--cl2_report_dir', '/report', '--cloud_info', '{"cloud":"test"}',
                        '--run_id', 'run123', '--run_url', 'http://example.com', '--result_file', '/result.json'])
    def test_main_collect_command(self, mock_collect):
        """Test collect command parsing"""
        main()

        mock_collect.assert_called_once_with(
            4, 20, 10, 3, '/report', '{"cloud":"test"}', 'run123', 'http://example.com', '/result.json'
        )


if __name__ == "__main__":
    unittest.main()
