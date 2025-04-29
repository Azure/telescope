import unittest
from unittest.mock import patch, mock_open, MagicMock
from kubernetes.client.models import (
    V1Node, V1NodeStatus, V1NodeCondition, V1NodeSpec, V1ObjectMeta, V1Taint,
    V1PersistentVolumeClaim, V1PersistentVolumeClaimStatus,
    V1VolumeAttachment, V1VolumeAttachmentStatus, V1VolumeAttachmentSpec, V1VolumeAttachmentSource,
    V1PodStatus, V1Pod, V1PodSpec, V1Namespace, V1PodCondition, V1Deployment, V1ObjectMeta
)
from clients.kubernetes_client import KubernetesClient

class TestKubernetesClient(unittest.TestCase):

    @patch('kubernetes.config.load_kube_config')
    def setUp(self, mock_load_kube_config):  # pylint: disable=unused-argument, arguments-differ
        self.client = KubernetesClient()
        return super().setUp()

    def _create_node(self, name, ready_status, network_unavailable_status=None, unschedulable=False, taints=None):
        conditions = [V1NodeCondition(type="Ready", status=ready_status)]
        if network_unavailable_status is not None:
            conditions.append(V1NodeCondition(type="NetworkUnavailable", status=network_unavailable_status))
        return V1Node(
            metadata=V1ObjectMeta(name=name),
            status=V1NodeStatus(conditions=conditions),
            spec=V1NodeSpec(unschedulable=unschedulable, taints=taints)
        )

    @patch('clients.kubernetes_client.KubernetesClient.get_nodes')
    def test_get_ready_nodes_with_network_unavailable(self, mock_get_nodes):
        # Mock nodes
        # Nodes ready to be scheduled
        node_ready_network_available = self._create_node(name="node_ready_network_available", ready_status="True", network_unavailable_status="False")
        node_ready_no_network_condition = self._create_node(name="node_ready_no_network_condition", ready_status="True")
        node_ready_taint_no_effect = self._create_node(
            name="node_ready_taint_no_effect", ready_status="True", taints=[V1Taint(key="node.cloudprovider.kubernetes.io/shutdown", effect="")])
        # Nodes NOT ready to be scheduled
        node_not_ready = self._create_node(name="node_not_ready", ready_status="False")
        node_ready_network_unavailable = self._create_node(name="node_ready_network_unavailable", ready_status="True", network_unavailable_status="True")
        node_ready_unschedulable_true = self._create_node(name="node_ready_unschedulable", ready_status="True", unschedulable=True)
        node_ready_shutdown_taint = self._create_node(
            name="node_ready_shutdown_taint", ready_status="True", taints=[V1Taint(key="node.cloudprovider.kubernetes.io/shutdown", effect="NoSchedule")])


        mock_get_nodes.return_value = [
            node_not_ready,
            node_ready_network_available,
            node_ready_network_unavailable,
            node_ready_no_network_condition,
            node_ready_unschedulable_true,
            node_ready_shutdown_taint,
            node_ready_taint_no_effect
        ]

        ready_nodes = self.client.get_ready_nodes()

        self.maxDiff = None # pylint: disable=invalid-name
        self.assertCountEqual(ready_nodes,
            [node_ready_network_available, node_ready_no_network_condition, node_ready_taint_no_effect]
        )

    def _create_namespace(self, name):
        return V1Namespace(metadata=V1ObjectMeta(name=name))

    def _create_pod(self, namespace, name, phase, labels=None):
        return V1Pod(
            metadata=V1ObjectMeta(name=name, namespace=namespace, labels=labels),
            status=V1PodStatus(
                phase=phase,
                conditions=[
                    V1PodCondition(
                        type="Ready", 
                        status="True" if phase == "Running" else "False"
                    ),
                ]
            ),
            spec=V1PodSpec(containers=[])
        )

    def _create_pvc(self, name, namespace, phase):
        return V1PersistentVolumeClaim(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            status=V1PersistentVolumeClaimStatus(phase=phase)
        )

    def _create_volume_attachment(self, name, namespace, phase, attacher, node_name):
        return V1VolumeAttachment(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            spec=V1VolumeAttachmentSpec(
                attacher=attacher,
                node_name=node_name,
                source=V1VolumeAttachmentSource(persistent_volume_name=name)),
            status=V1VolumeAttachmentStatus(attached=phase)
        )

    @patch("kubernetes.client.CoreV1Api.create_namespace")
    @patch("kubernetes.client.CoreV1Api.read_namespace")
    def test_create_existing_namespace(self, mock_read_namespace, mock_create_namespace):
        name = "test-namespace"
        mock_namespace = self._create_namespace(name)
        mock_read_namespace.return_value = mock_namespace

        namespace = self.client.create_namespace(name)
        self.assertEqual(namespace.metadata.name, mock_read_namespace.return_value.metadata.name)
        mock_create_namespace.assert_not_called()

    @patch('clients.kubernetes_client.KubernetesClient.create_namespace')
    @patch('clients.kubernetes_client.KubernetesClient.delete_namespace')
    def test_create_delete_namespace(self, mock_delete_namespace, mock_create_namespace):
        name = "test-namespace"
        mock_namespace = self._create_namespace(name)
        mock_create_namespace.return_value = mock_namespace

        namespace = self.client.create_namespace(name)

        self.assertEqual(namespace.metadata.name, mock_create_namespace.return_value.metadata.name)
        mock_create_namespace.assert_called_once_with(name)

        mock_delete_namespace.return_value = None
        namespace = self.client.delete_namespace(name)
        self.assertEqual(mock_delete_namespace.return_value, namespace)
        mock_delete_namespace.assert_called_once_with(name)

    @patch('clients.kubernetes_client.KubernetesClient.get_pods_by_namespace')
    def test_get_ready_pods_by_namespace(self, mock_get_pods_by_namespace):
        namespace = "test-namespace"
        running_pods = 10
        pending_pods = 5
        labels = {"app": "nginx"}

        mock_get_pods_by_namespace.return_value = [
            self._create_pod(namespace=namespace, name=f"pod-{i}", phase="Running", labels=labels) for i in range(running_pods)
        ]
        mock_get_pods_by_namespace.return_value.extend(
            [self._create_pod(namespace=namespace, name=f"pod-{i}", phase="Pending", labels=labels) for i in range(running_pods, pending_pods + running_pods)]
        )

        self.assertEqual(len(mock_get_pods_by_namespace.return_value), running_pods + pending_pods)

        expected_pods = [pod for pod in mock_get_pods_by_namespace.return_value if pod.status.phase == "Running"]
        returned_pods = self.client.get_ready_pods_by_namespace(namespace=namespace, label_selector="app=nginx")

        for pod in returned_pods:
            self.assertEqual(pod.metadata.labels, labels)
            self.assertEqual(pod.status.phase, "Running")
            self.assertEqual(pod.status.conditions[0].type, "Ready")
            self.assertEqual(pod.status.conditions[0].status, "True")

        mock_get_pods_by_namespace.assert_called_once_with(namespace=namespace, label_selector="app=nginx", field_selector=None)
        self.assertCountEqual(returned_pods, expected_pods)

    @patch('clients.kubernetes_client.KubernetesClient.get_persistent_volume_claims_by_namespace')
    def test_get_bound_persistent_volume_claims_by_namespace(self, mock_get_persistent_volume_claims_by_namespace):
        namespace = "test-namespace"
        bound_claims = 10
        pending_claims = 5
        mock_get_persistent_volume_claims_by_namespace.return_value = [
            self._create_pvc(name=f"pvc-{i}", namespace=namespace, phase="Bound") for i in range(bound_claims)
        ]
        mock_get_persistent_volume_claims_by_namespace.return_value.extend(
            self._create_pvc(name=f"pvc-{i}", namespace=namespace, phase="Pending") for i in range(bound_claims, pending_claims + bound_claims))

        self.assertEqual(len(mock_get_persistent_volume_claims_by_namespace.return_value), bound_claims + pending_claims)

        expected_claims = [claim for claim in mock_get_persistent_volume_claims_by_namespace.return_value if claim.status.phase == "Bound"]
        returned_claims = self.client.get_bound_persistent_volume_claims_by_namespace(namespace=namespace)
        self.assertCountEqual(returned_claims, expected_claims)
        mock_get_persistent_volume_claims_by_namespace.assert_called_once_with(namespace=namespace)

    @patch('clients.kubernetes_client.KubernetesClient.get_volume_attachments')
    def test_get_attached_volume_attachments(self, mock_get_volume_attachments):
        attached_attachments = 10
        detached_attachments = 5
        mock_get_volume_attachments.return_value = [
            self._create_volume_attachment(
                name=f"attachment-{i}", namespace="test-namespace", phase=True, attacher="csi-driver", node_name="node-{i}"
            ) for i in range(attached_attachments)
        ]
        mock_get_volume_attachments.return_value.extend(
            self._create_volume_attachment(
                name=f"attachment-{i}", namespace="test-namespace", phase=False, attacher="csi-driver", node_name="node-{i}"
            ) for i in range(attached_attachments, detached_attachments + attached_attachments))

        self.assertEqual(len(mock_get_volume_attachments.return_value), attached_attachments + detached_attachments)

        expected_volume_attachments = [attachment for attachment in mock_get_volume_attachments.return_value if attachment.status.attached]
        returned_volume_attachments = self.client.get_attached_volume_attachments()
        self.assertCountEqual(returned_volume_attachments, expected_volume_attachments)
        mock_get_volume_attachments.assert_called_once()

    @patch("builtins.open", new_callable=mock_open)
    @patch('clients.kubernetes_client.stream')
    def test_run_pod_exec_command(self, mock_stream, mock_open):
        mock_resp = MagicMock()
        mock_resp.is_open.side_effect = [True, False]
        mock_resp.read_stdout.return_value = 'command output'
        mock_resp.read_stderr.return_value = ''
        mock_resp.peek_stdout.return_value = True
        mock_resp.peek_stderr.return_value = False
        mock_stream.return_value = mock_resp

        result = self.client.run_pod_exec_command(
            pod_name='test-pod',
            container_name='test-container',
            command='echo "Hello, World!"',
            dest_path='/tmp/result.txt',
            namespace='default'
        )

        mock_stream.assert_called_with(
            self.client.api.connect_get_namespaced_pod_exec,
            name='test-pod',
            namespace='default',
            command=['/bin/sh', '-c', 'echo "Hello, World!"'],
            container='test-container',
            stderr=True, stdin=False,
            stdout=True, tty=False,
            _preload_content=False
        )
        self.assertEqual(result, 'command output')

        # Check if stdout was written to the file
        mock_open.assert_called_with('/tmp/result.txt', 'wb')
        mock_open().write.assert_any_call(b'command output')
        # Check if the file was closed
        mock_open().close.assert_called_once()

    @patch('clients.kubernetes_client.stream')
    @patch('builtins.open', new_callable=mock_open)
    def test_run_pod_exec_command_without_dest_path(self, mock_open, mock_stream):
        mock_resp = MagicMock()
        mock_resp.is_open.side_effect = [True, False]
        mock_resp.read_stdout.return_value = 'command output'
        mock_resp.read_stderr.return_value = ''
        mock_resp.peek_stdout.return_value = True
        mock_resp.peek_stderr.return_value = False
        mock_stream.return_value = mock_resp

        result = self.client.run_pod_exec_command(
            pod_name='test-pod',
            container_name='test-container',
            command='echo "Hello, World!"',
            dest_path=None,
            namespace='default'
        )

        mock_stream.assert_called_with(
            self.client.api.connect_get_namespaced_pod_exec,
            name='test-pod',
            namespace='default',
            command=['/bin/sh', '-c', 'echo "Hello, World!"'],
            container='test-container',
            stderr=True, stdin=False,
            stdout=True, tty=False,
            _preload_content=False
        )
        self.assertEqual(result, 'command output')

        # Check that the file was not opened and not written
        mock_open.assert_not_called()

    @patch("builtins.open", new_callable=mock_open)
    @patch('clients.kubernetes_client.stream')
    def test_run_pod_exec_command_error(self, mock_stream, mock_open):
        mock_resp = MagicMock()
        mock_resp.is_open.side_effect = [True, False]
        mock_resp.read_stdout.return_value = ''
        mock_resp.read_stderr.return_value = 'error output'
        mock_resp.peek_stdout.return_value = False
        mock_resp.peek_stderr.return_value = True
        mock_stream.return_value = mock_resp

        with self.assertRaises(Exception) as context:
            self.client.run_pod_exec_command(
                pod_name='test-pod',
                container_name='test-container',
                command='echo "Hello, World!"',
                dest_path=None,
                namespace='default'
            )

    @patch('clients.kubernetes_client.KubernetesClient.get_pod_logs')
    def test_get_pod_logs(self, mock_get_pod_logs):
        pod_name = "test-pod"
        namespace = "default"
        container = "test-container"
        tail_lines = 10
        expected_logs = "Sample log output"

        mock_get_pod_logs.return_value = expected_logs

        logs = self.client.get_pod_logs(pod_name=pod_name, namespace=namespace, container=container, tail_lines=tail_lines)

        # Assertions
        mock_get_pod_logs.assert_called_once_with(
            pod_name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines
        )
        self.assertEqual(logs, expected_logs)

        # Test exception handling
        mock_get_pod_logs.side_effect = Exception(f"Error getting logs for pod '{pod_name}' in namespace '{namespace}'")
        with self.assertRaises(Exception) as context:
            self.client.get_pod_logs(pod_name=pod_name, namespace=namespace)

        self.assertIn(f"Error getting logs for pod '{pod_name}' in namespace '{namespace}'", str(context.exception))

    @patch("builtins.open", new_callable=mock_open, read_data="apiVersion: v1\nmetadata:\n  name: {{DEPLOYMENT_NAME}}")
    @patch("os.path.isfile", return_value=True)
    def test_create_template_success(self, mock_isfile, mock_open_file):
        # Arrange
        template_path = "fake_path/deployment.yml"
        replacements = {"DEPLOYMENT_NAME": "test-deployment"}

        expected_output = "apiVersion: v1\nmetadata:\n  name: test-deployment"

        # Act
        result = self.client.create_template(template_path, replacements)

        # Assert
        mock_isfile.assert_called_once_with(template_path)
        mock_open_file.assert_called_once_with(template_path, "r", encoding="utf-8")
        self.assertEqual(result, expected_output)

    @patch('clients.kubernetes_client.KubernetesClient.create_deployment')
    def test_create_deployment(self, mock_create_deployment):
        template = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: test-deployment"
        namespace = "default"

        # Mock the V1Deployment object
        mock_deployment = V1Deployment(metadata=V1ObjectMeta(name="test-deployment"))
        mock_create_deployment.return_value = mock_deployment

        deployment = self.client.create_deployment(template, namespace)

        mock_create_deployment.assert_called_once_with(template, namespace)
        self.assertEqual(deployment.metadata.name, "test-deployment")

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_nodes')
    def test_wait_for_nodes_ready(self, mock_get_ready_nodes):
        mock_get_ready_nodes.side_effect = [[], ["node1", "node2"]]
        node_count = 2
        timeout = 1

        self.client.wait_for_nodes_ready(node_count, timeout)

        self.assertEqual(mock_get_ready_nodes.call_count, 2)

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_pods_by_namespace')
    def test_wait_for_pods_ready(self, mock_get_ready_pods):
        mock_get_ready_pods.side_effect = [[], ["pod1", "pod2"]]
        pod_count = 2
        timeout = 1
        namespace = "default"

        pods = self.client.wait_for_pods_ready(pod_count, timeout, namespace)

        self.assertEqual(len(pods), pod_count)
        self.assertEqual(mock_get_ready_pods.call_count, 2)

    
if __name__ == '__main__':
    unittest.main()
