from enum import Enum

class ResourceConfig:
    def __init__(self, memory: int, cpu: int):
        self.memory_ki = memory
        self.cpu_milli = cpu

    def minus(self, other):
        return ResourceConfig(self.memory_ki - other.memory_ki, self.cpu_milli - other.cpu_milli)

    def divide(self, parts):
        return ResourceConfig(self.memory_ki // parts, self.cpu_milli // parts)

    def multiply(self, factor: float):
        return ResourceConfig(int(self.memory_ki * factor), int(self.cpu_milli * factor))
    def __str__(self):
        return f"memory: {self.memory_ki}Ki, cpu: {self.cpu_milli}milli"

class LoadDuration(Enum):
    SPIKE = "spike"
    NORMAL = "normal"
    LONG = "long"

class LoadQoS(Enum):
    BEST_EFFORT = "best_effort"
    BURSTABLE = "burstable"
    GUARANTEED = "guaranteed"

class ResourceStressor:
    def __init__(self, load_type: str,  load_factor:str =  "best_effort", load_duration: str = "normal"):

        self.load_type = load_type
        self.load_factor =  LoadQoS(load_factor)
        self.load_duration = LoadDuration(load_duration)

    def __str__(self):
        return f"load_type: {self.load_type}, load_factor: {self.load_factor}, load_duration: {self.load_duration}"

    def get_stress_duration_seconds(self):
        # kubelet default watch is 10 seconds, try to get the pod to consume memory in [5, 10, 15] seconds
        stress_duration = 10
        if self.load_duration == LoadDuration.SPIKE:
            stress_duration = 5
        elif self.load_duration == LoadDuration.NORMAL:
            stress_duration = 10
        elif self.load_duration == LoadDuration.LONG:
            stress_duration = 15
        else:
            raise ValueError(f"Unknown load duration: {self.load_duration}")
        return stress_duration

# define struct to hold node resource information
# NodeResourceConfig has system_allocated_resources, node_allocatable_resources and remaining_resources
class NodeResourceConfig:
    def __init__(self, node_label: str, node_selector: str, system_allocated_resources: ResourceConfig, node_allocatable_resources: ResourceConfig, remaining_resources: ResourceConfig):
        self.node_label = node_label
        self.node_selector = node_selector
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
