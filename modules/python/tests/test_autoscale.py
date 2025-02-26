import os
import json
import unittest
from unittest.mock import patch, MagicMock, mock_open, call


from clusterloader2.autoscale.autoscale import (
        _get_daemonsets_pods_allocated_resources,
        calculate_cpu_request_for_clusterloader2,
        override_config_clusterloader2,
        execute_clusterloader2,
        collect_clusterloader2
    )


class TestAutoscale(unittest.TestCase):    
    def test_get_daemonsets_pods_allocated_resources(self):
        # Create mock pod with containers
        mock_container1 = MagicMock()
        mock_container1.name = "container1"
        mock_container1.resources.requests = {"cpu": "100m"}
        
        mock_container2 = MagicMock()
        mock_container2.name = "container2"
        mock_container2.resources.requests = {"cpu": "200m"}
        
        mock_container3 = MagicMock()
        mock_container3.name = "container3"
        mock_container3.resources.requests = None
        
        mock_pod1 = MagicMock()
        mock_pod1.metadata.name = "pod1"
        mock_pod1.spec.containers = [mock_container1, mock_container2]
        
        mock_pod2 = MagicMock()
        mock_pod2.metadata.name = "pod2"
        mock_pod2.spec.containers = [mock_container3]
        
        mock_client = MagicMock()
        mock_client.get_pods_by_namespace.return_value = [mock_pod1, mock_pod2]
        
        result = _get_daemonsets_pods_allocated_resources(mock_client, "test-node")
        
        mock_client.get_pods_by_namespace.assert_called_once_with(
            "kube-system", field_selector="spec.nodeName=test-node"
        )
        self.assertEqual(result, 300)  # 100m + 200m = 300m

    # @patch("clusterloader2.kubernetes_client.KubernetesClient")
    # @patch("clusterloader2.autoscale.autoscale._get_daemonsets_pods_allocated_resources")
    # @patch("clusterloader2.autoscale.autoscale.cleanup_warmup_deployment_for_karpeneter")
    # @patch("time.sleep")
    # def test_calculate_cpu_request_for_clusterloader2(
    #     self, mock_sleep, mock_cleanup, mock_get_allocated, mock_k8s_client
    # ):
    #     # Setup mocks
    #     mock_node = MagicMock()
    #     mock_node.metadata.name = "test-node"
    #     mock_node.status.allocatable = {"cpu": "1000m"}
        
    #     mock_client_instance = MagicMock()
    #     mock_client_instance.get_ready_nodes.return_value = [mock_node]
    #     mock_k8s_client.return_value = mock_client_instance
        
    #     mock_get_allocated.return_value = 200
        
    #     # Test with normal deployment
    #     result = calculate_cpu_request_for_clusterloader2(
    #         "node-label=value", 2, 10, "false"
    #     )
        
    #     mock_k8s_client.assert_called_once_with(os.path.expanduser("~/.kube/config"))
    #     mock_client_instance.get_ready_nodes.assert_called_once_with(label_selector="node-label=value")
    #     mock_get_allocated.assert_called_once_with(mock_client_instance, "test-node")
    #     mock_cleanup.assert_not_called()
        
    #     # CPU calculation: (1000 - 200) / (10 / 2) = 800 / 5 = 160
    #     self.assertEqual(result, 160)
        
    #     # Reset mocks for warmup deployment test
    #     mock_k8s_client.reset_mock()
    #     mock_client_instance.reset_mock()
    #     mock_get_allocated.reset_mock()
    #     mock_cleanup.reset_mock()
        
    #     # Test with warmup deployment
    #     mock_k8s_client.return_value = mock_client_instance
    #     result_warmup = calculate_cpu_request_for_clusterloader2(
    #         "node-label=value", 2, 10, "true"
    #     )
        
    #     mock_cleanup.assert_called_once_with("test-node")
        
    #     # CPU calculation: (1000 - 200 - 100) / (10 / 2) = 700 / 5 = 140
    #     self.assertEqual(result_warmup, 140)

    @patch("clusterloader2.autoscale.autoscale.warmup_deployment_for_karpeneter")
    @patch("clusterloader2.autoscale.autoscale.calculate_cpu_request_for_clusterloader2")
    @patch("builtins.open", new_callable=mock_open)
    def test_override_config_clusterloader2(
        self, mock_file, mock_calculate, mock_warmup
    ):
        mock_calculate.return_value = 150
        
        # Test with normal deployment
        override_config_clusterloader2(
            4, 3, 15, "10m", "15m", 5, "node-type=test", 
            "node-type=test", "test-override.yaml", "false"
        )
        
        mock_calculate.assert_called_once_with("node-type=test", 3, 15, "false")
        mock_warmup.assert_not_called()
        mock_file.assert_called_once_with("test-override.yaml", "w", encoding="utf-8")
        
        # Verify file write operations
        handle = mock_file()
        expected_calls = [
            call("CL2_DEPLOYMENT_CPU: 150m\n"),
            call("CL2_MIN_NODE_COUNT: 3\n"),
            call("CL2_MAX_NODE_COUNT: 13\n"),
            call("CL2_DESIRED_NODE_COUNT: 1\n"),
            call("CL2_DEPLOYMENT_SIZE: 15\n"),
            call("CL2_SCALE_UP_TIMEOUT: 10m\n"),
            call("CL2_SCALE_DOWN_TIMEOUT: 15m\n"),
            call("CL2_LOOP_COUNT: 5\n"),
            call("CL2_NODE_LABEL_SELECTOR: node-type=test\n"),
            call('CL2_NODE_SELECTOR: "node-type=test"\n'),
        ]
        handle.write.assert_has_calls(expected_calls)
        
        # Reset mocks for warmup deployment test
        mock_file.reset_mock()
        mock_calculate.reset_mock()
        mock_warmup.reset_mock()
        
        # Test with warmup deployment
        override_config_clusterloader2(
            4, 3, 15, "10m", "15m", 5, "node-type=test", 
            "node-type=test", "test-override.yaml", "true"
        )
        
        mock_calculate.assert_called_once_with("node-type=test", 3, 15, "true")
        mock_warmup.assert_called_once()

    @patch("clusterloader2.autoscale.autoscale.run_cl2_command")
    def test_execute_clusterloader2(self, mock_run_cl2):
        execute_clusterloader2(
            "test-image", "/config", "/report", "/kube/config", "test-provider"
        )
        
        mock_run_cl2.assert_called_once_with(
            "/kube/config", "test-image", "/config", "/report", 
            "test-provider", overrides=True
        )

    # @patch("clusterloader2.autoscale.autoscale.parse_xml_to_json")
    # @patch("os.makedirs")
    # @patch("builtins.open", new_callable=mock_open)
    # def test_collect_clusterloader2(self, mock_file, mock_makedirs, mock_parse_xml):
    #     # Mock data for XML parsing
    #     test_cases = [
    #         {"name": "WaitForRunningPodsUp", "time": 10, "failure": None},
    #         {"name": "WaitForNodesUp", "time": 20, "failure": None},
    #         {"name": "WaitForRunningPodsDown", "time": 15, "failure": None},
    #         {"name": "WaitForNodesDown", "time": 25, "failure": None},
    #         {"name": "WaitForRunningPodsUp", "time": 12, "failure": "error"},
    #         {"name": "WaitForNodesUp", "time": 22, "failure": None},
    #         {"name": "WaitForRunningPodsDown", "time": 17, "failure": None},
    #         {"name": "WaitForNodesDown", "time": 27, "failure": None},
    #         {"name": "InvalidName", "time": 5, "failure": None},
    #     ]
        
    #     test_suites = [{"testcases": test_cases}]
    #     mock_json_data = {"testsuites": test_suites}
    #     mock_parse_xml.return_value = json.dumps(mock_json_data)
        
    #     collect_clusterloader2(
    #         4, 3, 15, "/report", "test-cloud", "test-run", "http://test-url", 
    #         "/result/file.json"
    #     )
        
    #     mock_parse_xml.assert_called_once_with(os.path.join("/report", "junit.xml"), indent=2)
    #     mock_makedirs.assert_called_once_with(os.path.dirname("/result/file.json"), exist_ok=True)
    #     mock_file.assert_called_once_with("/result/file.json", "w", encoding="utf-8")
        
    #     # Check that four records were written (two phases for two indices)
    #     self.assertEqual(mock_file().write.call_count, 4)

    @patch("clusterloader2.autoscale.autoscale.parse_xml_to_json")
    def test_collect_clusterloader2_no_testsuites(self, mock_parse_xml):
        mock_json_data = {"testsuites": []}
        mock_parse_xml.return_value = json.dumps(mock_json_data)
        
        with self.assertRaises(Exception) as context:
            collect_clusterloader2(
                4, 3, 15, "/report", "test-cloud", "test-run", "http://test-url", 
                "/result/file.json"
            )
        
        self.assertTrue("No testsuites found in the report!" in str(context.exception))


if __name__ == "__main__":
    unittest.main()