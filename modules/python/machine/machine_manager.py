"""Orchestrate Machine API CRUD operations.

Differences from ado-telescope k8s/machine_manager.py:
- No mutation of caller's MachineConfig (we keep cluster_name in a local field).
- Single try/except (no triple-nested no-op).
- Default flow (operation unset) is documented as 'create then scale'.
- delete() raises NotImplementedError as before — argparse rejects 'delete' upstream.
"""
from datetime import datetime, timezone

from machine.data_classes import (
    MachineConfig, MachineOperationResponse, OperationNames, ScaleMachineRequest,
)
from machine.result_handler import save_test_result
from utils.logger_config import get_logger

logger = get_logger(__name__)


class MachineManager:
    def __init__(self, cloud_service, config: MachineConfig):
        self.cloud_service = cloud_service
        self.config = config  # do NOT mutate
        self._cluster_name = cloud_service.get_cluster_name() or config.cluster_name
        if not self._cluster_name:
            raise ValueError(
                "cluster_name could not be resolved from cloud_service.get_cluster_name() "
                "or config.cluster_name"
            )

    def perform_operation(self) -> None:
        op = (self.config.operation or "").lower()
        if not op:
            resp = self.create()
            if not resp.succeeded:
                logger.error("create failed; skipping scale: %s", resp.error)
                return
            self.scale()
        elif op == "create":
            self.create()
        elif op == "scale":
            self.scale()
        elif op == "delete":
            raise NotImplementedError("delete_machine is not implemented (v1)")
        else:
            raise ValueError(f"unknown operation: {op}")

    @save_test_result
    def create(self) -> MachineOperationResponse:
        start = datetime.now(timezone.utc)
        resp = MachineOperationResponse(
            operation_name=OperationNames.CREATE_MACHINE.value,
            start_time=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        try:
            ok = self.cloud_service.create_machine_agentpool(
                self.config.agentpool_name, self._cluster_name,
                self.config.resource_group, timeout=self.config.timeout)
            resp.succeeded = bool(ok)
        except Exception as e:  # pylint: disable=broad-except
            logger.exception("create failed")
            resp.error = str(e)
        finally:
            end = datetime.now(timezone.utc)
            resp.end_time = end.strftime("%Y-%m-%dT%H:%M:%SZ")
            resp.command_execution_time = (end - start).total_seconds()
        return resp

    @save_test_result
    def scale(self) -> MachineOperationResponse:
        req = ScaleMachineRequest(
            cluster_name=self._cluster_name,
            resource_group=self.config.resource_group,
            agentpool_name=self.config.agentpool_name,
            vm_size=self.config.vm_size,
            scale_machine_count=self.config.scale_machine_count,
            use_batch_api=self.config.use_batch_api,
            machine_workers=self.config.machine_workers,
            timeout=self.config.timeout,
            tags=self.config.tags,
            machine_name=self.config.machine_name,
        )
        return self.cloud_service.scale_machine(req)
