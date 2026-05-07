"""AKS Machine API client.

Composes the existing AKSClient (auth, ContainerServiceClient, KubernetesClient,
get_cluster_name, get_cluster_data) and adds raw REST methods for the Machine API
which is not exposed in the Azure SDK.

Ported from ado-telescope/modules/python/k8s/cloud_providers/azure.py with bug fixes:
- Truthful type hints (cloud_data Dict, not str).
- No mutation of input config.
- UTC timestamps.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from clients.aks_client import AKSClient
from machine.data_classes import MachineOperationResponse, OperationNames, ScaleMachineRequest
from utils.logger_config import get_logger

logger = get_logger(__name__)

_ARM_BASE = "https://management.azure.com"
_ARM_SCOPE = "https://management.azure.com/.default"
_AGENTPOOL_API_VERSION = "2024-06-02-preview"  # per ado azure.py — agentpool sub-resource
_MACHINE_API_VERSION = "2025-06-02-preview"  # per ado azure.py — machines sub-resource
_POLL_INTERVAL_SECONDS = 10
_PROVISIONING_NONE_STATE_LIMIT = 5
_BATCH_429_MAX_RETRIES = 3
_BATCH_429_INITIAL_BACKOFF_SECONDS = 1.0


class AKSMachineClient:
    """Composes AKSClient and adds Machine-API-specific REST plumbing."""

    # Disable too-many-arguments / too-many-positional-arguments: this constructor
    # is a thin pass-through to AKSClient, which already accepts these as kwargs.
    # Wrapping them in a config object would just add ceremony.
    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        resource_group: str,
        cluster_name: Optional[str] = None,
        subscription_id: Optional[str] = None,
        kube_config_file: Optional[str] = None,
        result_dir: Optional[str] = None,
        operation_timeout_minutes: int = 30,
    ):
        self.aks_client = AKSClient(
            subscription_id=subscription_id,
            resource_group=resource_group,
            cluster_name=cluster_name,
            kube_config_file=kube_config_file,
            result_dir=result_dir,
            operation_timeout_minutes=operation_timeout_minutes,
        )
        self.resource_group = self.aks_client.resource_group
        self.subscription_id = self.aks_client.subscription_id
        self._token_cache_value: Optional[str] = None
        self._token_cache_expiry: float = 0.0  # unix epoch seconds
        self._token_lock = threading.Lock()

    # ---- auth + REST plumbing ----
    def _get_access_token(self) -> str:
        """Cached token fetch. Re-uses token across worker threads with a 60s safety margin
        before expiry. Avoids forking `az account get-access-token` per worker."""
        with self._token_lock:
            if self._token_cache_value and time.time() < self._token_cache_expiry - 60:
                return self._token_cache_value
            tok = self.aks_client.credential.get_token(_ARM_SCOPE)
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
        calling ``raise_for_status()``) — this method does NOT raise on HTTP
        errors. Long-running Machine API operations return 200/202 with a
        Location header that callers must follow.
        """
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
        }
        return requests.request(method, url, headers=headers, json=data, timeout=timeout)

    # ---- thin pass-throughs to AKSClient (NOT duplicated) ----
    def get_cluster_name(self) -> str:
        """Return the configured/discovered AKS cluster name (delegates to AKSClient)."""
        return self.aks_client.get_cluster_name()

    def get_cluster_data(self, cluster_name: str) -> Dict:
        """Return the AKS cluster ARM payload (delegates to AKSClient)."""
        return self.aks_client.get_cluster_data(cluster_name)

    # ---- Machine API: agent pool provisioning ----
    def create_machine_agentpool(
        self,
        agentpool_name: str,
        cluster_name: str,
        resource_group: str,
        timeout: int = 300,
    ) -> bool:
        """Convert an existing agentpool to Machines mode via PUT.

        Args:
            agentpool_name: Target agentpool name.
            cluster_name: Parent AKS cluster name.
            resource_group: Resource group containing the cluster.
            timeout: Total budget (seconds) used as both the PUT HTTP timeout AND the
                polling deadline for ``_wait_for_agentpool_provisioning``. Default 300s.

        Returns:
            True iff the agentpool reaches provisioningState='Succeeded' before
            ``timeout`` seconds elapse. False on PUT failure, ARM-reported Failed
            state, or timeout. Never raises on HTTP errors.
        """
        if resource_group != self.resource_group:
            logger.warning(
                "create_machine_agentpool called with resource_group=%s but client bound to %s",
                resource_group, self.resource_group,
            )
        sub = self.subscription_id
        url = (
            f"{_ARM_BASE}/subscriptions/{sub}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.ContainerService/managedClusters/{cluster_name}"
            f"/agentPools/{agentpool_name}?api-version={_AGENTPOOL_API_VERSION}"
        )
        body = {"properties": {"mode": "Machines"}}
        resp = self.make_request("PUT", url, data=body, timeout=timeout)
        if resp.status_code not in (200, 201):
            logger.error("create_machine_agentpool PUT failed: %s %s", resp.status_code, resp.text)
            return False
        return self._wait_for_agentpool_provisioning(url, timeout)

    def _wait_for_agentpool_provisioning(self, url: str, timeout: int) -> bool:
        """Poll the agentpool URL until provisioningState is terminal.

        Polls every ``_POLL_INTERVAL_SECONDS`` (10s) using a 30s per-request HTTP
        timeout. Returns True on 'Succeeded'. Returns False on 'Failed' or when
        ``timeout`` seconds have elapsed since invocation. Transient non-200 GETs
        are logged and retried until the deadline.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.make_request("GET", url, timeout=30)
            if r.status_code != 200:
                logger.warning("agentpool GET %s -> %s", url, r.status_code)
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            state = r.json().get("properties", {}).get("provisioningState")
            if state == "Succeeded":
                return True
            if state == "Failed":
                logger.error("agentpool provisioning failed: %s", r.json())
                return False
            time.sleep(_POLL_INTERVAL_SECONDS)
        logger.error("agentpool provisioning timed out after %ss", timeout)
        return False

    # Disable too-many-locals: this is essentially a state machine over polling
    # results; refactoring to fewer locals would just hide intermediate state.
    def _wait_for_machine_node_readiness(
        self,
        agentpool_name: str,
        expected_count: int,
        timeout: int,
    ) -> Dict[str, float]:
        """Wait for nodes in ``agentpool_name`` to become Ready; return {P50,P90,P99}.

        AKS Machine ARM resource names (e.g. ``scale100-machine-1``) are NOT the
        same as the underlying k8s Node names (``aks-<pool>-<rand>-vmss<i>``), so
        we cannot look up Nodes by Machine name. Instead we poll Nodes labelled
        ``agentpool=<pool>`` and record the wall-clock elapsed when each percentile
        ready threshold is hit. Mirrors ado-telescope (azure.py:1420 / 1444).

        ``timeout`` is wall-clock seconds from invocation. Returns the zero-fallback
        dict if ``k8s_client`` is unavailable, ``expected_count`` <= 0, or no
        percentile target is met within ``timeout``. Polling exceptions are logged
        and treated as 0 ready this tick. This method never raises.
        """
        kc = self.aks_client.k8s_client
        if kc is None:
            logger.error(
                "k8s_client is None on AKSClient; cannot wait for machine readiness"
            )
            return {"P50": 0.0, "P90": 0.0, "P99": 0.0}
        if expected_count <= 0:
            return {"P50": 0.0, "P90": 0.0, "P99": 0.0}
        label_selector = f"agentpool={agentpool_name}"
        targets = {p: max(1, int((p / 100.0) * expected_count)) for p in (50, 90, 99)}
        elapsed: Dict[int, float] = {}
        start = time.time()
        deadline = start + timeout
        logger.info(
            "Waiting for nodes in agentpool %s (label %s) - targets %s, timeout %ss",
            agentpool_name, label_selector, targets, timeout,
        )
        while time.time() < deadline and len(elapsed) < len(targets):
            try:
                ready = len(kc.get_ready_nodes(label_selector=label_selector))
            except Exception as e:  # pylint: disable=broad-except
                logger.warning("get_ready_nodes(%s) failed: %s", label_selector, e)
                ready = 0
            now_elapsed = time.time() - start
            for p, target in targets.items():
                if p not in elapsed and ready >= target:
                    elapsed[p] = now_elapsed
                    logger.info(
                        "P%d hit: %d/%d ready at %.2fs",
                        p, ready, expected_count, now_elapsed,
                    )
            if len(elapsed) < len(targets):
                time.sleep(2)
        if not elapsed:
            logger.warning(
                "No percentile target met within %ss for agentpool %s",
                timeout, agentpool_name,
            )
            return {"P50": 0.0, "P90": 0.0, "P99": 0.0}
        return {f"P{p}": elapsed.get(p, 0.0) for p in (50, 90, 99)}

    def scale_machine(self, request: ScaleMachineRequest) -> MachineOperationResponse:
        """Scale a Machine-mode agentpool by creating ``request.scale_machine_count`` machines.

        Branches between batch and non-batch paths. This commit implements only the
        non-batch path; ``use_batch_api=True`` will reach a method that does not yet
        exist (Task 8). Never raises — failures recorded on the returned response.
        """
        start_dt = datetime.now(timezone.utc)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        response = MachineOperationResponse(
            operation_name=OperationNames.SCALE_MACHINE.value,
            start_time=start_iso,
        )
        try:
            # Naming parity with ado-telescope (azure.py:_get_machine_name_prefix +
            # _scale_machine_individually): prefix is "scale{N}" or "scale{N//1000}k",
            # machines are 1-indexed as "{prefix}-machine-{i}". Byte-identical names
            # let cross-repo Kusto dashboards correlate runs across ado/gh.
            prefix = self._get_machine_name_prefix(request.scale_machine_count)
            names = [
                f"{prefix}-machine-{i + 1}" for i in range(request.scale_machine_count)
            ]
            if request.use_batch_api:
                successful, batch_times = self._scale_machine_batch(request, names)
                response.batch_command_execution_times = batch_times
            else:
                successful = self._scale_machine_individually(request, names)
            response.successful_machines = successful
            response.percentile_node_readiness_times = self._wait_for_machine_node_readiness(
                agentpool_name=request.agentpool_name,
                expected_count=len(successful),
                timeout=request.timeout,
            )
            response.succeeded = len(successful) == request.scale_machine_count
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("scale_machine failed")
            response.succeeded = False
            response.error = str(exc)
        finally:
            end_dt = datetime.now(timezone.utc)
            response.end_time = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            response.command_execution_time = (end_dt - start_dt).total_seconds()
        # Attach cluster snapshot for Kusto cloud_data column.
        try:
            response.cloud_data = self.get_cluster_data(request.cluster_name)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("get_cluster_data failed: %s", exc)
        return response

    def _get_machine_name_prefix(self, scale_machine_count: int) -> str:
        """Generate the ado-compatible machine-name prefix for a given scale count.

        Mirrors ado-telescope ``azure.py::_get_machine_name_prefix`` exactly so
        that the resulting machine ARM resource names match across repos and
        cross-repo Kusto dashboards keyed on machine name continue to correlate.

        - ``scale1000`` -> ``scale1k`` (any multiple of 1000 >= 1000 collapses)
        - ``scale500``  -> ``scale500``
        - ``scale1``    -> ``scale1``
        """
        if scale_machine_count >= 1000 and scale_machine_count % 1000 == 0:
            return f"scale{scale_machine_count // 1000}k"
        return f"scale{scale_machine_count}"

    def _scale_machine_individually(self, request, names):
        """Submit per-machine PUTs concurrently via ThreadPoolExecutor.

        Each worker calls ``_create_single_machine(name, request)`` which PUTs
        the machine and waits for its provisioning to terminate. Returns the
        list of names that reported True. Per-machine exceptions are logged
        and treated as failure (name omitted from result).
        """
        successful: List[str] = []
        with ThreadPoolExecutor(max_workers=request.machine_workers) as ex:
            futures = {ex.submit(self._create_single_machine, n, request): n for n in names}
            for fut in as_completed(futures):
                n = futures[fut]
                try:
                    if fut.result():
                        successful.append(n)
                except Exception:  # pylint: disable=broad-except
                    logger.exception("create_single_machine failed for %s", n)
        return successful

    def _create_single_machine(self, name: str, request) -> bool:
        """PUT a single Machine resource and wait for it to reach a terminal state.

        Body is ``{"properties": {"hardware": {"vmSize": ...}}}``. Tags are inherited
        from the parent agentpool; the machine PUT body in api-version 2025-06-02-preview
        does not accept a top-level ``tags`` field (rejected with UnmarshalError).
        Returns True iff the machine eventually reaches provisioningState=Succeeded.
        Never raises on HTTP errors; logs and returns False on non-2xx responses.
        """
        sub = self.subscription_id
        url = (
            f"{_ARM_BASE}/subscriptions/{sub}/resourceGroups/{request.resource_group}"
            f"/providers/Microsoft.ContainerService/managedClusters/{request.cluster_name}"
            f"/agentPools/{request.agentpool_name}/machines/{name}"
            f"?api-version={_MACHINE_API_VERSION}"
        )
        body: Dict[str, Any] = {"properties": {"hardware": {"vmSize": request.vm_size}}}
        resp = self.make_request("PUT", url, data=body, timeout=request.timeout)
        if resp.status_code not in (200, 201, 202):
            logger.error("PUT machine %s -> %s %s", name, resp.status_code, resp.text[:500])
            return False
        return self._wait_for_machine_provisioning(url, request.timeout)

    def _wait_for_machine_provisioning(self, url: str, timeout: int) -> bool:
        """Thin wrapper around ``_wait_for_provisioning`` for machine resources."""
        return self._wait_for_provisioning(url, timeout)

    def _wait_for_provisioning(self, url: str, timeout: int) -> bool:
        """Poll ``url`` until ``properties.provisioningState`` is terminal or deadline.

        Returns True on Succeeded, False on Failed or timeout. Transient non-200
        responses are logged and retried until the deadline. If ``provisioningState``
        is missing from successful responses for ``_PROVISIONING_NONE_STATE_LIMIT``
        consecutive polls, treats the operation as Failed and returns False (rather
        than spinning until the deadline). Never raises.
        """
        deadline = time.time() + timeout
        none_count = 0
        while time.time() < deadline:
            r = self.make_request("GET", url, timeout=30)
            if r.status_code == 200:
                try:
                    body = r.json()
                except (ValueError, TypeError) as exc:
                    logger.warning("provisioning poll JSON parse failed: %s", exc)
                    time.sleep(_POLL_INTERVAL_SECONDS)
                    continue
                state = body.get("properties", {}).get("provisioningState")
                if state == "Succeeded":
                    return True
                if state == "Failed":
                    logger.error("provisioning Failed: %s", str(body)[:500])
                    return False
                if state is None:
                    none_count += 1
                    if none_count >= _PROVISIONING_NONE_STATE_LIMIT:
                        logger.warning(
                            "provisioningState absent for %d consecutive polls; "
                            "treating as Failed. body=%s",
                            none_count, str(body)[:500],
                        )
                        return False
                else:
                    none_count = 0
            else:
                logger.warning("provisioning poll non-200: %s", r.status_code)
            time.sleep(_POLL_INTERVAL_SECONDS)
        logger.error("provisioning timeout after %ss for %s", timeout, url)
        return False

    # ---- Machine API: batch scale path ----
    @staticmethod
    def _array_split(items: List[str], n: int) -> List[List[str]]:
        """Split ``items`` into ``n`` chunks of as-equal-as-possible size.

        Equivalent to ``numpy.array_split`` semantics with pure Python. ``n`` is
        clamped to ``[1, len(items)]`` so empty/oversized worker counts degrade
        gracefully. Returns at most ``len(items)`` chunks; never returns empty
        chunks unless ``items`` itself is empty.
        """
        if not items:
            return []
        n = max(1, min(n, len(items)))
        k, m = divmod(len(items), n)
        return [items[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]

    def _scale_machine_batch(
        self,
        request: ScaleMachineRequest,
        names: List[str],
    ) -> Tuple[List[str], Dict[str, float]]:
        """Dispatch ``names`` across ``request.machine_workers`` chunks via the AKS Batch API.

        Splits ``names`` into up to ``request.machine_workers`` chunks
        (``_array_split`` semantics) and submits each chunk to a
        ``ThreadPoolExecutor``. Each worker calls ``_create_batch_machines``,
        whose return value is the list of names that landed successfully in
        that chunk. Per-chunk wall time is captured under ``chunk_<idx>``
        regardless of success/failure. Per-chunk worker exceptions are caught
        and logged; the chunk's names are excluded from the returned
        ``successful`` list. The input ``request`` is not mutated.
        """
        chunks = self._array_split(names, request.machine_workers)
        successful: List[str] = []
        batch_times: Dict[str, float] = {}

        def run_chunk(idx: int, chunk: List[str]):
            t0 = time.time()
            try:
                created = self._create_batch_machines(request, chunk, idx)
            except Exception:  # pylint: disable=broad-except
                logger.exception("batch chunk %d failed", idx)
                created = []
            elapsed = time.time() - t0
            return idx, created, elapsed

        with ThreadPoolExecutor(max_workers=max(1, request.machine_workers)) as ex:
            futures = [ex.submit(run_chunk, i, chunk) for i, chunk in enumerate(chunks)]
            for fut in as_completed(futures):
                try:
                    idx, created, elapsed = fut.result()
                except Exception:  # pylint: disable=broad-except
                    # run_chunk already swallows; this is belt-and-suspenders.
                    logger.exception("unexpected error retrieving batch chunk result")
                    continue
                batch_times[f"chunk_{idx}"] = elapsed
                successful.extend(created)
        return successful, batch_times

    def _create_batch_machines(
        self,
        request: ScaleMachineRequest,
        chunk: List[str],
        chunk_idx: int,
    ) -> List[str]:
        """Submit a batch-PUT request creating every machine in ``chunk``.

        Uses the AKS Machine API ``BatchPutMachine`` HEADER pattern (NOT the
        non-existent ARM ``/$batch`` envelope): a single PUT to the first
        machine name in ``chunk`` carrying a ``BatchPutMachine`` header whose
        value is JSON containing ``vmSkus`` and ``batchMachines`` lists.

        Returns the list of machine names submitted on 2xx. Raises
        ``RuntimeError`` (from ``_make_batch_request``) if the request exhausts
        429 retries or returns a non-2xx. Caller catches and excludes failed
        chunks from the success list.
        """
        if not chunk:
            return []
        sub = self.subscription_id
        first_machine_name = chunk[0]
        url = (
            f"{_ARM_BASE}/subscriptions/{sub}/resourceGroups/{request.resource_group}"
            f"/providers/Microsoft.ContainerService/managedClusters/{request.cluster_name}"
            f"/agentPools/{request.agentpool_name}/machines/{first_machine_name}"
            f"?api-version={_MACHINE_API_VERSION}"
        )
        body: Dict[str, Any] = {"properties": {"hardware": {"vmSize": request.vm_size}}}
        batch_machines = [
            {"name": name, "properties": {"hardware": {"vmSize": request.vm_size}}}
            for name in chunk
        ]
        vm_skus = [{"name": request.vm_size, "count": len(chunk)}]
        batch_header_value = json.dumps({
            "vmSkus": vm_skus,
            "batchMachines": batch_machines,
        })
        logger.info(
            "chunk %d: submitting BatchPutMachine PUT for %d machines (target=%s)",
            chunk_idx, len(chunk), first_machine_name,
        )
        self._make_batch_request(
            "PUT", url, body, request.timeout, batch_header_value=batch_header_value,
        )
        return list(chunk)

    def _make_batch_request(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        method: str,
        url: str,
        data: Dict[str, Any],
        timeout: int,
        batch_header_value: str,
    ) -> None:
        """Send a ``BatchPutMachine``-headered request with bounded 429 backoff.

        Sends the request directly (NOT via ``make_request``) so we can attach
        the ``BatchPutMachine`` header alongside the standard auth/content-type
        headers. Retries on HTTP 429 up to ``_BATCH_429_MAX_RETRIES`` attempts
        with exponential backoff starting at
        ``_BATCH_429_INITIAL_BACKOFF_SECONDS`` and doubling each attempt
        (1s, 2s, 4s by default). All other non-2xx responses raise immediately.
        """
        backoff = _BATCH_429_INITIAL_BACKOFF_SECONDS
        last_resp: Optional[requests.Response] = None
        for attempt in range(_BATCH_429_MAX_RETRIES):
            headers = {
                "Authorization": f"Bearer {self._get_access_token()}",
                "Content-Type": "application/json",
                "BatchPutMachine": batch_header_value,
            }
            resp = requests.request(
                method, url, headers=headers, json=data, timeout=timeout,
            )
            last_resp = resp
            if resp.status_code in (200, 201, 202, 204):
                return
            if resp.status_code != 429:
                raise RuntimeError(
                    f"batch request failed: {resp.status_code} {resp.text[:500]}"
                )
            if attempt == _BATCH_429_MAX_RETRIES - 1:
                break
            logger.warning(
                "batch request 429; retrying in %.1fs (attempt %d/%d)",
                backoff, attempt + 1, _BATCH_429_MAX_RETRIES,
            )
            time.sleep(backoff)
            backoff *= 2
        text = last_resp.text[:500] if last_resp is not None else ""
        raise RuntimeError(
            f"batch request exceeded {_BATCH_429_MAX_RETRIES} 429 retries; last text={text}"
        )
