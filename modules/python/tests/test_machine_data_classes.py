from machine.data_classes import (
    MachineConfig, ScaleMachineRequest, MachineOperationResponse, OperationNames,
)

def test_operation_names_is_enum_with_required_values():
    assert OperationNames.CREATE_MACHINE.value == "create_machine"
    assert OperationNames.SCALE_MACHINE.value == "scale_machine"

def test_machine_config_defaults():
    cfg = MachineConfig(
        cloud="azure", cluster_name="c", resource_group="rg",
        agentpool_name="ap", vm_size="Standard_D2_v3",
        timeout=600, result_dir="/tmp/x",
    )
    assert cfg.scale_machine_count == 0
    assert cfg.use_batch_api is False
    assert cfg.machine_workers == 1
    assert cfg.region is None
    assert cfg.operation is None
    assert cfg.tags is None
    assert cfg.machine_name is None

def test_machine_operation_response_defaults_have_correct_types():
    r = MachineOperationResponse(operation_name="scale_machine")
    assert r.succeeded is False
    assert r.successful_machines == []
    assert r.percentile_node_readiness_times == {}
    assert r.batch_command_execution_times == {}
    assert r.command_execution_time == 0
    assert r.node_readiness_time == 0
    assert r.cloud_data is None  # dict | None, not str

def test_scale_machine_request_required_fields():
    req = ScaleMachineRequest(
        cluster_name="c", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=5,
        use_batch_api=False, machine_workers=2,
    )
    assert req.timeout == 300
    assert req.tags is None
    assert req.machine_name is None
