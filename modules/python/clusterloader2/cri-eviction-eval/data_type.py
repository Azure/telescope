from kubernetes_client import KubernetesClient

class ResourceConfig:
    def __init__(self, memory, cpu):
        self.memory_ki = memory
        self.cpu_milli = cpu

    def minus(self, other):
        return ResourceConfig(self.memory_ki - other.memory_ki, self.cpu_milli - other.cpu_milli)

    def divide(self, parts):
        return ResourceConfig(self.memory_ki // parts, self.cpu_milli // parts)

    def multiply(self, factor):
        return ResourceConfig(int(self.memory_ki * factor), int(self.cpu_milli * factor))
    def __str__(self):
        return f"memory: {self.memory_ki}Ki, cpu: {self.cpu_milli}milli"

# define struct to hold node resource information
# NodeResourceConfig has system_allocated_resources, node_allocatable_resources and remaining_resources

class NodeResourceConfig:
    def __init__(self,
                 system_allocated_resources: ResourceConfig,
                 node_allocatable_resources: ResourceConfig,
                 remaining_resources: ResourceConfig):
        self.system_allocated_resources = system_allocated_resources
        self.node_allocatable_resources = node_allocatable_resources
        self.remaining_resources = remaining_resources

    def __str__(self):
        resource_info_template = """:
    allocatable: {allocatable}
    allocated: {allocated}
    testRunActual: {actual}
    """
        print(resource_info_template.format(allocatable=self.node_allocatable_resources, allocated=self.system_allocated_resources, actual=self.remaining_resources))


class NodeResourceConfigurator:
    def __init__(self,  node_label: str, node_count:int):
        self.node_label = node_label
        self.node_count = node_count

        self.node_selector = f"{self.node_label}=true"
        self.nodes = None

    def validate(self, client: KubernetesClient):
        nodes = client.get_nodes(label_selector=self.node_selector)
        if len(nodes) == 0:
            raise Exception(f"Invalid node selector: {self.node_selector}")
        if len(nodes) < self.node_count:
            print(f"expected nodes available for the given node selector: {self.node_selector}. Found {len(nodes)}, expected {self.node_count}")

        self.nodes = nodes

    def get_system_pods_allocated_resources(self, client: KubernetesClient) -> ResourceConfig:
        pods = client.get_pods_by_namespace("kube-system", field_selector=f"spec.nodeName={self.nodes[0].metadata.name}")

        cpu_request = 0
        memory_request = 0
        for pod in pods:
            for container in pod.spec.containers:
                print(f"Pod {pod.metadata.name} has container {container.name} with resources {container.resources.requests}")
                cpu_request += int(container.resources.requests.get("cpu", "0m").replace("m", ""))
                memory_request += int(container.resources.requests.get("memory", "0Mi").replace("Mi", ""))

        return  ResourceConfig(memory_request * 1024, cpu_request)

    def get_node_available_resource(self) -> ResourceConfig:
        node_allocatable_cpu = int(self.nodes[0].status.allocatable.cpu.replace("m", ""))

        # Bottlerocket OS SKU on EKS has allocatable_memory property in Mi. AKS and Amazon Linux (default SKUs)
        # user Ki. Handling the Mi case here and converting Mi to Ki, if needed.
        #int(nodes[0].status.allocatable["memory"].replace("Ki", ""))
        node_allocatable_memory_str = self.nodes[0].status.allocatable.memory
        if "Mi" in node_allocatable_memory_str:
            node_allocatable_memory_ki = int(node_allocatable_memory_str.replace("Mi", "")) * 1024
        elif "Ki" in node_allocatable_memory_str:
            node_allocatable_memory_ki = int(node_allocatable_memory_str.replace("Ki", ""))
        else:
            raise Exception(f"Unexpected format of allocatable memory node property: {node_allocatable_memory_str}")

        return ResourceConfig( node_allocatable_memory_ki, node_allocatable_cpu)


    def populate_node_resources(self, client: KubernetesClient) -> NodeResourceConfig:
        # Get the first node to get the allocatable resources
        system_allocated = self.get_system_pods_allocated_resources(client)
        node_available = self.get_node_available_resource()
        remaining = node_available.minus(system_allocated)

        return NodeResourceConfig(system_allocated,node_available,remaining )

class WorkloadConfig:
    def __init__(self, load_type:str):
        self.load_type = load_type

        self.load_resource: ResourceConfig = None
        self.load_duration_seconds: int = None
        self.pod_request_resource : ResourceConfig = None

    def debug_stress_info(self):
        stress_pod_info_template = """
    stressPod: 
      timeout: {timeout}
      memory:
        request: {memory_request}Ki
        consume: {memory_consume}Ki
      cpu:
        request: {cpu_request}milli
    """
        print(stress_pod_info_template.format(
            timeout=self.load_duration_seconds, memory_request=self.pod_request_resource.memory_ki,  memory_consume=self.load_resource.memory_ki, cpu_request=self.pod_request_resource.cpu_milli))

    def calculate_workload_spec(self, node_config:NodeResourceConfigurator, pods_per_node: int, operation_timeout_seconds: int):
        # kubelet default watch is 10 seconds, try to get the pod to consume memory in 10 seconds (and spread over pods)
        resource_stress_duration = 10 * pods_per_node
        # Limit the resource-consume runtime to clusterloader timeout seconds
        if resource_stress_duration > operation_timeout_seconds:
            resource_stress_duration = operation_timeout_seconds
        self.load_duration_seconds = resource_stress_duration
        self.pod_request_resource = node_config.remaining_resources.divide(pods_per_node)

        # greedy behave workload consume memory more than requested to trigger OOM
        self.load_resource =  node_config.remaining_resources.divide(pods_per_node).multiply(1.1)
        self.debug_stress_info()
