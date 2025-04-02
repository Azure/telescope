
from data_type import  NodeResourceConfig, ResourceConfig
from typing import Optional

DAEMONSETS_PER_NODE_MAP = {
    "aws": 2,
    "aks": 6
}

MEMORY_SCALE_FACTOR = 0.95 # 95% of the total allocatable memory to account for error margin

class WorkloadConfig:
    def __init__(self,load_type: str,  load_duration_seconds: int, pod_request_resource: ResourceConfig, load_resource: ResourceConfig):
        self.load_type = load_type
        self.load_duration_seconds = load_duration_seconds

        self.load_resource =  load_resource
        self.pod_request_resource = pod_request_resource

    def debug_stress_info(self):
        stress_pod_info_template = """stressPod: 
  timeout: {timeout}
  loadType: {load_type}
  resource:
    request: {pod_request}
    consume: {pod_consume}  
    """
        print(stress_pod_info_template.format(
            timeout=self.load_duration_seconds,
            load_type=self.load_type,
            pod_request=self.pod_request_resource,
            pod_consume=self.load_resource))

class CL2Configurator:
    def __init__(self, max_pods : int,  timeout_seconds:int, provider:str):
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.pods_per_node = max_pods - DAEMONSETS_PER_NODE_MAP[provider]

        self.node_config: Optional[NodeResourceConfig] = None
        self.workload_config: Optional[WorkloadConfig] = None

    def generate_cl2_override(self, node_config: NodeResourceConfig, load_type: str):
        # kubelet default watch is 10 seconds, try to get the pod to consume memory in 10 seconds (and spread over pods)
        resource_stress_duration = 10 * self.pods_per_node
        # Limit the resource-consume runtime to clusterloader timeout seconds
        if resource_stress_duration > self.timeout_seconds:
            resource_stress_duration =  self.timeout_seconds

        # calculate the pod request resource, currently try to allocate MEMORY_SCALE_FACTOR available on the node
        # other strategy can be static memory allocation
        pod_request_resource = node_config.remaining_resources.multiply(MEMORY_SCALE_FACTOR).divide(self.pods_per_node)

        # greedy behave workload consume as much memory as possible from the node, and a bit more
        load_resource =  node_config.remaining_resources.divide(self.pods_per_node).multiply(1.1)

        self.workload_config = WorkloadConfig(load_type, resource_stress_duration, pod_request_resource, load_resource)
        self.node_config = node_config

