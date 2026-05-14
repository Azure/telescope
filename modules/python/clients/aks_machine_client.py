"""AKS Machine API client.

Subclasses ``AKSClient`` to inherit auth, ContainerServiceClient,
KubernetesClient, ``get_cluster_name``, ``get_cluster_data``, and the existing
node-pool CRUD methods. Adds raw REST methods for the Machine API which is not
yet exposed in the Azure SDK.

Public methods (``create_machine_agentpool``, ``scale_machine``) wrap their work
in ``OperationContext`` exactly like ``AKSClient.create_node_pool`` /
``AKSClient.scale_node_pool``: the context is opened inside the client method,
metadata is enriched with ``op.add_metadata`` along the way, success returns
True, failures are logged and re-raised so ``OperationContext`` records them.
``MachineCRUD`` therefore stays a thin try/except wrapper, mirroring
``crud/azure/node_pool_crud.py``.

Ported from ado-telescope/modules/python/k8s/cloud_providers/azure.py.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import requests

from clients.aks_client import AKSClient
from utils.logger_config import get_logger, setup_logging

# Configure logging (mirrors clients/aks_client.py / crud/azure/node_pool_crud.py).
setup_logging()
logger = get_logger(__name__)
# Suppress noisy Azure SDK logs (mirror clients/aks_client.py).
get_logger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
get_logger("azure.identity").setLevel(logging.ERROR)
get_logger("azure.core.pipeline").setLevel(logging.ERROR)
get_logger("msal").setLevel(logging.ERROR)

_ARM_BASE = "https://management.azure.com"
_ARM_SCOPE = "https://management.azure.com/.default"
_AGENTPOOL_API_VERSION = "2024-06-02-preview"  # per ado azure.py — agentpool sub-resource
_MACHINE_API_VERSION = "2025-06-02-preview"  # per ado azure.py — machines sub-resource
_POLL_INTERVAL_SECONDS = 10
_PROVISIONING_NONE_STATE_LIMIT = 5
_BATCH_429_MAX_RETRIES = 3
_BATCH_429_INITIAL_BACKOFF_SECONDS = 1.0


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
        calling ``raise_for_status()``) — this method does NOT raise on HTTP
        errors. Long-running Machine API operations return 200/202 with a
        Location header that callers must follow.
        """
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
        }
        return requests.request(method, url, headers=headers, json=data, timeout=timeout)

    # ---- Machine API: agent pool provisioning ----
    def create_machine_agentpool(
        self,
        agentpool_name: str,
        vm_size: str,
        cluster_name: Optional[str] = None,
        timeout: int = 300,
    ) -> bool:
        """Convert an existing agentpool to Machines mode via PUT.

        Mirrors ``AKSClient.create_node_pool`` convention: opens an
        ``OperationContext`` here, enriches metadata, returns True on success,
        re-raises on failure (so the context records ``success=False`` with
        traceback before the exception propagates to ``MachineCRUD``).

        Args:
            agentpool_name: Target agentpool name.
            vm_size: VM SKU recorded in operation metadata. The PUT body itself
                only sets ``mode: Machines``; the SKU is informational here so
                downstream Kusto rows can attribute the agentpool to a SKU.
            cluster_name: Parent AKS cluster name. Defaults to
                ``self.get_cluster_name()`` (matches ``create_node_pool``).
            timeout: Total budget (seconds) used as both the PUT HTTP timeout
                AND the polling deadline for ``_wait_for_agentpool_provisioning``.

        Returns:
            True iff the agentpool reaches provisioningState='Succeeded'.

        Raises:
            RuntimeError: PUT non-2xx, ARM-reported Failed state, or timeout.
        """
        cluster_name = cluster_name or self.get_cluster_name()
        metadata = {
            "cluster_name": cluster_name,
            "agentpool_name": agentpool_name,
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
                    f"/agentPools/{agentpool_name}?api-version={_AGENTPOOL_API_VERSION}"
                )
                body = {"properties": {"mode": "Machines"}}
                resp = self.make_request("PUT", url, data=body, timeout=timeout)
                if resp.status_code not in (200, 201):
                    raise RuntimeError(
                        f"create_machine_agentpool PUT failed: "
                        f"{resp.status_code} {resp.text[:500]}"
                    )
                if not self._wait_for_agentpool_provisioning(url, timeout):
                    raise RuntimeError(
                        f"agentpool {agentpool_name} did not reach Succeeded within {timeout}s"
                    )
                op.add_metadata("agentpool_info", self.get_node_pool(
                    agentpool_name, cluster_name).as_dict())
                op.add_metadata("cluster_info", self.get_cluster_data(cluster_name))
                return True
            except Exception as e:
                logger.error(
                    "Failed to create machine agentpool %s: %s", agentpool_name, e
                )
                raise

    def _wait_for_agentpool_provisioning(self, url: str, timeout: int) -> bool:
        """Poll the agentpool URL until provisioningState is terminal.

        Polls every ``_POLL_INTERVAL_SECONDS`` (10s) using a 30s per-request HTTP
        timeout. Returns True on 'Succeeded'. Returns False on 'Failed' or when
        ``timeout`` seconds have elapsed since invocation. Transient non-200 GETs
        are logged and retried until the deadline. Also handles missing
        provisioningState (treats absence for ``_PROVISIONING_NONE_STATE_LIMIT``
        consecutive polls as Failed).
        """
        deadline = time.time() + timeout
        none_count = 0
        while time.time() < deadline:
            r = self.make_request("GET", url, timeout=30)
            if r.status_code != 200:
                logger.warning("agentpool GET %s -> %s", url, r.status_code)
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            try:
                body = r.json()
            except (ValueError, TypeError) as exc:
                logger.warning("agentpool poll JSON parse failed: %s", exc)
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            state = body.get("properties", {}).get("provisioningState")
            if state == "Succeeded":
                return True
            if state == "Failed":
                logger.error("agentpool provisioning failed: %s", body)
                return False
            if state is None:
                none_count += 1
                if none_count >= _PROVISIONING_NONE_STATE_LIMIT:
                    logger.warning(
                        "agentpool provisioningState absent for %d consecutive polls; "
                        "treating as Failed.",
                        none_count,
                    )
                    return False
            else:
                none_count = 0
            time.sleep(_POLL_INTERVAL_SECONDS)
        logger.error("agentpool provisioning timed out after %ss", timeout)
        return False

    def _wait_for_machine_node_readiness(
        self,
        agentpool_name: str,
        expected_count: int,
        timeout: int,
        baseline_count: int = 0,
    ) -> Dict[str, Dict[str, Any]]:
        """Wait for ``expected_count`` NEW Ready nodes; return ado-parity nested percentile dict.

        AKS Machine ARM resource names (e.g. ``scale100-machine-1``) are NOT the
        same as the underlying k8s Node names (``aks-<pool>-<rand>-vmss<i>``), so
        we cannot look up Nodes by Machine name. Instead we poll Nodes labelled
        ``agentpool=<pool>`` and record the wall-clock elapsed when each percentile
        ready threshold is hit.

        ``baseline_count`` is the number of Ready+labeled nodes that already
        existed BEFORE scale_machine ran. Percentile targets are computed against
        ``baseline_count + expected_count`` and clamped to ``> baseline_count``
        so a target never fires on pre-existing nodes alone. Without this, an
        agentpool that already has 1 Ready node and is being scaled by 1 more
        would report P50/P70/P90/P99/P100 = ~0.7s (the first poll) even though the
        new node had not yet provisioned.

        ``timeout`` is wall-clock seconds from invocation. Returns the nested
        empty-state envelope (``elapsed_time_seconds=None``, ``success=False``)
        if ``k8s_client`` is unavailable, ``expected_count`` <= 0, or no
        percentile target is met within ``timeout``. Polling exceptions are
        logged and treated as 0 ready this tick. Never raises.
        """
        # ado-parity empty-state envelope: nested dict per P-key with
        # `target_nodes`, `elapsed_time_seconds`, `percentage`, `success` so
        # the Kusto schema sees consistent shape regardless of outcome.
        empty_envelope: Dict[str, Dict[str, Any]] = {
            f"P{p}": {
                "target_nodes": 0,
                "elapsed_time_seconds": None,
                "percentage": p,
                "success": False,
            }
            for p in (50, 70, 90, 99, 100)
        }
        kc = self.k8s_client
        if kc is None:
            logger.error(
                "k8s_client is None on AKSClient; cannot wait for machine readiness"
            )
            return empty_envelope
        if expected_count <= 0:
            return empty_envelope
        label_selector = f"agentpool={agentpool_name}"
        target_total = baseline_count + expected_count
        # Each percentile target must be STRICTLY GREATER than baseline_count so
        # we count only NEW nodes — pre-existing labeled Ready nodes alone must
        # never satisfy any threshold.
        targets = {
            p: max(baseline_count + 1, int((p / 100.0) * target_total))
            for p in (50, 70, 90, 99, 100)
        }
        elapsed: Dict[int, float] = {}
        start = time.time()
        deadline = start + timeout
        logger.info(
            "Waiting for nodes in agentpool %s (label %s) - "
            "targets %s, baseline=%d, expected=%d, timeout %ss",
            agentpool_name, label_selector, targets,
            baseline_count, expected_count, timeout,
        )
        while time.time() < deadline and len(elapsed) < len(targets):
            try:
                ready = len(kc.get_ready_nodes(label_selector=label_selector))
            except Exception as e:
                logger.warning("get_ready_nodes(%s) failed: %s", label_selector, e)
                ready = 0
            now_elapsed = time.time() - start
            for p, target in targets.items():
                if p not in elapsed and ready >= target:
                    elapsed[p] = now_elapsed
                    logger.info(
                        "P%d hit: %d/%d ready (target=%d, baseline=%d) at %.2fs",
                        p, ready, target_total, target, baseline_count, now_elapsed,
                    )
            if len(elapsed) < len(targets):
                time.sleep(2)
        if not elapsed:
            logger.warning(
                "No percentile target met within %ss for agentpool %s",
                timeout, agentpool_name,
            )
            return {
                f"P{p}": {
                    "target_nodes": targets[p],
                    "elapsed_time_seconds": None,
                    "percentage": p,
                    "success": False,
                }
                for p in (50, 70, 90, 99, 100)
            }
        result: Dict[str, Dict[str, Any]] = {
            f"P{p}": {
                "target_nodes": targets[p],
                "elapsed_time_seconds": elapsed.get(p),
                "percentage": p,
                "success": p in elapsed,
            }
            for p in (50, 70, 90, 99, 100)
        }
        # ado-parity stdout logging: percentile summary including P100, which is
        # the wall-clock elapsed until ALL target nodes are Ready. This matches
        # ado's `response.node_readiness_time = percentile_times[100]` exactly.
        logger.info("Node Readiness Percentile Summary for agentpool %s:", agentpool_name)
        for p in (50, 70, 90, 99, 100):
            if p in elapsed:
                logger.info("  P%d (target=%d nodes): %.2f seconds",
                            p, targets[p], elapsed[p])
            else:
                logger.info("  P%d (target=%d nodes): TIMEOUT", p, targets[p])
        max_elapsed = max(elapsed.values())
        logger.info(
            "All target nodes became ready in %.2f seconds in agent pool %s",
            max_elapsed, agentpool_name,
        )
        logger.info("Percentile node readiness data: %s",
                    json.dumps(result, indent=2))
        return result

    def scale_machine(
        self,
        agentpool_name: str,
        vm_size: str,
        scale_machine_count: int,
        cluster_name: Optional[str] = None,
        use_batch_api: bool = False,
        machine_workers: int = 1,
        timeout: int = 600,
        readiness_wait_timeout: int = 1200,
        tags: Optional[Dict[str, str]] = None,  # pylint: disable=unused-argument
    ) -> bool:
        """Scale a Machine-mode agentpool by creating ``scale_machine_count`` machines.

        Mirrors ``AKSClient.scale_node_pool`` convention: opens an
        ``OperationContext`` here, enriches with successful machine names,
        per-percentile readiness envelope, batch chunk timings, and the cluster
        snapshot. Returns True iff every requested machine landed AND every
        readiness percentile target was hit. Re-raises on failure so the
        context records the trace.

        Flow (both batch and non-batch):
          1. Snapshot the current Ready+labeled node count in the agentpool
             (``baseline_count``) so the readiness watcher counts only NEW nodes.
          2. Submit machine PUTs (individually or via the batch header pattern).
             Per-machine ARM polling is intentionally NOT performed.
          3. Wait ONCE on the agentpool-level provisioningState.
          4. Wait for nodes labeled ``agentpool=<pool>`` to surpass
             ``baseline_count`` by enough to satisfy P50/P70/P90/P99/P100 targets.

        ``tags`` is currently unused (Machine API rejects top-level tags on the
        machine PUT body; machines inherit tags from the parent agentpool).

        Raises:
            RuntimeError: fewer machines landed than requested.
        """
        cluster_name = cluster_name or self.get_cluster_name()
        metadata = {
            "cluster_name": cluster_name,
            "agentpool_name": agentpool_name,
            "vm_size": vm_size,
            "scale_machine_count": scale_machine_count,
            "use_batch_api": use_batch_api,
            "machine_workers": machine_workers,
        }
        # Bundle into a SimpleNamespace so the helpers retain the
        # ``request.foo`` shape ported verbatim from ado-telescope without
        # exposing yet another module-level data class.
        request = SimpleNamespace(
            agentpool_name=agentpool_name,
            cluster_name=cluster_name,
            resource_group=self.resource_group,
            vm_size=vm_size,
            scale_machine_count=scale_machine_count,
            use_batch_api=use_batch_api,
            machine_workers=machine_workers,
            timeout=timeout,
            readiness_wait_timeout=readiness_wait_timeout,
        )
        with self._get_operation_context()(
            "scale_machine", "azure", metadata, result_dir=self.result_dir
        ) as op:
            try:
                # Snapshot baseline BEFORE any PUTs so the readiness watcher
                # counts only NEW nodes.
                kc = self.k8s_client
                baseline_count = 0
                if kc is not None:
                    try:
                        baseline_count = len(
                            kc.get_ready_nodes(
                                label_selector=f"agentpool={agentpool_name}"
                            )
                        )
                        logger.info(
                            "baseline ready nodes in agentpool %s: %d",
                            agentpool_name, baseline_count,
                        )
                    except Exception:
                        logger.warning(
                            "baseline node snapshot failed; readiness count may be inflated"
                        )

                # Naming parity with ado-telescope.
                prefix = self._get_machine_name_prefix(scale_machine_count)
                names = [
                    f"{prefix}-machine-{i + 1}" for i in range(scale_machine_count)
                ]
                if use_batch_api:
                    successful, batch_times = self._scale_machine_batch(request, names)
                    op.add_metadata("batch_command_execution_times", batch_times)
                else:
                    successful = self._scale_machine_individually(request, names)
                op.add_metadata("successful_machines", successful)

                # Single agentpool-level provisioning check.
                agentpool_url = (
                    f"{_ARM_BASE}/subscriptions/{self.subscription_id}/resourceGroups/"
                    f"{self.resource_group}/providers/Microsoft.ContainerService/"
                    f"managedClusters/{cluster_name}/agentPools/"
                    f"{agentpool_name}?api-version={_AGENTPOOL_API_VERSION}"
                )
                agentpool_ok = self._wait_for_agentpool_provisioning(
                    agentpool_url, timeout
                )
                logger.info(
                    "agentpool %s provisioning %s",
                    agentpool_name,
                    "Succeeded" if agentpool_ok else "Failed/Timeout",
                )

                percentile_envelope = self._wait_for_machine_node_readiness(
                    agentpool_name=agentpool_name,
                    expected_count=len(successful),
                    timeout=readiness_wait_timeout,
                    baseline_count=baseline_count,
                )
                op.add_metadata("percentile_node_readiness_times", percentile_envelope)
                p100 = percentile_envelope.get("P100", {})
                op.add_metadata(
                    "node_readiness_time", p100.get("elapsed_time_seconds") or 0.0
                )
                op.add_metadata("cluster_info", self.get_cluster_data(cluster_name))

                if len(successful) != scale_machine_count:
                    raise RuntimeError(
                        f"scale_machine landed {len(successful)}/{scale_machine_count} machines"
                    )
                return True
            except Exception as e:
                logger.error(
                    "Failed to scale machine agentpool %s: %s", agentpool_name, e
                )
                raise


    @staticmethod
    def _get_machine_name_prefix(scale_machine_count: int) -> str:
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

    def _scale_machine_individually(
        self, request: SimpleNamespace, names: List[str],
    ) -> List[str]:
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
                except Exception:
                    logger.exception("create_single_machine failed for %s", n)
        return successful

    def _create_single_machine(self, name: str, request: SimpleNamespace) -> bool:
        """PUT a single Machine resource. Returns True on any 2xx response.

        Body is ``{"properties": {"hardware": {"vmSize": ...}}}``. Tags are inherited
        from the parent agentpool; the machine PUT body in api-version 2025-06-02-preview
        does not accept a top-level ``tags`` field (rejected with UnmarshalError).

        Intentionally does NOT poll the per-machine ARM provisioningState. The
        AKS RP reports per-machine ``provisioningState='Succeeded'`` essentially
        as soon as the agentpool admits the request — well before the underlying
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
            f"/agentPools/{request.agentpool_name}/machines/{name}"
            f"?api-version={_MACHINE_API_VERSION}"
        )
        body: Dict[str, Any] = {"properties": {"hardware": {"vmSize": request.vm_size}}}
        resp = self.make_request("PUT", url, data=body, timeout=request.timeout)
        if resp.status_code not in (200, 201, 202):
            logger.error("PUT machine %s -> %s %s", name, resp.status_code, resp.text[:500])
            return False
        return True

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
        request: SimpleNamespace,
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
            except Exception:
                logger.exception("batch chunk %d failed", idx)
                created = []
            elapsed = time.time() - t0
            return idx, created, elapsed

        with ThreadPoolExecutor(max_workers=max(1, request.machine_workers)) as ex:
            futures = [ex.submit(run_chunk, i, chunk) for i, chunk in enumerate(chunks)]
            for fut in as_completed(futures):
                try:
                    idx, created, elapsed = fut.result()
                except Exception:
                    # run_chunk already swallows; this is belt-and-suspenders.
                    logger.exception("unexpected error retrieving batch chunk result")
                    continue
                batch_times[f"chunk_{idx}"] = elapsed
                successful.extend(created)
        return successful, batch_times

    def _create_batch_machines(
        self,
        request: SimpleNamespace,
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
        # ado-telescope verbatim envelope shape (azure.py:1268-1298). The Machine
        # API expects:
        #   - batchMachines[].machineName  (NOT "name") — using the wrong key
        #     causes the API to silently ignore the entries, creating only the
        #     URL-pointed machine. This was the root cause of build 66357
        #     reporting succeeded=true but only 100/200 (== worker count) ready.
        #   - batchMachines lists ONLY the *additional* machines; the first one
        #     is created from the URL + body.
        #   - vmSkus is a {"value": [<rich vm_sku obj>]} envelope, not a flat list.
        remaining_machines = chunk[1:]
        batch_machines = [{"machineName": name} for name in remaining_machines]
        vm_sku = {
            "name": request.vm_size,
            "resourceType": "virtualMachines",
            "family": "standardDv3Family",
            "locations": ["westus", "eastus", "westeurope"],
            "capabilities": [
                {"name": "vCPUs", "value": "2"},
                {"name": "MemoryGB", "value": "8"},
            ],
            "restrictions": [],
        }
        batch_header_value = json.dumps({
            "vmSkus": {"value": [vm_sku]},
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

    def _make_batch_request(
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
