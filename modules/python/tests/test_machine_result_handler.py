import json
import os
import glob

from machine.data_classes import MachineConfig, MachineOperationResponse
from machine.result_handler import save_test_result


def test_save_test_result_writes_nested_dict(tmp_path):
    cfg = MachineConfig(
        cloud="azure", cluster_name="cl", resource_group="rg",
        agentpool_name="ap", vm_size="Standard_D2_v3",
        timeout=600, result_dir=str(tmp_path),
        machine_name="m1",
    )

    @save_test_result
    def fake_op(self):
        return MachineOperationResponse(
            operation_name="scale_machine",
            succeeded=True,
            command_execution_time=12.5,
        )

    class FakeMgr:
        def __init__(self, c):
            self.config = c

    mgr = FakeMgr(cfg)
    fake_op(mgr)
    files = glob.glob(str(tmp_path / "scale_machine-*.json"))
    assert len(files) == 1
    payload = json.loads(open(files[0]).read())
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
    def fake(self):
        return MachineOperationResponse(operation_name="create_machine", succeeded=True)

    class M:
        pass

    m = M()
    m.config = cfg
    fake(m)
    fs = glob.glob(str(tmp_path / "create_machine-*.json"))
    assert any("create_machine-azure-cl-apool-" in os.path.basename(f) for f in fs)
