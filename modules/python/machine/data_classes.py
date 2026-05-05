"""Data classes for the Machine API perf test.

Differences from ado-telescope's k8s/data_classes.py:
- OperationNames is an Enum (not @dataclass(frozen=True)).
- cloud_data typed as Optional[Dict] (truthful).
- Dropped dead types: BaseConfig, MachineRequestBase, CreateMachineRequest, DeleteMachineRequest.
- Dropped unused fields: api_response, time, feature_name.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class OperationNames(str, Enum):
    CREATE_MACHINE = "create_machine"
    SCALE_MACHINE = "scale_machine"


@dataclass
class MachineConfig:
    cloud: str
    cluster_name: str
    resource_group: str
    agentpool_name: str
    vm_size: str
    timeout: int
    result_dir: str
    region: Optional[str] = None
    operation: Optional[str] = None
    tags: Optional[Dict[str, str]] = None
    machine_name: Optional[str] = None
    scale_machine_count: int = 0
    use_batch_api: bool = False
    machine_workers: int = 1


@dataclass
class ScaleMachineRequest:
    cluster_name: str
    resource_group: str
    agentpool_name: str
    vm_size: str
    scale_machine_count: int
    use_batch_api: bool
    machine_workers: int
    timeout: int = 300
    tags: Optional[Dict[str, str]] = None
    machine_name: Optional[str] = None


@dataclass
class MachineOperationResponse:
    operation_name: str
    succeeded: bool = False
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    error: str = ""
    command_execution_time: float = 0
    node_readiness_time: float = 0
    successful_machines: List[str] = field(default_factory=list)
    percentile_node_readiness_times: Dict[str, float] = field(default_factory=dict)
    batch_command_execution_times: Dict[str, float] = field(default_factory=dict)
    cloud_data: Optional[Dict] = None
    warning_message: str = ""
