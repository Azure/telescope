"""
Unit tests for GPU module functionality
"""

import unittest
import os
import tempfile
from unittest.mock import patch, MagicMock, mock_open, call
import unittest.mock
import requests

# Mock kubernetes config before importing
with patch("kubernetes.config.load_kube_config"):
    from gpu.main import configure, execute, collect, main
    from gpu.pkg.gpu import install_gpu_operator
    from gpu.pkg.net import install_network_operator, _verify_rdma
    from gpu.pkg.efa import install_efa_operator
    from gpu.pkg.mpi import install_mpi_operator
    from gpu.pkg.utils import install_operator, create_topology_configmap, parse_nccl_test_results
from utils.logger_config import setup_logging, get_logger

# Create aliases for test compatibility
_parse_nccl_test_results = parse_nccl_test_results
_create_topology_configmap = create_topology_configmap

# Placeholder for unimplemented function (test is skipped)
def _get_gpu_node_count_and_allocatable():
    """Placeholder for unimplemented function."""
    raise NotImplementedError("Function not yet implemented")

# Configure logging
setup_logging()
logger = get_logger(__name__)


class TestGPU(unittest.TestCase):
    """Unit tests for the GPU module covering operator installation,
    NCCL testing, and result parsing.
    """

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.mock_kubernetes_client = MagicMock()
        self.test_chart_version = "v1.0.0"
        self.test_operator_name = "test-operator"
        self.test_config_dir = "/tmp/test-config"
        self.test_result_dir = "/tmp/test-results"
        self.test_vm_size = "Standard_ND96asr_v4"
        self.test_cloud_info = "azure"
        self.test_run_url = "https://test-url.com"
        self.test_run_id = "123456789"

    @patch("os.path.exists")
    @patch("subprocess.run")
    def test_install_operator_success_with_values_file(
        self, mock_subprocess, mock_exists
    ):
        """Test successful operator installation via Helm when values file exists."""
        mock_subprocess.return_value = MagicMock(returncode=0)
        mock_exists.return_value = True

        install_operator(
            chart_version=self.test_chart_version,
            operator_name=self.test_operator_name,
            config_dir=self.test_config_dir,
            namespace=self.test_operator_name,
            extra_args=["--set", "key=value"],
        )

        # Verify subprocess calls
        expected_calls = [
            call(
                ["helm", "repo", "add", "nvidia", "https://helm.ngc.nvidia.com/nvidia"],
                check=True,
            ),
            call(["helm", "repo", "update"], check=True),
            call(
                [
                    "helm",
                    "upgrade",
                    self.test_operator_name,
                    f"nvidia/{self.test_operator_name}",
                    "--create-namespace",
                    "--namespace",
                    self.test_operator_name,
                    "--version",
                    self.test_chart_version,
                    "--install",
                    "--values",
                    f"{self.test_config_dir}/{self.test_operator_name}/values.yaml",
                    "--set",
                    "key=value",
                ],
                check=True,
            ),
        ]
        mock_subprocess.assert_has_calls(expected_calls)
        mock_exists.assert_called_once_with(
            f"{self.test_config_dir}/{self.test_operator_name}/values.yaml"
        )

    @patch("os.path.exists")
    @patch("subprocess.run")
    def test_install_operator_success_without_values_file(
        self, mock_subprocess, mock_exists
    ):
        """Test successful operator installation via Helm when values file doesn't exist."""
        mock_subprocess.return_value = MagicMock(returncode=0)
        mock_exists.return_value = False

        install_operator(
            chart_version=self.test_chart_version,
            operator_name=self.test_operator_name,
            config_dir=self.test_config_dir,
            namespace=self.test_operator_name,
        )

        # Verify subprocess calls
        expected_calls = [
            call(
                ["helm", "repo", "add", "nvidia", "https://helm.ngc.nvidia.com/nvidia"],
                check=True,
            ),
            call(["helm", "repo", "update"], check=True),
            call(
                [
                    "helm",
                    "upgrade",
                    self.test_operator_name,
                    f"nvidia/{self.test_operator_name}",
                    "--create-namespace",
                    "--namespace",
                    self.test_operator_name,
                    "--version",
                    self.test_chart_version,
                    "--install",
                ],
                check=True,
            ),
        ]
        mock_subprocess.assert_has_calls(expected_calls)
        mock_exists.assert_called_once_with(
            f"{self.test_config_dir}/{self.test_operator_name}/values.yaml"
        )

    @patch("gpu.pkg.net.KUBERNETES_CLIENT")
    def test_verify_rdma_success(self, mock_k8s_client):
        """Test RDMA verification with mock pods."""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "mofed-pod-test"
        mock_k8s_client.get_ready_pods_by_namespace.return_value = [mock_pod]

        _verify_rdma()

        mock_k8s_client.get_ready_pods_by_namespace.assert_called_once_with(
            label_selector="nvidia.com/ofed-driver=", namespace="network-operator"
        )
        mock_k8s_client.run_pod_exec_command.assert_called_once_with(
            pod_name="mofed-pod-test",
            namespace="network-operator",
            command="ibdev2netdev",
        )

    @patch("gpu.pkg.net.execute_with_retries")
    @patch("gpu.pkg.net.KUBERNETES_CLIENT")
    @patch("gpu.pkg.net.install_operator")
    def test_install_network_operator_success(
        self, mock_install, mock_k8s_client, _mock_execute_with_retries
    ):
        """Test successful network operator installation."""
        _mock_execute_with_retries.return_value = None
        mock_k8s_client.apply_manifest_from_file.return_value = None

        install_network_operator(
            chart_version=self.test_chart_version, config_dir=self.test_config_dir
        )

        mock_install.assert_called_once_with(
            chart_version=self.test_chart_version,
            operator_name="network-operator",
            config_dir=self.test_config_dir,
            namespace="network-operator",
        )

        # Verify execute_with_retries is called 3 times for the wait operations
        self.assertEqual(_mock_execute_with_retries.call_count, 3)

    @patch("gpu.pkg.gpu.execute_with_retries")
    @patch("gpu.pkg.gpu.KUBERNETES_CLIENT")
    @patch("gpu.pkg.gpu.install_operator")
    def test_install_gpu_operator_success(
        self, mock_install, _mock_k8s_client, _mock_execute_with_retries
    ):
        """Test successful GPU operator installation."""
        _mock_execute_with_retries.return_value = None

        install_gpu_operator(
            chart_version=self.test_chart_version,
            config_dir=self.test_config_dir,
            install_driver=True,
            enable_nfd=True,
        )

        mock_install.assert_called_once_with(
            chart_version=self.test_chart_version,
            operator_name="gpu-operator",
            config_dir=self.test_config_dir,
            namespace="gpu-operator",
            extra_args=[
                "--set",
                "nfd.enabled=true",
            ],
        )

        # Verify execute_with_retries is called 4 times for the wait operations
        self.assertEqual(_mock_execute_with_retries.call_count, 4)

    @patch("gpu.pkg.mpi.execute_with_retries")
    @patch("gpu.pkg.mpi.KUBERNETES_CLIENT")
    def test_install_mpi_operator_success(
        self, mock_k8s_client, _mock_execute_with_retries
    ):
        """Test successful MPI operator installation."""
        mock_k8s_client.apply_manifest_from_url.return_value = None
        _mock_execute_with_retries.return_value = None

        install_mpi_operator(chart_version=self.test_chart_version)

        expected_url = f"https://raw.githubusercontent.com/kubeflow/mpi-operator/{self.test_chart_version}/deploy/v2beta1/mpi-operator.yaml"
        mock_k8s_client.apply_manifest_from_url.assert_called_once_with(expected_url)
        # Verify execute_with_retries is called once for the wait operation
        _mock_execute_with_retries.assert_called_once()

    @patch("gpu.pkg.efa.execute_with_retries")
    @patch("gpu.pkg.efa.KUBERNETES_CLIENT")
    @patch("gpu.pkg.efa.install_operator")
    def test_install_efa_operator_success(
        self, mock_install, _mock_k8s_client, _mock_execute_with_retries
    ):
        """Test successful EFA device plugin installation."""
        _mock_execute_with_retries.return_value = None

        install_efa_operator(
            config_dir=self.test_config_dir, version=self.test_chart_version
        )

        mock_install.assert_called_once_with(
            chart_version=self.test_chart_version,
            operator_name="aws-efa-k8s-device-plugin",
            config_dir=self.test_config_dir,
            namespace="kube-system",
            repo_name="aws",
            repo_url="https://aws.github.io/eks-charts",
        )

        # Verify execute_with_retries is called once for the wait operation
        _mock_execute_with_retries.assert_called_once()

    @patch("gpu.main.install_efa_operator")
    @patch("gpu.main.install_mpi_operator")
    @patch("gpu.main.install_gpu_operator")
    @patch("gpu.main.install_network_operator")
    def test_configure_all_operators(self, mock_network, mock_gpu, mock_mpi, mock_efa):
        """Test configure function that installs all operators when all versions are provided."""
        configure(
            efa_operator_version=self.test_chart_version,
            network_operator_version=self.test_chart_version,
            gpu_operator_version=self.test_chart_version,
            gpu_install_driver=True,
            gpu_enable_nfd=False,
            mpi_operator_version=self.test_chart_version,
            config_dir=self.test_config_dir,
        )

        mock_efa.assert_called_once_with(
            config_dir=self.test_config_dir,
            version=self.test_chart_version,
        )
        mock_network.assert_called_once_with(
            chart_version=self.test_chart_version, config_dir=self.test_config_dir
        )
        mock_gpu.assert_called_once_with(
            chart_version=self.test_chart_version,
            config_dir=self.test_config_dir,
            install_driver=True,
            enable_nfd=False,
        )
        mock_mpi.assert_called_once_with(chart_version=self.test_chart_version)

    @patch("gpu.main.install_efa_operator")
    @patch("gpu.main.install_mpi_operator")
    @patch("gpu.main.install_gpu_operator")
    @patch("gpu.main.install_network_operator")
    def test_configure_only_gpu_operator(
        self, mock_network, mock_gpu, mock_mpi, mock_efa
    ):
        """Test configure function that installs only GPU operator when only its version is provided."""
        configure(
            efa_operator_version="",
            network_operator_version="",
            gpu_operator_version=self.test_chart_version,
            gpu_install_driver=True,
            gpu_enable_nfd=False,
            mpi_operator_version="",
            config_dir=self.test_config_dir,
        )

        mock_efa.assert_not_called()
        mock_network.assert_not_called()
        mock_gpu.assert_called_once_with(
            chart_version=self.test_chart_version,
            config_dir=self.test_config_dir,
            install_driver=True,
            enable_nfd=False,
        )
        mock_mpi.assert_not_called()

    @patch("gpu.main.install_efa_operator")
    @patch("gpu.main.install_mpi_operator")
    @patch("gpu.main.install_gpu_operator")
    @patch("gpu.main.install_network_operator")
    def test_configure_both_network_and_mpi_operator(
        self, mock_network, mock_gpu, mock_mpi, mock_efa
    ):
        """Test configure function that installs both Network and MPI operators when their versions are provided."""
        configure(
            efa_operator_version="",
            network_operator_version=self.test_chart_version,
            gpu_operator_version="",
            gpu_install_driver=True,
            gpu_enable_nfd=False,
            mpi_operator_version=self.test_chart_version,
            config_dir=self.test_config_dir,
        )

        mock_efa.assert_not_called()
        mock_network.assert_called_once_with(
            chart_version=self.test_chart_version, config_dir=self.test_config_dir
        )
        mock_gpu.assert_not_called()
        mock_mpi.assert_called_once_with(chart_version=self.test_chart_version)

    @patch("gpu.main.install_efa_operator")
    @patch("gpu.main.install_mpi_operator")
    @patch("gpu.main.install_gpu_operator")
    @patch("gpu.main.install_network_operator")
    def test_configure_no_operators(self, mock_network, mock_gpu, mock_mpi, mock_efa):
        """Test configure function that installs no operators when no versions are provided."""
        configure(
            efa_operator_version="",
            network_operator_version="",
            gpu_operator_version="",
            gpu_install_driver=True,
            gpu_enable_nfd=False,
            mpi_operator_version="",
            config_dir=self.test_config_dir,
        )

        mock_efa.assert_not_called()
        mock_network.assert_not_called()
        mock_gpu.assert_not_called()
        mock_mpi.assert_not_called()

    @patch("requests.get")
    @patch("gpu.pkg.utils.KUBERNETES_CLIENT")
    def test_create_topology_configmap_success(self, mock_k8s_client, mock_requests):
        """Test successful topology ConfigMap creation."""
        mock_response = MagicMock()
        mock_response.text = "<topology>test content</topology>"
        mock_response.raise_for_status.return_value = None
        mock_requests.return_value = mock_response

        mock_api_client = MagicMock()
        mock_k8s_client.get_api_client.return_value = mock_api_client

        _create_topology_configmap(vm_size=self.test_vm_size)

        expected_url = f"https://raw.githubusercontent.com/Azure/azhpc-images/master/topology/{self.test_vm_size}-topo.xml"
        mock_requests.assert_called_once_with(expected_url, timeout=30)
        mock_api_client.create_namespaced_config_map.assert_called_once()

    @patch("requests.get")
    def test_create_topology_configmap_request_failure(self, mock_requests):
        """Test topology ConfigMap creation with request failure."""
        mock_requests.side_effect = requests.RequestException("Network error")

        with self.assertRaises(requests.RequestException):
            _create_topology_configmap(vm_size=self.test_vm_size)

    @patch("yaml.safe_load")
    @patch("gpu.main.execute_with_retries")
    @patch("gpu.main.KUBERNETES_CLIENT")
    @patch("gpu.main.create_topology_configmap")
    def test_execute_azure_provider(
        self, mock_topology, mock_k8s_client, _mock_execute_with_retries, mock_yaml
    ):
        """Test execute function with Azure provider."""
        # Mock template creation and YAML loading
        mock_k8s_client.create_template.return_value = "mocked template content"
        mock_yaml.return_value = {"kind": "MPIJob", "metadata": {"name": "test"}}

        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        _mock_execute_with_retries.return_value = [mock_pod]
        mock_k8s_client.get_pod_logs.return_value = b"test logs content"
        provider = "azure"

        with patch("builtins.open", mock_open()) as mock_file:
            execute(
                provider=provider,
                config_dir=self.test_config_dir,
                result_dir=self.test_result_dir,
                topology_vm_size='ndv4',
            )

            mock_topology.assert_called_once_with(vm_size='ndv4')
            mock_k8s_client.apply_manifest_from_file.assert_called_once_with(
                manifest_dict=unittest.mock.ANY
            )
            # Verify execute_with_retries is called once for waiting for pods
            _mock_execute_with_retries.assert_called_once()
            mock_file.assert_called_once_with(
                f"{self.test_result_dir}/raw.log", "w", encoding="utf-8"
            )

    @patch("yaml.safe_load")
    @patch("gpu.main.execute_with_retries")
    @patch("gpu.main.KUBERNETES_CLIENT")
    @patch("gpu.pkg.utils.create_topology_configmap")
    def test_execute_aws_provider(
        self, mock_topology, mock_k8s_client, _mock_execute_with_retries, mock_yaml
    ):
        """Test execute function with AWS provider."""

        # Mock template creation and YAML loading
        mock_k8s_client.create_template.return_value = "mocked template content"
        mock_yaml.return_value = {"kind": "MPIJob", "metadata": {"name": "test"}}

        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        _mock_execute_with_retries.return_value = [mock_pod]
        mock_k8s_client.get_pod_logs.return_value = b"test logs content"
        provider = "aws"

        with patch("builtins.open", mock_open()) as mock_file:
            execute(
                provider=provider,
                config_dir=self.test_config_dir,
                result_dir=self.test_result_dir,
                topology_vm_size="",
            )

            mock_topology.assert_not_called()
            mock_k8s_client.apply_manifest_from_file.assert_called_once_with(
                manifest_dict=unittest.mock.ANY
            )
            # Verify execute_with_retries is called once for waiting for pods
            _mock_execute_with_retries.assert_called_once()
            mock_file.assert_called_once_with(
                f"{self.test_result_dir}/raw.log", "w", encoding="utf-8"
            )

    def test_parse_nccl_test_results_success(self):
        """Test parsing NCCL test results from log file."""
        sample_log_content = """# nThread 1 nGpus 8 minBytes 8 maxBytes 134217728 step: 2(factor) warmup iters: 5 iters: 20
#  Rank  0 Group  0 Pid     123 on nccl-tests-worker-0 device  0 [0001:00:00] NVIDIA A100
#       size         count      type   redop    root     time   algbw   busbw #wrong     time   algbw   busbw #wrong
           8             1     float     sum      -1     10.5    15.2    13.4      0     11.2    14.3    12.8      0
          16             1     float     sum      -1     11.5    16.2    14.4      0     12.2    15.3    13.8      0
# Out of bounds values : 0 OK
# Avg bus bandwidth    : 13.1
"""

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".log"
        ) as temp_file:
            temp_file.write(sample_log_content)
            temp_file_path = temp_file.name

        try:
            result = _parse_nccl_test_results(temp_file_path)

            # Verify test info
            self.assertEqual(result["test_info"]["nThread"], 1)
            self.assertEqual(result["test_info"]["nGpus"], 8)
            self.assertEqual(result["test_info"]["minBytes"], 8)

            # Verify devices
            self.assertEqual(len(result["devices"]), 1)
            self.assertEqual(result["devices"][0]["rank"], 0)
            self.assertEqual(result["devices"][0]["hostname"], "nccl-tests-worker-0")

            # Verify performance data
            self.assertEqual(len(result["performance_data"]["out_of_place"]), 2)
            self.assertEqual(
                result["performance_data"]["out_of_place"][0]["size_bytes"], 8
            )

            # Verify summary
            self.assertEqual(result["summary"]["avg_bus_bandwidth_gbps"], 13.1)
            self.assertEqual(result["summary"]["out_of_bounds_count"], 0)

        finally:
            os.unlink(temp_file_path)

    def test_parse_nccl_test_results_file_not_found(self):
        """Test parsing with non-existent file."""
        with self.assertRaises(FileNotFoundError):
            _parse_nccl_test_results("/non/existent/file.log")

    @patch("builtins.open", new_callable=mock_open)
    @patch("json.dump")
    @patch("gpu.main.parse_nccl_test_results")
    def test_collect_success(self, mock_parse, mock_json_dump, mock_file):
        """Test successful collection and JSON output."""
        mock_parse.return_value = {"test": "result"}

        collect(
            result_dir=self.test_result_dir,
            run_id=self.test_run_id,
            run_url=self.test_run_url,
            cloud_info=self.test_cloud_info,
        )

        mock_parse.assert_called_once_with(f"{self.test_result_dir}/raw.log")
        mock_file.assert_called_once_with(
            f"{self.test_result_dir}/results.json", "a", encoding="utf-8"
        )
        mock_json_dump.assert_called_once()

    @patch("gpu.main.collect")
    @patch("gpu.main.execute")
    @patch("gpu.main.configure")
    @patch("argparse.ArgumentParser.parse_args")
    def test_main_configure_command(
        self, mock_args, mock_configure, _mock_execute, _mock_collect
    ):
        """Test main function with configure command."""
        mock_args.return_value = MagicMock(
            command="configure",
            efa_operator_version="0.5.0",
            network_operator_version="1.0.0",
            gpu_operator_version="2.0.0",
            gpu_install_driver=True,
            gpu_enable_nfd=False,
            mpi_operator_version="3.0.0",
            config_dir=self.test_config_dir,
        )

        main()

        mock_configure.assert_called_once_with(
            efa_operator_version="0.5.0",
            network_operator_version="1.0.0",
            gpu_operator_version="2.0.0",
            gpu_install_driver=True,
            gpu_enable_nfd=False,
            mpi_operator_version="3.0.0",
            config_dir=self.test_config_dir,
        )

    @patch("gpu.main.collect")
    @patch("gpu.main.execute")
    @patch("gpu.main.configure")
    @patch("argparse.ArgumentParser.parse_args")
    def test_main_execute_command(
        self, mock_args, _mock_configure, mock_execute, _mock_collect
    ):
        """Test main function with execute command."""
        mock_args.return_value = MagicMock(
            command="execute",
            provider="azure",
            config_dir=self.test_config_dir,
            result_dir=self.test_result_dir,
            topology_vm_size=self.test_vm_size,
            gpu_node_count=2,
            gpu_allocatable=4,
            ib_allocatable=None,
            efa_allocatable=None,
            nccl_tests_version="amd64",
        )

        main()

        mock_execute.assert_called_once_with(
            provider="azure",
            config_dir=self.test_config_dir,
            result_dir=self.test_result_dir,
            topology_vm_size=self.test_vm_size,
            gpu_node_count=2,
            gpu_allocatable=4,
            ib_allocatable=None,
            efa_allocatable=None,
            nccl_tests_version="amd64",
        )

    @patch("gpu.main.collect")
    @patch("gpu.main.execute")
    @patch("gpu.main.configure")
    @patch("argparse.ArgumentParser.parse_args")
    def test_main_collect_command(
        self, mock_args, _mock_configure, _mock_execute, mock_collect
    ):
        """Test main function with collect command."""
        mock_args.return_value = MagicMock(
            command="collect",
            result_dir=self.test_result_dir,
            run_id=self.test_run_id,
            run_url=self.test_run_url,
            cloud_info=self.test_cloud_info,
        )

        main()

        mock_collect.assert_called_once_with(
            result_dir=self.test_result_dir,
            run_id=self.test_run_id,
            run_url=self.test_run_url,
            cloud_info=self.test_cloud_info,
        )

    @patch("gpu.main.collect")
    @patch("gpu.main.execute")
    @patch("gpu.main.configure")
    @patch("argparse.ArgumentParser.parse_args")
    @patch("argparse.ArgumentParser.print_help")
    def test_main_no_command(
        self, mock_help, mock_args, _mock_configure, _mock_execute, _mock_collect
    ):
        """Test main function with no command specified."""
        mock_args.return_value = MagicMock(command=None)

        main()

        mock_help.assert_called_once()
        _mock_configure.assert_not_called()
        _mock_execute.assert_not_called()
        _mock_collect.assert_not_called()

    @unittest.skip("Function _get_gpu_node_count_and_allocatable not implemented yet")
    @patch("gpu.pkg.utils.KUBERNETES_CLIENT")
    def test_get_gpu_node_count_and_allocatable(self, mock_k8s_client):
        """Test GPU node count and allocatable retrieval with various scenarios."""

        # Test Case 1: Success with multiple nodes
        mock_node1 = MagicMock()
        mock_node1.status.allocatable = {"nvidia.com/gpu": "4"}
        mock_node2 = MagicMock()
        mock_node2.status.allocatable = {"nvidia.com/gpu": "4"}
        mock_k8s_client.get_nodes.return_value = [mock_node1, mock_node2]

        node_count, gpu_allocatable = _get_gpu_node_count_and_allocatable()
        self.assertEqual(node_count, 2)
        self.assertEqual(gpu_allocatable, 4)

        # Test Case 2: Success with single node
        mock_node = MagicMock()
        mock_node.status.allocatable = {"nvidia.com/gpu": "8"}
        mock_k8s_client.get_nodes.return_value = [mock_node]

        node_count, gpu_allocatable = _get_gpu_node_count_and_allocatable()
        self.assertEqual(node_count, 1)
        self.assertEqual(gpu_allocatable, 8)

        # Test Case 3: No GPU nodes found
        mock_k8s_client.get_nodes.return_value = []
        with self.assertRaises(RuntimeError) as context:
            _get_gpu_node_count_and_allocatable()
        self.assertEqual(str(context.exception), "No GPU nodes found in the cluster")

        # Test Case 4: Nodes with no GPU resources
        mock_node_no_gpu = MagicMock()
        mock_node_no_gpu.status.allocatable = {"cpu": "4", "memory": "16Gi"}
        mock_k8s_client.get_nodes.return_value = [mock_node_no_gpu]
        with self.assertRaises(RuntimeError) as context:
            _get_gpu_node_count_and_allocatable()
        self.assertEqual(
            str(context.exception),
            "No allocatable GPU resources found on the GPU nodes",
        )

        # Test Case 5: Nodes with zero GPU resources
        mock_node_zero_gpu = MagicMock()
        mock_node_zero_gpu.status.allocatable = {"nvidia.com/gpu": "0"}
        mock_k8s_client.get_nodes.return_value = [mock_node_zero_gpu]
        with self.assertRaises(RuntimeError) as context:
            _get_gpu_node_count_and_allocatable()
        self.assertEqual(
            str(context.exception),
            "No allocatable GPU resources found on the GPU nodes",
        )

        # Verify all calls used the correct label selector
        for node_call in mock_k8s_client.get_nodes.call_args_list:
            self.assertEqual(node_call[1]["label_selector"], "gpu=true")


if __name__ == "__main__":
    unittest.main()
