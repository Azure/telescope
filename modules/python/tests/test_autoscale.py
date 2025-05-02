import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from clusterloader2.autoscale.autoscale import (
    warmup_deployment_for_karpeneter,
    cleanup_warmup_deployment_for_karpeneter,
    _get_daemonsets_pods_allocated_resources,
    calculate_cpu_request_for_clusterloader2,
    override_config_clusterloader2,
    execute_clusterloader2,
    collect_clusterloader2,
)
from kubernetes.client.models import (
    V1Node, V1NodeStatus, V1NodeCondition, V1NodeSpec, V1ObjectMeta, V1Taint,
    V1PodStatus, V1Pod, V1PodSpec, V1Namespace
)
from clients.kubernetes_client import KubernetesClient

class TestClusterLoaderFunctions(unittest.TestCase):
    @patch('kubernetes.config.load_kube_config')
    def setUp(self, mock_load_kube_config):  # pylint: disable=unused-argument, arguments-differ
        self.client = KubernetesClient()
        return super().setUp()

    def _create_node(self, name, ready_status, cpu_allocatable="1000m", labels=None, unschedulable=False):
        conditions = [V1NodeCondition(type="Ready", status=ready_status)]
        allocatable = {"cpu": cpu_allocatable}
        metadata = V1ObjectMeta(name=name, labels=labels or {})
        return V1Node(
          metadata=metadata,
          status=V1NodeStatus(conditions=conditions, allocatable=allocatable),
          spec=V1NodeSpec(unschedulable=unschedulable)
        )

    def _create_pod(self, name, namespace, node_name, container_name, cpu_request):
        container = MagicMock()
        container.name = container_name
        container.resources.requests = {"cpu": cpu_request}
        pod = V1Pod(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            spec=V1PodSpec(node_name=node_name, containers=[container])
        )
        return pod

    @patch('subprocess.run')
    def test_warmup_deployment_for_karpeneter(self, mock_run):
        cl2_config_dir = '/mock/path'
        warmup_deployment_for_karpeneter(cl2_config_dir)
        mock_run.assert_called_once_with(["kubectl", "apply", "-f", f"{cl2_config_dir}/warmup_deployment.yaml"], check=True)

    @patch('subprocess.run')
    def test_cleanup_warmup_deployment_for_karpeneter(self, mock_run):
        cl2_config_dir = '/mock/path'
        cleanup_warmup_deployment_for_karpeneter(cl2_config_dir)
        mock_run.assert_any_call(["kubectl", "delete", "-f", f"{cl2_config_dir}/warmup_deployment.yaml"], check=True)
        mock_run.assert_any_call(["kubectl", "delete", "nodeclaims", "--all"], check=True)

    @patch('clients.kubernetes_client.KubernetesClient')
    def test_get_daemonsets_pods_allocated_resources(self, mock_client):
        # Create a mock client
        mock_client = MagicMock()
        
        # Create two mock pods with different CPU requests
        mock_pod1 = MagicMock()
        mock_pod1.metadata.name = "test-pod-1"
        mock_container1 = MagicMock()
        mock_container1.name = "test-container-1"
        mock_container1.resources.requests = {"cpu": "200m"}
        mock_pod1.spec.containers = [mock_container1]

        mock_pod2 = MagicMock()
        mock_pod2.metadata.name = "test-pod-2"
        mock_container2 = MagicMock()
        mock_container2.name = "test-container-2"
        mock_container2.resources.requests = {"cpu": "300m"}
        mock_pod2.spec.containers = [mock_container2]

        # Set the return value of the mock client
        mock_client.get_pods_by_namespace.return_value = [mock_pod1, mock_pod2]

        # Call the function under test
        cpu_request = _get_daemonsets_pods_allocated_resources(mock_client, "node1")

        # Assert the expected CPU request is sum of both
        self.assertEqual(cpu_request, 500)

    @patch('clients.kubernetes_client.KubernetesClient.get_nodes')
    @patch('clusterloader2.autoscale.autoscale._get_daemonsets_pods_allocated_resources')
    @patch('clusterloader2.autoscale.autoscale.cleanup_warmup_deployment_for_karpeneter')
    @patch('time.sleep')
    def test_calculate_cpu_request_with_warmup_success(self, mock_sleep, mock_cleanup, mock_get_allocated_resources, mock_get_nodes):
        # Mock nodes
        node_not_ready = self._create_node(name="node-1", ready_status="False")
        node_ready_one = self._create_node(name="node-2", ready_status="True", cpu_allocatable="2000m", labels={"autoscaler": "true"})
        node_ready_two = self._create_node(name="node-3", ready_status="True", cpu_allocatable="2000m", labels={"autoscaler": "false"})
        mock_get_nodes.return_value = [node_not_ready, node_ready_one, node_ready_two]
        
        # Mock the allocated CPU resources
        mock_get_allocated_resources.return_value = 100

        # Call the function under test
        with_warmup_cpu_request = calculate_cpu_request_for_clusterloader2('{"autoscaler": "true"}', 1, 1, 'true', '/mock/path')

        without_warmup_cpu_request = calculate_cpu_request_for_clusterloader2('{"autoscaler": "true"}', 1, 1, 'false', '/mock/path')
        
        # Assert the CPU request calculation
        self.assertEqual(with_warmup_cpu_request, 1800)  # 2000m - 100m (allocated) - 100m (warmup)
        self.assertEqual(without_warmup_cpu_request, 1900) # 2000m - 100m (allocated)

        # Assert cleanup is called
        mock_cleanup.assert_called_once_with('/mock/path')
    @patch('clients.kubernetes_client.KubernetesClient.get_nodes')
    @patch('clusterloader2.autoscale.autoscale._get_daemonsets_pods_allocated_resources')
    @patch('clusterloader2.autoscale.autoscale.cleanup_warmup_deployment_for_karpeneter')
    @patch('time.sleep')
    @patch('builtins.print')
    def test_calculate_cpu_request_with_warmup_failure(self, mock_print, mock_sleep, mock_cleanup, mock_get_allocated_resources, mock_get_nodes):
        # Mock nodes
        node_not_ready = self._create_node(name="node-1", ready_status="False")
        node_ready_one = self._create_node(name="node-2", ready_status="False", cpu_allocatable="2000m", labels={"autoscaler": "false"})
        mock_get_nodes.return_value = [node_not_ready, node_ready_one]
        
        # Mock the allocated CPU resources
        mock_get_allocated_resources.return_value = 100
        with self.assertRaises(Exception) as context:
          calculate_cpu_request_for_clusterloader2('{"autoscaler": "true"}', 1, 1, 'true', '/mock/path')

        self.assertIn("No nodes found with the label", str(context.exception))

        mock_get_nodes.side_effect = Exception("API failure")

        # Expect the function to eventually raise after the fallback logic
        with self.assertRaises(Exception) as context:
            calculate_cpu_request_for_clusterloader2('{"autoscaler": "true"}', 1, 1, 'true', '/mock/path')

        # Assert error print was called
        mock_print.assert_any_call("Error while getting nodes: API failure")
        mock_print.assert_any_call("Retrying in 30 seconds...")

        self.assertIn("No nodes found with the label", str(context.exception))

    @patch('clusterloader2.autoscale.autoscale.calculate_cpu_request_for_clusterloader2')
    @patch('clusterloader2.autoscale.autoscale.warmup_deployment_for_karpeneter')
    @patch('time.sleep')
    @patch('builtins.print')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)    
    def test_override_config_clusterloader2(self, mock_open, mock_print, mock_sleep, mock_warmup ,mock_calculate_cpu_request):
        # Mock the CPU request calculation
        mock_calculate_cpu_request.return_value = 1900

        override_config_clusterloader2(2, 100, 1000, '5m', '5m', 1, 'autoscaler = true', '{autoscaler : true}', 'override_file', 'false', '/mock/path')
        mock_open.assert_any_call('override_file', 'w', encoding='utf-8')
        handle = mock_open()
        handle.write.assert_any_call('CL2_DEPLOYMENT_CPU: 1900m\n')
        handle.write.assert_any_call('CL2_MIN_NODE_COUNT: 100\n')
        handle.write.assert_any_call('CL2_MAX_NODE_COUNT: 110\n')
        handle.write.assert_any_call('CL2_DESIRED_NODE_COUNT: 1\n')
        handle.write.assert_any_call('CL2_DEPLOYMENT_SIZE: 1000\n')
        handle.write.assert_any_call('CL2_SCALE_UP_TIMEOUT: 5m\n')
        handle.write.assert_any_call('CL2_SCALE_DOWN_TIMEOUT: 5m\n')
        handle.write.assert_any_call('CL2_LOOP_COUNT: 1\n')
        handle.write.assert_any_call('CL2_NODE_LABEL_SELECTOR: autoscaler = true\n')
        handle.write.assert_any_call('CL2_NODE_SELECTOR: "{autoscaler : true}"\n')

        # Test with warmup
        mock_warmup.retun_value = None
        override_config_clusterloader2(2, 100, 1000, '5m', '5m', 1, 'autoscaler = true', '{autoscaler : true}', 'override_file', 'true', '/mock/path')
        mock_open.assert_any_call('override_file', 'w', encoding='utf-8')
        handle = mock_open()
        handle.write.assert_any_call('CL2_DEPLOYMENT_CPU: 1900m\n')
        handle.write.assert_any_call('CL2_MIN_NODE_COUNT: 100\n')
        handle.write.assert_any_call('CL2_MAX_NODE_COUNT: 110\n')
        handle.write.assert_any_call('CL2_DESIRED_NODE_COUNT: 0\n')
        handle.write.assert_any_call('CL2_DEPLOYMENT_SIZE: 1000\n')
        handle.write.assert_any_call('CL2_SCALE_UP_TIMEOUT: 5m\n')
        handle.write.assert_any_call('CL2_SCALE_DOWN_TIMEOUT: 5m\n')
        handle.write.assert_any_call('CL2_LOOP_COUNT: 1\n')
        handle.write.assert_any_call('CL2_NODE_LABEL_SELECTOR: autoscaler = true\n')
        handle.write.assert_any_call('CL2_NODE_SELECTOR: "{autoscaler : true}"\n')
    
    @patch('clusterloader2.utils.parse_xml_to_json')
    def test_collect_clusterloader2_success(self, mock_parse_xml_to_json):
      # Mock the XML parsing

        cl2_report_dir = os.path.join(
              os.path.dirname(__file__), "mock_data", "autoscale", "report"
          )
        # Create a temporary file for result output
        result_file = tempfile.mktemp()

        # Call the function under test
        collect_clusterloader2(
          cpu_per_node=2,
          capacity_type="on-demand",
          node_count=500,
          pod_count=500,
          cl2_report_dir=cl2_report_dir,
          cloud_info="mock-cloud",
          run_id="mock-run-id",
          run_url="http://mock-run-url",
          result_file=result_file
        )
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(len(content) > 0)
        self.assertIn('"autoscale_type": "up"', content)
        self.assertIn('"autoscale_type": "down"', content)
        self.assertIn('"autoscale_result": "success"', content)

    @patch('clusterloader2.autoscale.autoscale.parse_xml_to_json')
    @patch('os.path.join')
    def test_collect_clusterloader2_no_testsuites(self, mock_path_join, mock_parse_xml_to_json):
        # Mock the XML parsing to return no testsuites
        mock_parse_xml_to_json.return_value = json.dumps({"testsuites": []})

        # Mock the path join
        mock_path_join.return_value = "/mock/path/junit.xml"

        # Call the function and expect an exception
        with self.assertRaises(Exception) as context:
            collect_clusterloader2(
              cpu_per_node=2000,
              capacity_type="on-demand",
              node_count=3,
              pod_count=30,
              cl2_report_dir="/mock/path",
              cloud_info="mock-cloud",
              run_id="mock-run-id",
              run_url="http://mock-run-url",
              result_file="/mock/result/file"
            )

        self.assertIn("No testsuites found in the report", str(context.exception))

if __name__ == '__main__':
    unittest.main()