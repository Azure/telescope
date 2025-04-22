from typing import Optional
import yaml

from kubernetes import utils, client

from clusterloader2.kubelet_benchmark.data_type import ResourceConfig, NodeResourceConfig
from clusterloader2.kubernetes_client import KubernetesClient


MEMORY_SCALE_FACTOR = 0.95 # 95% of the total allocatable memory to account for error margin
# pylint: disable=anomalous-backslash-in-string
class KubeletConfig:
    def __init__(self, eviction_hard_memory: str, busybox_image: str = "ghcr.io/containerd/busybox:1.36"):
        self.eviction_hard_memory = eviction_hard_memory
        self.busybox_image = busybox_image

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
    def __init__(self,  k8s_client: KubernetesClient, node_label:str):
        self.client = k8s_client
        self.api_client = k8s_client.api_client

        self.node_label = node_label
        self.node_selector = f"{self.node_label}=true"

        self.nodes = None
        self.node_count = 0

    def populate_nodes(self, node_count: int):
        nodes = self.client.get_nodes(label_selector=self.node_selector)
        if len(nodes) == 0:
            raise Exception(f"Could not find nodes with selector: {self.node_selector}")
        if len(nodes) < node_count:
            print(f"expected nodes available for the given node selector: {self.node_selector}. Found {len(nodes)}, expected {self.node_count}")

        self.node_count = len(nodes)
        self.nodes = nodes

    def reconfigure_kubelet(self, kubelet_config: KubeletConfig):
        if KubeletConfig.get_default_config().needs_override(kubelet_config):
            print(f"Reconfiguring {kubelet_config}")
            daemonset_yaml = self.generate_kubelet_reconfig_daemonset(kubelet_config)
            daemonset_object = list(yaml.safe_load_all(daemonset_yaml))
            try:
                self.client.create_daemonset(daemonset_object)
            except utils.FailToCreateError as e:
                print(f"Error creating ds: it might already exist: {e}")
        else:
            print("using default kubelet configuration. Skip reconfiguring kubelet.")

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
        image: {busybox_image}
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
        return kubelet_daemonset.format(node_label = self.node_label,
                                        busybox_image=kubelet_config.busybox_image,
                                        default_eviction_memory=KubeletConfig.get_default_config().eviction_hard_memory,
                                        desired_eviction_memory= kubelet_config.eviction_hard_memory)

    def get_system_pods_allocated_resources(self) -> tuple[ResourceConfig, int]:
        # iterate over all namespaces used by aks
        cpu_request = 0
        memory_request = 0
        pod_counts = 0
        
        known_namespaces = ["kube-system", "kube-public", "kube-node-lease", "gatekeeper-system", "gatekeeper-audit"]
        for namespace in known_namespaces:
            pods = self.client.get_pods_by_namespace(namespace, field_selector=f"spec.nodeName={self.nodes[0].metadata.name}")
            if len(pods) == 0:
                print(f"No pods in {namespace} namespace")
                continue
        
            for pod in pods:
                for container in pod.spec.containers:
                    print(f"Pod {pod.metadata.name} has container {container.name} with resources {container.resources.requests}")
                    # check whether the container has resources requests
                    if container.resources.requests is None:
                        print(f"Container {container.name} does not have resources requests.")
                        continue
                    cpu_request += int(container.resources.requests.get("cpu", "0m").replace("m", ""))
                    memory_request += int(container.resources.requests.get("memory", "0Mi").replace("Mi", ""))
            pod_counts += len(pods)
            print(f"{namespace} has {len(pods)} pods, consumes memory {memory_request}Mi and cpu {cpu_request}")
        return  ResourceConfig(memory_request * 1024, cpu_request), pod_counts

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
        system_allocated, pods = self.get_system_pods_allocated_resources()
        node_available = self.get_node_available_resource()

        remaining = node_available.minus(system_allocated)

        return NodeResourceConfig(pods, self.node_label, self.node_selector, system_allocated,node_available,remaining )

    def verify_measurement(self, node_count: int):
        self.populate_nodes(node_count)
        user_pool = [node.metadata.name for node in self.nodes]
        print(f"User pool: {user_pool}")
        for node_name in user_pool:
            self.get_node_metrics(node_name)
            # print(metrics)

    def get_node_metrics(self, node_name: str)-> Optional[str]:
        url = f"/api/v1/nodes/{node_name}/proxy/metrics"

        try:
            response = self.api_client.call_api(
                resource_path = url,
                method = "GET",
                auth_settings=['BearerToken'],
                response_type="str",
                _preload_content=True)

            metrics = response[0]  # The first item contains the response data
            filtered_metrics = "\n".join(
                line for line in metrics.splitlines() if line.startswith("kubelet_pod_start") or line.startswith("kubelet_runtime_operations")
            )

            #return the printed line in 1 line
            return f"##[section]Metrics for node: {node_name}\n{filtered_metrics}\n"
        except client.ApiException as e:
            return f"##[section]Error fetching Metrics for node: {node_name}\n{e}\n"
