import os
import json
import tempfile
import sys
import unittest
from unittest.mock import patch, MagicMock
from clusterloader2.autoscale.autoscale import (
    warmup_deployment_for_karpeneter,
    cleanup_warmup_deployment_for_karpeneter,
    calculate_cpu_request_for_clusterloader2,
    override_config_clusterloader2,
    execute_clusterloader2,
    collect_clusterloader2,
    main
)
from kubernetes.client.models import (
    V1Node, V1NodeStatus, V1NodeCondition, V1NodeSpec, V1ObjectMeta, V1Pod, V1PodSpec
)

class TestClusterLoaderFunctions(unittest.TestCase):
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
        warmup_deployment_for_karpeneter(cl2_config_dir, 'warmup_deployment.yaml')
        mock_run.assert_called_once_with(["kubectl", "apply", "-f", f"{cl2_config_dir}/warmup_deployment.yaml"], check=True)

    @patch('subprocess.run')
    def test_cleanup_warmup_deployment_for_karpeneter(self, mock_run):
        cl2_config_dir = '/mock/path'
        cleanup_warmup_deployment_for_karpeneter(cl2_config_dir, 'warmup_deployment.yaml')
        mock_run.assert_any_call(["kubectl", "delete", "-f", f"{cl2_config_dir}/warmup_deployment.yaml"], check=True)
        mock_run.assert_any_call(["kubectl", "delete", "nodeclaims", "--all"], check=True)

    @patch('clusterloader2.autoscale.autoscale.KubernetesClient')
    @patch('clusterloader2.autoscale.autoscale.cleanup_warmup_deployment_for_karpeneter')
    def test_calculate_cpu_request_with_warmup_success(self, mock_cleanup, mock_kubernetes_client):
        # Mock nodes
        node_ready = self._create_node(name="node-1", ready_status="True", cpu_allocatable="2000m", labels={"autoscaler": "true"})
        mock_kubernetes_instance = MagicMock()
        mock_kubernetes_instance.wait_for_nodes_ready.return_value = [node_ready]
        mock_kubernetes_instance.get_daemonsets_pods_allocated_resources.return_value = (100, 100000)
        mock_kubernetes_client.return_value = mock_kubernetes_instance

        # Call the function under test
        with_warmup_cpu_request = calculate_cpu_request_for_clusterloader2('{"autoscaler": "true"}', 1, 1, 'true', '/mock/path', 'warmup_deployment.yaml')

        without_warmup_cpu_request = calculate_cpu_request_for_clusterloader2('{"autoscaler": "true"}', 1, 1, 'false', '/mock/path', 'warmup_deployment.yaml')

        # Assert the CPU request calculation
        self.assertEqual(with_warmup_cpu_request, 1800*0.95)  # 2000m - 100m (allocated) - 100m (warmup)
        self.assertEqual(without_warmup_cpu_request, 1900*0.95) # 2000m - 100m (allocated)

        # Assert cleanup is called
        mock_cleanup.assert_called_once_with('/mock/path', 'warmup_deployment.yaml')

    @patch('clusterloader2.autoscale.autoscale.KubernetesClient')
    def test_calculate_cpu_request_with_warmup_failure(self, mock_kubernetes_client):
        mock_kubernetes_instance = MagicMock()
        mock_kubernetes_instance.wait_for_nodes_ready.return_value = []
        mock_kubernetes_client.return_value = mock_kubernetes_instance

        with self.assertRaises(Exception) as context:
            calculate_cpu_request_for_clusterloader2('{"autoscaler": "true"}', 1, 1, 'true', '/mock/path', 'warmup_deployment.yaml')

        self.assertIn("Error while getting nodes:", str(context.exception))

        mock_kubernetes_instance.wait_for_nodes_ready.side_effect = Exception("API failure")
        mock_kubernetes_client.return_value = mock_kubernetes_instance

        # Expect the function to eventually raise after the fallback logic
        with self.assertRaises(Exception) as context:
            calculate_cpu_request_for_clusterloader2('{"autoscaler": "true"}', 1, 1, 'true', '/mock/path', 'warmup_deployment.yaml')

        self.assertIn("Error while getting nodes:", str(context.exception))

    @patch('clusterloader2.autoscale.autoscale.calculate_cpu_request_for_clusterloader2')
    @patch('clusterloader2.autoscale.autoscale.warmup_deployment_for_karpeneter')
    @patch('clusterloader2.autoscale.autoscale.logger')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_override_config_clusterloader2(self, mock_open, mock_logger, mock_warmup, mock_calculate_cpu_request):
        # Mock the CPU request calculation
        mock_calculate_cpu_request.return_value = 1900

        override_config_clusterloader2(2, 100, 1000, '5m', '5m', 1, 'autoscaler = true', '{autoscaler : true}', 'override_file', 'false', '/mock/path', 'linux', 'warmup_deployment.yaml', 'deployment_template.yaml')
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
        handle.write.assert_any_call('CL2_OS_TYPE: linux\n')

        mock_logger.info.assert_any_call(
            "Total number of nodes: 100, total number of pods: 1000, cpu per node: 2"
        )
        mock_logger.info.assert_any_call("CPU request for each pod: 1900m")

        # Test with warmup deployment true
        mock_warmup.retun_value = None
        override_config_clusterloader2(2, 100, 1000, '5m', '5m', 1, 'autoscaler = true', '{autoscaler : true}', 'override_file', 'true', '/mock/path', 'windows', 'warmup_deployment.yaml', 'deployment_template.yaml')
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
        handle.write.assert_any_call('CL2_OS_TYPE: windows\n')
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

    @patch('clusterloader2.autoscale.autoscale.run_cl2_command')
    def test_execute_clusterloader2(self, mock_run_cl2_command):
        # Call the function under test
        execute_clusterloader2(
            cl2_image="mock-image",
            cl2_config_dir="/mock/config",
            cl2_report_dir="/mock/report",
            kubeconfig="/mock/kubeconfig",
            provider="aks",
        )

        # Verify the command execution
        mock_run_cl2_command.assert_called_once_with(
            "/mock/kubeconfig",
            "mock-image",
            "/mock/config",
            "/mock/report",
            "aks",
            "config.yaml",
            overrides=True,
            enable_prometheus=False,
            tear_down_prometheus=False,
            scrape_kubelets=False,
            scrape_ksm=False,
        )
    def test_collect_clusterloader2_success(self):
        cl2_report_dir = os.path.join(
              os.path.dirname(__file__), "mock_data", "autoscale", "report"
          )
        # Create a temporary file for result output
        result_file = tempfile.mktemp()

        collect_clusterloader2(
          cpu_per_node=2,
          capacity_type="on-demand",
          node_count=500,
          pod_count=500,
          cl2_report_dir=cl2_report_dir,
          cloud_info="mock-cloud",
          run_id="mock-run-id",
          run_url="http://mock-run-url",
          result_file=result_file,
          cl2_config_file="config.yaml",
          pod_cpu_request=1900,
          pod_memory_request="2Gi"
        )

        self.assertTrue(os.path.exists(result_file))
        with open(result_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(len(content) > 0)
        self.assertIn('"autoscale_type": "up"', content)
        self.assertIn('"autoscale_type": "down"', content)
        self.assertIn('"autoscale_result": "success"', content)

    @patch('clusterloader2.autoscale.autoscale.parse_xml_to_json')
    @patch('os.path.join', autospec=True)
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
              result_file="/mock/result/file",
              cl2_config_file="config.yaml",
              pod_cpu_request=2000,
              pod_memory_request="2Gi"
            )

        self.assertIn("No testsuites found in the report", str(context.exception))

    @patch('clusterloader2.autoscale.autoscale.override_config_clusterloader2')
    def test_override_command(self, mock_override):
        test_args = [
            'prog',
            'override',
            '4',
            '3',
            '200',
            '10m',
            '5m',
            '2',
            'nodepool=default',
            'env=prod',
            'override.yaml',
            'warmup-deploy',
            'config-dir',
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_override.assert_called_once_with(
                4,
                3,
                200,
                '10m',
                '5m',
                2,
                'nodepool=default',
                'env=prod',
                'override.yaml',
                'warmup-deploy',
                'config-dir',
                'linux',
                '',
                '',
                pod_cpu_request=None,
                pod_memory_request=None,
                cl2_config_file='config.yaml',
                enable_prometheus=False,
            )

    @patch('clusterloader2.autoscale.autoscale.execute_clusterloader2')
    def test_execute_command(self, mock_execute):
        test_args = [
            'prog',
            'execute',
            'cl2-image',
            'config-dir',
            'report-dir',
            'kubeconfig.yaml',
            'aws',
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_execute.assert_called_once_with(
                'cl2-image',
                'config-dir',
                'report-dir',
                'kubeconfig.yaml',
                'aws',
                'config.yaml',
                False,
                False,
                False,
            )

    @patch('clusterloader2.autoscale.autoscale.collect_clusterloader2')
    def test_collect_command(self, mock_collect):
        test_args = [
            'prog', 'collect', '4', 'on-demand', '3', '200',
            'report-dir', 'aws-info', 'run-123', 'http://run.url', 'results.json'
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_collect.assert_called_once_with(
                4, 'on-demand', 3, 200, 'report-dir',
                'aws-info', 'run-123', 'http://run.url', 'results.json',
                cl2_config_file='config.yaml', pod_cpu_request=None, pod_memory_request=None
            )

if __name__ == '__main__':
    unittest.main()
