from unittest.mock import MagicMock
import pytest
from machine.data_classes import MachineConfig, MachineOperationResponse
from machine.machine_manager import MachineManager


def _make_mgr(operation=None):
    cfg = MachineConfig(
        cloud="azure", cluster_name="c", resource_group="rg",
        agentpool_name="ap", vm_size="Standard_D2_v3",
        timeout=600, result_dir="/tmp/x",
        operation=operation, scale_machine_count=2,
        use_batch_api=False, machine_workers=2,
    )
    svc = MagicMock()
    svc.get_cluster_name.return_value = "c"
    svc.create_machine_agentpool.return_value = True
    svc.scale_machine.return_value = MachineOperationResponse(
        operation_name="scale_machine", succeeded=True)
    svc.get_cluster_data.return_value = {"k": "v"}
    return MachineManager(svc, cfg), svc


def test_perform_operation_default_runs_create_then_scale(tmp_path):
    mgr, svc = _make_mgr()
    mgr.config.result_dir = str(tmp_path)
    mgr.perform_operation()
    svc.create_machine_agentpool.assert_called_once()
    svc.scale_machine.assert_called_once()


def test_perform_operation_create_only(tmp_path):
    mgr, svc = _make_mgr(operation="create")
    mgr.config.result_dir = str(tmp_path)
    mgr.perform_operation()
    svc.create_machine_agentpool.assert_called_once()
    svc.scale_machine.assert_not_called()


def test_perform_operation_delete_raises(tmp_path):
    mgr, _ = _make_mgr(operation="delete")
    mgr.config.result_dir = str(tmp_path)
    with pytest.raises(NotImplementedError):
        mgr.perform_operation()


def test_no_input_mutation():
    """Manager must not mutate caller-provided MachineConfig.cluster_name."""
    cfg = MachineConfig(cloud="azure", cluster_name="orig", resource_group="rg",
                        agentpool_name="ap", vm_size="x", timeout=1, result_dir="/tmp")
    svc = MagicMock(); svc.get_cluster_name.return_value = "discovered"
    MachineManager(svc, cfg)
    assert cfg.cluster_name == "orig"  # unchanged
