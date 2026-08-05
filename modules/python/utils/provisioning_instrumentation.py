"""
Provisioning Instrumentation Module

Runs ARM operations and K8s node readiness checks concurrently,
capturing separate timing metrics for each. This enables regression
analysis by surfacing whether ARM or K8s is the provisioning bottleneck.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from azure.core.exceptions import HttpResponseError
from utils.logger_config import get_logger

logger = get_logger(__name__)


def instrument_nodepool_provisioning(
    node_pool_name,
    cluster_name,
    op,
    arm_callable,
    k8s_wait_callable,
    label="",
):
    """
    Run ARM operation and K8s node readiness check concurrently using threads.

    Args:
        node_pool_name: Name of the node pool being provisioned
        cluster_name: Name of the AKS cluster
        op: Operation context for recording timing metadata
        arm_callable: A zero-arg callable that performs the ARM operation and blocks
                      until complete (e.g. begin_create_or_update_with_retry)
        k8s_wait_callable: A zero-arg callable that waits for K8s nodes to be ready
                           and returns the list of ready nodes
        label: Optional label for log messages

    Returns:
        List of ready nodes

    Raises:
        Exception: If either the ARM operation or K8s readiness check fails.
    """
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=2) as executor:
        arm_future = executor.submit(
            lambda: (arm_callable(), time.time())
        )
        k8s_future = executor.submit(
            lambda: (k8s_wait_callable(), time.time())
        )

    arm_exc = arm_future.exception()
    k8s_exc = k8s_future.exception()

    if arm_exc or k8s_exc:
        elapsed = time.time() - start_time
        arm_status = f"FAILED: {arm_exc}" if arm_exc else "succeeded"
        k8s_status = f"FAILED: {k8s_exc}" if k8s_exc else "succeeded"
        logger.error(
            "Concurrent operation failed after %.2fs - ARM: %s, K8s readiness: %s",
            elapsed, arm_status, k8s_status
        )
        if arm_exc:
            raise arm_exc
        raise k8s_exc

    arm_result, arm_timestamp = arm_future.result()
    ready_nodes, ready_timestamp = k8s_future.result()

    node_readiness_time = ready_timestamp - start_time
    command_execution_time = arm_timestamp - start_time

    op.add_metadata("node_readiness_time", node_readiness_time)
    op.add_metadata("command_execution_time", command_execution_time)
    op.add_metadata("retry_occurred", bool(arm_result))
    logger.info(
        "[%s] %sARM completed in %.2fs, K8s nodes ready in %.2fs | Delta: %.2fs",
        node_pool_name, label, command_execution_time, node_readiness_time,
        abs(command_execution_time - node_readiness_time)
    )

    return ready_nodes


def begin_create_or_update_with_retry(
    aks_sdk_client,
    resource_group,
    cluster_name,
    node_pool_name,
    parameters,
    label="",
    retries=10,
    retry_wait=30,
    poll_interval=30,
    timeout=1800,
):
    """
    Call begin_create_or_update with retry on OperationNotAllowed/EtagMismatch,
    polling every poll_interval seconds and raising TimeoutError after timeout seconds.
    timeout defaults to 1800s (30 min) for slow GPU node provisioning (A100 MIG).

    Returns:
        bool: True if a retry occurred, False if the operation succeeded on the first attempt.
    """
    retry_occurred = False
    for attempt in range(retries):
        try:
            poller = aks_sdk_client.agent_pools.begin_create_or_update(
                resource_group_name=resource_group,
                resource_name=cluster_name,
                agent_pool_name=node_pool_name,
                parameters=parameters,
            )
            elapsed = 0
            while not poller.done():
                time.sleep(poll_interval)
                elapsed += poll_interval
                if elapsed >= timeout:
                    raise TimeoutError(
                        f"Node pool {node_pool_name} {label}timed out after {timeout}s"
                    )
                logger.info(
                    f"Waiting for node pool {node_pool_name} {label}to complete "
                    f"({elapsed}s elapsed)..."
                )
            poller.result()
            return retry_occurred
        except HttpResponseError as e:
            if any(code in str(e) for code in ("OperationNotAllowed", "EtagMismatch")) and attempt < retries - 1:
                retry_occurred = True
                error_code = e.error.code if e.error else str(e)
                logger.warning(
                    f"Cluster has an in-progress operation, retrying in {retry_wait}s "
                    f"(attempt {attempt + 1}/{retries}): {error_code}"
                )
                time.sleep(retry_wait)
            else:
                raise
