"""AKS Machine API client.

Composes the existing AKSClient (auth, ContainerServiceClient, KubernetesClient,
get_cluster_name, get_cluster_data) and adds raw REST methods for the Machine API
which is not exposed in the Azure SDK.

Ported from ado-telescope/modules/python/k8s/cloud_providers/azure.py with bug fixes:
- Truthful type hints (cloud_data Dict, not str).
- No mutation of input config.
- UTC timestamps.
"""
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
_AGENTPOOL_API_VERSION = "2024-06-02-preview"  # per ado azure.py
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

    # ---- auth + REST plumbing ----
    def _get_access_token(self) -> str:
        return self.aks_client.credential.get_token(_ARM_SCOPE).token

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
    def _wait_for_machine_node_readiness(  # pylint: disable=too-many-locals
        self,
        machine_names: List[str],
        start_time_utc: str,
        timeout: int,
    ) -> Dict[str, float]:
        """Polls each machine until Ready=True; returns percentile dict {P50,P90,P99}.

        Each per-node "readiness time" = (Ready transition time) - start_time_utc.
        ``timeout`` is wall-clock seconds from invocation (not per-machine).
        Returns {"P50":0.0,"P90":0.0,"P99":0.0} if no nodes became Ready before timeout,
        if ``machine_names`` is empty, if ``k8s_client`` is unavailable, or if
        ``start_time_utc`` cannot be parsed. Per-machine ``get_node_details`` failures
        are logged and skipped. This method never raises.
        """
        def parse_iso(s):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        kc = self.aks_client.k8s_client
        if kc is None:
            logger.error(
                "k8s_client is None on AKSClient; cannot wait for machine readiness"
            )
            return {"P50": 0.0, "P90": 0.0, "P99": 0.0}
        try:
            start_dt = parse_iso(start_time_utc)
        except (ValueError, TypeError) as e:
            logger.error("Invalid start_time_utc %r: %s", start_time_utc, e)
            return {"P50": 0.0, "P90": 0.0, "P99": 0.0}
        pending = set(machine_names)
        per_node: Dict[str, float] = {}
        deadline = time.time() + timeout
        while pending and time.time() < deadline:
            for name in list(pending):
                try:
                    details = kc.get_node_details(name)
                    for cond in details.get("status", {}).get("conditions", []):
                        if cond.get("type") == "Ready" and cond.get("status") == "True":
                            ready_dt = parse_iso(cond["lastTransitionTime"])
                            per_node[name] = max((ready_dt - start_dt).total_seconds(), 0.0)
                            pending.discard(name)
                            break
                except Exception as e:  # pylint: disable=broad-except
                    logger.warning("Failed to read node %s readiness: %s", name, e)
                    continue
            if pending:
                time.sleep(2)
        if not per_node:
            return {"P50": 0.0, "P90": 0.0, "P99": 0.0}
        sorted_vals = sorted(per_node.values())
        def pct(p):
            idx = max(0, int(round((p / 100.0) * (len(sorted_vals) - 1))))
            return sorted_vals[idx]
        return {"P50": pct(50), "P90": pct(90), "P99": pct(99)}

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
            prefix = self._get_machine_name_prefix()
            names = [f"{prefix}{i:04d}" for i in range(request.scale_machine_count)]
            if request.use_batch_api:
                successful, batch_times = self._scale_machine_batch(request, names)
                response.batch_command_execution_times = batch_times
            else:
                successful = self._scale_machine_individually(request, names)
            response.successful_machines = successful
            response.percentile_node_readiness_times = self._wait_for_machine_node_readiness(
                successful, start_iso, request.timeout)
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

    def _get_machine_name_prefix(self) -> str:
        """Return the machine-name prefix used for batch and individual scale paths."""
        return "tmach"

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

        Body is ``{"properties": {"hardware": {"vmSize": ...}}}`` plus optional tags.
        Returns True iff the machine eventually reaches provisioningState=Succeeded.
        Never raises on HTTP errors; logs and returns False on non-2xx responses.
        """
        sub = self.subscription_id
        url = (
            f"{_ARM_BASE}/subscriptions/{sub}/resourceGroups/{request.resource_group}"
            f"/providers/Microsoft.ContainerService/managedClusters/{request.cluster_name}"
            f"/agentPools/{request.agentpool_name}/machines/{name}"
            f"?api-version={_AGENTPOOL_API_VERSION}"
        )
        body: Dict[str, Any] = {"properties": {"hardware": {"vmSize": request.vm_size}}}
        if request.tags:
            body["tags"] = request.tags
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
        """Submit a single ``$batch`` request creating every machine in ``chunk``.

        Returns the list of machine names that the batch endpoint accepted.
        Raises ``RuntimeError`` (from ``_make_batch_request``) if the batch
        request exhausts 429 retries or returns a non-2xx response. The caller
        (``_scale_machine_batch.run_chunk``) is expected to catch and exclude
        the chunk's names from the success list.
        """
        if not chunk:
            return []
        sub = self.subscription_id
        # AKS Batch endpoint pattern: collection-level $batch with api-version.
        url = (
            f"{_ARM_BASE}/subscriptions/{sub}/resourceGroups/{request.resource_group}"
            f"/providers/Microsoft.ContainerService/managedClusters/{request.cluster_name}"
            f"/agentPools/{request.agentpool_name}/machines/$batch"
            f"?api-version={_AGENTPOOL_API_VERSION}"
        )
        machine_body = {"properties": {"hardware": {"vmSize": request.vm_size}}}
        if request.tags:
            machine_body["tags"] = request.tags
        # ARM batch envelope: each request targets a child machine name.
        body = {
            "requests": [
                {
                    "httpMethod": "PUT",
                    "name": name,
                    "content": machine_body,
                }
                for name in chunk
            ]
        }
        logger.info(
            "chunk %d: submitting $batch for %d machines",
            chunk_idx, len(chunk),
        )
        self._make_batch_request("POST", url, body, request.timeout)
        return list(chunk)

    def _make_batch_request(
        self,
        method: str,
        url: str,
        data: Dict[str, Any],
        timeout: int,
    ) -> None:
        """Send a ``$batch`` request with bounded 429 exponential backoff.

        Retries on HTTP 429 up to ``_BATCH_429_MAX_RETRIES`` attempts with
        exponential backoff starting at ``_BATCH_429_INITIAL_BACKOFF_SECONDS``
        and doubling each attempt (1s, 2s, 4s by default). All other non-2xx
        responses raise immediately. Reuses ``make_request`` for auth.
        """
        backoff = _BATCH_429_INITIAL_BACKOFF_SECONDS
        last_resp: Optional[requests.Response] = None
        for attempt in range(_BATCH_429_MAX_RETRIES):
            resp = self.make_request(method, url, data=data, timeout=timeout)
            last_resp = resp
            if resp.status_code in (200, 201, 202, 204):
                return resp
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
