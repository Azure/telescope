
from data_type import NodeResourceConfig, ResourceConfig, ResourceStressor
from typing import Optional

DAEMONSETS_PER_NODE_MAP = {
    "aws": 2,
    "aks": 6
}

class WorkloadConfig:
    def __init__(self, stress_config: ResourceStressor,  resource_request: ResourceConfig,
                 resource_limit: ResourceConfig, resource_usage: ResourceConfig):
        self.stress_config = stress_config

        self.resource_usage =  resource_usage
        self.resource_limit = resource_limit
        self.resource_request = resource_request

    def debug_stress_info(self):
        stress_pod_info_template = """stressPod: 
  loadDuration: {load_duration}
  loadType: {load_type}
  resource:
    request: {pod_request}
    limit: {pod_limit}
    consume: {pod_consume}  
    """
        print(stress_pod_info_template.format(
            load_duration=self.stress_config.load_duration,
            load_type=self.stress_config.load_type,
            pod_request=self.resource_request,
            pod_consume=self.resource_usage,
            pod_limit=self.resource_limit))

class CL2Configurator:
    def __init__(self, max_pods : int, stress_config: ResourceStressor, timeout_seconds:int, provider:str):
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.stress_config = stress_config
        self.pods_per_node = max_pods - DAEMONSETS_PER_NODE_MAP[provider]

        self.node_config: Optional[NodeResourceConfig] = None
        self.workload_config: Optional[WorkloadConfig] = None

    def generate_cl2_override(self, node_config: NodeResourceConfig):

        # calculate the pod request resource, currently try to allocate MEMORY_SCALE_FACTOR available on the node
        # other strategy can be static memory allocation
        resource_limit = node_config.remaining_resources.divide(self.pods_per_node)
        resource_request = ResourceConfig(300000, 100) #300Mi memory limit
        # greedy behave workload consume as much memory as possible from the node, and a bit more
        resource_load =  resource_limit.multiply(self.stress_config.load_factor)

        self.workload_config = WorkloadConfig(self.stress_config, resource_request, resource_limit, resource_load)
        self.node_config = node_config

