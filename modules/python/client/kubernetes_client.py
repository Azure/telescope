from kubernetes import client, config

class KubernetesClient:
    def __init__(self, kubeconfig=None):
        config.load_kube_config(kubeconfig)
        self.api = client.CoreV1Api()
        self.app = client.AppsV1Api()
        self.storage = client.StorageV1Api()
    
    def get_app_client(self):
        return self.app

    def describe_node(self, node_name):
        return self.api.read_node(node_name)

    def get_nodes(self, label_selector=None, field_selector=None):
        return self.api.list_node(label_selector=label_selector, field_selector=field_selector).items
    
    def get_ready_nodes(self, label_selector=None, field_selector=None):
        nodes = self.get_nodes(label_selector=label_selector, field_selector=field_selector)
        return [node for node in nodes for condition in node.status.conditions if condition.type == "Ready" and condition.status == "True"]
    
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
            self.api.delete_namespaced_persistent_volume_claim(pvc.metadata.name, namespace, body=client.V1DeleteOptions())
    
    def get_attached_volume_attachments(self):
        volume_attachments = self.storage.list_volume_attachment().items
        return [attachment for attachment in volume_attachments if attachment.status.attached]

    def create_namespace(self, namespace):
        # Check if namespace exists
        try:
            namespace = self.api.read_namespace(namespace)
            return namespace
        except client.rest.ApiException as e:
            if e.status == 404:
                body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
                return self.api.create_namespace(body)
            else:
                raise e
    
    def delete_namespace(self, namespace):
        return self.api.delete_namespace(namespace)
