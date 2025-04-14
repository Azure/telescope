from typing import Optional
from .data_type import NodeResourceConfig, ResourceConfig, ResourceStressor,LoadQoS

DAEMONSETS_PER_NODE_MAP = {
    "aws": 2,
    "aks": 6
}

class WorkloadConfig:
    def __init__(self, stress_config: ResourceStressor, resource_usage: ResourceConfig, resource_request: Optional[ResourceConfig],
                 resource_limit: Optional[ResourceConfig]):
        self.stress_config = stress_config
        self.resource_usage =  resource_usage

        self.resource_limit = resource_limit
        self.resource_request = resource_request

    def debug_stress_info(self):
        stress_pod_info_template = """stressPod:
  stressor: {stress_config}
  resource:
    consume: {pod_consume}  
    request: {pod_request}
    limit: {pod_limit}
    """
        print(stress_pod_info_template.format(
            stress_config=self.stress_config,
            pod_request=self.resource_request,
            pod_consume=self.resource_usage,
            pod_limit=self.resource_limit))

class CL2Configurator:
    def __init__(self, max_pods : int, stress_config: ResourceStressor, timeout_seconds:int, provider:str, overload_factor: float= 1.1):
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.stress_config = stress_config
        self.pods_per_node = max_pods - DAEMONSETS_PER_NODE_MAP[provider]
        self.overload_factor = overload_factor

        self.node_config: Optional[NodeResourceConfig] = None
        self.workload_config: Optional[WorkloadConfig] = None

    def generate_cl2_override(self, node_config: NodeResourceConfig):


        # calculate the pod request resource, currently try to allocate MEMORY_SCALE_FACTOR available on the node
        # other strategy can be static memory allocation
        resource_limit = node_config.remaining_resources.divide(self.pods_per_node)

        resource_request = ResourceConfig(100000, 100) #100Mi memory request
        # greedy behave workload consume as much memory as possible from the node, and a bit more

        resource_load =  resource_limit.multiply(self.overload_factor)

        self.node_config = node_config

        if self.stress_config.load_factor == LoadQoS.BEST_EFFORT:
            # for best effort workload, we do not set request or limit
            self.workload_config = WorkloadConfig(self.stress_config, resource_load, None, None )
        elif self.stress_config.load_factor == LoadQoS.BURSTABLE:
            # for burstable workload, we just set request and no limit
            self.workload_config = WorkloadConfig(self.stress_config, resource_load, resource_request, None)
        elif self.stress_config.load_factor == LoadQoS.GUARANTEED:
            # for guaranteed workload, we set request and limit to the same value
            self.workload_config = WorkloadConfig(self.stress_config, resource_load, resource_limit, resource_limit)
        else:
            raise ValueError(f"Unknown load factor: {self.stress_config.load_factor}")
