"""AKS Machine API client.

Subclasses ``AKSClient`` to inherit auth, ContainerServiceClient,
KubernetesClient, ``get_cluster_name``, ``get_cluster_data``, and the existing
node-pool CRUD methods. Adds raw REST methods for the Machine API which is not
yet exposed in the Azure SDK.

Public methods (``create_machine_agentpool``, ``scale_machine``) wrap their work
in ``OperationContext``: the context is opened inside the client method,
metadata is enriched with ``op.add_metadata`` along the way, success returns
None, failures are logged and re-raised so ``OperationContext`` records them.
``MachineCRUD`` therefore stays a thin try/except wrapper.

The non-batch scale path PUTs machines one at a time. The batch dispatch
(``use_batch_api=True``) uses the private ``BatchPutMachine`` header contract.
"""
import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

import requests
from requests.adapters import HTTPAdapter

from clients.aks_client import AKSClient
from utils.logger_config import get_logger, setup_logging

# Configure logging.
setup_logging()
logger = get_logger(__name__)
# Suppress noisy Azure SDK logs.
get_logger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
get_logger("azure.identity").setLevel(logging.ERROR)
get_logger("azure.core.pipeline").setLevel(logging.ERROR)
get_logger("msal").setLevel(logging.ERROR)

_ARM_BASE = "https://management.azure.com"
_ARM_SCOPE = "https://management.azure.com/.default"
_AGENTPOOL_API_VERSION = "2024-06-02-preview"
_MACHINE_API_VERSION = "2025-06-02-preview"
_POLL_INTERVAL_SECONDS = 10
# Per-request HTTP timeout is capped so that a single slow PUT/GET cannot
# consume the caller's whole ``timeout`` budget before the polling loop starts.
# The remaining budget is reserved for ``_wait_for_agentpool_provisioning``.
_PER_REQUEST_TIMEOUT_CAP = 60
# Bounded 429 retry budget for ``_scale_machine_batch``. Total number of
# attempts (NOT additional retries on top of an initial call). The AKS RP
# throttles BatchPutMachine independently of normal PUTs; small bursts at
# the start of a scale-out are common, so a short exponential backoff
# (1s, 2s, 4s, 8s between the five attempts) usually clears them without
# ballooning the chunk's wall-time.
_BATCH_429_MAX_RETRIES = 5
_BATCH_429_INITIAL_BACKOFF_SECONDS = 1.0
_BATCH_MAX_MACHINES_PER_REQUEST = 50
_MACHINE_TERMINAL_STATES = {"Succeeded", "Failed", "Canceled"}
_MACHINE_FAILURE_STATES = {"Failed", "Canceled"}
_MACHINE_FAILURE_DETAIL_LIMIT = 10
# ARM ListMachines returns up to 50 Machines per page. Following up to 50 pages
# covers 2,500 Machines before failing the list operation.
_LIST_MACHINES_MAX_PAGES = 50
_MACHINE_FAILURE_CHECK_INTERVAL_SECONDS = 30
_NODE_READINESS_POLL_INTERVAL_SECONDS = 2
# urllib3's default ``HTTPAdapter`` (mounted implicitly by ``requests.Session``)
# caps each host's connection pool at ``pool_maxsize=10``. The parallel scale
# paths fan out far beyond that (up to ``machine_workers`` concurrent PUTs
# against ``management.azure.com``), which triggers
# ``WARNING - Connection pool is full, discarding connection`` and forces
# urllib3 to tear down and re-establish TLS for every excess request.
# We mount an explicitly-sized adapter so the pool can retain one warm
# connection per worker thread; 64 covers the current pipeline maxima
# (50 individual workers, 10 batch workers) with comfortable headroom and
# stays well below ARM's per-client connection ceilings.
_HTTPS_POOL_SIZE = 64


class MachineProvisioningFailed(RuntimeError):
    """Terminal Machine failure with readiness metadata captured before failure."""
    def __init__(
        self,
        agent_pool_name: str,
        failed_machines: List[Dict[str, Any]],
        readiness_envelope: Dict[str, Dict[str, Any]],
    ):
        super().__init__(
            f"machine provisioning failed in agentpool {agent_pool_name}: "
            f"failed_machines={failed_machines}"
        )
        self.failed_machines = failed_machines
        self.readiness_envelope = readiness_envelope


class AKSMachineClient(AKSClient):
    """Extends ``AKSClient`` with Machine-API REST plumbing.

    Inherits ``credential``, ``subscription_id``, ``resource_group``,
    ``k8s_client``, ``get_cluster_name``, ``get_cluster_data``, and the
    existing ``create_node_pool`` / ``scale_node_pool`` / ``delete_node_pool``
    methods. Tests that require a baseline node pool can therefore call the
    inherited methods directly without a separate client.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.k8s_client is None:
            raise RuntimeError("k8s_client is required by AKSMachineClient")
        self._token_cache_value: Optional[str] = None
        self._token_cache_expiry: float = 0.0  # unix epoch seconds
        self._token_lock = threading.Lock()
        # Pool TCP/TLS across calls. ``requests.Session`` is thread-safe for
        # sending requests (each request creates its own urllib3 connection
        # from the shared pool), so this is safe for the parallel scale path.
        # Explicitly mount a sized adapter so the per-host pool can hold one
        # warm connection per worker thread; otherwise the default
        # ``pool_maxsize=10`` causes ``WARNING - Connection pool is full,
        # discarding connection`` once worker fan-out exceeds 10.
        self._session = requests.Session()
        _https_adapter = HTTPAdapter(
            pool_connections=_HTTPS_POOL_SIZE,
            pool_maxsize=_HTTPS_POOL_SIZE,
            pool_block=False,
        )
        self._session.mount("https://", _https_adapter)
        self._session.mount("http://", _https_adapter)

    # ---- auth + REST plumbing ----
    def _get_access_token(self) -> str:
        """Cached token fetch. Re-uses token across worker threads with a 60s safety margin
        before expiry. Avoids forking `az account get-access-token` per worker."""
        with self._token_lock:
            if self._token_cache_value and time.time() < self._token_cache_expiry - 60:
                return self._token_cache_value
            tok = self.credential.get_token(_ARM_SCOPE)
            self._token_cache_value = tok.token
            self._token_cache_expiry = float(tok.expires_on)
            return self._token_cache_value

    def make_request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> requests.Response:
        """Send an authenticated ARM REST request and return the raw Response.

        Callers are responsible for checking ``response.status_code`` (or
        calling ``raise_for_status()``) -- this method does NOT raise on HTTP
        errors. Long-running Machine API operations return 200/202 with a
        Location header that callers must follow.

        Uses ``self._session`` for connection pooling so TCP/TLS handshakes
        are reused across polls and parallel scale-path workers.
        """
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
        }
        return self._session.request(
            method, url, headers=headers, json=data, timeout=timeout
        )

    # ---- Machine API: agent pool provisioning ----
    def create_machine_agentpool(
        self,
        agent_pool_name: str,
        vm_size: str,
        cluster_name: Optional[str] = None,
        timeout: int = 300,
    ) -> None:
        """Convert an existing agentpool to Machines mode via PUT.

        Opens an ``OperationContext`` here, enriches metadata, returns on
        success, re-raises on failure (so the context records ``success=False``
        with traceback before the exception propagates to ``MachineCRUD``).

        Args:
            agent_pool_name: Target agentpool name.
            vm_size: VM SKU recorded in operation metadata. The PUT body itself
                only sets ``mode: Machines``; the SKU is informational here so
                downstream Kusto rows can attribute the agentpool to a SKU.
            cluster_name: Parent AKS cluster name. Defaults to
                ``self.get_cluster_name()`` (matches ``create_node_pool``).
            timeout: Total wall-clock budget (seconds) for this operation.
                Used as the polling deadline for ``_wait_for_agentpool_provisioning``.
                The per-request HTTP timeout is capped at
                ``_PER_REQUEST_TIMEOUT_CAP`` so a single slow PUT cannot consume
                the whole budget before polling starts.

        Raises:
            RuntimeError: PUT non-2xx, ARM-reported Failed state, or timeout.
        """
        cluster_name = cluster_name or self.get_cluster_name()
        metadata = {
            "cluster_name": cluster_name,
            "agent_pool_name": agent_pool_name,
            "vm_size": vm_size,
        }
        with self._get_operation_context()(
            "create_machine_agentpool", "azure", metadata, result_dir=self.result_dir
        ) as op:
            try:
                sub = self.subscription_id
                url = (
                    f"{_ARM_BASE}/subscriptions/{sub}/resourceGroups/{self.resource_group}"
                    f"/providers/Microsoft.ContainerService/managedClusters/{cluster_name}"
                    f"/agentPools/{agent_pool_name}?api-version={_AGENTPOOL_API_VERSION}"
                )
                body = {"properties": {"mode": "Machines"}}
                # Cap the PUT timeout so the bulk of ``timeout`` is preserved
                # for the polling loop below.
                put_timeout = min(timeout, _PER_REQUEST_TIMEOUT_CAP)
                resp = self.make_request("PUT", url, data=body, timeout=put_timeout)
                # ARM async PUT acceptance returns 200/201/202; the agentpool
                # provisioning poll below is the real completion gate.
                if resp.status_code not in (200, 201, 202):
                    raise RuntimeError(
                        f"create_machine_agentpool PUT failed: "
                        f"{resp.status_code} {resp.text[:500]}"
                    )
                if not self._wait_for_agentpool_provisioning(url, timeout):
                    raise RuntimeError(
                        f"agentpool {agent_pool_name} did not reach Succeeded within {timeout}s"
                    )
                op.add_metadata("agentpool_info", self.get_node_pool(
                    agent_pool_name, cluster_name).as_dict())
                op.add_metadata("cluster_info", self.get_cluster_data(cluster_name))
            except Exception as e:
                logger.error(f"Failed to create machine agentpool {agent_pool_name}: {e}")
                raise

    def _wait_for_agentpool_provisioning(self, url: str, timeout: int) -> bool:
        """Poll the agentpool URL until provisioningState is terminal.

        Polls every ``_POLL_INTERVAL_SECONDS`` (10s) using a 30s per-request HTTP
        timeout. Returns True on 'Succeeded'. Returns False on 'Failed' or when
        ``timeout`` seconds have elapsed since invocation. 4xx GETs are raised
        immediately (e.g. 404 'agentpool not found', 401/403) since retrying
        won't change the outcome; 5xx and other transient failures are logged
        and retried until the deadline. By AKS contract a 200 GET on the
        agentpool always includes ``properties.provisioningState``; if it is
        absent on a 200 response, that is a Failed signal and we stop
        immediately rather than waiting out the timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.make_request("GET", url, timeout=30)
            if r.status_code != 200:
                if 400 <= r.status_code < 500:
                    raise RuntimeError(
                        f"agentpool GET {url} -> {r.status_code} {r.text[:500]}"
                    )
                logger.warning(f"agentpool GET {url} -> {r.status_code}")
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            try:
                body = r.json()
            except (ValueError, TypeError) as exc:
                logger.warning(f"agentpool poll JSON parse failed: {exc}")
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            state = body.get("properties", {}).get("provisioningState")
            if state == "Succeeded":
                return True
            if state == "Failed":
                logger.error(f"agentpool provisioning failed: {body}")
                return False
            if state is None:
                logger.error(
                    f"agentpool 200 GET returned without provisioningState; "
                    f"treating as Failed. body={body}"
                )
                return False
            time.sleep(_POLL_INTERVAL_SECONDS)
        logger.error(f"agentpool provisioning timed out after {timeout}s")
        return False

    def _wait_for_machine_node_readiness(
        self,
        agent_pool_name: str,
        expected_count: int,
        timeout: int,
        baseline_count: int = 0,
        cluster_name: Optional[str] = None,
        expected_machine_names: Optional[Set[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Wait for ``expected_count`` NEW Ready nodes; return nested percentile dict.

        AKS Machine ARM resource names (e.g. ``scale100-machine-1``) are NOT the
        same as underlying k8s Node names, so readiness is measured from Nodes
        labelled ``agentpool=<pool>``. Percentile targets are computed against
        ``baseline_count + expected_count`` and clamped above ``baseline_count``
        so pre-existing Ready nodes never satisfy a new-node threshold.

        ``cluster_name`` and ``expected_machine_names`` enable the periodic
        ListMachines terminal-failure check. If either is omitted, the helper
        preserves the node-readiness-only behavior and skips ARM failure polling.

        ``timeout`` is wall-clock seconds from invocation. Returns the nested
        empty-state envelope (``elapsed_time_seconds=None``, ``success=False``)
        if ``expected_count`` <= 0 or no percentile target is met within
        ``timeout``. Raises only after every expected Machine is terminal and at
        least one failed.
        """
        empty_envelope: Dict[str, Dict[str, Any]] = {
            f"P{p}": {
                "target_nodes": 0,
                "elapsed_time_seconds": None,
                "percentage": p,
                "success": False,
            }
            for p in (50, 70, 90, 99, 100)
        }
        if expected_count <= 0:
            return empty_envelope
        label_selector = f"agentpool={agent_pool_name}"
        target_total = baseline_count + expected_count
        # Each percentile target must be STRICTLY GREATER than baseline_count so
        # we count only NEW nodes -- pre-existing labeled Ready nodes alone must
        # never satisfy any threshold. Use math.ceil so e.g. P50 of 3 -> 2 (not 1)
        # and P100 always equals target_total (ceil(1.0 * N) == N).
        targets = {
            p: max(baseline_count + 1, math.ceil((p / 100.0) * target_total))
            for p in (50, 70, 90, 99, 100)
        }
        readiness_times: Dict[int, float] = {}
        start = time.time()
        deadline = start + timeout
        next_machine_failure_check_at: Optional[float] = (
            start if cluster_name and expected_machine_names else None
        )
        logger.info(
            f"Waiting for nodes in agentpool {agent_pool_name} (label {label_selector}) - "
            f"targets {targets}, baseline={baseline_count}, expected={expected_count}, "
            f"timeout {timeout}s"
        )
        while time.time() < deadline and len(readiness_times) < len(targets):
            should_check_machines = (
                next_machine_failure_check_at is not None
                and time.time() >= next_machine_failure_check_at
            )
            failed_machines_result: List[Dict[str, Any]] = []
            if should_check_machines and cluster_name and expected_machine_names:
                with ThreadPoolExecutor(max_workers=2) as ex:
                    ready_nodes = ex.submit(self._get_ready_node_count, label_selector)
                    failed_machines = ex.submit(
                        self._get_terminal_machine_provisioning_failures,
                        cluster_name=cluster_name,
                        agent_pool_name=agent_pool_name,
                        expected_names=expected_machine_names,
                    )
                    ready = ready_nodes.result()
                try:
                    failed_machines_result = failed_machines.result()
                except Exception as e:
                    logger.warning(
                        "get_machine_provisioning_failures failed; "
                        f"retrying on next cadence: {e}"
                    )
                next_machine_failure_check_at = (
                    time.time() + _MACHINE_FAILURE_CHECK_INTERVAL_SECONDS
                )
            else:
                ready = self._get_ready_node_count(label_selector)
            # Once all expected Machines are terminal, no more requested nodes
            # can join. Preserve lower-percentile timings before failing.
            if failed_machines_result:
                raise MachineProvisioningFailed(
                    agent_pool_name=agent_pool_name,
                    failed_machines=failed_machines_result,
                    readiness_envelope=self._build_readiness_envelope(targets, readiness_times),
                )
            now_elapsed = time.time() - start
            for p, target in targets.items():
                if p not in readiness_times and ready >= target:
                    readiness_times[p] = now_elapsed
                    logger.info(
                        f"P{p} hit: {ready}/{target_total} ready "
                        f"(target={target}, baseline={baseline_count}) at {now_elapsed:.2f}s"
                    )
            if len(readiness_times) < len(targets):
                now = time.time()
                # Wake for the next node poll, next ListMachines check, or
                # overall timeout, whichever comes first.
                next_wake_at = min(
                    now + _NODE_READINESS_POLL_INTERVAL_SECONDS,
                    deadline,
                )
                if next_machine_failure_check_at is not None:
                    next_wake_at = min(next_wake_at, next_machine_failure_check_at)
                sleep_seconds = max(0.0, next_wake_at - now)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
        result = self._build_readiness_envelope(targets, readiness_times)
        if not readiness_times:
            logger.warning(
                f"No percentile target met within {timeout}s for agentpool {agent_pool_name}"
            )
            return result
        # Log percentile summary including P100, which is the wall-clock
        # elapsed until ALL target nodes are Ready.
        logger.info(f"Node Readiness Percentile Summary for agentpool {agent_pool_name}:")
        for p in (50, 70, 90, 99, 100):
            if p in readiness_times:
                logger.info(
                    f"  P{p} (target={targets[p]} nodes): "
                    f"{readiness_times[p]:.2f} seconds"
                )
            else:
                logger.info(f"  P{p} (target={targets[p]} nodes): TIMEOUT")
        max_elapsed = max(readiness_times.values())
        if len(readiness_times) == len(targets):
            logger.info(
                f"All target nodes became ready in {max_elapsed:.2f} seconds "
                f"in agent pool {agent_pool_name}"
            )
        else:
            missed = [f"P{p}" for p in (50, 70, 90, 99, 100) if p not in readiness_times]
            logger.warning(
                f"Partial readiness in agent pool {agent_pool_name}: "
                f"{len(readiness_times)}/{len(targets)} percentiles met within "
                f"{timeout}s; missed {missed}; last successful percentile at "
                f"{max_elapsed:.2f}s"
            )
        logger.info(f"Percentile node readiness data: {json.dumps(result, indent=2)}")
        return result

    @staticmethod
    def _build_readiness_envelope(
        targets: Dict[int, int],
        readiness_times: Dict[int, float],
    ) -> Dict[str, Dict[str, Any]]:
        """Build the upload-safe readiness metadata envelope."""
        return {
            f"P{p}": {
                "target_nodes": targets[p],
                "elapsed_time_seconds": readiness_times.get(p),
                "percentage": p,
                "success": p in readiness_times,
            }
            for p in (50, 70, 90, 99, 100)
        }

    def _get_ready_node_count(self, label_selector: str) -> int:
        """Return Ready node count for the pool, treating transient list failures as 0."""
        try:
            ready_nodes = self.k8s_client.get_ready_nodes(label_selector=label_selector)
        except Exception as e:
            logger.warning(f"get_ready_nodes({label_selector}) failed; treating as 0 ready: {e}")
            return 0
        return len(ready_nodes)

    # ---- Machine API: scale path ----
    def scale_machine(
        self,
        agent_pool_name: str,
        vm_size: str,
        scale_machine_count: int,
        cluster_name: Optional[str] = None,
        use_batch_api: bool = False,
        machine_workers: int = 1,
        timeout: int = 600,
        readiness_wait_timeout: int = 1200,
        tags: Optional[Dict[str, str]] = None,  # pylint: disable=unused-argument
    ) -> None:
        """Scale a Machine-mode agentpool by creating ``scale_machine_count`` machines.

        Opens an ``OperationContext`` here, enriches with successful machine
        names, per-batch command execution times, per-percentile readiness
        envelope, and the cluster snapshot.
        Returns on success; re-raises on failure so the context records the
        trace.

        Flow:
          1. Snapshot the current Ready+labeled node count in the agentpool
             (``baseline_count``) so the readiness watcher counts only NEW nodes.
          2. Submit machine PUTs -- individually by default, or sharded into
             ``machine_workers`` chunks where each chunk is sent as a single
             ``BatchPutMachine``-headered PUT when ``use_batch_api=True`` (per-
             machine ARM polling is intentionally NOT performed in either path).
          3. Wait ONCE on the agentpool-level provisioningState.
          4. Wait for nodes labeled ``agentpool=<pool>`` to surpass
             ``baseline_count`` by enough to satisfy P50/P70/P90/P99/P100 targets.

        ``tags`` is currently unused (Machine API rejects top-level tags on the
        machine PUT body; machines inherit tags from the parent agentpool).

        See ``_create_batch_machines`` for the batch chunking contract and the
        ``BatchPutMachine`` header schema.

        Raises:
            RuntimeError: fewer machines landed than requested, agentpool did
                not reach Succeeded within ``timeout``, or P100 readiness did
                not complete within ``readiness_wait_timeout``.
        """
        cluster_name = cluster_name or self.get_cluster_name()
        metadata = {
            "cluster_name": cluster_name,
            "agent_pool_name": agent_pool_name,
            "vm_size": vm_size,
            "scale_machine_count": scale_machine_count,
            "use_batch_api": use_batch_api,
            "machine_workers": machine_workers,
        }
        # Bundle into a SimpleNamespace so the helpers retain the
        # ``request.foo`` shape without exposing yet another module-level data class.
        request = SimpleNamespace(
            agent_pool_name=agent_pool_name,
            cluster_name=cluster_name,
            resource_group=self.resource_group,
            vm_size=vm_size,
            scale_machine_count=scale_machine_count,
            use_batch_api=use_batch_api,
            machine_workers=machine_workers,
            timeout=timeout,
            readiness_wait_timeout=readiness_wait_timeout,
            batch_command_execution_times={},
            batch_command_execution_times_lock=threading.Lock(),
        )
        with self._get_operation_context()(
            "scale_machine", "azure", metadata, result_dir=self.result_dir
        ) as op:
            try:
                # Snapshot baseline BEFORE any PUTs so the readiness watcher
                # counts only NEW nodes.
                baseline_count = 0
                try:
                    baseline_count = len(
                        self.k8s_client.get_ready_nodes(
                            label_selector=f"agentpool={agent_pool_name}"
                        )
                    )
                    logger.info(
                        f"baseline ready nodes in agentpool {agent_pool_name}: {baseline_count}"
                    )
                except Exception:
                    logger.warning(
                        "baseline node snapshot failed; readiness count may be inflated"
                    )

                prefix = self._get_machine_name_prefix(scale_machine_count)
                names = [
                    f"{prefix}-machine-{i + 1}" for i in range(scale_machine_count)
                ]
                command_t0 = time.time()
                if use_batch_api:
                    successful = self._scale_machine_batch(request, names)
                else:
                    successful = self._scale_machine_individually(request, names)
                op.add_metadata("command_execution_time", time.time() - command_t0)
                if use_batch_api:
                    op.add_metadata(
                        "batch_command_execution_times",
                        dict(request.batch_command_execution_times),
                    )
                op.add_metadata("successful_machines", len(successful))

                # Fail fast on partial landing BEFORE waiting on the agentpool
                # or readiness against a reduced count -- otherwise the recorded
                # percentile envelope and node_readiness_time describe a smaller
                # target than the caller actually requested.
                if len(successful) != scale_machine_count:
                    raise RuntimeError(
                        f"scale_machine landed {len(successful)}/{scale_machine_count} machines"
                    )

                # Single agentpool-level provisioning check.
                agentpool_url = (
                    f"{_ARM_BASE}/subscriptions/{self.subscription_id}/resourceGroups/"
                    f"{self.resource_group}/providers/Microsoft.ContainerService/"
                    f"managedClusters/{cluster_name}/agentPools/"
                    f"{agent_pool_name}?api-version={_AGENTPOOL_API_VERSION}"
                )
                agentpool_ok = self._wait_for_agentpool_provisioning(
                    agentpool_url, timeout
                )
                logger.info(
                    f"agentpool {agent_pool_name} provisioning "
                    f"{'Succeeded' if agentpool_ok else 'Failed/Timeout'}"
                )

                readiness_failure = None
                try:
                    percentile_envelope = self._wait_for_machine_node_readiness(
                        agent_pool_name=agent_pool_name,
                        expected_count=len(successful),
                        timeout=readiness_wait_timeout,
                        baseline_count=baseline_count,
                        cluster_name=cluster_name,
                        expected_machine_names=set(names),
                    )
                except MachineProvisioningFailed as exc:
                    readiness_failure = exc
                    percentile_envelope = exc.readiness_envelope
                    op.add_metadata("failed_machines", exc.failed_machines)
                op.add_metadata("percentile_node_readiness_times", percentile_envelope)
                p100 = percentile_envelope.get("P100", {})
                op.add_metadata(
                    "node_readiness_time", p100.get("elapsed_time_seconds") or 0.0
                )
                op.add_metadata("cluster_info", self.get_cluster_data(cluster_name))
                if readiness_failure:
                    raise readiness_failure

                if not agentpool_ok:
                    raise RuntimeError(
                        f"agentpool {agent_pool_name} did not reach Succeeded within {timeout}s"
                    )
                # P100 is the strictest readiness envelope (all target nodes
                # Ready); if it succeeded, every lower percentile did too.
                if not p100.get("success", False):
                    raise RuntimeError(
                        f"node readiness P100 did not complete within "
                        f"{readiness_wait_timeout}s for agentpool {agent_pool_name}"
                    )
            except Exception as e:
                logger.error(f"Failed to scale machine agentpool {agent_pool_name}: {e}")
                raise

    @staticmethod
    def _get_machine_name_prefix(scale_machine_count: int) -> str:
        """Generate the machine-name prefix for a given scale count.

        The prefix is part of the machine ARM resource name; cross-repo Kusto
        dashboards key on machine name, so this scheme is kept stable.

        - ``scale1000`` -> ``scale1k`` (any multiple of 1000 >= 1000 collapses)
        - ``scale500``  -> ``scale500``
        - ``scale1``    -> ``scale1``
        """
        if scale_machine_count >= 1000 and scale_machine_count % 1000 == 0:
            return f"scale{scale_machine_count // 1000}k"
        return f"scale{scale_machine_count}"

    def _scale_machine_individually(
        self, request: SimpleNamespace, names: List[str],
    ) -> List[str]:
        """Submit per-machine PUTs concurrently via ThreadPoolExecutor.

        Each worker calls ``_create_single_machine(name, request)`` which PUTs
        the machine and returns True on any 2xx response. Per-machine
        provisioningState is intentionally NOT polled (see
        ``_create_single_machine`` for why); the agentpool-level poll in
        ``scale_machine`` is the real completion signal. Returns the list of
        names that reported True. Per-machine exceptions are logged and
        treated as failure (name omitted from result).
        """
        successful: List[str] = []
        # Clamp workers to >=1 so a misconfigured request (0 or negative) cannot
        # crash ThreadPoolExecutor with ValueError.
        with ThreadPoolExecutor(max_workers=max(1, request.machine_workers)) as ex:
            futures = {ex.submit(self._create_single_machine, n, request): n for n in names}
            for fut in as_completed(futures):
                n = futures[fut]
                try:
                    if fut.result():
                        successful.append(n)
                except Exception:
                    logger.exception(f"create_single_machine failed for {n}")
        return successful

    def _create_single_machine(self, name: str, request: SimpleNamespace) -> bool:
        """PUT a single Machine resource. Returns True on any 2xx response.

        Body is ``{"properties": {"hardware": {"vmSize": ...}}}``. Tags are inherited
        from the parent agentpool; the machine PUT body in api-version 2025-06-02-preview
        does not accept a top-level ``tags`` field (rejected with UnmarshalError).

        Intentionally does NOT poll the per-machine ARM provisioningState. The
        AKS RP reports per-machine ``provisioningState='Succeeded'`` essentially
        as soon as the agentpool admits the request -- well before the underlying
        VM is created. Polling here therefore returns spuriously early and only
        adds N round-trips of latency without surfacing useful signal. The
        canonical completion signal is the agentpool-level provisioningState,
        which ``scale_machine`` polls once after all PUTs return.

        Never raises on HTTP errors; logs and returns False on non-2xx responses.
        """
        sub = self.subscription_id
        url = (
            f"{_ARM_BASE}/subscriptions/{sub}/resourceGroups/{request.resource_group}"
            f"/providers/Microsoft.ContainerService/managedClusters/{request.cluster_name}"
            f"/agentPools/{request.agent_pool_name}/machines/{name}"
            f"?api-version={_MACHINE_API_VERSION}"
        )
        body: Dict[str, Any] = {"properties": {"hardware": {"vmSize": request.vm_size}}}
        resp = self.make_request("PUT", url, data=body, timeout=request.timeout)
        if resp.status_code not in (200, 201, 202):
            logger.error(f"PUT machine {name} -> {resp.status_code} {resp.text[:500]}")
            return False
        return True

    def _list_machines(
        self,
        cluster_name: str,
        agent_pool_name: str,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """List Machine resources for an agentpool, following ARM pagination."""
        url = (
            f"{_ARM_BASE}/subscriptions/{self.subscription_id}/resourceGroups/"
            f"{self.resource_group}/providers/Microsoft.ContainerService/"
            f"managedClusters/{cluster_name}/agentPools/{agent_pool_name}/machines"
            f"?api-version={_MACHINE_API_VERSION}"
        )
        machines: List[Dict[str, Any]] = []
        for _ in range(_LIST_MACHINES_MAX_PAGES):
            resp = self.make_request("GET", url, timeout=timeout)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"ListMachines failed for agentpool {agent_pool_name}: "
                    f"{resp.status_code} {resp.text[:500]}"
                )
            try:
                body = resp.json()
            except (ValueError, TypeError) as exc:
                raise RuntimeError(
                    f"ListMachines returned invalid JSON for agentpool "
                    f"{agent_pool_name}: {exc}"
                ) from exc
            machines.extend(body.get("value", []))
            next_link = body.get("nextLink")
            if not next_link:
                return machines
            url = next_link
        raise RuntimeError(
            f"ListMachines exceeded {_LIST_MACHINES_MAX_PAGES} pages for "
            f"agentpool {agent_pool_name}"
        )

    def _get_terminal_machine_provisioning_failures(
        self,
        cluster_name: str,
        agent_pool_name: str,
        expected_names: Set[str],
    ) -> List[Dict[str, Any]]:
        """Return failed Machines once all expected Machines are terminal.

        We intentionally do not return on the first failed Machine. Successful
        subsets can still contribute P50/P70/P90 readiness timings before the
        operation is marked failed.
        """
        if not expected_names:
            return []
        machines = self._list_machines(cluster_name, agent_pool_name)
        machines_by_name = {
            machine.get("name"): machine
            for machine in machines
            if machine.get("name") in expected_names
        }
        if set(machines_by_name) != expected_names:
            return []
        states = {
            name: machines_by_name[name].get("properties", {}).get("provisioningState")
            for name in expected_names
        }
        # A failed Machine can never become a Ready node, but other Machines may
        # still join and improve lower-percentile readiness telemetry. Wait for
        # the full expected set to become terminal before returning failures.
        if not all(state in _MACHINE_TERMINAL_STATES for state in states.values()):
            return []
        failed_names = [
            name for name, state in states.items() if state in _MACHINE_FAILURE_STATES
        ]
        return [
            self._get_machine_failure_detail(machines_by_name[name])
            for name in sorted(failed_names)[:_MACHINE_FAILURE_DETAIL_LIMIT]
        ]

    @staticmethod
    def _get_machine_failure_detail(machine: Dict[str, Any]) -> Dict[str, Any]:
        """Extract compact failure details from a Machine resource."""
        properties = machine.get("properties", {})
        status = properties.get("status", {})
        provisioning_error = status.get("provisioningError") or {}
        message = provisioning_error.get("message")
        if isinstance(message, str):
            message = message[:300]
        return {
            "name": machine.get("name"),
            "provisioningState": properties.get("provisioningState"),
            "error_code": provisioning_error.get("code"),
            "error_message": message,
        }

    # ---- Machine API: batch scale path ----
    def _scale_machine_batch(
        self,
        request: SimpleNamespace,
        names: List[str],
    ) -> List[str]:
        """Dispatch ``names`` across ``machine_workers`` worker slices via the Batch API.

        Each worker submits exactly one ``BatchPutMachine``-headered PUT carrying
        a contiguous slice of ``names``. Slices are computed by arithmetic from
        the ``worker_id``.

        ``scale_machine_count`` MUST be an exact multiple of ``machine_workers``
        and the resulting per-worker batch size MUST be no larger than
        ``_BATCH_MAX_MACHINES_PER_REQUEST``. ``ValueError`` is raised otherwise
        so the failure surfaces before any partial batch submission reaches ARM.

        Per-worker exceptions are caught and logged; the worker's slice is
        excluded from the returned ``successful`` list. The input ``request``
        is not mutated.
        """
        n = len(names)
        workers = request.machine_workers
        if workers <= 0:
            raise ValueError(f"machine_workers must be positive (got {workers})")
        if n % workers != 0:
            raise ValueError(
                f"scale_machine_count ({n}) must be an exact multiple of "
                f"machine_workers ({workers}) when use_batch_api=True; "
                f"got remainder {n % workers}"
            )
        per_worker = n // workers
        if per_worker > _BATCH_MAX_MACHINES_PER_REQUEST:
            raise ValueError(
                f"calculated batch size ({per_worker}) exceeds "
                f"BatchPutMachine limit ({_BATCH_MAX_MACHINES_PER_REQUEST}); "
                f"increase machine_workers for scale_machine_count ({n})"
            )
        successful: List[str] = []

        def run_worker(worker_id: int) -> List[str]:
            start = worker_id * per_worker
            chunk = names[start:start + per_worker]
            try:
                return self._create_batch_machines(request, chunk, worker_id)
            except Exception:
                logger.exception(f"batch worker {worker_id} failed")
                return []

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(run_worker, w) for w in range(workers)]
            for fut in as_completed(futures):
                try:
                    created = fut.result()
                except Exception:
                    # run_worker already swallows; this is belt-and-suspenders.
                    logger.exception("unexpected error retrieving batch worker result")
                    continue
                successful.extend(created)
        return successful

    def _create_batch_machines(
        self,
        request: SimpleNamespace,
        chunk: List[str],
        chunk_idx: int,
    ) -> List[str]:
        """Submit a batch-PUT request creating every machine in ``chunk``.

        Uses the AKS Machine API ``BatchPutMachine`` HEADER pattern (implicit
        contract with AKS NAP, not publicly available): a single PUT to the first
        machine name in ``chunk`` carrying a ``BatchPutMachine`` header whose
        value is JSON containing ``vmSkus`` and ``batchMachines`` lists.

        ``batchMachines`` lists ONLY the *additional* machines; the first one
        is created from the URL + body. Each entry uses the key
        ``machineName`` -- the wrong key (e.g. ``name``) causes the API to
        silently ignore the extras and create only the URL-pointed machine.

        ``vmSkus`` is a ``{"value": [<vm_sku obj>]}`` envelope (not a flat
        list); the inner object only needs ``name`` (the requested VM size)
        and ``resourceType`` -- the AKS NAP Batch endpoint validates the
        rest server-side. We deliberately omit speculative SKU shape fields
        (family, locations, capabilities) so the header schema stays
        consistent across all VM sizes.

        Returns the list of machine names submitted on 2xx. Raises
        ``RuntimeError`` (from ``_make_batch_request``) if the request
        exhausts 429 retries or returns a non-2xx. Caller catches and
        excludes failed chunks from the success list.
        """
        if not chunk:
            return []
        if len(chunk) > _BATCH_MAX_MACHINES_PER_REQUEST:
            raise ValueError(
                f"BatchPutMachine supports at most "
                f"{_BATCH_MAX_MACHINES_PER_REQUEST} machines per request; "
                f"got {len(chunk)}"
            )
        sub = self.subscription_id
        first_machine_name = chunk[0]
        url = (
            f"{_ARM_BASE}/subscriptions/{sub}/resourceGroups/{request.resource_group}"
            f"/providers/Microsoft.ContainerService/managedClusters/{request.cluster_name}"
            f"/agentPools/{request.agent_pool_name}/machines/{first_machine_name}"
            f"?api-version={_MACHINE_API_VERSION}"
        )
        body: Dict[str, Any] = {"properties": {"hardware": {"vmSize": request.vm_size}}}
        remaining_machines = chunk[1:]
        batch_machines = [{"machineName": name} for name in remaining_machines]
        vm_sku = {
            "name": request.vm_size,
            "resourceType": "virtualMachines",
        }
        batch_header_value = json.dumps({
            "vmSkus": {"value": [vm_sku]},
            "batchMachines": batch_machines,
        })
        logger.info(
            f"chunk {chunk_idx}: submitting BatchPutMachine PUT for {len(chunk)} machines "
            f"(target={first_machine_name})"
        )
        # Cap the timeout value passed to this batch PUT attempt. This limits
        # the per-attempt request timeout given to ``_make_batch_request``,
        # but it does not bound total wall time for the chunk because retry
        # and backoff handling can still extend the overall elapsed time.
        put_timeout = min(request.timeout, _PER_REQUEST_TIMEOUT_CAP)
        start_time = datetime.now(timezone.utc)
        self._make_batch_request(
            "PUT",
            url,
            body,
            put_timeout,
            batch_header_value=batch_header_value,
            chunk_idx=chunk_idx,
            first_machine_name=first_machine_name,
        )
        end_time = datetime.now(timezone.utc)
        execution_time_seconds = (end_time - start_time).total_seconds()
        batch_command_execution_times = getattr(
            request, "batch_command_execution_times", None
        )
        if batch_command_execution_times is None:
            batch_command_execution_times = {}
            request.batch_command_execution_times = batch_command_execution_times
        metric = {
            "start_time": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "execution_time_seconds": execution_time_seconds,
            "total_machines_in_batch": len(chunk),
        }
        metric_lock = getattr(request, "batch_command_execution_times_lock", None)
        if metric_lock is None:
            batch_command_execution_times[first_machine_name] = metric
        else:
            with metric_lock:
                batch_command_execution_times[first_machine_name] = metric
        logger.info(
            f"chunk {chunk_idx}: BatchPutMachine PUT completed for {len(chunk)} "
            f"machines in {execution_time_seconds:.3f} seconds "
            f"(target={first_machine_name})"
        )
        return list(chunk)

    def _make_batch_request(
        self,
        method: str,
        url: str,
        data: Dict[str, Any],
        timeout: int,
        batch_header_value: str,
        chunk_idx: Optional[int] = None,
        first_machine_name: Optional[str] = None,
    ) -> None:
        """Send a ``BatchPutMachine``-headered request with bounded 429 backoff.

        Sends the request directly (NOT via ``make_request``) so we can attach
        the ``BatchPutMachine`` header alongside the standard auth/content-type
        headers. Calls the endpoint up to ``_BATCH_429_MAX_RETRIES`` total
        times on HTTP 429, sleeping between attempts with exponential backoff
        starting at ``_BATCH_429_INITIAL_BACKOFF_SECONDS`` and doubling each
        time (1s, 2s, 4s, 8s by default). All other non-2xx responses raise
        immediately.
        """
        # Compact prefix so every error/log line is self-identifying in Kusto
        # (chunk_idx + first machine name pinpoint the failing slice without
        # cross-referencing the per-worker log).
        ctx = (
            f"chunk={chunk_idx} target={first_machine_name} {method} {url}"
        )
        backoff = _BATCH_429_INITIAL_BACKOFF_SECONDS
        last_resp: Optional[requests.Response] = None
        for attempt in range(_BATCH_429_MAX_RETRIES):
            headers = {
                "Authorization": f"Bearer {self._get_access_token()}",
                "Content-Type": "application/json",
                "BatchPutMachine": batch_header_value,
            }
            # Use the client's shared Session so this batch path reuses the
            # same pooled TCP/TLS connections (and adapters/proxies) as the
            # individual ``make_request`` path; avoids per-PUT handshakes
            # during large scales.
            resp = self._session.request(
                method, url, headers=headers, json=data, timeout=timeout,
            )
            last_resp = resp
            if resp.status_code in (200, 201, 202, 204):
                return
            if resp.status_code != 429:
                raise RuntimeError(
                    f"batch request failed [{ctx}]: "
                    f"{resp.status_code} {resp.text[:500]}"
                )
            if attempt == _BATCH_429_MAX_RETRIES - 1:
                break
            logger.warning(
                f"batch request 429 [{ctx}]; retrying in {backoff:.1f}s "
                f"(attempt {attempt + 1}/{_BATCH_429_MAX_RETRIES})"
            )
            time.sleep(backoff)
            backoff *= 2
        text = last_resp.text[:500] if last_resp is not None else ""
        raise RuntimeError(
            f"batch request exceeded {_BATCH_429_MAX_RETRIES} attempts "
            f"after HTTP 429 responses [{ctx}]; last text={text}"
        )
