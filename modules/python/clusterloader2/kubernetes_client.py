# TODO: Move this file to a separate folder called 'clients'
from kubernetes import client, config, utils

# https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/#taint-based-evictions
# https://kubernetes.io/docs/reference/labels-annotations-taints/
builtin_taints_keys = [
	"node.kubernetes.io/not-ready",
	"node.kubernetes.io/unreachable",
	"node.kubernetes.io/pid-pressure",
	"node.kubernetes.io/out-of-disk",
	"node.kubernetes.io/memory-pressure",
	"node.kubernetes.io/disk-pressure",
	"node.kubernetes.io/network-unavailable",
	"node.kubernetes.io/unschedulable",
	"node.cloudprovider.kubernetes.io/uninitialized",
	"node.cloudprovider.kubernetes.io/shutdown",
]

class KubernetesClient:
    def __init__(self, kubeconfig=None):
        config.load_kube_config(kubeconfig)
        self.api = client.CoreV1Api()
        self.app = client.AppsV1Api()
        self.api_client = client.ApiClient()
        self.storage = client.StorageV1Api()

    def get_app_client(self):
        return self.app

    def describe_node(self, node_name):
        return self.api.read_node(node_name)

    def get_nodes(self, label_selector=None, field_selector=None):
        return self.api.list_node(label_selector=label_selector, field_selector=field_selector).items

    def get_ready_nodes(self, label_selector=None, field_selector=None):
        """
        Get a list of nodes that are ready to be scheduled. Should apply all those conditions:
        - 'Ready' condition status is True
        - 'NetworkUnavailable' condition status is not present or is False
        - Spec unschedulable is False
        - Spec taints do not have any of the builtin taints keys with effect 'NoSchedule' or 'NoExecute'
        """
        nodes = self.get_nodes(label_selector=label_selector, field_selector=field_selector)
        return [
            node for node in nodes
            if self._is_node_schedulable(node) and self._is_node_untainted(node)
        ]

    def _is_node_schedulable(self, node):
        status_conditions = {cond.type: cond.status for cond in node.status.conditions}
        is_schedulable = (
            status_conditions.get("Ready") == "True"
            and status_conditions.get("NetworkUnavailable") != "True"
            and node.spec.unschedulable is not True
        )
        if not is_schedulable:
            print(f"Node NOT Ready: '{node.metadata.name}' is not schedulable. status_conditions: {status_conditions}. unschedulable: {node.spec.unschedulable}")

        return is_schedulable

    def _is_node_untainted(self, node):
        if not node.spec.taints:
            return True

        for taint in node.spec.taints:
            if taint.key in builtin_taints_keys and taint.effect in ("NoSchedule", "NoExecute"):
                print(f"Node NOT Ready: '{node.metadata.name}' has taint '{taint.key}' with effect '{taint.effect}'")
                return False

        return True

    def get_pods_by_namespace(self, namespace, label_selector=None, field_selector=None):
        return self.api.list_namespaced_pod(namespace=namespace, label_selector=label_selector, field_selector=field_selector).items

    def get_running_pods_by_namespace(self, namespace=None, label_selector=None, field_selector=None):
        pods = self.get_pods_by_namespace(namespace=namespace, label_selector=label_selector, field_selector=field_selector)
        return [pod for pod in pods if pod.status.phase == "Running"]

    def get_persistent_volume_claims_by_namespace(self, namespace):
        return self.api.list_namespaced_persistent_volume_claim(namespace=namespace).items

    def get_bound_persistent_volume_claims_by_namespace(self, namespace):
        claims = self.get_persistent_volume_claims_by_namespace(namespace=namespace)
        return [claim for claim in claims if claim.status.phase == "Bound"]

    def delete_persistent_volume_claim_by_namespace(self, namespace):
        pvcs = self.get_persistent_volume_claims_by_namespace(namespace=namespace)
        for pvc in pvcs:
            try:
                self.api.delete_namespaced_persistent_volume_claim(pvc.metadata.name, namespace, body=client.V1DeleteOptions())
            except client.rest.ApiException as e:
                print(f"Error deleting PVC '{pvc.metadata.name}': {e}")

    def get_volume_attachments(self):
        return self.storage.list_volume_attachment().items

    def get_attached_volume_attachments(self):
        volume_attachments = self.get_volume_attachments()
        return [attachment for attachment in volume_attachments if attachment.status.attached]

    def create_namespace(self, namespace):
        """
        Returns the namespace object if it exists, otherwise creates it.
        """
        try:
            namespace = self.api.read_namespace(namespace)
            print(f"Namespace '{namespace.metadata.name}' already exists.")
            return namespace
        except client.rest.ApiException as e:
            if e.status == 404:
                body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
                return self.api.create_namespace(body)
            raise e

    def delete_namespace(self, namespace):
        return self.api.delete_namespace(namespace)

    def create_daemonset(self, daemonset_object):
        utils.create_from_yaml(self.api_client, yaml_objects=daemonset_object)
