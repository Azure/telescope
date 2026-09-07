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

IN_PROGRESS_CODES = ("OperationNotAllowed", "EtagMismatch")
MAX_RETRIES = 10               # in-progress (409) submit attempts
RETRY_WAIT_SECONDS = 30        # sleep between rejected submit attempts
POLL_INTERVAL_SECONDS = 30     # poller.done() polling cadence
TIMEOUT_SECONDS = 1800         # LRO poll timeout (slow A100 MIG provisioning)


def _record_excluded_time(op, command_start, start_time):
    """Exclude pre-accept queue-wait from the op duration; return the seconds excluded."""
    if command_start is None:
        return 0.0
    excluded = max(0, command_start - start_time)
    op.exclude_time(excluded)
    return excluded


def _log_provisioning_success(node_pool_name, label, command_time, readiness_time, queue_wait):
    logger.info(
        "[%s] %sARM %.2fs, K8s ready %.2fs | Delta %.2fs | queue-wait excluded %.2fs",
        node_pool_name, label, command_time, readiness_time,
        abs(command_time - readiness_time), queue_wait,
    )


def instrument_nodepool_provisioning(
    node_pool_name,
    op,
    arm_callable,
    k8s_wait_callable,
    label="",
):
    """
    Run ARM operation and K8s node readiness check concurrently using threads.

    Args:
        node_pool_name: Name of the node pool being provisioned
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
        if not arm_exc:
            (command_start, _), _ = arm_future.result()
        else:
            command_start = getattr(arm_exc, "request_started_at", None)
        _record_excluded_time(op, command_start, start_time)
        raise arm_exc or k8s_exc

    (command_start, retry_occurred), arm_timestamp = arm_future.result()
    ready_nodes, ready_timestamp = k8s_future.result()
    command_execution_time = max(0, arm_timestamp - command_start)
    node_readiness_time = max(0, ready_timestamp - command_start)

    queue_wait = _record_excluded_time(op, command_start, start_time)
    op.add_metadata("node_readiness_time", node_readiness_time)
    op.add_metadata("command_execution_time", command_execution_time)
    op.add_metadata("retry_occurred", retry_occurred)
    _log_provisioning_success(node_pool_name, label, command_execution_time, node_readiness_time, queue_wait)

    return ready_nodes


def begin_create_or_update_with_retry(
    aks_sdk_client,
    resource_group,
    cluster_name,
    node_pool_name,
    parameters,
    label="",
):
    """
    Call begin_create_or_update, retrying IN_PROGRESS_CODES (a *previous* op still
    in progress) up to MAX_RETRIES; poll until done, TimeoutError after
    TIMEOUT_SECONDS.

    Returns (request_started_at, retry_occurred): request_started_at is when the
    accepted (2xx) attempt's PUT was issued, so callers count the accepted
    request's frontend time and exclude the failed prior attempts as queue-wait.
    On failure it attaches request_started_at to the exception (see below) so the
    caller can still exclude the queue-wait.
    """
    retry_occurred = False
    for attempt in range(MAX_RETRIES):
        request_started_at = time.time()
        try:
            poller = aks_sdk_client.agent_pools.begin_create_or_update(
                resource_group_name=resource_group,
                resource_name=cluster_name,
                agent_pool_name=node_pool_name,
                parameters=parameters,
            )
        except HttpResponseError as e:
            in_progress = any(code in str(e) for code in IN_PROGRESS_CODES)
            if in_progress and attempt < MAX_RETRIES - 1:
                retry_occurred = True
                error_code = e.error.code if e.error else str(e)
                logger.warning(
                    f"Cluster has an in-progress operation, retrying in {RETRY_WAIT_SECONDS}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): {error_code}"
                )
                time.sleep(RETRY_WAIT_SECONDS)
                continue
            if in_progress:
                e.request_started_at = time.time()
            raise
        try:
            elapsed = 0
            while not poller.done():
                time.sleep(POLL_INTERVAL_SECONDS)
                elapsed += POLL_INTERVAL_SECONDS
                if elapsed >= TIMEOUT_SECONDS:
                    raise TimeoutError(
                        f"Node pool {node_pool_name} {label}timed out after {TIMEOUT_SECONDS}s"
                    )
                logger.info(
                    f"Waiting for node pool {node_pool_name} {label}to complete "
                    f"({elapsed}s elapsed)..."
                )
            poller.result()
        except Exception as e:
            e.request_started_at = request_started_at
            raise
        return request_started_at, retry_occurred
    raise RuntimeError(
        f"Node pool {node_pool_name} {label}exhausted {MAX_RETRIES} create/update retries"
    )
