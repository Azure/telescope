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


def test_perform_operation_default_skips_scale_when_create_fails(tmp_path):
    mgr, svc = _make_mgr()
    mgr.config.result_dir = str(tmp_path)
    svc.create_machine_agentpool.side_effect = RuntimeError("boom")
    mgr.perform_operation()  # must not raise
    svc.create_machine_agentpool.assert_called_once()
    svc.scale_machine.assert_not_called()


def test_scale_builds_request_from_config(tmp_path):
    mgr, svc = _make_mgr(operation="scale")
    mgr.config.result_dir = str(tmp_path)
    mgr.perform_operation()
    req = svc.scale_machine.call_args.args[0]
    assert req.cluster_name == "c"  # discovered cluster_name used
    assert req.resource_group == "rg"
    assert req.agentpool_name == "ap"
    assert req.vm_size == "Standard_D2_v3"
    assert req.scale_machine_count == 2
    assert req.use_batch_api is False
    assert req.machine_workers == 2
    assert req.timeout == 600


def test_init_raises_when_cluster_name_unresolvable():
    cfg = MachineConfig(
        cloud="azure", cluster_name="placeholder", resource_group="rg",
        agentpool_name="ap", vm_size="x", timeout=1, result_dir="/tmp",
    )
    cfg.cluster_name = None  # MachineConfig types it as required str
    svc = MagicMock(); svc.get_cluster_name.return_value = None
    with pytest.raises(ValueError, match="cluster_name"):
        MachineManager(svc, cfg)
