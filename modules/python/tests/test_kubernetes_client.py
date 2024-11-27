import unittest
from unittest.mock import patch
from kubernetes.client.models import (
    V1Node, V1NodeStatus, V1NodeCondition, V1NodeSpec, V1ObjectMeta, V1Taint,
    V1PersistentVolumeClaim, V1PersistentVolumeClaimStatus,
    V1VolumeAttachment, V1VolumeAttachmentStatus, V1VolumeAttachmentSpec, V1VolumeAttachmentSource,
    V1PodStatus, V1Pod, V1PodSpec, V1Namespace
)
from clusterloader2.kubernetes_client import KubernetesClient

class TestKubernetesClient(unittest.TestCase):

    @patch('kubernetes.config.load_kube_config')
    def setUp(self, mock_load_kube_config):
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

    @patch('clusterloader2.kubernetes_client.KubernetesClient.get_nodes')
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

        self.maxDiff = None
        self.assertCountEqual(ready_nodes, 
            [node_ready_network_available, node_ready_no_network_condition, node_ready_taint_no_effect]
        )
    
    def _create_namespace(self, name):
        return V1Namespace(metadata=V1ObjectMeta(name=name))

    def _create_pod(self, namespace, name, phase, labels=None):
        return V1Pod(
            metadata=V1ObjectMeta(name=name, namespace=namespace, labels=labels),
            status=V1PodStatus(phase=phase),
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

    @patch('clusterloader2.kubernetes_client.KubernetesClient.create_namespace')
    @patch('clusterloader2.kubernetes_client.KubernetesClient.delete_namespace')
    def test_create_delete_namespace(self, mock_delete_namespace, mock_create_namespace):
        name = "test-namespace"
        mock_namespace = self._create_namespace(name)
        mock_create_namespace.return_value = mock_namespace

        ns = self.client.create_namespace(name)

        self.assertEqual(ns.metadata.name, mock_create_namespace.return_value.metadata.name)
        mock_create_namespace.assert_called_once_with(name)

        mock_delete_namespace.return_value = None
        ns = self.client.delete_namespace(name)
        self.assertEqual(mock_delete_namespace.return_value, ns)
        mock_delete_namespace.assert_called_once_with(name)

    @patch('clusterloader2.kubernetes_client.KubernetesClient.get_running_pods_by_namespace')
    def test_get_running_pods_by_namespace(self, mock_get_running_pods_by_namespace):
        namespace = "test-namespace"

        running_pods = 10
        pending_pods = 5
        labels = {"csi": "true"}
        all_pods = [
            self._create_pod(namespace=namespace, name=f"pod-{i}", phase="Running", labels=labels) for i in range(running_pods)
        ]
        all_pods.extend(
            self._create_pod(namespace=namespace, name=f"pod-{i}", phase="Pending", labels=labels) for i in range(running_pods, pending_pods + running_pods))

        mock_get_running_pods_by_namespace.return_value = [pod for pod in all_pods if pod.status.phase == "Running"]
        pods = self.client.get_running_pods_by_namespace(namespace=namespace, label_selector="csi=true")
        for pod in pods:
            self.assertEqual(pod.metadata.labels, labels)
            self.assertEqual(pod.status.phase, "Running")
        mock_get_running_pods_by_namespace.assert_called_once_with(namespace=namespace, label_selector="csi=true")
        self.assertEqual(len(all_pods), running_pods + pending_pods)
        self.assertEqual(len(pods), running_pods)
    
    @patch('clusterloader2.kubernetes_client.KubernetesClient.get_bound_persistent_volume_claims_by_namespace')
    def test_get_bound_persistent_volume_claims_by_namespace(self, mock_get_persistent_volume_claims_by_namespace):
        namespace = "test-namespace"
        bound_claims = 10
        pending_claims = 5
        all_claims = [
            self._create_pvc(name=f"pvc-{i}", namespace=namespace, phase="Bound") for i in range(bound_claims)
        ]
        all_claims.extend(
            self._create_pvc(name=f"pvc-{i}", namespace=namespace, phase="Pending") for i in range(bound_claims, pending_claims + bound_claims))

        mock_get_persistent_volume_claims_by_namespace.return_value = [claim for claim in all_claims if claim.status.phase == "Bound"]
        claims = self.client.get_bound_persistent_volume_claims_by_namespace(namespace=namespace)
        self.assertEqual(len(all_claims), bound_claims + pending_claims)
        self.assertEqual(len(claims), bound_claims)
        mock_get_persistent_volume_claims_by_namespace.assert_called_once_with(namespace=namespace)

    @patch('clusterloader2.kubernetes_client.KubernetesClient.get_attached_volume_attachments')
    def test_get_attached_volume_attachments(self, mock_get_volume_attachments):
        attached_attachments = 10
        detached_attachments = 5
        all_attachments = [
            self._create_volume_attachment(
                name=f"attachment-{i}", namespace="test-namespace", phase=True, attacher="csi-driver", node_name="node-{i}"
            ) for i in range(attached_attachments)
        ]
        all_attachments.extend(
            self._create_volume_attachment(
                name=f"attachment-{i}", namespace="test-namespace", phase=False, attacher="csi-driver", node_name="node-{i}"
            ) for i in range(attached_attachments, detached_attachments + attached_attachments))

        mock_get_volume_attachments.return_value = [attachment for attachment in all_attachments if attachment.status.attached]
        attachments = self.client.get_attached_volume_attachments()
        self.assertEqual(len(all_attachments), attached_attachments + detached_attachments)
        self.assertEqual(len(attachments), attached_attachments)
        mock_get_volume_attachments.assert_called_once()

if __name__ == '__main__':
    unittest.main()