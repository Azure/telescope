
from data_type import NodeResourceConfigurator, WorkloadConfig

DAEMONSETS_PER_NODE_MAP = {
    "aws": 2,
    "aks": 6
}

MEMORY_SCALE_FACTOR = 0.95 # 95% of the total allocatable memory to account for error margin

# system_allocated_resources, node_allocatable_resources, pods_per_node, operation_timeout_seconds

class EvictionEval:
    def __init__(self,max_pods : int,  timeout_seconds:int, provider:str):

        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.pods_per_node = max_pods - DAEMONSETS_PER_NODE_MAP[provider]

        self.workload_config: WorkloadConfig = None

    def generate_cl2_override(self, node_config: NodeResourceConfigurator, load_type: str):
        # Get the first node to get the allocatable resources
        workload_config = WorkloadConfig(load_type)
        workload_config.calculate_workload_spec(node_config, self.pods_per_node, self.timeout_seconds)
        self.workload_config = workload_config

    def export_cl2_override(self, node_config: NodeResourceConfigurator, override_file):
        print(f"write override file to {override_file}")

        with open(override_file, 'w', encoding='utf-8') as file:
            file.write(f"CL2_NODE_LABEL: {node_config.node_label}\n")
            file.write(f"CL2_NODE_SELECTOR: {node_config.node_selector}\n")
            file.write(f"CL2_NODE_COUNT: {node_config.node_count}\n")

            file.write(f"CL2_OPERATION_TIMEOUT: {self.timeout_seconds}\n")
            file.write(f"CL2_PROVIDER: {self.provider}\n")
            file.write(f"CL2_DEPLOYMENT_SIZE: {self.pods_per_node}\n")

            file.write(f"CL2_LOAD_TYPE: {self.workload_config.load_type}\n")
            file.write(f"CL2_RESOURCE_CONSUME_MEMORY_REQUEST_KI: {self.workload_config.pod_request_resource.memory_ki}Ki\n")
            file.write(f"CL2_RESOURCE_CONSUME_CPU: {self.workload_config.pod_request_resource.cpu_milli}\n")
            file.write(f"CL2_RESOURCE_CONSUME_MEMORY_CONSUME_MI: {self.workload_config.load_resource.memory_ki // 1024}\n") # Convert Ki to Mi
            file.write(f"CL2_RESOURCE_CONSUME_DURATION_SEC: {self.workload_config.load_duration_seconds}\n")

            file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
            file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")

        file.close()
