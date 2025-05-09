import os
import json
import tempfile
import unittest
import sys
from unittest.mock import patch, MagicMock
from clusterloader2.cri.cri import (
    override_config_clusterloader2,
    execute_clusterloader2,
    verify_measurement,
    collect_clusterloader2,
    main
)
from kubernetes.client.models import (
    V1Node, V1NodeStatus, V1NodeCondition, V1NodeSpec, V1ObjectMeta, V1Pod, V1PodSpec
)

class TestCRIClusterLoaderFunctions(unittest.TestCase):
    def _create_node(self, name, ready_status, cpu_allocatable="1000m", memory_allocatable="2048Mi", labels=None):
        conditions = [V1NodeCondition(type="Ready", status=ready_status)]
        allocatable = {"cpu": cpu_allocatable, "memory": memory_allocatable}
        metadata = V1ObjectMeta(name=name, labels=labels or {})
        return V1Node(
            metadata=metadata,
            status=V1NodeStatus(conditions=conditions, allocatable=allocatable),
            spec=V1NodeSpec()
        )

    def _create_pod(self, name, namespace, node_name, container_name, cpu_request, memory_request):
        container = MagicMock()
        container.name = container_name
        container.resources.requests = {"cpu": cpu_request, "memory": memory_request}
        pod = V1Pod(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            spec=V1PodSpec(node_name=node_name, containers=[container])
        )
        return pod

    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('clusterloader2.cri.cri.KubernetesClient')
    def test_override_config_clusterloader2(self, mock_kubernetes_client, mock_open):
        # Mock nodes
        node_ready = self._create_node(
            name="node-1", ready_status="True", cpu_allocatable="2000m", memory_allocatable="4096Mi", labels={"cri-resource-consume": "true"})

        mock_kubernetes_instance = MagicMock()
        mock_kubernetes_instance.get_nodes.return_value = [node_ready]
        mock_kubernetes_instance.get_daemonsets_pods_allocated_resources.return_value = (100, 204800)
        mock_kubernetes_client.return_value = mock_kubernetes_instance

        # Call the function under test
        override_config_clusterloader2(
            node_count=10,
            node_per_step=2,
            max_pods=30,
            repeats=1,
            operation_timeout="2m",
            load_type="memory",
            scale_enabled=False,
            pod_startup_latency_threshold="15s",
            provider="aks",
            scrape_kubelets=True,
            override_file="/mock/override.yaml"
        )

        mock_open.assert_called_once_with("/mock/override.yaml", 'w', encoding='utf-8')
        handle = mock_open()
        handle.write.assert_any_call("CL2_DEPLOYMENT_SIZE: 24\n")
        handle.write.assert_any_call("CL2_RESOURCE_CONSUME_CPU: 79\n")
        handle.write.assert_any_call("CL2_RESOURCE_CONSUME_MEMORY: 154215\n")
        handle.write.assert_any_call("CL2_RESOURCE_CONSUME_MEMORY_KI: 157917Ki\n")
        handle.write.assert_any_call("CL2_REPEATS: 1\n")
        handle.write.assert_any_call("CL2_NODE_COUNT: 10\n")
        handle.write.assert_any_call("CL2_STEPS: 5\n")
        handle.write.assert_any_call("CL2_LOAD_TYPE: memory\n")
        handle.write.assert_any_call("CL2_POD_STARTUP_LATENCY_THRESHOLD: 15s\n")
        handle.write.assert_any_call("CL2_OPERATION_TIMEOUT: 2m\n")
        handle.write.assert_any_call("CL2_SCALE_ENABLED: false\n")
        handle.write.assert_any_call("CL2_PROVIDER: aks\n")
        handle.write.assert_any_call("CL2_SCRAPE_KUBELETS: true\n")

    @patch('clusterloader2.cri.cri.run_cl2_command')
    def test_execute_clusterloader2(self, mock_run_cl2_command):
        # Call the function under test
        execute_clusterloader2(
            cl2_image="mock-image",
            cl2_config_dir="/mock/config",
            cl2_report_dir="/mock/report",
            kubeconfig="/mock/kubeconfig",
            provider="aks",
            scrape_kubelets=True
        )

        # Verify the command execution
        mock_run_cl2_command.assert_called_once_with(
            "/mock/kubeconfig", "mock-image", "/mock/config", "/mock/report", "aks",
            overrides=True, enable_prometheus=True, tear_down_prometheus=False, scrape_kubelets=True
        )

    @patch('clusterloader2.cri.cri.KubernetesClient')
    @patch('kubernetes.client.ApiClient.call_api')
    def test_verify_measurement(self, mock_call_api, mock_kubernetes_client):
        # Mock nodes
        mock_node = self._create_node(name="node-1", ready_status="True")
        mock_kubernetes_instance = MagicMock()
        mock_kubernetes_instance.get_nodes.return_value = [mock_node]
        mock_kubernetes_client.return_value = mock_kubernetes_instance

        # Mock API response
        mock_call_api.return_value = ["kubelet_pod_start_duration_seconds_bucket{le=\"0.1\"} 5"]

        # Call the function under test
        verify_measurement()

        # Verify API calls
        mock_call_api.assert_called_once_with(
            resource_path="/api/v1/nodes/node-1/proxy/metrics",
            method="GET",
            auth_settings=['BearerToken'],
            response_type="str",
            _preload_content=True
        )

    def test_collect_clusterloader2(self):
        cl2_report_dir = os.path.join(
              os.path.dirname(__file__), "mock_data", "cri", "report"
          )
        # Create a temporary file for result output
        result_file = tempfile.mktemp()
        # Call the function under test
        collect_clusterloader2(
            node_count=10,
            max_pods=30,
            repeats=1,
            load_type="memory",
            cl2_report_dir=cl2_report_dir,
            cloud_info="aks",
            run_id="12345",
            run_url="http://example.com",
            result_file=result_file,
            scrape_kubelets=False
        )

        self.assertTrue(os.path.exists(result_file))
        with open(result_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('"status": "failure"', content)

    @patch('clusterloader2.cri.cri.parse_xml_to_json')
    def test_collect_clusterloader2_no_testsuites(self, mock_parse_xml_to_json):
        # Mock XML parsing with no testsuites
        mock_parse_xml_to_json.return_value = json.dumps({"testsuites": []})

        # Call the function and expect an exception
        with self.assertRaises(Exception) as context:
            collect_clusterloader2(
                node_count=10,
                max_pods=110,
                repeats=3,
                load_type="memory",
                cl2_report_dir="/mock/report",
                cloud_info="aws",
                run_id="12345",
                run_url="http://example.com",
                result_file="/mock/result.json",
                scrape_kubelets=False
            )

        self.assertIn("No testsuites found in the report", str(context.exception))

    @patch("clusterloader2.cri.cri.override_config_clusterloader2")
    def test_override_command(self, mock_override):
        test_args = [
            "main.py", "override", "5", "1", "110", "3", "2m", "cpu", "True", "10s",
            "aws", "False", "/tmp/override.yaml"
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_override.assert_called_once_with(
                5, 1, 110, 3, "2m", "cpu", True, "10s", "aws", False, "/tmp/override.yaml"
            )

    @patch("clusterloader2.cri.cri.execute_clusterloader2")
    def test_execute_command(self, mock_execute):
        test_args = [
            "main.py", "execute", "gcr.io/cl2:latest", "/configs", "/reports",
            "/home/user/.kube/config", "gcp", "True"
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_execute.assert_called_once_with(
                "gcr.io/cl2:latest", "/configs", "/reports",
                "/home/user/.kube/config", "gcp", True
            )

    @patch("clusterloader2.cri.cri.collect_clusterloader2")
    def test_collect_command(self, mock_collect):
        test_args = [
            "main.py", "collect", "3", "100", "5", "memory", "/reports",
            "gcp-zone", "run-123", "https://run.url", "/tmp/results.json", "False"
        ]
        with patch.object(sys, 'argv', test_args):
            main()
            mock_collect.assert_called_once_with(
                3, 100, 5, "memory", "/reports", "gcp-zone", "run-123",
                "https://run.url", "/tmp/results.json", False
            )

if __name__ == '__main__':
    unittest.main()
