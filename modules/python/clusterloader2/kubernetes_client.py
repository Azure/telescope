from kubernetes import client, config


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

    def describe_node(self, node_name):
        return self.api.read_node(node_name)

    def get_nodes(self, label_selector=None, field_selector=None):
        return self.api.list_node(label_selector=label_selector, field_selector=field_selector).items
    
    def get_ready_nodes(self):
        """
        Get a list of nodes that are ready to be scheduled. Should apply all those conditions:
        - 'Ready' condition status is True
        - 'NetworkUnavailable' condition status is not present or is False
        - Spec unschedulable is False
        - Spec taints do not have any of the builtin taints keys with effect 'NoSchedule' or 'NoExecute'
        """
        nodes = self.get_nodes()
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