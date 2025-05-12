import unittest
from unittest.mock import MagicMock, patch, call
from clients.pod_command import PodRoleCommand


class TestPodRoleCommand(unittest.TestCase):
    @patch('kubernetes.config.load_kube_config')
    def setUp(self, _mock_load_kube_config): # pylint: disable=arguments-differ
        self.namespace = "test-namespace"

        self.pod_cmd = PodRoleCommand(
            cluster_cli_context="cli-context",
            cluster_srv_context="srv-context",
            server_container="server-container",
            client_container="client-container",
            server_label_selector="app=server",
            client_label_selector="app=client",
            namespace=self.namespace,
            validate_command="validate-cmd",
            service_name="test-service"
        )

        # Create a new MagicMock for k8s_client
        self.k8s_client = MagicMock()
        self.pod_cmd.k8s_client = self.k8s_client

    def test_get_role_pod_server(self):
        pod_info = {"name": "server-pod", "ip": "10.0.0.1"}
        self.k8s_client.get_pod_name_and_ip.return_value = pod_info

        res = self.pod_cmd.get_pod_by_role(role="server")

        self.k8s_client.set_context.assert_called_with("srv-context")
        self.k8s_client.get_pod_name_and_ip.assert_called_with(
            label_selector="app=server",
            namespace=self.namespace
        )

        self.assertEqual(pod_info, res)

    def test_get_role_pod_client(self):
        pod_info = {"name": "client-pod", "ip": "10.0.0.2"}
        self.k8s_client.get_pod_name_and_ip.return_value = pod_info

        res = self.pod_cmd.get_pod_by_role(role="client")

        self.k8s_client.set_context.assert_called_with("cli-context")
        self.k8s_client.get_pod_name_and_ip.assert_called_with(
            label_selector="app=client",
            namespace=self.namespace
        )
        self.assertEqual(pod_info, res)

    def test_get_role_pod_invalid_role(self):
        with self.assertRaises(ValueError):
            self.pod_cmd.get_pod_by_role(role="invalid")

    def test_get_role_pod_existing_role(self):
        pod_info = {"name": "existing-pod", "ip": "10.0.0.1"}
        self.pod_cmd.pod_role = {"server": pod_info}
        self.pod_cmd.get_pod_by_role(role="server")
        self.k8s_client.get_pod_name_and_ip.assert_not_called()

    @patch('clients.pod_command.execute_with_retries')
    def test_run_command_for_role_client(self, mock_execute_with_retries):

        self.pod_cmd.k8s_client.get_pod_name_and_ip.return_value = {
            "name": "client-pod", "ip": "10.0.0.2"}

        self.pod_cmd.run_command_for_role(
            role="client",
            command="test-command",
            result_file="/tmp/result.txt"
        )

        self.pod_cmd.k8s_client.set_context.assert_any_call("cli-context")
        self.pod_cmd.k8s_client.get_pod_name_and_ip.assert_called_with(
            label_selector="app=client",
            namespace=self.namespace
        )
        mock_execute_with_retries.assert_called_with(
            self.pod_cmd.k8s_client.run_pod_exec_command,
            pod_name="client-pod",
            command="test-command",
            container_name="client-container",
            dest_path="/tmp/result.txt",
            namespace=self.namespace
        )

    @patch('clients.pod_command.execute_with_retries')
    def test_run_command_for_role_server(self, mock_execute_with_retries):
        self.pod_cmd.k8s_client.get_pod_name_and_ip.return_value = {
            "name": "server-pod", "ip": "10.0.0.1"}

        self.pod_cmd.run_command_for_role(
            role="server",
            command="test-command",
            result_file="/tmp/result.txt"
        )

        self.pod_cmd.k8s_client.set_context.assert_any_call("srv-context")
        self.pod_cmd.k8s_client.get_pod_name_and_ip.assert_called_with(
            label_selector="app=server",
            namespace=self.namespace
        )
        mock_execute_with_retries.assert_called_with(
            self.pod_cmd.k8s_client.run_pod_exec_command,
            pod_name="server-pod",
            command="test-command",
            container_name="server-container",
            dest_path="/tmp/result.txt",
            namespace=self.namespace
        )

    def test_run_command_for_role_invalid_role(self):
        with self.assertRaises(ValueError) as context:
            self.pod_cmd.run_command_for_role(
                role="invalid",
                command="test-command",
                result_file="/tmp/result.txt"
            )

        self.assertEqual(str(context.exception),
                         "Unsupported role: invalid")
        self.k8s_client.get_pod_name_and_ip.assert_not_called()

    def test_run_command_for_not_found_pod(self):
        self.pod_cmd.k8s_client.get_pod_name_and_ip.return_value = None

        with self.assertRaises(ValueError) as context:
            self.pod_cmd.run_command_for_role(
                role="client",
                command="test-command",
                result_file="/tmp/result.txt"
            )

        self.assertEqual(str(context.exception),
                         "No pod found for role: client")
        self.k8s_client.get_pod_name_and_ip.assert_called_with(
            label_selector="app=client",
            namespace=self.namespace
        )

    @patch('clients.pod_command.execute_with_retries')
    def test_validate(self, mock_execute_with_retries):
        # Setup return values for get_pod calls
        self.k8s_client.get_pod_name_and_ip.side_effect = [
            {"name": "client-pod", "ip": "10.0.0.2"},
            {"name": "server-pod", "ip": "10.0.0.1"}
        ]

        # Call validate
        self.pod_cmd.validate()

        # Verify context switches and pod lookups
        context_calls = [
            call("cli-context"),
            call("srv-context")
        ]
        self.k8s_client.set_context.assert_has_calls(context_calls)

        # Verify execute_with_retries calls
        execute_calls = [
            call(
                self.k8s_client.run_pod_exec_command,
                pod_name="client-pod",
                command="validate-cmd",
                container_name="client-container",
                dest_path="",
                namespace=self.namespace
            ),
            call(
                self.k8s_client.run_pod_exec_command,
                pod_name="server-pod",
                command="validate-cmd",
                container_name="server-container",
                dest_path="",
                namespace=self.namespace
            )
        ]
        mock_execute_with_retries.assert_has_calls(execute_calls)

    @patch('kubernetes.config.load_kube_config')
    @patch('clients.pod_command.execute_with_retries')
    def test_validate_empty_command(self, mock_execute_with_retries, _mock_load_kube_config):
        # Create a new PodRoleCommand instance with an empty validate_command
        self.pod_cmd = PodRoleCommand(
            cluster_cli_context="cli-context",
            cluster_srv_context="srv-context",
            server_container="server-container",
            client_container="client-container",
            server_label_selector="app=server",
            client_label_selector="app=client",
            namespace=self.namespace,
            service_name="test-service"
        )

        # Set up the mock k8s_client
        self.pod_cmd.k8s_client = self.k8s_client

        # Validate should not make any calls since validate_command is empty
        self.pod_cmd.validate()

        # Verify that no context switches or pod executions occurred
        self.k8s_client.set_context.assert_not_called()
        self.k8s_client.get_pod_name_and_ip.assert_not_called()
        mock_execute_with_retries.assert_not_called()

    def test_collect(self):
        result_dir = "/tmp/test-results"

        self.pod_cmd.collect(result_dir)

        context_calls = [
            call("cli-context"),
            call("srv-context")
        ]
        self.k8s_client.set_context.assert_has_calls(context_calls)

        collect_calls = [
            call(
                namespace=self.namespace,
                label_selector="app=client",
                result_dir=result_dir,
                role="client"
            ),
            call(
                namespace=self.namespace,
                label_selector="app=server",
                result_dir=result_dir,
                role="server"
            )
        ]
        self.k8s_client.collect_pod_and_node_info.assert_has_calls(
            collect_calls)

    def test_get_service_external_ip_success(self):
        expected_ip = "1.2.3.4"
        self.k8s_client.get_service_external_ip.return_value = expected_ip

        result = self.pod_cmd.get_service_external_ip()

        self.k8s_client.set_context.assert_called_with("srv-context")
        self.k8s_client.get_service_external_ip.assert_called_with(
            service_name="test-service",
            namespace=self.namespace
        )
        self.assertEqual(expected_ip, result)

        result = self.pod_cmd.get_service_external_ip()
        self.assertEqual(expected_ip, result)
        self.k8s_client.get_service_external_ip.assert_called_once()

    @patch('kubernetes.config.load_kube_config')
    def test_get_service_external_ip_no_service_name(self, _mock_load_kube_config):
        self.pod_cmd = PodRoleCommand(
            cluster_cli_context="cli-context",
            cluster_srv_context="srv-context",
            server_container="server-container",
            client_container="client-container",
            server_label_selector="app=server",
            client_label_selector="app=client",
            namespace=self.namespace,
            validate_command="validate-cmd",
            service_name=""
        )
        with self.assertRaises(ValueError) as context:
            self.pod_cmd.get_service_external_ip()

        self.assertEqual(str(context.exception),
                         "Service name must be provided to get the external IP.")
        self.k8s_client.get_service_external_ip.assert_not_called()

    def test_configure(self):
        pod_count = 1
        self.pod_cmd.configure(pod_count=pod_count)

        context_calls = [
            call(self.pod_cmd.cluster_cli_context),
            call(self.pod_cmd.cluster_srv_context)
        ]
        self.k8s_client.set_context.assert_has_calls(context_calls)

        wait_calls = [
            call(
                pod_count=pod_count,
                operation_timeout_in_minutes=5,
                label_selector=self.pod_cmd.client_label_selector,
                namespace=self.namespace
            ),
            call(
                pod_count=pod_count,
                operation_timeout_in_minutes=5,
                label_selector=self.pod_cmd.server_label_selector,
                namespace=self.namespace
            )
        ]
        self.k8s_client.wait_for_pods_ready.assert_has_calls(wait_calls)

    def test_configure_with_labels(self):
        pod_count = 2
        custom_label = "app=custom"

        self.pod_cmd.configure(pod_count=pod_count, label_selector=custom_label)

        context_calls = [
            call(self.pod_cmd.cluster_cli_context),
            call(self.pod_cmd.cluster_srv_context)
        ]
        self.k8s_client.set_context.assert_has_calls(context_calls)

        wait_calls = [
            call(
                pod_count=pod_count,
                operation_timeout_in_minutes=5,
                label_selector=custom_label,
                namespace=self.namespace
            ),
            call(
                pod_count=pod_count,
                operation_timeout_in_minutes=5,
                label_selector=custom_label,
                namespace=self.namespace
            )
        ]
        self.k8s_client.wait_for_pods_ready.assert_has_calls(wait_calls)


if __name__ == '__main__':
    unittest.main()
