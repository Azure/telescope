import unittest
from unittest.mock import patch, mock_open, MagicMock
from kubernetes.client.models import (
    V1Node, V1NodeStatus, V1NodeCondition, V1NodeSpec, V1ObjectMeta, V1Taint,
    V1PersistentVolumeClaim, V1PersistentVolumeClaimStatus,
    V1VolumeAttachment, V1VolumeAttachmentStatus, V1VolumeAttachmentSpec, V1VolumeAttachmentSource,
    V1PodStatus, V1Pod, V1PodSpec, V1Namespace, V1PodCondition,
    V1Service, V1ServiceStatus, V1LoadBalancerStatus, V1LoadBalancerIngress, V1NodeSystemInfo,
    V1PodList
)
from clients.kubernetes_client import KubernetesClient
from utils.logger_config import setup_logging, get_logger

# Configure logging
setup_logging()
logger = get_logger(__name__)


class TestKubernetesClient(unittest.TestCase):

    @patch('kubernetes.config.load_kube_config')
    def setUp(self, _mock_load_kube_config): # pylint: disable=arguments-differ
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

    def _create_pod(self, namespace, name, phase, labels=None, node_name=None, container=None, pod_ip=None, host_ip=None):
        return V1Pod(
            metadata=V1ObjectMeta(name=name, namespace=namespace, labels=labels),
            status=V1PodStatus(
                phase=phase,
                conditions=[
                    V1PodCondition(
                        type="Ready",
                        status="True" if phase == "Running" else "False"
                    ),
                ],
                pod_ip=pod_ip,
                host_ip=host_ip
            ),
            spec=V1PodSpec(node_name=node_name, containers=[container])
        )

    def _create_pod_list(self, pods):
        return V1PodList(items=pods)

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

    def _create_service(self, name, namespace, external_ip):
        return V1Service(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            status=V1ServiceStatus(load_balancer=V1LoadBalancerStatus(
                ingress=[V1LoadBalancerIngress(ip=external_ip)]))
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
    def test_run_pod_exec_command(self, mock_stream, mock_open_file):
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
        mock_open_file.assert_called_with('/tmp/result.txt', 'wb')
        mock_open_file().write.assert_any_call(b'command output')
        # Check if the file was closed
        mock_open_file().close.assert_called_once()

    @patch('clients.kubernetes_client.stream')
    @patch('builtins.open', new_callable=mock_open)
    def test_run_pod_exec_command_without_dest_path(self, mock_open_file, mock_stream):
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
            dest_path='',
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
        mock_open_file.assert_not_called()

    @patch("builtins.open", new_callable=mock_open)
    @patch('clients.kubernetes_client.stream')
    def test_run_pod_exec_command_error(self, mock_stream, _mock_open_file):
        mock_resp = MagicMock()
        mock_resp.is_open.side_effect = [True, False]
        mock_resp.read_stdout.return_value = ''
        mock_resp.read_stderr.return_value = 'error output'
        mock_resp.peek_stdout.return_value = False
        mock_resp.peek_stderr.return_value = True
        mock_stream.return_value = mock_resp

        with self.assertRaises(Exception) as _context:
            self.client.run_pod_exec_command(
                pod_name='test-pod',
                container_name='test-container',
                command='echo "Hello, World!"',
                dest_path='',
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

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_nodes')
    def test_wait_for_nodes_ready(self, mock_get_ready_nodes):
        mock_get_ready_nodes.side_effect = [[], ["node1", "node2"]]
        node_count = 2
        timeout = 1

        nodes = self.client.wait_for_nodes_ready(node_count, timeout)

        self.assertEqual(mock_get_ready_nodes.call_count, 2)
        self.assertEqual(len(nodes), node_count)

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_nodes')
    def test_wait_for_nodes_ready_exception(self, mock_get_ready_nodes):
        mock_get_ready_nodes.return_value = ["node1"]
        node_count = 2
        timeout = 1
        with self.assertRaises(Exception) as context:
            self.client.wait_for_nodes_ready(node_count, timeout)
        self.assertIn("Only 1 nodes are ready, expected 2 nodes!", str(context.exception))

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_pods_by_namespace')
    def test_wait_for_pods_ready(self, mock_get_ready_pods):
        mock_get_ready_pods.side_effect = [[], ["pod1", "pod2"]]
        pod_count = 2
        timeout = 1
        namespace = "default"

        pods = self.client.wait_for_pods_ready(pod_count, timeout, namespace)

        self.assertEqual(len(pods), pod_count)
        self.assertEqual(mock_get_ready_pods.call_count, 2)

    @patch("kubernetes.client.BatchV1Api.read_namespaced_job")
    def test_wait_for_job_completed_success(self, mock_read_namespaced_job):
        job_name = "test-job"
        namespace = "default"
        mock_job = MagicMock()
        mock_job.status.succeeded = 1
        mock_job.status.failed = 0
        mock_job.metadata.name = job_name
        mock_read_namespaced_job.return_value = mock_job

        result = self.client.wait_for_job_completed(job_name, namespace)

        self.assertEqual(mock_job.status.succeeded, 1)
        self.assertEqual(mock_job.status.failed, 0)
        self.assertEqual(result, job_name)
        mock_read_namespaced_job.assert_called_once_with(
            name=job_name, namespace=namespace
        )

    @patch("kubernetes.client.BatchV1Api.read_namespaced_job")
    def test_wait_for_job_completed_failure(self, mock_read_namespaced_job):
        job_name = "test-job"
        namespace = "default"
        mock_job = MagicMock()
        mock_job.status.succeeded = 0
        mock_job.status.failed = 1
        mock_job.metadata.name = job_name
        mock_read_namespaced_job.return_value = mock_job

        with self.assertRaises(Exception) as context:
            self.client.wait_for_job_completed(job_name, namespace)
        self.assertEqual(
            f"Job '{job_name}' in namespace '{namespace}' has failed.",
            str(context.exception),
        )
        mock_read_namespaced_job.assert_called_once_with(
            name=job_name, namespace=namespace
        )

    @patch("kubernetes.client.BatchV1Api.read_namespaced_job")
    def test_wait_for_job_completed_timeout(self, mock_read_namespaced_job):
        job_name = "test-job"
        namespace = "default"
        timeout = 10
        mock_read_namespaced_job.return_value = MagicMock(
            status=MagicMock(succeeded=0, failed=0, conditions=[]),
            metadata=MagicMock(name=job_name),
        )

        with self.assertRaises(Exception) as context:
            self.client.wait_for_job_completed(job_name, namespace, timeout)
        self.assertEqual(
            f"Job '{job_name}' in namespace '{namespace}' did not complete within {timeout} seconds.",
            str(context.exception),
        )

    @patch('clients.kubernetes_client.KubernetesClient.get_pods_by_namespace')
    def test_get_daemonsets_pods_allocated_resources(self, mock_get_pods_by_namespace):
        # Create mock pods with containers and resource requests
        container1 = MagicMock()
        container1.name = "container-1"
        container1.resources.requests = {"cpu": "200m", "memory": "512Mi"}

        container2 = MagicMock()
        container2.name = "container-2"
        container2.resources.requests = {"cpu": "300m", "memory": "1024Mi"}

        mock_pod1 = MagicMock()
        mock_pod1.metadata.name = "test-pod-1"
        mock_pod1.spec.containers = [container1]

        mock_pod2 = MagicMock()
        mock_pod2.metadata.name = "test-pod-2"
        mock_pod2.spec.containers = [container2]

        # Set the return value of the mock client
        mock_get_pods_by_namespace.return_value = [mock_pod1, mock_pod2]

        # Call the function under test
        cpu_request, memory_request = self.client.get_daemonsets_pods_allocated_resources("default", "node-1")

        # Assert the expected CPU and memory requests
        self.assertEqual(cpu_request, 500)  # 200m + 300m
        self.assertEqual(memory_request, 1536 * 1024)  # 512Mi + 1024Mi in KiB

        # Verify the mock was called with the correct parameters
        mock_get_pods_by_namespace.assert_called_once_with(
          namespace='default',
          field_selector="spec.nodeName=node-1"
        )

    @patch('clients.kubernetes_client.KubernetesClient.get_pods_by_namespace')
    def test_get_daemonsets_pods_count(self, mock_get_pods_by_namespace):
        # Create mock pods
        mock_pod1 = MagicMock()
        mock_pod1.metadata.name = "test-pod-1"
        mock_pod2 = MagicMock()
        mock_pod2.metadata.name = "test-pod-2"

        # Set the return value of the mock client
        mock_get_pods_by_namespace.return_value = [mock_pod1, mock_pod2]

        # Call the function under test
        count = self.client.get_daemonsets_pods_count("default", "node-1")

        # Assert the expected count
        self.assertEqual(count, 2)

        # Verify the mock was called with the correct parameters
        mock_get_pods_by_namespace.assert_called_once_with(
            namespace='default',
            field_selector="spec.nodeName=node-1"
        )

    @patch('kubernetes.config.load_kube_config')
    def test_set_context(self, mock_load_kube_config):
        context_name = "test-context"
        self.client.set_context(context_name)
        mock_load_kube_config.assert_called_with(
            config_file=None, context=context_name)

    @patch('kubernetes.config.load_kube_config')
    def test_set_context_failure(self, mock_load_kube_config):
        context_name = "non-existent-context"
        mock_load_kube_config.side_effect = Exception("Failed to load context")

        with self.assertRaises(Exception) as context:
            self.client.set_context(context_name)

        self.assertIn(
            f"Failed to switch to context {context_name}", str(context.exception))
        mock_load_kube_config.assert_called_with(
            config_file=None, context=context_name)

    @patch('clients.kubernetes_client.KubernetesClient.get_pods_by_namespace')
    def test_get_pods_name_and_ip(self, mock_get_pods):
        labels = {"app": "test"}
        pod1 = self._create_pod(
            namespace="default", name="pod1", labels=labels, phase="Running",
            pod_ip="10.0.0.1", host_ip="192.168.1.1")
        pod2 = self._create_pod(
            namespace="default", name="pod2", labels=labels, phase="Running",
            pod_ip="10.0.0.2", host_ip="192.168.1.2")
        mock_get_pods.return_value = [pod1, pod2]
        expected = [
            {"name": "pod1", "ip": "10.0.0.1", "node_ip": "192.168.1.1"},
            {"name": "pod2", "ip": "10.0.0.2", "node_ip": "192.168.1.2"}
        ]

        result = self.client.get_pods_name_and_ip(
            label_selector="app=test", namespace="default")
        self.assertEqual(result, expected)
        mock_get_pods.assert_called_with(
            namespace="default", label_selector="app=test")

    @patch('kubernetes.client.CoreV1Api.list_namespaced_pod')
    def test_get_pod_name_and_ip(self, mock_list_namespaced_pod):
        pod = self._create_pod(
            namespace="default", name="pod1", labels={"app": "test"}, phase="Running",
            pod_ip="10.0.0.1", host_ip="192.168.1.1")
        pod_list = self._create_pod_list([pod])
        mock_list_namespaced_pod.return_value = pod_list
        expected = {"name": "pod1", "ip": "10.0.0.1", "node_ip": "192.168.1.1"}

        result = self.client.get_pod_name_and_ip(
            label_selector="app=test", namespace="default")
        self.assertEqual(result, expected)
        mock_list_namespaced_pod.assert_called_with(
            namespace="default", label_selector="app=test", field_selector=None)

    @patch('kubernetes.client.CoreV1Api.list_namespaced_pod')
    def test_get_pod_name_and_ip_no_pods(self, mock_list_namespaced_pod):
        mock_list_namespaced_pod.return_value = V1PodList(items=[])

        with self.assertRaises(Exception) as context:
            self.client.get_pod_name_and_ip(
                label_selector="app=test", namespace="default")

        self.assertIn("No pod found with label: app=test and namespace: default", str(
            context.exception))

    @patch('kubernetes.client.CoreV1Api.read_namespaced_service')
    def test_get_service_external_ip_success(self, mock_read_namespaced_service):
        expected_ip = "1.2.3.4"
        service = self._create_service(
            name="my-service", namespace="default", external_ip=expected_ip)
        mock_read_namespaced_service.return_value = service

        external_ip = self.client.get_service_external_ip(
            "my-service", namespace="default")
        self.assertEqual(external_ip, expected_ip)
        mock_read_namespaced_service.assert_called_once_with(
            "my-service", "default")

    @patch('kubernetes.client.CoreV1Api.read_namespaced_service')
    def test_get_service_external_ip_no_ingress(self, mock_read_namespaced_service):
        service = self._create_service(
            name="my-service", namespace="default", external_ip=None)
        mock_read_namespaced_service.return_value = service

        external_ip = self.client.get_service_external_ip(
            "my-service", namespace="default")
        self.assertIsNone(external_ip)
        mock_read_namespaced_service.assert_called_once_with(
            "my-service", "default")

    @patch('kubernetes.client.CoreV1Api.list_namespaced_pod')
    def test_get_pod_details(self, mock_list_namespaced_pod):
        pod = self._create_pod(
            namespace="default",
            name="test-pod",
            phase="Running",
            labels={"app": "test"},
            node_name="test-node",
            pod_ip="10.0.0.1",
            container={"name": "test-container"}
        )
        pod_list = self._create_pod_list([pod])
        mock_list_namespaced_pod.return_value = pod_list
        expected = [{
            "name": "test-pod",
            "labels": {"app": "test"},
            "node_name": "test-node",
            "ip": "10.0.0.1",
            "status": "Running",
            "spec": pod.spec.to_dict(),
        }]

        result = self.client.get_pod_details(
            namespace="default", label_selector="app=test")
        self.assertEqual(result, expected)

    @patch('kubernetes.client.CoreV1Api.read_node')
    def test_get_node_details(self, mock_read_node):
        labels = {
            "topology.kubernetes.io/region": "us-east-1",
            "topology.kubernetes.io/zone": "us-east-1a",
            "node.kubernetes.io/instance-type": "t3.large"
        }
        node = V1Node(
            metadata=V1ObjectMeta(
                name="test-node",
                labels=labels,
            ),
            status=V1NodeStatus(
                allocatable={"cpu": "2", "memory": "4Gi"},
                capacity={"cpu": "2", "memory": "4Gi"},
                node_info=V1NodeSystemInfo(
                    architecture="amd64",
                    boot_id="1234567890abcdef",
                    container_runtime_version="docker://20.10.7",
                    kernel_version="5.4.0-80-generic",
                    kubelet_version="1.25.0",
                    machine_id="1234567890abcdef",
                    operating_system="linux",
                    os_image="Ubuntu 20.04.3 LTS",
                    system_uuid="12345678-1234-5678-1234-123456789abc",
                    kube_proxy_version="v1.25.0",
                )
            ),
        )
        mock_read_node.return_value = node
        expected = {
            "name": "test-node",
            "labels": labels,
            "region": "us-east-1",
            "zone": "us-east-1a",
            "instance_type": "t3.large",
            "allocatable": {"cpu": "2", "memory": "4Gi"},
            "capacity": {"cpu": "2", "memory": "4Gi"},
            "node_info": node.status.node_info.to_dict()
        }

        result = self.client.get_node_details("test-node")
        self.assertEqual(result, expected)

    @patch('kubernetes.client.CoreV1Api.read_node')
    @patch('kubernetes.client.CoreV1Api.list_namespaced_pod')
    @patch('clients.kubernetes_client.save_info_to_file')
    def test_collect_pod_and_node_info(self, mock_save_info, mock_list_namespaced_pod, mock_read_node):
        pod = self._create_pod(
            namespace="default",
            name="test-pod",
            phase="Running",
            labels={"app": "test"},
            node_name="test-node",
            pod_ip="10.0.0.1",
            container={"name": "test-container"}
        )
        pod_list = self._create_pod_list([pod])
        mock_list_namespaced_pod.return_value = pod_list
        labels = {
            "topology.kubernetes.io/region": "us-east-1",
            "topology.kubernetes.io/zone": "us-east-1a",
            "node.kubernetes.io/instance-type": "t3.large"
        }
        node = V1Node(
            metadata=V1ObjectMeta(
                name="test-node",
                labels=labels,
            ),
            status=V1NodeStatus(
                allocatable={"cpu": "2", "memory": "4Gi"},
                capacity={"cpu": "2", "memory": "4Gi"},
                node_info=V1NodeSystemInfo(
                    architecture="amd64",
                    boot_id="1234567890abcdef",
                    container_runtime_version="docker://20.10.7",
                    kernel_version="5.4.0-80-generic",
                    kubelet_version="1.25.0",
                    machine_id="1234567890abcdef",
                    operating_system="linux",
                    os_image="Ubuntu 20.04.3 LTS",
                    system_uuid="12345678-1234-5678-1234-123456789abc",
                    kube_proxy_version="v1.25.0",
                )
            ),
        )
        mock_read_node.return_value = node
        expected_info = [{
            "pod": {
                "name": "test-pod",
                "labels": {"app": "test"},
                "node_name": "test-node",
                "ip": "10.0.0.1",
                "status": "Running",
                "spec": pod.spec.to_dict(),
            },
            "node": {
                "name": "test-node",
                "labels": labels,
                "region": "us-east-1",
                "zone": "us-east-1a",
                "instance_type": "t3.large",
                "allocatable": {"cpu": "2", "memory": "4Gi"},
                "capacity": {"cpu": "2", "memory": "4Gi"},
                "node_info": node.status.node_info.to_dict()
            }
        }]

        self.client.collect_pod_and_node_info(
            namespace="default",
            label_selector="app=test",
            result_dir="/tmp",
            role="test"
        )

        mock_list_namespaced_pod.assert_called_with(
            namespace="default", label_selector="app=test", field_selector=None)
        mock_read_node.assert_called_with("test-node")
        mock_save_info.assert_called_with(
            expected_info, "/tmp/test_pod_node_info.json")


if __name__ == '__main__':
    unittest.main()
