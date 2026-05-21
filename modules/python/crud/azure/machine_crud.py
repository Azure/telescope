"""
Azure AKS Machine CRUD Operations Module.

This module provides a thin orchestration layer over ``AKSMachineClient`` for the
AKS Machine API. It mirrors ``crud/azure/node_pool_crud.py``: each public method
delegates to the underlying client (which already opens an ``OperationContext``
and writes the per-operation result file), wraps the call in try/except, and
returns a boolean so the CLI dispatcher can translate to a process exit code.

All telemetry (start/end timestamps, duration, success flag, error traceback,
metadata enrichment) is recorded by ``AKSMachineClient`` itself; this layer
deliberately adds no result-handling logic of its own.
"""

import logging

from clients.aks_machine_client import AKSMachineClient
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)
get_logger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
get_logger("azure.identity").setLevel(logging.ERROR)
get_logger("azure.core.pipeline").setLevel(logging.ERROR)
get_logger("msal").setLevel(logging.ERROR)


class MachineCRUD:
    """Thin CRUD wrapper around :class:`AKSMachineClient` for the Machine API.

    Mirrors :class:`crud.azure.node_pool_crud.NodePoolCRUD`: public methods are
    a try/except over the equivalent client method. The client already records
    the operation via ``OperationContext`` so no extra bookkeeping happens here.
    """

    def __init__(self, resource_group, kube_config_file=None, result_dir=None,
                 step_timeout=600):
        self.aks_client = AKSMachineClient(
            resource_group=resource_group,
            kube_config_file=kube_config_file,
            result_dir=result_dir,
            operation_timeout_minutes=max(1, step_timeout // 60),
        )
        self.cluster_name = self.aks_client.get_cluster_name()
        self.result_dir = result_dir
        self.step_timeout = step_timeout

    def create_machine_agentpool(self, agentpool_name, vm_size):
        """Create a machine-mode agent pool. Returns True on success, False on failure."""
        try:
            return self.aks_client.create_machine_agentpool(
                agentpool_name=agentpool_name,
                vm_size=vm_size,
                cluster_name=self.cluster_name,
                timeout=self.step_timeout,
            )
        except Exception as e:
            logger.error(f"create_machine_agentpool failed for {agentpool_name}: {e}")
            return False

    def scale_machine(self, agentpool_name, vm_size, scale_machine_count,
                      use_batch_api=False, machine_workers=1,
                      readiness_wait_timeout=1200, tags=None):
        """Scale a machine-mode agent pool by ``scale_machine_count`` machines.

        Returns True on success, False on failure. All timing and percentile
        metadata are written by ``AKSMachineClient.scale_machine`` via
        ``OperationContext``.
        """
        try:
            return self.aks_client.scale_machine(
                agentpool_name=agentpool_name,
                vm_size=vm_size,
                scale_machine_count=scale_machine_count,
                cluster_name=self.cluster_name,
                use_batch_api=use_batch_api,
                machine_workers=machine_workers,
                timeout=self.step_timeout,
                readiness_wait_timeout=readiness_wait_timeout,
                tags=tags,
            )
        except Exception as e:
            logger.error(f"scale_machine failed for {agentpool_name}: {e}")
            return False
