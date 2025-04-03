from kubernetes_client import KubernetesClient
from data_type import ResourceConfig, NodeResourceConfig

class KubeletConfig:
    def __init__(self, eviction_hard_memory: str):
        self.eviction_hard_memory = eviction_hard_memory

    default_kubelet_config = None  # Default value, can be overridden

    @staticmethod
    def set_default_config(eviction_hard_memory: str):
        KubeletConfig.default_kubelet_config = KubeletConfig(eviction_hard_memory)

    @staticmethod
    def get_default_config():
        return KubeletConfig.default_kubelet_config

    def __str__(self):
        return f"eviction_hard_memory: {self.eviction_hard_memory}"

    def __eq__(self, other):
        if not isinstance(other, KubeletConfig):
            return False
        return self.eviction_hard_memory == other.eviction_hard_memory

    def needs_override(self, other):
        if not isinstance(other, KubeletConfig):
            raise Exception(f"Invalid type for comparison: {type(other)}")
        return self.eviction_hard_memory != other.eviction_hard_memory


class ClusterController:
    def __init__(self,  client: KubernetesClient, node_label:str):
        self.client = client

        self.node_label = node_label
        self.node_selector = f"{self.node_label}=true"

        self.nodes = None
        self.node_count = 0

    def populate_nodes(self, node_count: int):
        nodes = self.client.get_nodes(label_selector=self.node_selector)
        if len(nodes) == 0:
            raise Exception(f"Invalid node selector: {self.node_selector}")
        if len(nodes) < node_count:
            print(f"expected nodes available for the given node selector: {self.node_selector}. Found {len(nodes)}, expected {self.node_count}")

        self.node_count = len(nodes)
        self.nodes = nodes



    def reconfigure_kubelet(self, kubelet_config: KubeletConfig):
        if KubeletConfig.get_default_config().needs_override(kubelet_config):
            print(f"Reconfiguring {kubelet_config}")
            daemonset_yaml = self.generate_kubelet_reconfig_daemonset(kubelet_config)
            self.client.create_daemonset(daemonset_yaml)
        else:
            print(f"using default kubelet configuration. Skip reconfiguring kubelet.")

    def generate_kubelet_reconfig_daemonset(self, kubelet_config: KubeletConfig) -> str:
        kubelet_daemonset = """apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: kubelet-config-updater
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: kubelet-config-updater
  template:
    metadata:
      labels:
        app: kubelet-config-updater
    spec:
      hostPID: true
      nodeSelector:
        {node_label}: "true"
      tolerations:
      - key: {node_label}
        operator: "Equal"
        value: "true"
        effect: "NoSchedule"
      - key: {node_label}
        operator: "Equal"
        value: "true"
        effect: "NoExecute"
      containers:
      - name: kubelet-config-updater
        image: mcr.microsoft.com/cbl-mariner/busybox:2.0
        securityContext:
          privileged: true
        command:
        - /bin/sh
        - -c
        - |
          echo "Updating kubelet configuration..."
          sed -i 's/--eviction-hard=memory\.available<{default_eviction_memory}/--eviction-hard=memory\.available<{desired_eviction_memory}/' "/etc/default/kubelet"
          echo "Restarting kubelet..."
          nsenter --mount=/proc/1/ns/mnt -- systemctl restart kubelet
          echo "Done. Sleeping indefinitely to keep the pod running."
          sleep infinity
        volumeMounts:
        - name: systemd
          mountPath: /run/systemd
        - name: kubelet-config
          mountPath: /etc/default
      volumes:
      - name: kubelet-config
        hostPath:
          path: /etc/default
          type: Directory
      - name: systemd
        hostPath:
          path: /run/systemd
      restartPolicy: Always
        """
        # rewrite using string template
        return kubelet_daemonset.format(node_label = self.node_label, default_eviction_memory=KubeletConfig.get_default_config().eviction_hard_memory, desired_eviction_memory= kubelet_config.eviction_hard_memory)

    def get_system_pods_allocated_resources(self) -> ResourceConfig:
        pods = self.client.get_pods_by_namespace("kube-system", field_selector=f"spec.nodeName={self.nodes[0].metadata.name}")

        cpu_request = 0
        memory_request = 0
        for pod in pods:
            for container in pod.spec.containers:
                print(f"Pod {pod.metadata.name} has container {container.name} with resources {container.resources.requests}")
                cpu_request += int(container.resources.requests.get("cpu", "0m").replace("m", ""))
                memory_request += int(container.resources.requests.get("memory", "0Mi").replace("Mi", ""))

        return  ResourceConfig(memory_request * 1024, cpu_request)

    def get_node_available_resource(self) -> ResourceConfig:
        node_allocatable_cpu = int(self.nodes[0].status.allocatable["cpu"].replace("m", ""))
        # Bottlerocket OS SKU on EKS has allocatable_memory property in Mi. AKS and Amazon Linux (default SKUs)
        # user Ki. Handling the Mi case here and converting Mi to Ki, if needed.
        #int(nodes[0].status.allocatable["memory"].replace("Ki", ""))
        node_allocatable_memory_str = self.nodes[0].status.allocatable["memory"]
        if "Mi" in node_allocatable_memory_str:
            node_allocatable_memory_ki = int(node_allocatable_memory_str.replace("Mi", "")) * 1024
        elif "Ki" in node_allocatable_memory_str:
            node_allocatable_memory_ki = int(node_allocatable_memory_str.replace("Ki", ""))
        else:
            raise Exception(f"Unexpected format of allocatable memory node property: {node_allocatable_memory_str}")

        return ResourceConfig( node_allocatable_memory_ki, node_allocatable_cpu)

    def populate_node_resources(self) -> NodeResourceConfig:
        # Get the first node to get the allocatable resources
        system_allocated = self.get_system_pods_allocated_resources()
        node_available = self.get_node_available_resource()
        remaining = node_available.minus(system_allocated)

        return NodeResourceConfig(self.node_label, self.node_selector, system_allocated,node_available,remaining )

    def verify_measurement(self, node_count: int):
        self.populate_nodes(node_count)
        user_pool = [node.metadata.name for node in self.nodes]
        print(f"User pool: {user_pool}")
        for node_name in user_pool:
            metrics = self.client.get_node_metrics(node_name)
            # print(metrics)

