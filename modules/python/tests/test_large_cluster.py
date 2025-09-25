import json
import os
import unittest
import tempfile
import datetime
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
            "run_url": "http://example.com/run123",
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


    # ==================== self.large_cluster.execute() Tests ====================

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.execute')
    def test_execute_clusterloader2_basic_aws_execution(self, mock_base_execute):
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

        mock_base_execute.assert_called_once_with(
            cl2_image="k8s.io/perf-tests/clusterloader2:latest",
            cl2_config_dir="/test/config",
            cl2_report_dir="/test/report",
            cl2_config_file="config.yaml",
            kubeconfig="/test/kubeconfig",
            provider="aws",
            scrape_containerd=False,
            overrides=True,
            enable_prometheus=True
        )

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.execute')
    def test_execute_clusterloader2_basic_azure_execution(self, mock_base_execute):
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

        mock_base_execute.assert_called_once_with(
            cl2_image="k8s.io/perf-tests/clusterloader2:v1.2.3",
            cl2_config_dir="/azure/config",
            cl2_report_dir="/azure/report",
            cl2_config_file="azure-config.yaml",
            kubeconfig="/azure/kubeconfig",
            provider="azure",
            scrape_containerd=False,
            overrides=True,
            enable_prometheus=True
        )

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.execute')
    def test_execute_clusterloader2_with_containerd_scraping(self, mock_base_execute):
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

        mock_base_execute.assert_called_once_with(
            cl2_image="custom/cl2:latest",
            cl2_config_dir="/custom/config",
            cl2_report_dir="/custom/report",
            cl2_config_file="custom-config.yaml",
            kubeconfig="/custom/kubeconfig",
            provider="aws",
            scrape_containerd=True,
            overrides=True,
            enable_prometheus=True
        )

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.execute')
    def test_execute_clusterloader2_custom_image(self, mock_base_execute):
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

        mock_base_execute.assert_called_once_with(
            cl2_image="private-registry/cl2:dev",
            cl2_config_dir="/dev/config",
            cl2_report_dir="/dev/report",
            cl2_config_file="dev-config.yaml",
            kubeconfig="/dev/kubeconfig",
            provider="azure",
            scrape_containerd=False,
            overrides=True,
            enable_prometheus=True
        )
        
    # ==================== self.large_cluster.collect() Tests ====================

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

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_basic_functionality(self, mock_process_reports):
        """Test basic collect functionality"""
        mock_process_reports.return_value = '{"test": "result"}\n'
        
        result = self.large_cluster.collect(
            cpu_per_node=4,
            node_count=20,
            pods_per_node=10,
            repeats=3,
            cl2_report_dir="/test/reports",
            cloud_info='{"provider": "aws"}',
            run_id="test123",
            run_url="http://test.com",
            test_status="success"
        )

        # Verify process_cl2_reports was called with correct template
        self.assertEqual(result, '{"test": "result"}\n')
        mock_process_reports.assert_called_once()
        
        # Verify template structure
        call_args = mock_process_reports.call_args
        template = call_args[0][1]  # Second argument is the template
        
        self.assertEqual(template["cpu_per_node"], 4)
        self.assertEqual(template["node_count"], 20)
        self.assertEqual(template["pod_count"], 200)  # 20 * 10
        self.assertEqual(template["churn_rate"], 3)
        self.assertEqual(template["status"], "success")
        self.assertEqual(template["cloud_info"], '{"provider": "aws"}')
        self.assertEqual(template["run_id"], "test123")
        self.assertEqual(template["run_url"], "http://test.com")
        self.assertIsNone(template["group"])
        self.assertIsNone(template["measurement"])
        self.assertIsNone(template["result"])

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_pod_count_calculation(self, mock_process_reports):
        """Test pod count calculation in collect method"""
        mock_process_reports.return_value = ""
        
        # Test various combinations
        test_cases = [
            (10, 5, 50),    # 10 nodes * 5 pods = 50
            (100, 10, 1000), # 100 nodes * 10 pods = 1000
            (1000, 20, 20000), # 1000 nodes * 20 pods = 20000
        ]
        
        for node_count, pods_per_node, expected_pod_count in test_cases:
            with self.subTest(nodes=node_count, pods=pods_per_node):
                self.large_cluster.collect(
                    cpu_per_node=4,
                    node_count=node_count,
                    pods_per_node=pods_per_node,
                    repeats=1,
                    cl2_report_dir="/test",
                    cloud_info="{}",
                    run_id="test",
                    run_url="test",
                    test_status="success"
                )
                
                # Get the template from the last call
                template = mock_process_reports.call_args[0][1]
                self.assertEqual(template["pod_count"], expected_pod_count)

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_different_test_statuses(self, mock_process_reports):
        """Test collect with different test statuses"""
        mock_process_reports.return_value = ""
        
        test_statuses = ["success", "failure", "error", "timeout"]
        
        for status in test_statuses:
            with self.subTest(status=status):
                self.large_cluster.collect(
                    cpu_per_node=2,
                    node_count=10,
                    pods_per_node=5,
                    repeats=2,
                    cl2_report_dir="/test",
                    cloud_info="{}",
                    run_id="test",
                    run_url="test",
                    test_status=status
                )
                
                template = mock_process_reports.call_args[0][1]
                self.assertEqual(template["status"], status)

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_timestamp_format(self, mock_process_reports):
        """Test that timestamp is generated in correct format"""
        mock_process_reports.return_value = ""
        
        with patch('clusterloader2.large_cluster.large_cluster.datetime') as mock_datetime:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "2025-01-15T10:30:45Z"
            mock_datetime.now.return_value = mock_now
            mock_datetime.timezone = datetime.timezone
            
            self.large_cluster.collect(
                cpu_per_node=4,
                node_count=20,
                pods_per_node=10,
                repeats=1,
                cl2_report_dir="/test",
                cloud_info="{}",
                run_id="test",
                run_url="test",
                test_status="success"
            )
            mock_datetime.now.assert_called_once_with(datetime.timezone.utc)
            mock_now.strftime.assert_called_once_with('%Y-%m-%dT%H:%M:%SZ')
            
            template = mock_process_reports.call_args[0][1]
            self.assertEqual(template["timestamp"], "2025-01-15T10:30:45Z")

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_cloud_info_handling(self, mock_process_reports):
        """Test different cloud info formats"""
        mock_process_reports.return_value = ""
        
        cloud_info_tests = [
            '{"provider": "aws", "region": "us-east-1"}',
            '{"provider": "azure", "location": "eastus2"}',
            '{}',  # Empty JSON
            'simple_string',  # Non-JSON string
        ]
        
        for cloud_info in cloud_info_tests:
            with self.subTest(cloud_info=cloud_info):
                self.large_cluster.collect(
                    cpu_per_node=4,
                    node_count=10,
                    pods_per_node=5,
                    repeats=1,
                    cl2_report_dir="/test",
                    cloud_info=cloud_info,
                    run_id="test",
                    run_url="test",
                    test_status="success"
                )
                
                template = mock_process_reports.call_args[0][1]
                self.assertEqual(template["cloud_info"], cloud_info)

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_kwargs_handling(self, mock_process_reports):
        """Test that extra kwargs are properly ignored"""
        mock_process_reports.return_value = "result"
        
        result = self.large_cluster.collect(
            cpu_per_node=4,
            node_count=10,
            pods_per_node=5,
            repeats=1,
            cl2_report_dir="/test",
            cloud_info="{}",
            run_id="test",
            run_url="test",
            test_status="success",
            # Extra parameters that should be ignored
            extra_param1="ignored",
            extra_param2=123,
            result_file="/ignored/path"
        )
        
        self.assertEqual(result, "result")
        mock_process_reports.assert_called_once()

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_large_scale_values(self, mock_process_reports):
        """Test collect with large scale values"""
        mock_process_reports.return_value = "large_scale_result"
        
        result = self.large_cluster.collect(
            cpu_per_node=64,
            node_count=5000,
            pods_per_node=50,
            repeats=10,
            cl2_report_dir="/large/test",
            cloud_info='{"type": "large_scale_test"}',
            run_id="large_test_001",
            run_url="http://large.test.com",
            test_status="success"
        )
        
        self.assertEqual(result, "large_scale_result")
        
        template = mock_process_reports.call_args[0][1]
        self.assertEqual(template["cpu_per_node"], 64)
        self.assertEqual(template["node_count"], 5000)
        self.assertEqual(template["pod_count"], 250000)  # 5000 * 50
        self.assertEqual(template["churn_rate"], 10)

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_zero_values(self, mock_process_reports):
        """Test collect with zero/minimal values"""
        mock_process_reports.return_value = "minimal_result"
        
        result = self.large_cluster.collect(
            cpu_per_node=1,
            node_count=1,
            pods_per_node=1,
            repeats=0,
            cl2_report_dir="/minimal",
            cloud_info="{}",
            run_id="min_test",
            run_url="http://min.test",
            test_status="success"
        )
        
        self.assertEqual(result, "minimal_result")
        
        template = mock_process_reports.call_args[0][1]
        self.assertEqual(template["cpu_per_node"], 1)
        self.assertEqual(template["node_count"], 1)
        self.assertEqual(template["pod_count"], 1)  # 1 * 1
        self.assertEqual(template["churn_rate"], 0)

    @patch('clusterloader2.large_cluster.base.ClusterLoader2Base.process_cl2_reports')
    def test_collect_special_characters_in_params(self, mock_process_reports):
        """Test collect with special characters in string parameters"""
        mock_process_reports.return_value = "special_chars_result"
        
        result = self.large_cluster.collect(
            cpu_per_node=4,
            node_count=10,
            pods_per_node=5,
            repeats=1,
            cl2_report_dir="/path/with spaces/and-dashes",
            cloud_info='{"region": "us-east-1", "special": "value with spaces & symbols!"}',
            run_id="test_with_underscores_and_numbers_123",
            run_url="https://test.example.com/path?param=value&other=123",
            test_status="success"
        )
        
        self.assertEqual(result, "special_chars_result")
        mock_process_reports.assert_called_once()

    def test_collect_return_type(self):
        """Test that collect returns a string"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.large_cluster.collect(
                cpu_per_node=4,
                node_count=10,
                pods_per_node=5,
                repeats=1,
                cl2_report_dir=temp_dir,
                cloud_info="{}",
                run_id="test",
                run_url="test",
                test_status="success"
            )
            
            self.assertIsInstance(result, str)

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
