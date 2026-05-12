import json
import logging
import os
import glob
from unittest.mock import patch

from machine.data_classes import MachineConfig, MachineOperationResponse
from machine.result_handler import save_test_result


class _FakeMgr:
    """Minimal stand-in for MachineManager exposing only ``config``."""
    def __init__(self, config):
        self.config = config


def test_save_test_result_writes_nested_dict(tmp_path):
    cfg = MachineConfig(
        cloud="azure", cluster_name="cl", resource_group="rg",
        agentpool_name="ap", vm_size="Standard_D2_v3",
        timeout=600, result_dir=str(tmp_path),
        machine_name="m1",
    )

    @save_test_result
    def fake_op(self):  # pylint: disable=unused-argument
        return MachineOperationResponse(
            operation_name="scale_machine",
            succeeded=True,
            command_execution_time=12.5,
        )

    fake_op(_FakeMgr(cfg))
    files = glob.glob(str(tmp_path / "scale_machine-*.json"))
    assert len(files) == 1
    with open(files[0], encoding="utf-8") as fh:
        payload = json.loads(fh.read())
    # Nested, not flat-merged. Distinct keys preserved.
    assert "config" in payload and "response" in payload
    assert payload["config"]["cloud"] == "azure"
    assert payload["response"]["operation_name"] == "scale_machine"
    assert payload["response"]["succeeded"] is True
    # Filename includes operation, cloud, cluster, machine_name.
    assert "scale_machine-azure-cl-m1-" in os.path.basename(files[0])


def test_save_test_result_uses_agentpool_when_no_machine_name(tmp_path):
    cfg = MachineConfig(
        cloud="azure", cluster_name="cl", resource_group="rg",
        agentpool_name="apool", vm_size="x", timeout=1, result_dir=str(tmp_path),
    )

    @save_test_result
    def fake(self):  # pylint: disable=unused-argument
        return MachineOperationResponse(operation_name="create_machine", succeeded=True)

    fake(_FakeMgr(cfg))
    fs = glob.glob(str(tmp_path / "create_machine-*.json"))
    assert any("create_machine-azure-cl-apool-" in os.path.basename(f) for f in fs)


def test_save_test_result_swallows_write_errors(tmp_path, caplog):
    cfg = MachineConfig(
        cloud="azure", cluster_name="cl", resource_group="rg",
        agentpool_name="ap", vm_size="x", timeout=1, result_dir=str(tmp_path),
        machine_name="m1",
    )

    @save_test_result
    def fake(self):  # pylint: disable=unused-argument
        return MachineOperationResponse(operation_name="scale_machine", succeeded=True)

    with patch("machine.result_handler.save_info_to_file", side_effect=OSError("disk full")):
        with caplog.at_level(logging.WARNING, logger="machine.result_handler"):
            response = fake(_FakeMgr(cfg))

    assert response.operation_name == "scale_machine"
    assert any("Failed to save result" in rec.message for rec in caplog.records)
