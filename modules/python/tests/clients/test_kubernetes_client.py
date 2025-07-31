# pylint: disable=too-many-lines, too-many-public-methods
"""
Unit tests for KubernetesClient class
"""
import unittest
from unittest import mock
from unittest.mock import patch, mock_open, MagicMock

import requests
from kubernetes import client
from kubernetes.client.models import (
    V1Node, V1NodeStatus, V1NodeCondition, V1NodeSpec, V1ObjectMeta, V1Taint,
    V1PersistentVolumeClaim, V1PersistentVolumeClaimStatus,
    V1VolumeAttachment, V1VolumeAttachmentStatus, V1VolumeAttachmentSpec, V1VolumeAttachmentSource,
    V1PodStatus, V1Pod, V1PodSpec, V1Namespace, V1PodCondition,
    V1Service, V1ServiceStatus, V1LoadBalancerStatus, V1LoadBalancerIngress, V1NodeSystemInfo,
    V1PodList
)
from kubernetes.client.rest import ApiException

from clients.kubernetes_client import KubernetesClient
from utils.constants import UrlConstants
from utils.logger_config import setup_logging, get_logger

# Configure logging
setup_logging()
logger = get_logger(__name__)

class TestKubernetesClient(unittest.TestCase):
    """Unit tests for the KubernetesClient class covering node, pod, PVC, service,
       and GPU plugin operations.
    """
    @patch('kubernetes.config.load_kube_config')
    def setUp(self, _mock_load_kube_config): # pylint: disable=arguments-differ
        self.client = KubernetesClient()
        return super().setUp()

    def _create_node(self, name, ready_status, **kwargs):
        """
        Helper to create a V1Node with flexible optional parameters.
        """
        network_unavailable_status = kwargs.get("network_unavailable_status")
        unschedulable = kwargs.get("unschedulable", False)
        taints = kwargs.get("taints", None)
        conditions = [V1NodeCondition(type="Ready", status=ready_status)]
        if network_unavailable_status is not None:
            conditions.append(
                V1NodeCondition(
                    type="NetworkUnavailable",
                    status=network_unavailable_status
                )
            )
        return V1Node(
            metadata=V1ObjectMeta(name=name),
            status=V1NodeStatus(conditions=conditions),
            spec=V1NodeSpec(unschedulable=unschedulable, taints=taints)
        )

    @patch('clients.kubernetes_client.KubernetesClient.get_nodes')
    def test_get_ready_nodes_with_network_unavailable(self, mock_get_nodes):
        """Test getting ready nodes when network is unavailable."""
        # Mock nodes
        # Nodes ready to be scheduled
        node_ready_network_available = self._create_node(
            name="node_ready_network_available",
            ready_status="True",
            network_unavailable_status="False"
        )
        node_ready_no_network_condition = self._create_node(
            name="node_ready_no_network_condition",
            ready_status="True"
        )
        node_ready_taint_no_effect = self._create_node(
            name="node_ready_taint_no_effect",
            ready_status="True",
            taints=[V1Taint(key="node.cloudprovider.kubernetes.io/shutdown", effect="")]
        )
        # Nodes NOT ready to be scheduled
        node_not_ready = self._create_node(
            name="node_not_ready",
            ready_status="False"
        )
        node_ready_network_unavailable = self._create_node(
            name="node_ready_network_unavailable",
            ready_status="True",
            network_unavailable_status="True"
        )
        node_ready_unschedulable_true = self._create_node(
            name="node_ready_unschedulable",
            ready_status="True",
            unschedulable=True
        )
        node_ready_shutdown_taint = self._create_node(
            name="node_ready_shutdown_taint",
            ready_status="True",
            taints=[V1Taint(key="node.cloudprovider.kubernetes.io/shutdown", effect="NoSchedule")]
        )

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
        self.assertCountEqual(
            ready_nodes,
            [
                node_ready_network_available,
                node_ready_no_network_condition,
                node_ready_taint_no_effect,
            ]
        )

    def _create_namespace(self, name):
        return V1Namespace(metadata=V1ObjectMeta(name=name))

    def _create_pod(
        self,
        namespace,
        name,
        phase,
        **kwargs
    ):
        """
        Helper to create a V1Pod with flexible optional parameters.
        """
        labels = kwargs.get("labels", None)
        node_name = kwargs.get("node_name", None)
        container = kwargs.get("container", None)
        pod_ip = kwargs.get("pod_ip", None)
        host_ip = kwargs.get("host_ip", None)
        return V1Pod(
            metadata=V1ObjectMeta(
                name=name,
                namespace=namespace,
                labels=labels
            ),
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
            spec=V1PodSpec(
                node_name=node_name,
                containers=[container]
            )
        )

    def _create_pod_list(self, pods):
        return V1PodList(items=pods)

    def _create_pvc(self, name, namespace, phase):
        return V1PersistentVolumeClaim(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            status=V1PersistentVolumeClaimStatus(phase=phase)
        )

    def _create_volume_attachment(self, name, namespace, **kwargs):
        """
        Helper to create a V1VolumeAttachment with flexible optional parameters.
        Required kwargs: attached, attacher, node_name.
        Optional kwargs: persistent_volume_name.
        """
        attached = kwargs["attached"]
        attacher = kwargs["attacher"]
        node_name = kwargs["node_name"]
        persistent_volume_name = kwargs.get("persistent_volume_name", name)
        return V1VolumeAttachment(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            spec=V1VolumeAttachmentSpec(
                attacher=attacher,
                node_name=node_name,
                source=V1VolumeAttachmentSource(persistent_volume_name=persistent_volume_name)),
            status=V1VolumeAttachmentStatus(attached=attached)
        )

    def _create_service(self, name, namespace, external_ip):
        return V1Service(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            status=V1ServiceStatus(load_balancer=V1LoadBalancerStatus(
                ingress=[V1LoadBalancerIngress(ip=external_ip)]))
        )

    def test_get_app_client_returns_app_attribute(self):
        """ Test that get_app_client returns the app attribute from the client."""
        # Execute
        result = self.client.get_app_client()

        # Verify - the result should be the same object as client.app
        self.assertIs(result, self.client.app)

        # Verify it's the expected type (AppsV1Api)
        self.assertEqual(type(result).__name__, 'AppsV1Api')

    def test_get_api_client_returns_api_attribute(self):
        """ Test that get_api_client returns the api attribute from the client."""
        # Execute
        result = self.client.get_api_client()

        # Verify - the result should be the same object as client.api
        self.assertIs(result, self.client.api)

        # Verify it's the expected type (AppsV1Api)
        self.assertEqual(type(result).__name__, 'CoreV1Api')

    @patch('kubernetes.client.CoreV1Api.read_node')
    def test_describe_node(self, mock_read_node):
        """Test that describe_node calls the Kubernetes API read_node method
        with the correct node name and returns the node object."""
        # Setup
        node_name = "test-node-1"
        mock_node = MagicMock()
        mock_node.metadata.name = node_name
        mock_read_node.return_value = mock_node

        # Execute
        result = self.client.describe_node(node_name)

        # Verify
        mock_read_node.assert_called_once_with(node_name)
        self.assertEqual(result, mock_node)
        self.assertEqual(result.metadata.name, node_name)

    @patch('kubernetes.client.CoreV1Api.list_node')
    def test_get_nodes_with_label_selector(self, mock_list_node):
        """Test get_nodes method with label selector only."""
        # Setup
        label_selector = "node-role.kubernetes.io/worker=true"
        mock_node = MagicMock()
        mock_node.metadata.name = "worker-node"
        mock_node.metadata.labels = {"node-role.kubernetes.io/worker": "true"}

        mock_node_list = MagicMock()
        mock_node_list.items = [mock_node]
        mock_list_node.return_value = mock_node_list

        # Execute
        result = self.client.get_nodes(label_selector=label_selector)

        # Verify
        mock_list_node.assert_called_once_with(
            label_selector=label_selector,
            field_selector=None
        )
        self.assertEqual(result, [mock_node])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].metadata.name, "worker-node")

    @patch('kubernetes.client.CoreV1Api.list_node')
    def test_get_nodes_with_field_selector(self, mock_list_node):
        """Test get_nodes method with field selector only."""
        # Setup
        field_selector = "spec.unschedulable=false"
        mock_node = MagicMock()
        mock_node.metadata.name = "schedulable-node"
        mock_node.spec.unschedulable = False

        mock_node_list = MagicMock()
        mock_node_list.items = [mock_node]
        mock_list_node.return_value = mock_node_list

        # Execute
        result = self.client.get_nodes(field_selector=field_selector)

        # Verify
        mock_list_node.assert_called_once_with(
            label_selector=None,
            field_selector=field_selector
        )
        self.assertEqual(result, [mock_node])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].metadata.name, "schedulable-node")

    @patch('kubernetes.client.CoreV1Api.list_node')
    def test_get_nodes_with_both_selectors(self, mock_list_node):
        """Test get_nodes method with both label and field selectors."""
        # Setup
        label_selector = "node-role.kubernetes.io/control-plane="
        field_selector = "spec.unschedulable=false"

        mock_node = MagicMock()
        mock_node.metadata.name = "control-plane-node"
        mock_node.metadata.labels = {"node-role.kubernetes.io/control-plane": ""}
        mock_node.spec.unschedulable = False

        mock_node_list = MagicMock()
        mock_node_list.items = [mock_node]
        mock_list_node.return_value = mock_node_list

        # Execute
        result = self.client.get_nodes(
            label_selector=label_selector,
            field_selector=field_selector
        )

        # Verify
        mock_list_node.assert_called_once_with(
            label_selector=label_selector,
            field_selector=field_selector
        )
        self.assertEqual(result, [mock_node])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].metadata.name, "control-plane-node")

    @patch('kubernetes.client.CoreV1Api.list_node')
    def test_get_nodes_with_no_selectors(self, mock_list_node):
        """Test get_nodes method with no label or field selectors."""
        # Setup
        mock_node1 = MagicMock()
        mock_node1.metadata.name = "node-1"
        mock_node2 = MagicMock()
        mock_node2.metadata.name = "node-2"

        mock_node_list = MagicMock()
        mock_node_list.items = [mock_node1, mock_node2]
        mock_list_node.return_value = mock_node_list

        # Execute
        result = self.client.get_nodes()

        # Verify
        mock_list_node.assert_called_once_with(
            label_selector=None,
            field_selector=None
        )
        self.assertEqual(result, [mock_node1, mock_node2])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].metadata.name, "node-1")
        self.assertEqual(result[1].metadata.name, "node-2")

    @patch("kubernetes.client.CoreV1Api.create_namespace")
    @patch("kubernetes.client.CoreV1Api.read_namespace")
    def test_create_existing_namespace(self, mock_read_namespace, mock_create_namespace):
        """Test creating a namespace that already exists."""
        name = "test-namespace"
        mock_namespace = self._create_namespace(name)
        mock_read_namespace.return_value = mock_namespace

        namespace = self.client.create_namespace(name)
        self.assertEqual(namespace.metadata.name, mock_read_namespace.return_value.metadata.name)
        mock_create_namespace.assert_not_called()

    @patch('kubernetes.client.CoreV1Api.read_namespace')
    @patch('kubernetes.client.CoreV1Api.create_namespace')
    def test_create_namespace_other_api_exception_raises(
        self, mock_create_namespace, mock_read_namespace
    ):
        """Test create_namespace when read_namespace raises non-404 ApiException."""
        namespace_name = "test-namespace"

        forbidden_exception = client.rest.ApiException(
            status=403,
            reason="Forbidden"
        )
        mock_read_namespace.side_effect = forbidden_exception

        with self.assertRaises(client.rest.ApiException) as context:
            self.client.create_namespace(namespace_name)

        self.assertEqual(context.exception.status, 403)
        self.assertEqual(context.exception.reason, "Forbidden")
        mock_read_namespace.assert_called_once_with(namespace_name)
        mock_create_namespace.assert_not_called()

    @patch('kubernetes.client.CoreV1Api.read_namespace')
    @patch('kubernetes.client.CoreV1Api.create_namespace')
    def test_create_namespace_not_found_creates_new(
        self, mock_create_namespace, mock_read_namespace
    ):
        """Test create_namespace when namespace doesn't exist (404 error)."""
        # Setup
        namespace_name = "test-namespace"

        # Mock 404 exception when trying to read namespace
        mock_read_namespace.side_effect = client.rest.ApiException(
            status=404,
            reason="Not Found"
        )

        # Mock successful namespace creation
        mock_created_namespace = MagicMock()
        mock_created_namespace.metadata.name = namespace_name
        mock_create_namespace.return_value = mock_created_namespace

        # Execute
        result = self.client.create_namespace(namespace_name)

        # Verify
        mock_read_namespace.assert_called_once_with(namespace_name)
        mock_create_namespace.assert_called_once()

        # Verify the namespace object structure - fix the access pattern
        call_args = mock_create_namespace.call_args[0][0]  # Get the first positional argument
        self.assertIsInstance(call_args, client.V1Namespace)
        self.assertEqual(
            call_args.metadata.name,
            namespace_name
        )
        self.assertIsInstance(
            call_args.metadata,
            client.V1ObjectMeta
        )

        # Verify return value
        self.assertEqual(result, mock_created_namespace)
        self.assertEqual(result.metadata.name, namespace_name)

    @patch('clients.kubernetes_client.KubernetesClient.create_namespace')
    @patch('clients.kubernetes_client.KubernetesClient.delete_namespace')
    def test_create_delete_namespace(self, mock_delete_namespace, mock_create_namespace):
        """Test creating and then deleting a namespace."""
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

    @patch('kubernetes.client.CoreV1Api.delete_namespace')
    def test_delete_namespace_success(self, mock_delete_namespace):
        """Test delete_namespace method successfully deletes a namespace."""
        # Setup
        namespace_name = "test-namespace"
        mock_delete_response = MagicMock()
        mock_delete_response.metadata.name = namespace_name
        mock_delete_response.status = "Terminating"
        mock_delete_namespace.return_value = mock_delete_response

        # Execute
        result = self.client.delete_namespace(namespace_name)

        # Verify
        mock_delete_namespace.assert_called_once_with(namespace_name)
        self.assertEqual(result, mock_delete_response)
        self.assertEqual(result.metadata.name, namespace_name)

    @patch('clients.kubernetes_client.KubernetesClient.get_pods_by_namespace')
    def test_get_ready_pods_by_namespace(self, mock_get_pods_by_namespace):
        """Test getting ready pods by namespace."""
        namespace = "test-namespace"
        running_pods = 10
        pending_pods = 5
        labels = {"app": "nginx"}

        mock_get_pods_by_namespace.return_value = [
            self._create_pod(
                namespace=namespace, name=f"pod-{i}", phase="Running", labels=labels
            ) for i in range(running_pods)
        ]
        mock_get_pods_by_namespace.return_value.extend([
            self._create_pod(
                namespace=namespace,
                name=f"pod-{i}",
                phase="Pending",
                labels=labels
            ) for i in range(running_pods, pending_pods + running_pods)
        ])

        self.assertEqual(
            len(mock_get_pods_by_namespace.return_value),
            running_pods + pending_pods
        )

        expected_pods = [
            pod for pod in mock_get_pods_by_namespace.return_value
            if pod.status.phase == "Running"
        ]
        returned_pods = self.client.get_ready_pods_by_namespace(
            namespace=namespace, label_selector="app=nginx"
        )

        for pod in returned_pods:
            self.assertEqual(pod.metadata.labels, labels)
            self.assertEqual(pod.status.phase, "Running")
            self.assertEqual(pod.status.conditions[0].type, "Ready")
            self.assertEqual(pod.status.conditions[0].status, "True")

        mock_get_pods_by_namespace.assert_called_once_with(
            namespace=namespace,
            label_selector="app=nginx",
            field_selector=None
        )
        self.assertCountEqual(returned_pods, expected_pods)

    @patch('kubernetes.client.CoreV1Api.list_namespaced_pod')
    def test_get_ready_pods_covers_is_ready_pod_logic(self, mock_list_pod):
        """Test that covers _is_ready_pod through public method"""
        # Setup pods with different conditions to exercise _is_ready_pod logic
        running_ready_pod = MagicMock()
        running_ready_pod.status.phase = "Running"
        running_ready_pod.status.conditions = [
            MagicMock(type="Ready", status="True")
        ]

        running_not_ready_pod = MagicMock()
        running_not_ready_pod.status.phase = "Running"
        running_not_ready_pod.status.conditions = [
            MagicMock(type="Ready", status="False")
        ]

        pending_pod = MagicMock()
        pending_pod.status.phase = "Pending"
        pending_pod.status.conditions = []

        mock_pod_list = MagicMock()
        mock_pod_list.items = [running_ready_pod, running_not_ready_pod, pending_pod]
        mock_list_pod.return_value = mock_pod_list

        # Execute - this will call _is_ready_pod internally
        result = self.client.get_ready_pods_by_namespace("test-namespace")

        # Verify - only the ready pod should be returned
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], running_ready_pod)

    @patch('kubernetes.client.CoreV1Api.list_namespaced_persistent_volume_claim')
    def test_get_persistent_volume_claims_by_namespace(self, mock_list_pvc):
        """
        Test that get_persistent_volume_claims_by_namespace calls the Kubernetes API
        list_namespaced_persistent_volume_claim method with the correct namespace
        and returns the items from the response."""
        # Setup
        namespace = "test-namespace"
        mock_pvc1 = MagicMock()
        mock_pvc1.metadata.name = "pvc-1"
        mock_pvc1.status.phase = "Bound"

        mock_pvc2 = MagicMock()
        mock_pvc2.metadata.name = "pvc-2"
        mock_pvc2.status.phase = "Pending"

        mock_pvc_list = MagicMock()
        mock_pvc_list.items = [mock_pvc1, mock_pvc2]
        mock_list_pvc.return_value = mock_pvc_list

        # Execute
        result = self.client.get_persistent_volume_claims_by_namespace(
            namespace
        )

        # Verify
        mock_list_pvc.assert_called_once_with(namespace=namespace)
        self.assertEqual(result, [mock_pvc1, mock_pvc2])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].metadata.name, "pvc-1")
        self.assertEqual(result[1].metadata.name, "pvc-2")

    @patch(
        'clients.kubernetes_client.KubernetesClient.'
        'get_persistent_volume_claims_by_namespace'
    )
    def test_get_bound_persistent_volume_claims_by_namespace(
        self, mock_get_persistent_volume_claims_by_namespace
    ):
        """Test getting bound persistent volume claims by namespace."""
        namespace = "test-namespace"
        bound_claims = 10
        pending_claims = 5
        mock_get_persistent_volume_claims_by_namespace.return_value = [
            self._create_pvc(
                name=f"pvc-{i}",
                namespace=namespace,
                phase="Bound"
            ) for i in range(bound_claims)
        ]
        mock_get_persistent_volume_claims_by_namespace.return_value.extend(
            self._create_pvc(
                name=f"pvc-{i}",
                namespace=namespace,
                phase="Pending"
            ) for i in range(bound_claims, pending_claims + bound_claims)
        )

        self.assertEqual(
            len(mock_get_persistent_volume_claims_by_namespace.return_value),
            bound_claims + pending_claims
        )

        expected_claims = [
            claim for claim in mock_get_persistent_volume_claims_by_namespace.return_value
            if claim.status.phase == "Bound"
        ]
        returned_claims = self.client.get_bound_persistent_volume_claims_by_namespace(
            namespace=namespace
        )
        self.assertCountEqual(returned_claims, expected_claims)
        mock_get_persistent_volume_claims_by_namespace.assert_called_once_with(
            namespace=namespace
        )

    @patch('clients.kubernetes_client.KubernetesClient.get_persistent_volume_claims_by_namespace')
    @patch('kubernetes.client.CoreV1Api.delete_namespaced_persistent_volume_claim')
    def test_delete_persistent_volume_claim_by_namespace_success(
        self, mock_delete_pvc, mock_get_pvcs
    ):
        """Test successful deletion of all PVCs in a namespace."""
        # Setup
        namespace = "test-namespace"

        # Create mock PVCs
        mock_pvc1 = MagicMock()
        mock_pvc1.metadata.name = "pvc-1"
        mock_pvc2 = MagicMock()
        mock_pvc2.metadata.name = "pvc-2"

        mock_get_pvcs.return_value = [mock_pvc1, mock_pvc2]

        # Execute
        self.client.delete_persistent_volume_claim_by_namespace(namespace)

        # Verify
        mock_get_pvcs.assert_called_once_with(namespace=namespace)
        self.assertEqual(mock_delete_pvc.call_count, 2)

        # Verify each PVC deletion call
        expected_calls = [
            mock.call("pvc-1", namespace, body=client.V1DeleteOptions()),
            mock.call("pvc-2", namespace, body=client.V1DeleteOptions())
        ]
        mock_delete_pvc.assert_has_calls(expected_calls, any_order=True)

    @patch('clients.kubernetes_client.KubernetesClient.get_persistent_volume_claims_by_namespace')
    @patch('kubernetes.client.CoreV1Api.delete_namespaced_persistent_volume_claim')
    @patch('clients.kubernetes_client.logger')
    def test_delete_persistent_volume_claim_by_namespace_all_failures(
        self, mock_logger, mock_delete_pvc, mock_get_pvcs
    ):
        """Test deletion when all PVC deletions fail."""
        # Setup
        namespace = "test-namespace"

        # Create mock PVCs
        mock_pvc1 = MagicMock()
        mock_pvc1.metadata.name = "pvc-1"
        mock_pvc2 = MagicMock()
        mock_pvc2.metadata.name = "pvc-2"

        mock_get_pvcs.return_value = [mock_pvc1, mock_pvc2]

        # Configure mock to fail on all deletions
        mock_delete_pvc.side_effect = client.rest.ApiException(
            status=500, reason="Internal Server Error"
        )

        # Execute
        self.client.delete_persistent_volume_claim_by_namespace(namespace)

        # Verify
        mock_get_pvcs.assert_called_once_with(namespace=namespace)
        self.assertEqual(mock_delete_pvc.call_count, 2)

        # Verify errors were logged for both failed deletions
        self.assertEqual(mock_logger.error.call_count, 2)

        # Verify specific error messages
        error_calls = mock_logger.error.call_args_list

        # Check that we have the expected error messages for both PVCs
        pvc1_found = False
        pvc2_found = False

        for call in error_calls:
            if call.args and len(call.args) >= 2:
                # Format the message like the logger would
                formatted_msg = call.args[0] % call.args[1:] if len(call.args) > 1 else call.args[0]
                if "Error deleting PVC 'pvc-1'" in formatted_msg:
                    pvc1_found = True
                if "Error deleting PVC 'pvc-2'" in formatted_msg:
                    pvc2_found = True

        self.assertTrue(pvc1_found, "Expected error message for pvc-1 not found")
        self.assertTrue(pvc2_found, "Expected error message for pvc-2 not found")

    @patch('kubernetes.client.StorageV1Api.list_volume_attachment')
    def test_get_volume_attachments_success(self, mock_list_volume_attachment):
        """Test get_volume_attachments method returns volume attachments successfully."""
        # Setup
        mock_attachment1 = MagicMock()
        mock_attachment1.metadata.name = "pvc-attachment-1"
        mock_attachment1.spec.attacher = "csi.azuredisk.com"
        mock_attachment1.status.attached = True

        mock_attachment2 = MagicMock()
        mock_attachment2.metadata.name = "pvc-attachment-2"
        mock_attachment2.spec.attacher = "kubernetes.io/azure-disk"
        mock_attachment2.status.attached = False

        mock_attachment_list = MagicMock()
        mock_attachment_list.items = [mock_attachment1, mock_attachment2]
        mock_list_volume_attachment.return_value = mock_attachment_list

        # Execute
        result = self.client.get_volume_attachments()

        # Verify
        mock_list_volume_attachment.assert_called_once()
        self.assertEqual(result, [mock_attachment1, mock_attachment2])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].metadata.name, "pvc-attachment-1")
        self.assertEqual(result[1].metadata.name, "pvc-attachment-2")
        self.assertTrue(result[0].status.attached)
        self.assertFalse(result[1].status.attached)

    @patch(
        'clients.kubernetes_client.KubernetesClient.get_volume_attachments'
    )
    def test_get_attached_volume_attachments(self, mock_get_volume_attachments):
        """Test getting attached volume attachments."""
        attached_attachments = 10
        detached_attachments = 5
        mock_get_volume_attachments.return_value = [
            self._create_volume_attachment(
                name=f"attachment-{i}",
                namespace="test-namespace",
                attached=True,
                attacher="csi-driver",
                node_name="node-{i}"
            ) for i in range(attached_attachments)
        ]
        mock_get_volume_attachments.return_value.extend([
            self._create_volume_attachment(
                name=f"attachment-{i}",
                namespace="test-namespace",
                attached=False,
                attacher="csi-driver",
                node_name="node-{i}"
            ) for i in range(attached_attachments, detached_attachments + attached_attachments)
        ])

        self.assertEqual(
            len(mock_get_volume_attachments.return_value),
            attached_attachments + detached_attachments
        )

        expected_volume_attachments = [
            attachment for attachment in mock_get_volume_attachments.return_value
            if attachment.status.attached
        ]
        returned_volume_attachments = self.client.get_attached_volume_attachments()
        self.assertCountEqual(
            returned_volume_attachments, expected_volume_attachments
        )
        mock_get_volume_attachments.assert_called_once()

    @patch("builtins.open", new_callable=mock_open)
    @patch('clients.kubernetes_client.stream')
    def test_run_pod_exec_command(self, mock_stream, mock_open_file):
        """Test running an exec command on a pod."""
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
        """Test running an exec command on a pod without destination path."""
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
        """Test running an exec command on a pod with error response."""
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
        """Test getting pod logs."""
        pod_name = "test-pod"
        namespace = "default"
        container = "test-container"
        tail_lines = 10
        expected_logs = "Sample log output"

        mock_get_pod_logs.return_value = expected_logs

        logs = self.client.get_pod_logs(
            pod_name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines
        )

        # Assertions
        mock_get_pod_logs.assert_called_once_with(
            pod_name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines
        )
        self.assertEqual(logs, expected_logs)

        # Test exception handling
        mock_get_pod_logs.side_effect = Exception(
            f"Error getting logs for pod '{pod_name}' in namespace '{namespace}'"
        )
        with self.assertRaises(Exception) as context:
            self.client.get_pod_logs(
                pod_name=pod_name, namespace=namespace
            )

        self.assertIn(
            f"Error getting logs for pod '{pod_name}' in namespace '{namespace}'",
            str(context.exception)
        )

    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="apiVersion: v1\nmetadata:\n  name: {{DEPLOYMENT_NAME}}"
    )
    @patch("os.path.isfile", return_value=True)
    def test_create_template_success(self, mock_isfile, mock_open_file):
        """Test creating a template successfully."""
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

    @patch("os.path.isfile", return_value=False)
    def test_create_template_file_not_found(self, mock_isfile):
        """Test create_template when template file does not exist."""
        # Setup
        template_path = "nonexistent/path/template.yml"
        replacements = {"DEPLOYMENT_NAME": "test-deployment"}

        # Execute & Verify
        with self.assertRaises(FileNotFoundError) as context:
            self.client.create_template(template_path, replacements)

        # Verify error message
        expected_message = f"Template file not found: {template_path}"
        self.assertEqual(str(context.exception), expected_message)
        mock_isfile.assert_called_once_with(template_path)

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", side_effect=IOError("Disk read error"))
    def test_create_template_file_read_error(self, mock_open_file, mock_isfile):
        """Test create_template when there is a disk read error."""
        # Setup
        template_path = "unreadable/template.yml"
        replacements = {"DEPLOYMENT_NAME": "test-deployment"}

        # Execute & Verify
        with self.assertRaises(Exception) as context:
            self.client.create_template(template_path, replacements)

        # Verify error message format
        expected_message = f"Error processing template file {template_path}: Disk read error"
        self.assertEqual(str(context.exception), expected_message)
        mock_isfile.assert_called_once_with(template_path)
        mock_open_file.assert_called_once_with(template_path, "r", encoding="utf-8")

    @patch('kubernetes.client.CoreV1Api.replace_node')
    @patch('kubernetes.client.CoreV1Api.create_node')
    def test_create_node_success(self, mock_create_node, _mock_replace_node):
        """Test creating a node successfully."""
        template = """
        apiVersion: v1
        kind: Node
        metadata:
          name: test-node
        """
        mock_response = MagicMock()
        mock_response.metadata.name = "test-node"
        mock_create_node.return_value = mock_response

        result = self.client.create_node(template)
        self.assertEqual(result, "test-node")
        mock_create_node.assert_called_once()

    @patch('kubernetes.client.CoreV1Api.replace_node')
    @patch('kubernetes.client.CoreV1Api.create_node')
    def test_create_node_already_exists(self, mock_create_node, mock_replace_node):
        """Test creating a node that already exists."""
        template = """
        apiVersion: v1
        kind: Node
        metadata:
          name: existing-node
        """
        mock_create_node.side_effect = ApiException(status=409)

        result = self.client.create_node(template)
        self.assertEqual(result, "existing-node")
        mock_replace_node.assert_called_once()

    def test_create_node_invalid_kind(self):
        """Test creating a node with invalid kind."""
        template = """
        apiVersion: v1
        kind: Pod
        metadata:
          name: test-pod
        """
        with self.assertRaises(ValueError):
            self.client.create_node(template)

    def test_create_node_yaml_error(self):
        """Test creating a node with YAML parsing error."""
        template = "invalid: [unclosed"
        with self.assertRaises(Exception) as context:
            self.client.create_node(template)
        self.assertIn("Error parsing Node template", str(context.exception))

    @patch('kubernetes.client.CoreV1Api.create_node')
    def test_create_node_other_api_exception(self, mock_create_node):
        """Test creating a node with other API exception."""
        template = """
        apiVersion: v1
        kind: Node
        metadata:
          name: error-node
        """
        mock_create_node.side_effect = ApiException(status=500, reason="Internal Server Error")

        with self.assertRaises(Exception) as context:
            self.client.create_node(template)
        self.assertIn("Error creating Node", str(context.exception))

    @patch('kubernetes.client.CoreV1Api.delete_node')
    def test_delete_node_success(self, mock_delete_node):
        """Test delete_node method successfully deletes a kubelet measurement node."""
        # Setup
        node_name = "telescope-kubelet-perf-node-us-west-2a"

        # Mock
        mock_delete_node.return_value = None

        # Execute
        self.client.delete_node(node_name)

        # Verify
        mock_delete_node.assert_called_once_with(
            name=node_name,
            body=client.V1DeleteOptions()
        )

    @patch('kubernetes.client.CoreV1Api.delete_node')
    def test_delete_node_404_not_found_exception(self, mock_delete_node):
        """Test delete_node method when node is not found (404 exception path)."""
        # Setup - Node name for KubeletPodStartupTotalDuration measurement
        node_name = "telescope-pod-startup-total-node-gcp-us-central1-a"

        # Mock 404 Not Found exception
        mock_delete_node.side_effect = client.rest.ApiException(
            status=404,
            reason="Not Found"
        )

        # Execute
        self.client.delete_node(node_name)

        # Verify - 404 should be handled gracefully for Telescope cleanup
        mock_delete_node.assert_called_once_with(
            name=node_name,
            body=client.V1DeleteOptions()
        )

    @patch('kubernetes.client.CoreV1Api.delete_node')
    def test_delete_node_403_forbidden_exception(self, mock_delete_node):
        """Test delete_node method when deletion is forbidden (403 exception path)."""
        # Setup - Node name for runtime operation measurement without pull_image
        node_name = "telescope-runtime-ops-no-pull-node-azure-eastus-1"

        # Mock 403 Forbidden exception during Telescope cleanup
        mock_delete_node.side_effect = client.rest.ApiException(
            status=403,
            reason="Forbidden"
        )

        # Execute & Verify - Exception should be raised with proper error context
        with self.assertRaises(Exception) as context:
            self.client.delete_node(node_name)

        # Verify deletion was attempted
        mock_delete_node.assert_called_once_with(
            name=node_name,
            body=client.V1DeleteOptions()
        )

        # Verify proper exception handling for Telescope error reporting
        self.assertIn(f"Error deleting Node '{node_name}':", str(context.exception))
        self.assertIsInstance(context.exception.__cause__, client.rest.ApiException)
        self.assertEqual(context.exception.__cause__.status, 403)

    @patch('kubernetes.client.CoreV1Api.delete_node')
    def test_delete_node_500_internal_server_error_exception(self, mock_delete_node):
        """Test delete_node method when API server returns 500 error (exception path)."""
        # Setup - Node name for runtime operation measurement with pull_image
        node_name = "telescope-runtime-ops-pull-image-node-aws-us-east-1a"

        # Mock 500 Internal Server Error during Telescope cleanup
        mock_delete_node.side_effect = client.rest.ApiException(
            status=500,
            reason="Internal Server Error"
        )

        # Execute & Verify - Exception should be raised with proper error context
        with self.assertRaises(Exception) as context:
            self.client.delete_node(node_name)

        # Verify deletion was attempted
        mock_delete_node.assert_called_once_with(
            name=node_name,
            body=client.V1DeleteOptions()
        )

        # Verify proper exception handling for Telescope error reporting
        self.assertIn(f"Error deleting Node '{node_name}':", str(context.exception))
        self.assertIsInstance(context.exception.__cause__, client.rest.ApiException)
        self.assertEqual(context.exception.__cause__.status, 500)

    @patch('kubernetes.client.CoreV1Api.delete_node')
    def test_delete_node_409_conflict_exception(self, mock_delete_node):
        """
        Test delete_node method when deletion conflicts with current state (409 exception path).
        """
        # Setup - Node name for KubeletPodStartupDuration measurement
        node_name = "telescope-pod-startup-duration-node-gcp-europe-west1-b"

        # Mock 409 Conflict exception during Telescope cleanup
        mock_delete_node.side_effect = client.rest.ApiException(
            status=409,
            reason="Conflict"
        )

        # Execute & Verify - Exception should be raised with proper error context
        with self.assertRaises(Exception) as context:
            self.client.delete_node(node_name)

        # Verify deletion was attempted
        mock_delete_node.assert_called_once_with(
            name=node_name,
            body=client.V1DeleteOptions()
        )

        # Verify proper exception handling for Telescope error reporting
        self.assertIn(f"Error deleting Node '{node_name}':", str(context.exception))
        self.assertIsInstance(context.exception.__cause__, client.rest.ApiException)
        self.assertEqual(context.exception.__cause__.status, 409)

    @patch('kubernetes.client.CoreV1Api.delete_node')
    def test_delete_node_timeout_exception(self, mock_delete_node):
        """Test delete_node method when deletion times out (408 exception path)."""
        # Setup - Node name for cross-cloud kubelet runtime operation measurement
        node_name = "telescope-runtime-ops-cross-cloud-measurement-node"

        # Mock 408 Request Timeout exception during Telescope cleanup
        mock_delete_node.side_effect = client.rest.ApiException(
            status=408,
            reason="Request Timeout"
        )

        # Execute & Verify - Exception should be raised with proper error context
        with self.assertRaises(Exception) as context:
            self.client.delete_node(node_name)

        # Verify deletion was attempted
        mock_delete_node.assert_called_once_with(
            name=node_name,
            body=client.V1DeleteOptions()
        )

        # Verify proper exception handling for Telescope error reporting
        self.assertIn(f"Error deleting Node '{node_name}':", str(context.exception))
        self.assertIsInstance(context.exception.__cause__, client.rest.ApiException)
        self.assertEqual(context.exception.__cause__.status, 408)

        # Verify timeout error is properly chained for ADO pipeline reporting
        self.assertIn("Request Timeout", str(context.exception.__cause__))

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_nodes')
    @patch("time.sleep", return_value=None)
    def test_wait_for_nodes_ready(self, mock_sleep, mock_get_ready_nodes):
        """Test waiting for nodes to be ready."""
        mock_get_ready_nodes.side_effect = [[], ["node1", "node2"]]
        node_count = 2
        timeout = 0.01

        nodes = self.client.wait_for_nodes_ready(node_count, timeout)

        self.assertEqual(mock_get_ready_nodes.call_count, 2)
        self.assertEqual(len(nodes), node_count)
        self.assertEqual(nodes, ["node1", "node2"])
        self.assertIsInstance(nodes, list)
        mock_sleep.assert_called()

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_nodes')
    @patch("time.sleep", return_value=None)
    def test_wait_for_nodes_ready_exception(self, mock_sleep, mock_get_ready_nodes):
        """Test waiting for nodes ready with exception when timeout occurs."""
        mock_get_ready_nodes.return_value = ["node1"]
        node_count = 2
        timeout = 0.01

        with self.assertRaises(Exception) as context:
            self.client.wait_for_nodes_ready(node_count, timeout)

        self.assertIn("Only 1 nodes are ready, expected 2 nodes!", str(context.exception))
        mock_sleep.assert_called()

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_pods_by_namespace')
    @patch("time.sleep", return_value=None)
    def test_wait_for_pods_ready(self, mock_sleep, mock_get_ready_pods):
        """Test waiting for pods to be ready."""
        mock_get_ready_pods.side_effect = [[], ["pod1", "pod2"]]
        pod_count = 2
        timeout = 0.01
        namespace = "default"

        pods = self.client.wait_for_pods_ready(pod_count, timeout, namespace)

        self.assertEqual(len(pods), pod_count)
        self.assertEqual(mock_get_ready_pods.call_count, 2)
        mock_sleep.assert_called()

    @patch('clients.kubernetes_client.KubernetesClient.get_ready_pods_by_namespace')
    @patch('time.sleep', return_value=None)
    def test_wait_for_pods_ready_raises_exception_on_timeout(
        self, mock_sleep, mock_get_ready_pods
    ):
        """Test that wait_for_pods_ready raises an exception if the expected number
        of pods are not ready in time."""
        mock_get_ready_pods.return_value = ["pod1"]

        pod_count = 2
        timeout_minutes = 0.001  # Very short timeout to trigger exception quickly

        with self.assertRaises(Exception) as context:
            self.client.wait_for_pods_ready(
                pod_count,
                timeout_minutes,
                namespace="default",
                label_selector="app=test"
            )

        self.assertIn("Only 1 pods are ready, expected 2 pods!", str(context.exception))
        self.assertGreaterEqual(mock_get_ready_pods.call_count, 1)
        mock_sleep.assert_called()

    @patch("clients.kubernetes_client.KubernetesClient.wait_for_pods_ready")
    @patch("clients.kubernetes_client.KubernetesClient.get_pods_by_namespace")
    def test_wait_for_labeled_pods_ready_success(
        self, mock_get_pods, mock_wait_for_pods
    ):
        """Test waiting for labeled pods to be ready - success case."""
        label_selector = "app=test-app"
        namespace = "test-namespace"
        timeout_in_minutes = 5

        # Mock pods found with the label selector
        mock_pods = ["pod1", "pod2", "pod3"]
        mock_get_pods.return_value = mock_pods
        mock_wait_for_pods.return_value = None

        # Execute
        self.client.wait_for_labeled_pods_ready(
            label_selector=label_selector,
            namespace=namespace,
            timeout_in_minutes=timeout_in_minutes,
        )

        # Verify
        mock_get_pods.assert_called_once_with(
            namespace=namespace, label_selector=label_selector
        )
        mock_wait_for_pods.assert_called_once_with(
            pod_count=3,
            operation_timeout_in_minutes=timeout_in_minutes,
            namespace=namespace,
            label_selector=label_selector,
        )

    @patch("clients.kubernetes_client.KubernetesClient.get_pods_by_namespace")
    def test_wait_for_labeled_pods_ready_no_pods_found(self, mock_get_pods):
        """Test waiting for labeled pods when no pods are found with the selector."""
        label_selector = "app=nonexistent-app"
        namespace = "test-namespace"

        # Mock no pods found
        mock_get_pods.return_value = []

        # Execute and verify exception
        with self.assertRaises(Exception) as context:
            self.client.wait_for_labeled_pods_ready(
                label_selector=label_selector, namespace=namespace
            )

        expected_message = (
            f"No pods found with selector '{label_selector}' in namespace '{namespace}'"
        )
        self.assertEqual(str(context.exception), expected_message)

        mock_get_pods.assert_called_once_with(
            namespace=namespace, label_selector=label_selector
        )

    @patch("clients.kubernetes_client.KubernetesClient.wait_for_pods_ready")
    @patch("clients.kubernetes_client.KubernetesClient.get_pods_by_namespace")
    def test_wait_for_labeled_pods_ready_wait_fails(
        self, mock_get_pods, mock_wait_for_pods
    ):
        """Test waiting for labeled pods when wait_for_pods_ready fails."""
        label_selector = "app=failing-app"
        namespace = "test-namespace"

        # Mock pods found
        mock_pods = ["pod1", "pod2"]
        mock_get_pods.return_value = mock_pods

        # Mock wait_for_pods_ready raising an exception
        expected_error = "Only 1 pods are ready, expected 2 pods!"
        mock_wait_for_pods.side_effect = Exception(expected_error)

        # Execute and verify exception is propagated
        with self.assertRaises(Exception) as context:
            self.client.wait_for_labeled_pods_ready(
                label_selector=label_selector, namespace=namespace
            )

        self.assertEqual(str(context.exception), expected_error)

        mock_get_pods.assert_called_once_with(
            namespace=namespace, label_selector=label_selector
        )
        mock_wait_for_pods.assert_called_once_with(
            pod_count=2,
            operation_timeout_in_minutes=5,
            namespace=namespace,
            label_selector=label_selector,
        )

    @patch("time.sleep", return_value=None)
    @patch("clients.kubernetes_client.KubernetesClient.get_pods_by_namespace")
    def test_wait_for_pods_completed_success(self, mock_get_pods, mock_sleep):
        """Test wait_for_pods_completed when all pods complete successfully."""
        label_selector = "app=test"
        namespace = "default"
        pod1 = self._create_pod(
            namespace="default",
            name="pod1",
            phase="Pending",
        )
        pod2 = self._create_pod(
            namespace="default",
            name="pod2",
            phase="Succeeded",
        )
        pod3 = self._create_pod(
            namespace="default",
            name="pod3",
            phase="Succeeded",
        )
        mock_get_pods.side_effect = [
            [pod1, pod2, pod3],
            [pod2, pod3],
        ]
        result = self.client.wait_for_pods_completed(
            label_selector, namespace, timeout=1
        )
        self.assertEqual(result, [pod2, pod3])
        self.assertGreaterEqual(mock_get_pods.call_count, 2)
        mock_sleep.assert_called()

    @patch("time.sleep", return_value=None)
    @patch("clients.kubernetes_client.KubernetesClient.get_pods_by_namespace")
    def test_wait_for_pods_completed_timeout(self, mock_get_pods, mock_sleep):
        """Test wait_for_pods_completed raises exception on timeout."""
        label_selector = "app=test"
        namespace = "default"
        pod1 = self._create_pod(
            namespace="default",
            name="pod1",
            phase="Pending",
        )
        mock_get_pods.return_value = [pod1]
        with self.assertRaises(Exception) as context:
            self.client.wait_for_pods_completed(label_selector, namespace, timeout=0.01)
        self.assertIn(
            f"Pods with label '{label_selector}' in namespace '{namespace}' did not complete",
            str(context.exception),
        )
        mock_sleep.assert_called()

    @patch("clients.kubernetes_client.KubernetesClient.get_pods_by_namespace")
    def test_wait_for_pods_completed_no_pods(self, mock_get_pods):
        """Test wait_for_pods_completed raises exception if no pods found."""
        label_selector = "app=none"
        namespace = "default"
        mock_get_pods.return_value = []
        with self.assertRaises(Exception) as context:
            self.client.wait_for_pods_completed(label_selector, namespace, timeout=1)
        self.assertIn(
            f"No pods found with label '{label_selector}' in namespace '{namespace}'.",
            str(context.exception),
        )
        mock_get_pods.assert_called_once_with(
            namespace=namespace, label_selector=label_selector
        )

    @patch("kubernetes.client.BatchV1Api.read_namespaced_job")
    def test_wait_for_job_completed_success(self, mock_read_job):
        """Test waiting for job completion when job succeeds."""
        job_name = "successful-job"
        namespace = "default"

        mock_metadata = MagicMock()
        mock_metadata.name = job_name  # Explicitly set the name attribute

        mock_status = MagicMock()
        mock_status.succeeded = 1
        mock_status.failed = 0

        mock_job = MagicMock()
        mock_job.status = mock_status
        mock_job.metadata = mock_metadata

        mock_read_job.return_value = mock_job

        result = self.client.wait_for_job_completed(job_name, namespace)
        self.assertEqual(result, job_name)
        mock_read_job.assert_called_once_with(name=job_name, namespace=namespace)

    @patch("kubernetes.client.BatchV1Api.read_namespaced_job")
    def test_wait_for_job_completed_failure(self, mock_read_namespaced_job):
        """Test waiting for job completion when job has failed."""
        job_name = "test-job"
        namespace = "default"
        mock_status = MagicMock()
        mock_status.succeeded = 0
        mock_status.failed = 1
        mock_job = MagicMock()
        mock_job.status = mock_status
        mock_metadata = MagicMock()
        mock_metadata.name = job_name
        mock_job.metadata = mock_metadata
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
    @patch("time.sleep", return_value=None)  # Mock sleep to return immediately
    def test_wait_for_job_completed_timeout(
        self, mock_sleep, mock_read_namespaced_job
    ):
        """Test waiting for job completion when timeout occurs."""
        job_name = "test-job"
        namespace = "default"
        timeout = 0.01  # Very short timeout

        mock_read_namespaced_job.return_value = MagicMock(
            status=MagicMock(succeeded=0, failed=0, conditions=[]),
            metadata=MagicMock(name=job_name),
        )

        with self.assertRaises(Exception) as context:
            self.client.wait_for_job_completed(job_name, namespace, timeout)

        self.assertEqual(
            f"Job '{job_name}' in namespace '{namespace}' did not complete "
            f"within {timeout} seconds.",
            str(context.exception),
        )

        # Verify sleep was called but didn't actually wait
        mock_sleep.assert_called()

    @patch('kubernetes.client.BatchV1Api.read_namespaced_job')
    def test_wait_for_job_completed_job_not_found(self, mock_read_job):
        """Test that wait_for_job_completed raises an exception when the job is not found (404)."""
        # Simulate 404 Not Found error
        mock_read_job.side_effect = client.rest.ApiException(status=404, reason="Not Found")

        job_name = "nonexistent-job"
        namespace = "default"

        with self.assertRaises(Exception) as context:
            self.client.wait_for_job_completed(job_name, namespace=namespace, timeout=1)

        self.assertIn(
            f"Job '{job_name}' not found in namespace '{namespace}'.",
            str(context.exception)
        )
        self.assertIsInstance(context.exception.__cause__, client.rest.ApiException)
        self.assertEqual(context.exception.__cause__.status, 404)
        mock_read_job.assert_called()

    @patch('kubernetes.client.BatchV1Api.read_namespaced_job')
    def test_wait_for_job_completed_unexpected_api_exception(
        self, mock_read_job
    ):
        """Test that wait_for_job_completed re-raises unexpected API exceptions (not 404)."""
        # Simulate 500 Internal Server Error
        mock_read_job.side_effect = client.rest.ApiException(
            status=500, reason="Internal Server Error"
        )

        job_name = "failing-job"
        namespace = "default"

        with self.assertRaises(client.rest.ApiException) as context:
            self.client.wait_for_job_completed(
                job_name, namespace=namespace, timeout=1
            )

        self.assertEqual(context.exception.status, 500)
        self.assertEqual(context.exception.reason, "Internal Server Error")
        mock_read_job.assert_called()

    @patch(
        'clients.kubernetes_client.KubernetesClient.get_pods_by_namespace'
    )
    def test_get_daemonsets_pods_allocated_resources(
        self, mock_get_pods_by_namespace
    ):
        """Test getting allocated resources for daemonset pods."""
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
        cpu_request, memory_request = (
            self.client.get_daemonsets_pods_allocated_resources("default", "node-1")
        )

        # Assert the expected CPU and memory requests
        self.assertEqual(cpu_request, 500)  # 200m + 300m
        self.assertEqual(memory_request, 1536 * 1024)  # 512Mi + 1024Mi in KiB

        # Verify the mock was called with the correct parameters
        mock_get_pods_by_namespace.assert_called_once_with(
          namespace='default',
          field_selector="spec.nodeName=node-1"
        )

    @patch('kubernetes.config.load_kube_config')
    def test_set_context(self, mock_load_kube_config):
        """Test setting Kubernetes context."""
        context_name = "test-context"
        self.client.set_context(context_name)
        mock_load_kube_config.assert_called_with(
            config_file=None, context=context_name)

    @patch('kubernetes.config.load_kube_config')
    def test_set_context_failure(self, mock_load_kube_config):
        """Test setting Kubernetes context with failure."""
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
        """Test getting pod names and IPs."""
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
        """Test getting pod name and IP."""
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
        """Test getting pod name and IP when no pods are found."""
        mock_list_namespaced_pod.return_value.items = []

        with self.assertRaises(Exception) as context:
            self.client.get_pod_name_and_ip(label_selector="app=test", namespace="default")

        self.assertIn(
            "No pod found with label: app=test and namespace: default",
            str(context.exception)
        )

    @patch('kubernetes.client.CoreV1Api.read_namespaced_service')
    def test_get_service_external_ip_success(self, mock_read_namespaced_service):
        """Test getting service external IP successfully."""
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
        """Test getting service external IP when no ingress is available."""
        service = self._create_service(
            name="my-service", namespace="default", external_ip=None)
        mock_read_namespaced_service.return_value = service
        service.status.load_balancer.ingress = None

        external_ip = self.client.get_service_external_ip(
            "my-service", namespace="default")
        self.assertIsNone(external_ip)
        mock_read_namespaced_service.assert_called_once_with(
            "my-service", "default")

    @patch('kubernetes.client.CoreV1Api.list_namespaced_pod')
    def test_get_pod_details(self, mock_list_namespaced_pod):
        """Test getting pod details."""
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
        """Test getting node details."""
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
    def test_get_node_details_node_not_found(self, mock_read_node):
        """Test that get_node_details raises an exception when the node is not found."""
        mock_read_node.return_value = None

        with self.assertRaises(Exception) as context:
            self.client.get_node_details("nonexistent-node")
        self.assertIn(
            "Node 'nonexistent-node' not found.", str(context.exception)
        )
        mock_read_node.assert_called_once_with("nonexistent-node")

    @patch('kubernetes.client.CoreV1Api.read_namespaced_pod_log')
    def test_get_pod_logs_success(self, mock_read_log):
        """Test successful retrieval of pod logs. """
        mock_response = MagicMock()
        mock_response.data = "log line 1\nlog line 2"
        mock_read_log.return_value = mock_response

        logs = self.client.get_pod_logs(
            "test-pod", namespace="default", container="app", tail_lines=100
        )

        self.assertEqual(logs, "log line 1\nlog line 2")
        mock_read_log.assert_called_once_with(
            name="test-pod",
            namespace="default",
            container="app",
            tail_lines=100,
            _preload_content=False
        )

    @patch('kubernetes.client.CoreV1Api.read_namespaced_pod_log')
    def test_get_pod_logs_api_exception(self, mock_read_log):
        """Test getting pod logs with API exception."""
        mock_read_log.side_effect = client.rest.ApiException(status=404, reason="Not Found")

        with self.assertRaises(Exception) as context:
            self.client.get_pod_logs("missing-pod", namespace="default")

        self.assertIn(
            "Error getting logs for pod 'missing-pod'", str(context.exception)
        )
        self.assertIsInstance(context.exception.__cause__, client.rest.ApiException)

    @patch('kubernetes.client.CoreV1Api.read_node')
    @patch('kubernetes.client.CoreV1Api.list_namespaced_pod')
    @patch('clients.kubernetes_client.save_info_to_file')
    def test_collect_pod_and_node_info(
        self, mock_save_info, mock_list_namespaced_pod, mock_read_node
    ):
        """Test collecting pod and node information."""
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

    @patch("kubernetes.client.AppsV1Api.read_namespaced_daemon_set")
    @patch("time.sleep")
    @patch("time.time")
    def test_verify_gpu_device_plugin_timeout(self, mock_time, mock_sleep, mock_app):
        """Test GPU device plugin verification timeout"""
        namespace = "kube-system"
        timeout = 60

        # Mock time progression to exceed timeout - provide enough values
        mock_time.side_effect = [0, 0, 30, 65, 70, 75]  # Provide more values to avoid StopIteration

        # Mock DaemonSet that never becomes ready
        mock_daemonset = MagicMock()
        mock_daemonset.status.number_ready = 1
        mock_daemonset.status.desired_number_scheduled = 2  # Never matches
        mock_app.return_value = mock_daemonset

        result = self.client.verify_gpu_device_plugin(namespace, timeout)

        self.assertFalse(result)
        mock_app.assert_called()
        mock_sleep.assert_called()

    @patch("kubernetes.client.AppsV1Api.read_namespaced_daemon_set")
    def test_verify_gpu_device_plugin_api_exception(self, mock_app):
        """Test GPU device plugin verification with API exception"""
        namespace = "kube-system"

        # Mock API exception - use the correct import path
        mock_app.side_effect = client.rest.ApiException(
            status=500, reason="Internal Server Error"
        )

        with self.assertRaises(client.rest.ApiException):
            self.client.verify_gpu_device_plugin(namespace)

    @patch("kubernetes.client.AppsV1Api.read_namespaced_daemon_set")
    def test_verify_gpu_device_plugin_success(self, mock_app):
        """Test successful GPU device plugin verification."""
        namespace = "kube-system"

        # Mock successful DaemonSet
        mock_daemonset = MagicMock()
        mock_daemonset.status.number_ready = 3
        mock_daemonset.status.desired_number_scheduled = 3  # Matches - success
        mock_app.return_value = mock_daemonset

        result = self.client.verify_gpu_device_plugin(namespace)

        self.assertTrue(result)
        mock_app.assert_called_once_with(
            name="nvidia-device-plugin-daemonset",
            namespace=namespace
        )

    @patch("time.sleep", return_value=None)
    @patch("clients.kubernetes_client.KubernetesClient.get_pod_logs")
    @patch("kubernetes.client.CoreV1Api.delete_namespaced_pod")
    @patch("kubernetes.client.CoreV1Api.read_namespaced_pod")
    @patch("kubernetes.client.CoreV1Api.create_namespaced_pod")
    def test_verify_nvidia_smi_success(
        self,
        _mock_create_pod,
        mock_read_pod,
        _mock_delete_pod,
        mock_get_logs,
        mock_sleep
    ):
        """Test successful nvidia-smi verification."""
        node = MagicMock()
        node.metadata.name = "gpu-node-1"

        # Simulate pod status: first Pending, then Succeeded
        mock_read_pod.side_effect = [
            MagicMock(status=MagicMock(phase="Pending")),
            MagicMock(status=MagicMock(phase="Succeeded")),
        ]
        mock_get_logs.return_value = "NVIDIA-SMI GPU driver info"

        result = self.client.verify_nvidia_smi_on_node([node])

        self.assertIn("gpu-node-1", result)
        self.assertTrue(result["gpu-node-1"]["device_status"])
        mock_sleep.assert_called()

    @patch("clients.kubernetes_client.KubernetesClient.get_pod_logs")
    @patch("kubernetes.client.CoreV1Api.delete_namespaced_pod")
    @patch("kubernetes.client.CoreV1Api.read_namespaced_pod")
    @patch("kubernetes.client.CoreV1Api.create_namespaced_pod")
    def test_verify_nvidia_smi_failure(
        self, _mock_create_pod, mock_read_pod, mock_delete_pod, mock_get_logs
    ):
        """Test nvidia-smi verification failure."""
        node = MagicMock()
        node.metadata.name = "gpu-node-2"

        mock_read_pod.return_value.status.phase = "Succeeded"
        mock_get_logs.return_value = "Some unrelated output"

        result = self.client.verify_nvidia_smi_on_node([node])

        self.assertFalse(result["gpu-node-2"]["device_status"])
        mock_delete_pod.assert_called_once()

    @patch("clients.kubernetes_client.KubernetesClient.get_pod_logs")
    @patch(
        "kubernetes.client.CoreV1Api.delete_namespaced_pod",
        side_effect=Exception("Delete failed")
    )
    @patch("kubernetes.client.CoreV1Api.read_namespaced_pod")
    @patch("kubernetes.client.CoreV1Api.create_namespaced_pod")
    def test_verify_nvidia_smi_delete_pod_fails(
        self, _mock_create_pod, mock_read_pod, mock_delete_pod, mock_get_logs
    ):
        """Test nvidia-smi verification when pod deletion fails."""
        node = MagicMock()
        node.metadata.name = "gpu-node-3"

        mock_read_pod.return_value.status.phase = "Succeeded"
        mock_get_logs.return_value = "NVIDIA-SMI GPU driver info"

        result = self.client.verify_nvidia_smi_on_node([node])

        self.assertTrue(result["gpu-node-3"]["device_status"])
        mock_delete_pod.assert_called_once()

    @patch(
        "kubernetes.client.CoreV1Api.create_namespaced_pod",
        side_effect=Exception("API failure")
    )
    def test_verify_nvidia_smi_general_exception(self, _mock_create_pod):
        """Test nvidia-smi verification with general exception."""
        node = MagicMock()
        node.metadata.name = "gpu-node-4"

        result = self.client.verify_nvidia_smi_on_node([node])
        self.assertFalse(result)

    @patch("kubernetes.client.AppsV1Api.create_namespaced_daemon_set")
    @patch("requests.get")
    def test_install_gpu_device_plugin_success(self, mock_requests_get, mock_create_ds):
        """
        Test successful installation of the NVIDIA GPU device plugin.
        """
        # Mock response from requests.get
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: nvidia-device-plugin-daemonset
spec: {}
"""
        mock_requests_get.return_value = mock_response

        self.client.install_gpu_device_plugin(namespace="kube-system")

        mock_requests_get.assert_called_once_with(
            UrlConstants.NVIDIA_GPU_DEVICE_PLUGIN_YAML, timeout=30
        )
        mock_create_ds.assert_called_once()

    @patch("kubernetes.client.AppsV1Api.create_namespaced_daemon_set")
    @patch("requests.get", side_effect=requests.exceptions.RequestException("Network error"))
    def test_install_gpu_device_plugin_request_exception(self, mock_requests_get, mock_create_ds):
        """
        Test that an exception is raised when the YAML fetch fails.
        """
        with self.assertRaises(Exception) as context:
            self.client.install_gpu_device_plugin()

        self.assertIn("Network error", str(context.exception))
        mock_requests_get.assert_called_once()
        mock_create_ds.assert_not_called()

    @patch('clients.kubernetes_client.KubernetesClient.get_pods_by_namespace')
    def test_get_daemonsets_pods_count(self, mock_get_pods_by_namespace):
        """
        Test that get_daemonsets_pods_count returns the correct number of pods scheduled on a node.
        """
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

    @patch('requests.get')
    @patch('clients.kubernetes_client.KubernetesClient._apply_single_manifest')
    def test_apply_manifest_from_url_success_single_document(self, mock_apply_single,
                                                            mock_requests_get):
        """Test successful application of a single manifest document from URL."""
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.text = """
apiVersion: v1
kind: Namespace
metadata:
  name: test-namespace
"""
        mock_response.raise_for_status.return_value = None
        mock_requests_get.return_value = mock_response

        # Call the method
        self.client.apply_manifest_from_url("https://example.com/manifest.yaml")

        # Verify HTTP request
        mock_requests_get.assert_called_once_with("https://example.com/manifest.yaml", timeout=30)
        mock_response.raise_for_status.assert_called_once()

        # Verify manifest application
        mock_apply_single.assert_called_once()
        applied_manifest = mock_apply_single.call_args[0][0]
        self.assertEqual(applied_manifest['kind'], 'Namespace')
        self.assertEqual(applied_manifest['metadata']['name'], 'test-namespace')

    @patch('requests.get')
    @patch('clients.kubernetes_client.KubernetesClient._apply_single_manifest')
    def test_apply_manifest_from_url_success_multiple_documents(self, mock_apply_single,
                                                               mock_requests_get):
        """Test successful application of multiple manifest documents from URL."""
        # Mock successful HTTP response with multiple YAML documents
        mock_response = MagicMock()
        mock_response.text = """
apiVersion: v1
kind: Namespace
metadata:
  name: test-namespace
---
apiVersion: v1
kind: Service
metadata:
  name: test-service
  namespace: test-namespace
spec:
  selector:
    app: test-app
"""
        mock_response.raise_for_status.return_value = None
        mock_requests_get.return_value = mock_response

        # Call the method
        self.client.apply_manifest_from_url("https://example.com/multi-manifest.yaml")

        # Verify HTTP request
        mock_requests_get.assert_called_once_with(
            "https://example.com/multi-manifest.yaml", timeout=30)

        # Verify both manifests were applied
        self.assertEqual(mock_apply_single.call_count, 2)

        # Check first manifest (Namespace)
        first_manifest = mock_apply_single.call_args_list[0][0][0]
        self.assertEqual(first_manifest['kind'], 'Namespace')
        self.assertEqual(first_manifest['metadata']['name'], 'test-namespace')

        # Check second manifest (Service)
        second_manifest = mock_apply_single.call_args_list[1][0][0]
        self.assertEqual(second_manifest['kind'], 'Service')
        self.assertEqual(second_manifest['metadata']['name'], 'test-service')

    @patch('requests.get')
    def test_apply_manifest_from_url_http_404_error(self, mock_requests_get):
        """Test handling of HTTP 404 error when fetching manifest."""
        # Mock HTTP 404 error
        mock_requests_get.side_effect = requests.exceptions.HTTPError(
            "404 Client Error: Not Found")

        # Verify exception is raised
        with self.assertRaises(Exception) as context:
            self.client.apply_manifest_from_url("https://example.com/nonexistent.yaml")

        self.assertIn("Error applying manifest from "
                     "https://example.com/nonexistent.yaml", str(context.exception))
        self.assertIn("404 Client Error", str(context.exception))

    @patch('requests.get')
    def test_apply_manifest_from_url_http_timeout(self, mock_requests_get):
        """Test handling of HTTP timeout when fetching manifest."""
        # Mock HTTP timeout
        mock_requests_get.side_effect = requests.exceptions.Timeout("Request timed out")

        # Verify exception is raised
        with self.assertRaises(Exception) as context:
            self.client.apply_manifest_from_url("https://example.com/slow-manifest.yaml")

        self.assertIn("Error applying manifest from "
                     "https://example.com/slow-manifest.yaml", str(context.exception))
        self.assertIn("Request timed out", str(context.exception))

    @patch('requests.get')
    def test_apply_manifest_from_url_yaml_parse_error(self, mock_requests_get):
        """Test handling of YAML parsing errors."""
        # Mock successful HTTP response with invalid YAML
        mock_response = MagicMock()
        mock_response.text = """
invalid: yaml: content:
  - missing
    closing bracket
"""
        mock_response.raise_for_status.return_value = None
        mock_requests_get.return_value = mock_response

        # Verify exception is raised for invalid YAML
        with self.assertRaises(Exception) as context:
            self.client.apply_manifest_from_url("https://example.com/invalid.yaml")

        self.assertIn("Error applying manifest from "
                     "https://example.com/invalid.yaml", str(context.exception))

    @patch('requests.get')
    @patch('clients.kubernetes_client.KubernetesClient._apply_single_manifest')
    def test_apply_manifest_from_url_empty_documents(self, mock_apply_single,
                                                    mock_requests_get):
        """Test handling of empty YAML documents."""
        # Mock successful HTTP response with empty documents
        mock_response = MagicMock()
        mock_response.text = """
---
# Empty document
---
apiVersion: v1
kind: Namespace
metadata:
  name: test-namespace
---
# Another empty document
"""
        mock_response.raise_for_status.return_value = None
        mock_requests_get.return_value = mock_response

        # Call the method
        self.client.apply_manifest_from_url(
            "https://example.com/manifest-with-empty.yaml")

        # Verify only non-empty manifest was applied
        mock_apply_single.assert_called_once()
        applied_manifest = mock_apply_single.call_args[0][0]
        self.assertEqual(applied_manifest['kind'], 'Namespace')

    @patch('requests.get')
    @patch('clients.kubernetes_client.KubernetesClient._apply_single_manifest')
    def test_apply_manifest_from_url_apply_single_manifest_exception(
            self, mock_apply_single, mock_requests_get):
        """Test handling of exceptions during single manifest application."""
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.text = """
apiVersion: v1
kind: Namespace
metadata:
  name: test-namespace
"""
        mock_response.raise_for_status.return_value = None
        mock_requests_get.return_value = mock_response

        # Mock _apply_single_manifest to raise an exception
        mock_apply_single.side_effect = Exception("Failed to create resource")

        # Verify exception is propagated
        with self.assertRaises(Exception) as context:
            self.client.apply_manifest_from_url("https://example.com/manifest.yaml")

        self.assertIn("Error applying manifest from "
                     "https://example.com/manifest.yaml", str(context.exception))
        self.assertIn("Failed to create resource", str(context.exception))

    @patch('kubernetes.client.CoreV1Api.create_namespace')
    def test_apply_single_manifest_namespace(self, mock_create_namespace):
        """Test _apply_single_manifest with Namespace resource."""
        manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "test-namespace"}
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_namespace.assert_called_once_with(body=manifest)

    @patch('kubernetes.client.AppsV1Api.create_namespaced_deployment')
    def test_apply_single_manifest_deployment(self, mock_create_deployment):
        """Test _apply_single_manifest with Deployment resource."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {}
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_deployment.assert_called_once_with(
            namespace="test-namespace", body=manifest)

    def test_apply_single_manifest_deployment_no_namespace(self):
        """Test _apply_single_manifest with Deployment missing namespace."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment"},
            "spec": {}
        }

        with self.assertRaises(ValueError) as context:
            # pylint: disable=protected-access
            self.client._apply_single_manifest(manifest)

        self.assertEqual(str(context.exception), "Deployment requires a namespace")

    @patch('kubernetes.client.AppsV1Api.create_namespaced_daemon_set')
    def test_apply_single_manifest_daemonset(self, mock_create_daemonset):
        """Test _apply_single_manifest with DaemonSet resource."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "DaemonSet",
            "metadata": {"name": "test-daemonset", "namespace": "test-namespace"},
            "spec": {}
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_daemonset.assert_called_once_with(
            namespace="test-namespace", body=manifest)

    @patch('kubernetes.client.AppsV1Api.create_namespaced_stateful_set')
    def test_apply_single_manifest_statefulset(self, mock_create_statefulset):
        """Test _apply_single_manifest with StatefulSet resource."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": "test-statefulset", "namespace": "test-namespace"},
            "spec": {}
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_statefulset.assert_called_once_with(
            namespace="test-namespace", body=manifest)

    def test_apply_single_manifest_statefulset_no_namespace(self):
        """Test _apply_single_manifest with StatefulSet missing namespace."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": "test-statefulset"},
            "spec": {}
        }

        with self.assertRaises(ValueError) as context:
            # pylint: disable=protected-access
            self.client._apply_single_manifest(manifest)

        self.assertEqual(str(context.exception), "StatefulSet requires a namespace")

    @patch('kubernetes.client.CoreV1Api.create_namespaced_service')
    def test_apply_single_manifest_service(self, mock_create_service):
        """Test _apply_single_manifest with Service resource."""
        manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "test-service", "namespace": "test-namespace"},
            "spec": {}
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_service.assert_called_once_with(
            namespace="test-namespace", body=manifest)

    @patch('kubernetes.client.RbacAuthorizationV1Api.create_cluster_role')
    def test_apply_single_manifest_cluster_role(self, mock_create_cluster_role):
        """Test _apply_single_manifest with ClusterRole resource."""
        manifest = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "test-cluster-role"},
            "rules": []
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_cluster_role.assert_called_once_with(body=manifest)

    @patch('kubernetes.client.CustomObjectsApi.create_cluster_custom_object')
    def test_apply_single_manifest_kwok_stage(self, mock_create_custom_object):
        """Test _apply_single_manifest with KWOK Stage custom resource."""
        manifest = {
            "apiVersion": "kwok.x-k8s.io/v1alpha1",
            "kind": "Stage",
            "metadata": {"name": "test-stage"},
            "spec": {}
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_custom_object.assert_called_once_with(
            group="kwok.x-k8s.io",
            version="v1alpha1",
            plural="stages",
            body=manifest
        )

    @patch('kubernetes.client.CustomObjectsApi.create_namespaced_custom_object')
    def test_apply_single_manifest_mpi_job(self, mock_create_custom_object):
        """Test _apply_single_manifest with MPIJob custom resource."""
        manifest = {
            "apiVersion": "kubeflow.org/v2beta1",
            "kind": "MPIJob",
            "metadata": {"name": "test-mpi-job", "namespace": "kubeflow"},
            "spec": {
                "slotsPerWorker": 1,
                "runPolicy": {},
                "mpiReplicaSpecs": {}
            }
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_custom_object.assert_called_once_with(
            group="kubeflow.org",
            version="v2beta1",
            namespace="kubeflow",
            plural="mpijobs",
            body=manifest
        )

    def test_apply_single_manifest_mpi_job_no_namespace(self):
        """Test _apply_single_manifest with MPIJob missing namespace."""
        manifest = {
            "apiVersion": "kubeflow.org/v2beta1",
            "kind": "MPIJob",
            "metadata": {"name": "test-mpi-job"},
            "spec": {}
        }

        with self.assertRaises(ValueError) as context:
            # pylint: disable=protected-access
            self.client._apply_single_manifest(manifest)

        self.assertEqual(str(context.exception), "MPIJob requires a namespace")

    @patch('kubernetes.client.CustomObjectsApi.create_cluster_custom_object')
    def test_apply_single_manifest_node_feature_rule(self, mock_create_custom_object):
        """Test _apply_single_manifest with NodeFeatureRule custom resource."""
        manifest = {
            "apiVersion": "nfd.k8s-sigs.io/v1alpha1",
            "kind": "NodeFeatureRule",
            "metadata": {"name": "test-node-feature-rule"},
            "spec": {}
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_custom_object.assert_called_once_with(
            group="nfd.k8s-sigs.io",
            version="v1alpha1",
            plural="nodefeaturerules",
            body=manifest
        )

    @patch('kubernetes.client.CustomObjectsApi.create_cluster_custom_object')
    def test_apply_single_manifest_nic_cluster_policy(self, mock_create_custom_object):
        """Test _apply_single_manifest with NicClusterPolicy custom resource."""
        manifest = {
            "apiVersion": "mellanox.com/v1alpha1",
            "kind": "NicClusterPolicy",
            "metadata": {"name": "nic-cluster-policy"},
            "spec": {}
        }

        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_create_custom_object.assert_called_once_with(
            group="mellanox.com",
            version="v1alpha1",
            plural="nicclusterpolicies",
            body=manifest
        )

    @patch('clients.kubernetes_client.logger')
    def test_apply_single_manifest_unsupported_kind(self, mock_logger):
        """Test _apply_single_manifest with unsupported resource kind."""
        manifest = {
            "apiVersion": "v1",
            "kind": "UnsupportedResource",
            "metadata": {"name": "test-resource"}
        }

        # Should not raise an exception, just log a warning
        # pylint: disable=protected-access
        self.client._apply_single_manifest(manifest)
        mock_logger.warning.assert_called_once_with(
            "Unsupported resource kind: %s. Skipping...", "UnsupportedResource")

    @patch('kubernetes.client.CoreV1Api.create_namespace')
    def test_apply_single_manifest_resource_already_exists(self, mock_create_namespace):
        """Test _apply_single_manifest when resource already exists (409 conflict)."""
        manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "existing-namespace"}
        }

        # Mock 409 conflict error (resource already exists)
        api_exception = ApiException(status=409, reason="Conflict")
        mock_create_namespace.side_effect = api_exception

        # Should not raise an exception, just log and continue
        with patch('clients.kubernetes_client.logger') as mock_logger:
            # pylint: disable=protected-access
            self.client._apply_single_manifest(manifest)
            mock_logger.info.assert_called_once_with(
                "Resource %s/%s already exists, skipping creation",
                "Namespace", "existing-namespace"
            )

    @patch('kubernetes.client.CoreV1Api.create_namespace')
    def test_apply_single_manifest_api_exception_non_409(self, mock_create_namespace):
        """Test _apply_single_manifest with API exception other than 409."""
        manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "test-namespace"}
        }

        # Mock 403 forbidden error
        api_exception = ApiException(status=403, reason="Forbidden")
        mock_create_namespace.side_effect = api_exception

        # Should raise an exception
        with self.assertRaises(Exception) as context:
            # pylint: disable=protected-access
            self.client._apply_single_manifest(manifest)

        self.assertIn("Error creating Namespace", str(context.exception))

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_with_manifest_path_success(self, mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with manifest_path - success case"""
        # Mock file existence check
        mock_isfile.return_value = True

        # Mock YAML content
        yaml_content = """
apiVersion: v1
kind: Service
metadata:
  name: test-service
  namespace: test-namespace
spec:
  selector:
    app: test-app
  ports:
    - port: 80
      targetPort: 8080
"""
        manifest_dict = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "test-service",
                "namespace": "test-namespace"
            },
            "spec": {
                "selector": {"app": "test-app"},
                "ports": [{"port": 80, "targetPort": 8080}]
            }
        }

        mock_open_file.return_value.read.return_value = yaml_content
        mock_yaml_load.return_value = [manifest_dict]

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespaced_service.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/manifest.yaml")

            # Verify file was opened correctly
            mock_open_file.assert_called_once_with("/path/to/manifest.yaml", 'r', encoding='utf-8')
            mock_yaml_load.assert_called_once()

            # Verify API was called correctly
            mock_api.create_namespaced_service.assert_called_once_with(
                namespace="test-namespace",
                body=manifest_dict
            )

    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_with_manifest_dict_success(self, mock_open_file, mock_yaml_load):
        """Test apply_manifest_from_file with manifest_dict - success case"""
        manifest_dict = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "test-deployment",
                "namespace": "test-namespace"
            },
            "spec": {
                "replicas": 3,
                "selector": {"matchLabels": {"app": "test-app"}},
                "template": {
                    "metadata": {"labels": {"app": "test-app"}},
                    "spec": {"containers": [{"name": "test-container", "image": "nginx:latest"}]}
                }
            }
        }

        # Mock the API client
        with patch.object(self.client, 'app') as mock_app:
            mock_app.create_namespaced_deployment.return_value = None

            # Call the method with manifest_dict
            self.client.apply_manifest_from_file(manifest_dict=manifest_dict)

            # Verify file operations were not called
            mock_open_file.assert_not_called()
            mock_yaml_load.assert_not_called()

            # Verify API was called correctly
            mock_app.create_namespaced_deployment.assert_called_once_with(
                namespace="test-namespace",
                body=manifest_dict
            )

    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_no_parameters_error(self, mock_open_file):
        """Test apply_manifest_from_file with no parameters - should raise ValueError"""
        # Call without parameters should raise ValueError
        with self.assertRaises(ValueError) as context:
            self.client.apply_manifest_from_file()

        self.assertIn("At least one of manifest_path or manifest_dict must be provided", str(context.exception))
        mock_open_file.assert_not_called()

    @patch('os.path.isfile')
    @patch('os.path.isdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_file_not_found_error(self, mock_open_file, mock_isdir, mock_isfile):
        """Test apply_manifest_from_file with file not found error"""
        # Mock file and directory existence checks to return False (file doesn't exist)
        mock_isfile.return_value = False
        mock_isdir.return_value = False

        # Call should raise FileNotFoundError
        with self.assertRaises(FileNotFoundError) as context:
            self.client.apply_manifest_from_file(manifest_path="/nonexistent/path.yaml")

        self.assertIn("Path does not exist", str(context.exception))
        # Verify open was not called since we check file existence first
        mock_open_file.assert_not_called()

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_yaml_parse_error(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with YAML parsing error"""
        # Mock file existence check
        mock_isfile.return_value = True

        # Mock YAML parsing error
        mock_yaml_load.side_effect = Exception("Invalid YAML content")

        # Call should raise Exception
        with self.assertRaises(Exception) as context:
            self.client.apply_manifest_from_file(manifest_path="/path/to/invalid.yaml")

        self.assertIn("Invalid YAML content", str(context.exception))

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_configmap_success(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with ConfigMap resource"""
        # Mock file existence check
        mock_isfile.return_value = True
        manifest_dict = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "test-configmap",
                "namespace": "test-namespace"
            },
            "data": {
                "config.yaml": "key: value",
                "app.properties": "setting=enabled"
            }
        }

        mock_yaml_load.return_value = [manifest_dict]

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespaced_config_map.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/configmap.yaml")

            # Verify API was called correctly
            mock_api.create_namespaced_config_map.assert_called_once_with(
                namespace="test-namespace",
                body=manifest_dict
            )

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_secret_success(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with Secret resource"""
        # Mock file existence check
        mock_isfile.return_value = True
        manifest_dict = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "test-secret",
                "namespace": "test-namespace"
            },
            "type": "Opaque",
            "data": {
                "username": "dGVzdA==",  # base64 encoded "test"
                "password": "cGFzcw=="   # base64 encoded "pass"
            }
        }

        mock_yaml_load.return_value = [manifest_dict]

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespaced_secret.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/secret.yaml")

            # Verify API was called correctly
            mock_api.create_namespaced_secret.assert_called_once_with(
                namespace="test-namespace",
                body=manifest_dict
            )

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_namespace_success(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with Namespace resource (cluster-scoped)"""
        # Mock file existence check
        mock_isfile.return_value = True
        manifest_dict = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": "test-namespace",
                "labels": {
                    "environment": "test"
                }
            }
        }

        mock_yaml_load.return_value = [manifest_dict]

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespace.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/namespace.yaml")

            # Verify API was called correctly
            mock_api.create_namespace.assert_called_once_with(body=manifest_dict)

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_cluster_role_success(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with ClusterRole resource"""
        # Mock file existence check
        mock_isfile.return_value = True
        manifest_dict = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {
                "name": "test-cluster-role"
            },
            "rules": [
                {
                    "apiGroups": [""],
                    "resources": ["pods"],
                    "verbs": ["get", "list", "watch"]
                }
            ]
        }

        mock_yaml_load.return_value = [manifest_dict]

        # Mock the RBAC API client
        with patch('kubernetes.client.RbacAuthorizationV1Api') as mock_rbac_api_class:
            mock_rbac_api = mock_rbac_api_class.return_value
            mock_rbac_api.create_cluster_role.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/clusterrole.yaml")

            # Verify API was called correctly
            mock_rbac_api.create_cluster_role.assert_called_once_with(body=manifest_dict)

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_unsupported_resource_warning(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with unsupported resource type - should log warning"""
        # Mock file existence check
        mock_isfile.return_value = True
        manifest_dict = {
            "apiVersion": "custom.io/v1",
            "kind": "UnsupportedResource",
            "metadata": {
                "name": "test-unsupported"
            }
        }

        mock_yaml_load.return_value = [manifest_dict]

        # Call the method - should not raise exception, just log warning
        with patch('clients.kubernetes_client.logger') as mock_logger:
            self.client.apply_manifest_from_file(manifest_path="/path/to/unsupported.yaml")

            # Verify warning was logged
            mock_logger.warning.assert_called_once_with(
                "Unsupported resource kind: %s. Skipping...", 
                "UnsupportedResource"
            )

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_api_exception_409_conflict(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with API exception 409 (resource already exists)"""
        # Mock file existence check
        mock_isfile.return_value = True
        manifest_dict = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "test-service",
                "namespace": "test-namespace"
            }
        }

        mock_yaml_load.return_value = [manifest_dict]

        # Mock API exception with 409 status (conflict - resource already exists)
        api_exception = ApiException(status=409, reason="Conflict")

        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespaced_service.side_effect = api_exception

            # Should not raise exception, just log info
            with patch('clients.kubernetes_client.logger') as mock_logger:
                self.client.apply_manifest_from_file(manifest_path="/path/to/service.yaml")

                # Verify info was logged about resource already existing
                mock_logger.info.assert_any_call(
                    "Resource %s/%s already exists, skipping creation",
                    "Service", "test-service"
                )

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_api_exception_other_error(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with API exception other than 409"""
        # Mock file existence check
        mock_isfile.return_value = True
        manifest_dict = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "test-service",
                "namespace": "test-namespace"
            }
        }

        mock_yaml_load.return_value = [manifest_dict]

        # Mock API exception with 403 status (forbidden)
        api_exception = ApiException(status=403, reason="Forbidden")

        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespaced_service.side_effect = api_exception

            # Should raise an exception
            with self.assertRaises(Exception) as context:
                self.client.apply_manifest_from_file(manifest_path="/path/to/service.yaml")

            self.assertIn("Error creating Service", str(context.exception))

    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_deployment_success(self, _mock_open_file, mock_yaml_load, mock_isfile):
        """Test apply_manifest_from_file with deployment manifest - success case"""
        # Mock file existence check
        mock_isfile.return_value = True

        manifest_dict = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "test-deployment",
                "namespace": "test-namespace"
            }
        }

        mock_yaml_load.return_value = [manifest_dict]

        # Mock the API client
        with patch.object(self.client, 'app') as mock_app:
            mock_app.create_namespaced_deployment.return_value = None

            # Call method
            self.client.apply_manifest_from_file(manifest_path="/path/to/deployment.yaml")

            # Verify API was called correctly
            mock_app.create_namespaced_deployment.assert_called_once_with(
                namespace="test-namespace",
                body=manifest_dict
            )

    @patch('time.time')
    def test_wait_for_condition_deployment_success(self, mock_time):
        """Test wait_for_condition for deployment - success case"""
        # Mock time progression - provide enough values to avoid StopIteration
        mock_time.side_effect = [0, 0, 1, 2, 2]  # start_time, timeout check, loop check, success, elapsed

        # Mock deployment with available condition
        mock_deployment = MagicMock()
        mock_deployment.status.conditions = [
            MagicMock(type="Available", status="True"),
            MagicMock(type="Progressing", status="True")
        ]

        with patch.object(self.client, 'app') as mock_app, \
             patch('time.sleep'):  # Mock sleep to speed up test
            mock_app.read_namespaced_deployment.return_value = mock_deployment

            # Test successful wait
            result = self.client.wait_for_condition(
                resource_type="deployment",
                resource_name="test-deployment",
                wait_condition_type="available",
                namespace="test-namespace",
                timeout_seconds=5
            )

            self.assertTrue(result)
            mock_app.read_namespaced_deployment.assert_called_with(
                name="test-deployment",
                namespace="test-namespace"
            )

    @patch('time.time')
    def test_wait_for_condition_deployment_timeout(self, mock_time):
        """Test wait_for_condition for deployment - timeout case"""
        # Mock time progression to simulate timeout - provide enough values
        mock_time.side_effect = [0, 0, 2, 5, 6, 6]  # start_time, timeout calc, loop checks, timeout, elapsed

        # Mock deployment with unavailable condition
        mock_deployment = MagicMock()
        mock_deployment.status.conditions = [
            MagicMock(type="Available", status="False"),
            MagicMock(type="Progressing", status="True")
        ]

        with patch.object(self.client, 'app') as mock_app, \
             patch('time.sleep'):  # Mock sleep to speed up test
            mock_app.read_namespaced_deployment.return_value = mock_deployment

            # Test timeout
            result = self.client.wait_for_condition(
                resource_type="deployment",
                resource_name="test-deployment",
                wait_condition_type="available",
                namespace="test-namespace",
                timeout_seconds=1
            )

            self.assertFalse(result)

    @patch('time.time')
    def test_wait_for_condition_all_deployments_success(self, mock_time):
        """Test wait_for_condition for all deployments - success case"""
        mock_time.side_effect = [0, 0, 1, 2, 2]  # start_time, timeout check, loop check, success, elapsed

        # Mock multiple deployments, all available
        mock_deployment1 = MagicMock()
        mock_deployment1.status.conditions = [MagicMock(type="Available", status="True")]
        mock_deployment2 = MagicMock()
        mock_deployment2.status.conditions = [MagicMock(type="Available", status="True")]

        with patch.object(self.client, 'app') as mock_app, \
             patch('time.sleep'):  # Mock sleep to speed up test
            mock_app.list_namespaced_deployment.return_value.items = [mock_deployment1, mock_deployment2]

            result = self.client.wait_for_condition(
                resource_type="deployment",
                resource_name=None,  # No specific name = all deployments
                wait_condition_type="available",
                namespace="test-namespace",
                timeout_seconds=5,
                wait_all=True
            )

            self.assertTrue(result)

    def test_wait_for_condition_unsupported_resource_type(self):
        """Test wait_for_condition with unsupported resource type"""
        with self.assertRaises(ValueError) as context:
            self.client.wait_for_condition(
                resource_type="pod",
                resource_name="test",
                wait_condition_type="ready",
                namespace="test-namespace",
                timeout_seconds=1
            )

        self.assertIn("Resource type 'pod' is not supported", str(context.exception))

    @patch('time.time')
    def test_wait_for_condition_resource_not_found(self, mock_time):
        """Test wait_for_condition when resource is not found"""
        mock_time.side_effect = [0, 0, 2, 5, 6, 6]  # start_time, timeout calc, loop checks, timeout, elapsed

        # Mock 404 error (resource not found)
        api_exception = ApiException(status=404, reason="Not Found")

        with patch.object(self.client, 'app') as mock_app, \
             patch('time.sleep'):
            mock_app.read_namespaced_deployment.side_effect = api_exception

            result = self.client.wait_for_condition(
                resource_type="deployment",
                resource_name="nonexistent",
                wait_condition_type="available",
                namespace="test-namespace",
                timeout_seconds=1
            )

            self.assertFalse(result)

    def test_wait_for_condition_invalid_condition_type(self):
        """Test wait_for_condition with invalid condition type"""
        with self.assertRaises(ValueError) as context:
            self.client.wait_for_condition(
                resource_type="deployment",
                resource_name="test-deployment",
                wait_condition_type="invalid_condition",
                namespace="test-namespace",
                timeout_seconds=1
            )

        self.assertIn("Invalid condition 'invalid_condition' for resource type 'deployment'", str(context.exception))
        self.assertIn("Valid conditions: available, progressing, replicafailure, ready", str(context.exception))

    def test_wait_for_condition_empty_condition(self):
        """Test wait_for_condition with empty condition"""
        with self.assertRaises(ValueError) as context:
            self.client.wait_for_condition(
                resource_type="deployment",
                resource_name="test-deployment",
                wait_condition_type="",
                namespace="test-namespace",
                timeout_seconds=1
            )

        self.assertIn("wait_condition_type must be a non-empty string", str(context.exception))

    def test_wait_for_condition_none_condition(self):
        """Test wait_for_condition with None condition"""
        with self.assertRaises(ValueError) as context:
            self.client.wait_for_condition(
                resource_type="deployment",
                resource_name="test-deployment",
                wait_condition_type=None,
                namespace="test-namespace",
                timeout_seconds=1
            )

        self.assertIn("wait_condition_type must be a non-empty string", str(context.exception))

    def test_wait_for_condition_valid_condition_types(self):
        """Test wait_for_condition with various valid condition types"""
        valid_conditions = [
            "available",
            "ready", 
            "progressing",
            "replicafailure"
        ]

        # Mock deployment with all conditions to make tests pass quickly
        mock_deployment = MagicMock()
        mock_deployment.status.conditions = [
            MagicMock(type="Available", status="True"),
            MagicMock(type="Ready", status="True"),
            MagicMock(type="Progressing", status="True"),
            MagicMock(type="ReplicaFailure", status="True")
        ]

        with patch.object(self.client, 'app') as mock_app, \
             patch('time.time', side_effect=[0, 0, 1, 2, 2] * len(valid_conditions)), \
             patch('time.sleep'):
            mock_app.read_namespaced_deployment.return_value = mock_deployment

            for condition in valid_conditions:
                with self.subTest(condition=condition):
                    result = self.client.wait_for_condition(
                        resource_type="deployment",
                        resource_name="test-deployment",
                        wait_condition_type=condition,
                        namespace="test-namespace",
                        timeout_seconds=5
                    )
                    self.assertTrue(result)

    def test_wait_for_condition_case_insensitive(self):
        """Test wait_for_condition with different case conditions"""
        case_variations = [
            "Available",
            "AVAILABLE", 
            "available",
            "aVaiLaBle"
        ]

        # Mock deployment with available condition
        mock_deployment = MagicMock()
        mock_deployment.status.conditions = [
            MagicMock(type="Available", status="True")
        ]

        with patch.object(self.client, 'app') as mock_app, \
             patch('time.time', side_effect=[0, 0, 1, 2, 2] * len(case_variations)), \
             patch('time.sleep'):
            mock_app.read_namespaced_deployment.return_value = mock_deployment

            for condition in case_variations:
                with self.subTest(condition=condition):
                    result = self.client.wait_for_condition(
                        resource_type="deployment",
                        resource_name="test-deployment",
                        wait_condition_type=condition,
                        namespace="test-namespace",
                        timeout_seconds=5
                    )
                    self.assertTrue(result)

    # Tests for the enhanced apply_manifest_from_file method with folder support
    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('glob.glob')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_folder_success(self, mock_open_file, mock_yaml_load, mock_glob, mock_isfile, mock_isdir):
        """Test apply_manifest_from_file with folder path - success case"""
        # Setup mocks
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        mock_glob.return_value = [
            "/path/to/manifests/01-namespace.yaml",
            "/path/to/manifests/02-service.yaml",
            "/path/to/manifests/subdir/03-deployment.yml"
        ]

        # Mock YAML content for different files
        namespace_manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "test-namespace"}
        }
        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "test-service", "namespace": "test-namespace"},
            "spec": {"selector": {"app": "test"}, "ports": [{"port": 80}]}
        }
        deployment_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        # Mock yaml.safe_load_all to return different content for each file
        mock_yaml_load.side_effect = [
            [namespace_manifest],
            [service_manifest],
            [deployment_manifest]
        ]

        # Mock the API clients
        with patch.object(self.client, 'api') as mock_api, \
             patch.object(self.client, 'app') as mock_app:
            mock_api.create_namespace.return_value = None
            mock_api.create_namespaced_service.return_value = None
            mock_app.create_namespaced_deployment.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/manifests")

            # Verify glob was called correctly
            expected_calls = [
                mock.call('/path/to/manifests/**/*.yaml', recursive=True),
                mock.call('/path/to/manifests/**/*.yml', recursive=True)
            ]
            mock_glob.assert_has_calls(expected_calls)

            # Verify files were opened
            self.assertEqual(mock_open_file.call_count, 3)

            # Verify API calls were made
            mock_api.create_namespace.assert_called_once()
            mock_api.create_namespaced_service.assert_called_once()
            mock_app.create_namespaced_deployment.assert_called_once()

    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('glob.glob')
    def test_apply_manifest_from_file_folder_no_yaml_files(self, mock_glob, mock_isfile, mock_isdir):
        """Test apply_manifest_from_file with folder path - no YAML files found"""
        # Setup mocks
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        mock_glob.return_value = []  # No files found

        # Call the method and expect ValueError
        with self.assertRaises(ValueError) as context:
            self.client.apply_manifest_from_file(manifest_path="/path/to/empty/manifests")

        self.assertIn("No YAML files found in directory", str(context.exception))

    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('glob.glob')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_folder_with_multi_doc_yaml(self, _mock_open_file, mock_yaml_load,
                                                               mock_glob, mock_isfile, mock_isdir):
        """Test apply_manifest_from_file with folder containing multi-document YAML files"""
        # Setup mocks
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        mock_glob.return_value = ["/path/to/manifests/multi-doc.yaml"]

        # Mock multi-document YAML content
        manifest1 = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "test-configmap", "namespace": "test-namespace"},
            "data": {"key": "value"}
        }
        manifest2 = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "test-secret", "namespace": "test-namespace"},
            "data": {"password": "dGVzdA=="}
        }

        # Mock yaml.safe_load_all to return multiple documents
        mock_yaml_load.return_value = [manifest1, None, manifest2]  # Include None to test filtering

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespaced_config_map.return_value = None
            mock_api.create_namespaced_secret.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/manifests")

            # Verify API calls were made for both non-None documents
            mock_api.create_namespaced_config_map.assert_called_once()
            mock_api.create_namespaced_secret.assert_called_once()

    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('glob.glob')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_folder_with_deployment(self, _mock_open_file, mock_yaml_load,
                                                               mock_glob, mock_isfile, mock_isdir):
        """Test apply_manifest_from_file with folder containing deployment"""
        # Setup mocks
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        mock_glob.return_value = ["/path/to/manifests/deployment.yaml"]

        deployment_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        mock_yaml_load.return_value = [deployment_manifest]

        # Mock the API client
        with patch.object(self.client, 'app') as mock_app:
            mock_app.create_namespaced_deployment.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/manifests")

            # Verify deployment was created
            mock_app.create_namespaced_deployment.assert_called_once_with(
                namespace="test-namespace",
                body=deployment_manifest
            )

    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('glob.glob')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_folder_duplicate_files_removed(self, mock_open_file, mock_yaml_load,
                                                                   mock_glob, mock_isfile, mock_isdir):
        """Test apply_manifest_from_file removes duplicate files from glob results"""
        # Setup mocks
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        # Mock glob to return duplicates (simulating recursive pattern overlap)
        mock_glob.side_effect = [
            ["/path/to/manifests/test.yaml", "/path/to/manifests/test.yaml"],  # Duplicates
            []  # No .yml files
        ]

        manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "test-namespace"}
        }

        mock_yaml_load.return_value = [manifest]

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespace.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/manifests")

            # Verify file was opened only once (duplicates removed)
            mock_open_file.assert_called_once_with("/path/to/manifests/test.yaml", 'r', encoding='utf-8')

            # Verify API call was made only once
            mock_api.create_namespace.assert_called_once()

    @patch('os.path.isdir')
    @patch('os.path.isfile')
    def test_apply_manifest_from_file_path_not_exists(self, mock_isfile, mock_isdir):
        """Test apply_manifest_from_file with non-existent path"""
        # Setup mocks
        mock_isfile.return_value = False
        mock_isdir.return_value = False

        # Call the method and expect FileNotFoundError
        with self.assertRaises(FileNotFoundError) as context:
            self.client.apply_manifest_from_file(manifest_path="/path/to/nonexistent")

        self.assertIn("Path does not exist", str(context.exception))

    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_single_file_multi_doc(self, _mock_open_file, mock_yaml_load,
                                                          mock_isfile, mock_isdir):
        """Test apply_manifest_from_file with single file containing multiple documents"""
        # Setup mocks
        mock_isfile.return_value = True
        mock_isdir.return_value = False

        # Mock multi-document YAML content
        manifest1 = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "test-namespace"}
        }
        manifest2 = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "test-configmap", "namespace": "test-namespace"},
            "data": {"key": "value"}
        }

        mock_yaml_load.return_value = [manifest1, manifest2]

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespace.return_value = None
            mock_api.create_namespaced_config_map.return_value = None

            # Call the method
            self.client.apply_manifest_from_file(manifest_path="/path/to/multi-doc.yaml")

            # Verify both manifests were applied
            mock_api.create_namespace.assert_called_once()
            mock_api.create_namespaced_config_map.assert_called_once()

    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('glob.glob')
    @patch('yaml.safe_load_all')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_manifest_from_file_combined_sources(self, _mock_open_file, mock_yaml_load,
                                                     mock_glob, mock_isfile, mock_isdir):
        """Test apply_manifest_from_file with both folder and dictionary"""
        # Setup mocks
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        mock_glob.return_value = ["/path/to/manifests/service.yaml"]

        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "test-service", "namespace": "test-namespace"},
            "spec": {"selector": {"app": "test"}, "ports": [{"port": 80}]}
        }

        config_manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "test-configmap", "namespace": "test-namespace"},
            "data": {"key": "value"}
        }

        mock_yaml_load.return_value = [service_manifest]

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.create_namespaced_service.return_value = None
            mock_api.create_namespaced_config_map.return_value = None

            # Call the method with both folder and dictionary
            self.client.apply_manifest_from_file(
                manifest_path="/path/to/manifests",
                manifest_dict=config_manifest
            )

            # Verify both manifests were applied
            mock_api.create_namespaced_service.assert_called_once()
            mock_api.create_namespaced_config_map.assert_called_once()

    @patch('os.path.isfile')
    @patch('builtins.open', new_callable=mock_open)
    @patch('yaml.safe_load_all')
    def test_delete_manifest_from_file_single_file(self, mock_yaml_load, mock_file, mock_isfile):
        """Test deleting a single manifest file."""
        mock_isfile.return_value = True

        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        mock_yaml_load.return_value = [manifest]

        # Mock the API client
        with patch.object(self.client, 'app') as mock_app:
            mock_app.delete_namespaced_deployment.return_value = None

            # Call the method
            self.client.delete_manifest_from_file(manifest_path="/path/to/manifest.yaml")

            # Verify the file was opened and parsed
            mock_file.assert_called_once_with("/path/to/manifest.yaml", 'r', encoding='utf-8')
            mock_yaml_load.assert_called_once()

            # Verify the deployment was deleted
            mock_app.delete_namespaced_deployment.assert_called_once_with(
                name="test-deployment",
                namespace="test-namespace",
                body=unittest.mock.ANY
            )

    @patch('os.path.isdir')
    @patch('glob.glob')
    @patch('builtins.open', new_callable=mock_open)
    @patch('yaml.safe_load_all')
    def test_delete_manifest_from_file_directory(self, mock_yaml_load, _mock_file, mock_glob, mock_isdir):
        """Test deleting manifests from a directory."""
        mock_isdir.return_value = True
        mock_glob.return_value = ["/path/to/manifests/deployment.yaml", "/path/to/manifests/service.yaml"]

        deployment_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "test-service", "namespace": "test-namespace"},
            "spec": {"selector": {"app": "test"}, "ports": [{"port": 80}]}
        }

        # Return different manifests for each file
        mock_yaml_load.side_effect = [[deployment_manifest], [service_manifest]]

        # Mock both API clients
        with patch.object(self.client, 'app') as mock_app, \
             patch.object(self.client, 'api') as mock_api:

            mock_app.delete_namespaced_deployment.return_value = None
            mock_api.delete_namespaced_service.return_value = None

            # Call the method
            self.client.delete_manifest_from_file(manifest_path="/path/to/manifests")

            # Verify glob was called to find YAML files
            self.assertEqual(mock_glob.call_count, 2)  # Called for *.yaml and *.yml

            # Verify both manifests were deleted (in reverse order)
            mock_api.delete_namespaced_service.assert_called_once()
            mock_app.delete_namespaced_deployment.assert_called_once()

    def test_delete_manifest_from_file_dict_only(self):
        """Test deleting a manifest from dictionary only."""
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "test-configmap", "namespace": "test-namespace"},
            "data": {"key": "value"}
        }

        # Mock the API client
        with patch.object(self.client, 'api') as mock_api:
            mock_api.delete_namespaced_config_map.return_value = None

            # Call the method
            self.client.delete_manifest_from_file(manifest_dict=manifest)

            # Verify the configmap was deleted
            mock_api.delete_namespaced_config_map.assert_called_once_with(
                name="test-configmap",
                namespace="test-namespace",
                body=unittest.mock.ANY
            )

    def test_delete_manifest_from_file_with_namespace_injection(self):
        """Test deleting manifest with default namespace injection."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment"},  # No namespace specified
            "spec": {"replicas": 1}
        }

        # Mock the API client
        with patch.object(self.client, 'app') as mock_app:
            mock_app.delete_namespaced_deployment.return_value = None

            # Call the method with default namespace
            self.client.delete_manifest_from_file(
                manifest_dict=manifest,
                default_namespace="default-namespace"
            )

            # Verify the deployment was deleted with injected namespace
            mock_app.delete_namespaced_deployment.assert_called_once_with(
                name="test-deployment",
                namespace="default-namespace",
                body=unittest.mock.ANY
            )

    def test_delete_manifest_from_file_ignore_not_found(self):
        """Test deleting manifest with ignore_not_found=True when resource doesn't exist."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        # Mock the API client to raise 404 error
        with patch.object(self.client, 'app') as mock_app:
            mock_app.delete_namespaced_deployment.side_effect = ApiException(status=404, reason="Not Found")

            # Call the method with ignore_not_found=True (default)
            try:
                self.client.delete_manifest_from_file(manifest_dict=manifest, ignore_not_found=True)
            except Exception as e:
                self.fail(f"Method should not raise exception when ignore_not_found=True: {e}")

            # Verify the deployment deletion was attempted
            mock_app.delete_namespaced_deployment.assert_called_once()

    def test_delete_manifest_from_file_not_ignore_not_found(self):
        """Test deleting manifest with ignore_not_found=False when resource doesn't exist."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        # Mock the API client to raise 404 error
        with patch.object(self.client, 'app') as mock_app:
            mock_app.delete_namespaced_deployment.side_effect = ApiException(status=404, reason="Not Found")

            # Call the method with ignore_not_found=False
            with self.assertRaises(Exception):
                self.client.delete_manifest_from_file(manifest_dict=manifest, ignore_not_found=False)

            # Verify the deployment deletion was attempted
            mock_app.delete_namespaced_deployment.assert_called_once()

    def test_delete_single_manifest_deployment(self):
        """Test deleting a single deployment manifest."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        with patch.object(self.client, 'app') as mock_app:
            mock_app.delete_namespaced_deployment.return_value = None

            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

            mock_app.delete_namespaced_deployment.assert_called_once_with(
                name="test-deployment",
                namespace="test-namespace",
                body=unittest.mock.ANY
            )

    def test_delete_single_manifest_statefulset(self):
        """Test deleting a single StatefulSet manifest."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": "test-statefulset", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        with patch.object(self.client, 'app') as mock_app:
            mock_app.delete_namespaced_stateful_set.return_value = None

            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

            mock_app.delete_namespaced_stateful_set.assert_called_once_with(
                name="test-statefulset",
                namespace="test-namespace",
                body=unittest.mock.ANY
            )

    def test_delete_single_manifest_statefulset_no_namespace(self):
        """Test _delete_single_manifest with StatefulSet missing namespace."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": "test-statefulset"},
            "spec": {}
        }

        with self.assertRaises(Exception) as context:
            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

        self.assertIn("StatefulSet requires a namespace", str(context.exception))

    def test_delete_single_manifest_service(self):
        """Test deleting a single service manifest."""
        manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "test-service", "namespace": "test-namespace"},
            "spec": {"selector": {"app": "test"}, "ports": [{"port": 80}]}
        }

        with patch.object(self.client, 'api') as mock_api:
            mock_api.delete_namespaced_service.return_value = None

            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

            mock_api.delete_namespaced_service.assert_called_once_with(
                name="test-service",
                namespace="test-namespace",
                body=unittest.mock.ANY
            )

    def test_delete_single_manifest_cluster_scoped(self):
        """Test deleting a cluster-scoped resource (ClusterRole)."""
        manifest = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "test-clusterrole"},
            "rules": []
        }

        with patch('clients.kubernetes_client.client.RbacAuthorizationV1Api') as mock_rbac_api_class:
            mock_rbac_api = mock_rbac_api_class.return_value
            mock_rbac_api.delete_cluster_role.return_value = None

            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

            mock_rbac_api.delete_cluster_role.assert_called_once_with(
                name="test-clusterrole",
                body=unittest.mock.ANY
            )

    def test_delete_single_manifest_unsupported_kind(self):
        """Test deleting an unsupported resource kind."""
        manifest = {
            "apiVersion": "v1",
            "kind": "UnsupportedKind",
            "metadata": {"name": "test-resource", "namespace": "test-namespace"}
        }

        # Should log warning but not raise exception
        try:
            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)
        except Exception as e:
            self.fail(f"Method should not raise exception for unsupported kind: {e}")

    def test_delete_single_manifest_no_name(self):
        """Test deleting a manifest without a resource name."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"namespace": "test-namespace"},  # No name
            "spec": {"replicas": 1}
        }

        with patch.object(self.client, 'app') as mock_app:
            # Should return early without calling delete
            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)
            mock_app.delete_namespaced_deployment.assert_not_called()

    def test_delete_single_manifest_mpi_job(self):
        """Test deleting a single MPIJob custom resource."""
        manifest = {
            "apiVersion": "kubeflow.org/v2beta1",
            "kind": "MPIJob",
            "metadata": {"name": "test-mpi-job", "namespace": "kubeflow"},
            "spec": {
                "slotsPerWorker": 1,
                "runPolicy": {},
                "mpiReplicaSpecs": {}
            }
        }

        with patch('clients.kubernetes_client.client.CustomObjectsApi') as mock_custom_api_class:
            mock_custom_api = mock_custom_api_class.return_value
            mock_custom_api.delete_namespaced_custom_object.return_value = None

            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

            mock_custom_api.delete_namespaced_custom_object.assert_called_once_with(
                group="kubeflow.org",
                version="v2beta1",
                namespace="kubeflow",
                plural="mpijobs",
                name="test-mpi-job",
                body=unittest.mock.ANY
            )

    def test_delete_single_manifest_mpi_job_no_namespace(self):
        """Test deleting MPIJob without namespace raises error."""
        manifest = {
            "apiVersion": "kubeflow.org/v2beta1",
            "kind": "MPIJob",
            "metadata": {"name": "test-mpi-job"},
            "spec": {}
        }

        with self.assertRaises(Exception) as context:
            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

        self.assertIn("MPIJob requires a namespace", str(context.exception))

    def test_delete_single_manifest_node_feature_rule(self):
        """Test deleting a single NodeFeatureRule custom resource."""
        manifest = {
            "apiVersion": "nfd.k8s-sigs.io/v1alpha1",
            "kind": "NodeFeatureRule",
            "metadata": {"name": "test-node-feature-rule"},
            "spec": {}
        }

        with patch('clients.kubernetes_client.client.CustomObjectsApi') as mock_custom_api_class:
            mock_custom_api = mock_custom_api_class.return_value
            mock_custom_api.delete_cluster_custom_object.return_value = None

            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

            mock_custom_api.delete_cluster_custom_object.assert_called_once_with(
                group="nfd.k8s-sigs.io",
                version="v1alpha1",
                plural="nodefeaturerules",
                name="test-node-feature-rule",
                body=unittest.mock.ANY
            )

    def test_delete_single_manifest_nic_cluster_policy(self):
        """Test deleting a single NicClusterPolicy custom resource."""
        manifest = {
            "apiVersion": "mellanox.com/v1alpha1",
            "kind": "NicClusterPolicy",
            "metadata": {"name": "nic-cluster-policy"},
            "spec": {}
        }

        with patch('clients.kubernetes_client.client.CustomObjectsApi') as mock_custom_api_class:
            mock_custom_api = mock_custom_api_class.return_value
            mock_custom_api.delete_cluster_custom_object.return_value = None

            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

            mock_custom_api.delete_cluster_custom_object.assert_called_once_with(
                group="mellanox.com",
                version="v1alpha1",
                plural="nicclusterpolicies",
                name="nic-cluster-policy",
                body=unittest.mock.ANY
            )

    def test_delete_single_manifest_kwok_stage(self):
        """Test deleting a single KWOK Stage custom resource."""
        manifest = {
            "apiVersion": "kwok.x-k8s.io/v1alpha1",
            "kind": "Stage",
            "metadata": {"name": "test-stage"},
            "spec": {}
        }

        with patch('clients.kubernetes_client.client.CustomObjectsApi') as mock_custom_api_class:
            mock_custom_api = mock_custom_api_class.return_value
            mock_custom_api.delete_cluster_custom_object.return_value = None

            # pylint: disable=protected-access
            self.client._delete_single_manifest(manifest)

            mock_custom_api.delete_cluster_custom_object.assert_called_once_with(
                group="kwok.x-k8s.io",
                version="v1alpha1",
                plural="stages",
                name="test-stage",
                body=unittest.mock.ANY
            )

    def test_delete_single_manifest_api_exception_404_ignore_not_found_true(self):
        """Test delete with 404 error when ignore_not_found=True."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        with patch.object(self.client, 'app') as mock_app:
            # Mock 404 not found error
            api_exception = ApiException(status=404, reason="Not Found")
            mock_app.delete_namespaced_deployment.side_effect = api_exception

            # Should not raise an exception, just log and continue
            with patch('clients.kubernetes_client.logger') as mock_logger:
                # pylint: disable=protected-access
                self.client._delete_single_manifest(manifest, ignore_not_found=True)
                mock_logger.info.assert_called_once_with(
                    "Resource %s/%s not found, skipping deletion",
                    "Deployment", "test-deployment"
                )

    def test_delete_single_manifest_api_exception_404_ignore_not_found_false(self):
        """Test delete with 404 error when ignore_not_found=False."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        with patch.object(self.client, 'app') as mock_app:
            # Mock 404 not found error
            api_exception = ApiException(status=404, reason="Not Found")
            mock_app.delete_namespaced_deployment.side_effect = api_exception

            # Should raise an exception
            with self.assertRaises(Exception) as context:
                # pylint: disable=protected-access
                self.client._delete_single_manifest(manifest, ignore_not_found=False)

            self.assertIn("Error deleting Deployment/test-deployment", str(context.exception))

    def test_delete_single_manifest_api_exception_non_404(self):
        """Test delete with API exception other than 404."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        with patch.object(self.client, 'app') as mock_app:
            # Mock 403 forbidden error
            api_exception = ApiException(status=403, reason="Forbidden")
            mock_app.delete_namespaced_deployment.side_effect = api_exception

            # Should raise an exception
            with self.assertRaises(Exception) as context:
                # pylint: disable=protected-access
                self.client._delete_single_manifest(manifest)

            self.assertIn("Error deleting Deployment/test-deployment", str(context.exception))

    def test_delete_manifest_from_file_no_arguments(self):
        """Test calling delete_manifest_from_file without any arguments."""
        with self.assertRaises(ValueError) as context:
            self.client.delete_manifest_from_file()

        self.assertIn("At least one of manifest_path or manifest_dict must be provided", str(context.exception))

    @patch('os.path.exists')
    def test_delete_manifest_from_file_nonexistent_path(self, mock_exists):
        """Test deleting from a non-existent file path."""
        mock_exists.return_value = False

        with self.assertRaises(FileNotFoundError):
            self.client.delete_manifest_from_file(manifest_path="/nonexistent/path")

    # Test helper methods
    @patch('os.path.isfile')
    @patch('builtins.open', new_callable=mock_open)
    @patch('yaml.safe_load_all')
    def test_load_manifests_from_sources_single_file(self, mock_yaml_load, _mock_file, mock_isfile):
        """Test loading manifests from a single file."""
        mock_isfile.return_value = True

        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        mock_yaml_load.return_value = [manifest]

        # Call the helper method
        # pylint: disable=protected-access
        manifests, sources = self.client._load_manifests_from_sources(manifest_path="/path/to/manifest.yaml")

        # Verify results
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0], manifest)
        self.assertEqual(sources, ["file: /path/to/manifest.yaml"])

    @patch('os.path.isdir')
    @patch('glob.glob')
    @patch('builtins.open', new_callable=mock_open)
    @patch('yaml.safe_load_all')
    def test_load_manifests_from_sources_directory(self, mock_yaml_load, _mock_file, mock_glob, mock_isdir):
        """Test loading manifests from a directory."""
        mock_isdir.return_value = True
        mock_glob.return_value = ["/path/to/manifests/deployment.yaml"]

        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "test-namespace"},
            "spec": {"replicas": 1}
        }

        mock_yaml_load.return_value = [manifest]

        # Call the helper method
        # pylint: disable=protected-access
        manifests, sources = self.client._load_manifests_from_sources(manifest_path="/path/to/manifests")

        # Verify results
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0], manifest)
        self.assertEqual(sources, ["directory: /path/to/manifests (1 files)"])

    def test_load_manifests_from_sources_dictionary(self):
        """Test loading manifests from a dictionary."""
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "test-configmap", "namespace": "test-namespace"},
            "data": {"key": "value"}
        }

        # Call the helper method
        # pylint: disable=protected-access
        manifests, sources = self.client._load_manifests_from_sources(manifest_dict=manifest)

        # Verify results
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0], manifest)
        self.assertEqual(sources, ["dictionary"])

    def test_load_manifests_from_sources_no_sources(self):
        """Test loading manifests with no sources provided."""
        with self.assertRaises(ValueError) as context:
            # pylint: disable=protected-access
            self.client._load_manifests_from_sources()

        self.assertIn("At least one of manifest_path or manifest_dict must be provided", str(context.exception))

    def test_inject_namespace_if_needed_deployment(self):
        """Test namespace injection for deployment without namespace."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment"},
            "spec": {"replicas": 1}
        }

        # Call the helper method
        # pylint: disable=protected-access
        self.client._inject_namespace_if_needed(manifest, "default-namespace")

        # Verify namespace was injected
        self.assertEqual(manifest["metadata"]["namespace"], "default-namespace")

    def test_inject_namespace_if_needed_existing_namespace(self):
        """Test namespace injection when namespace already exists."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deployment", "namespace": "existing-namespace"},
            "spec": {"replicas": 1}
        }

        # Call the helper method
        # pylint: disable=protected-access
        self.client._inject_namespace_if_needed(manifest, "default-namespace")

        # Verify original namespace was preserved
        self.assertEqual(manifest["metadata"]["namespace"], "existing-namespace")

    def test_inject_namespace_if_needed_cluster_scoped(self):
        """Test namespace injection for cluster-scoped resources (should not inject)."""
        manifest = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "test-clusterrole"},
            "rules": []
        }

        # Call the helper method
        # pylint: disable=protected-access
        self.client._inject_namespace_if_needed(manifest, "default-namespace")

        # Verify no namespace was injected for cluster-scoped resource
        self.assertNotIn("namespace", manifest.get("metadata", {}))

    def test_inject_namespace_if_needed_no_metadata(self):
        """Test namespace injection when manifest has no metadata."""
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "spec": {"replicas": 1}
        }

        # Call the helper method
        # pylint: disable=protected-access
        self.client._inject_namespace_if_needed(manifest, "default-namespace")

        # Verify metadata and namespace were created
        self.assertEqual(manifest["metadata"]["namespace"], "default-namespace")

if __name__ == '__main__':
    unittest.main()
