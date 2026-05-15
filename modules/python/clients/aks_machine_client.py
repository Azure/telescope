"""AKS Machine API client.

Subclasses ``AKSClient`` to inherit auth, ContainerServiceClient,
KubernetesClient, ``get_cluster_name``, ``get_cluster_data``, and the existing
node-pool CRUD methods. Adds raw REST methods for the Machine API which is not
yet exposed in the Azure SDK.

Public methods (``create_machine_agentpool``, ``scale_machine``) wrap their work
in ``OperationContext``: the context is opened inside the client method,
metadata is enriched with ``op.add_metadata`` along the way, success returns
True, failures are logged and re-raised so ``OperationContext`` records them.
``MachineCRUD`` therefore stays a thin try/except wrapper.

This is the scaffolding revision: ``create_machine_agentpool`` and the
agentpool provisioning poll are fully implemented; ``scale_machine``, its
private helpers, and the ``_get_machine_name_prefix`` naming helper raise
``NotImplementedError`` and will land in a follow-up PR.
"""
import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

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
_POLL_INTERVAL_SECONDS = 10
# Per-request HTTP timeout is capped so that a single slow PUT/GET cannot
# consume the caller's whole ``timeout`` budget before the polling loop starts.
# The remaining budget is reserved for ``_wait_for_agentpool_provisioning``.
_PER_REQUEST_TIMEOUT_CAP = 60


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
        # Pool TCP/TLS across calls. ``requests.Session`` is thread-safe for
        # sending requests (each request creates its own urllib3 connection
        # from the shared pool), so this is safe for the planned parallel
        # scale path landing in PR-2.
        self._session = requests.Session()

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

        Uses ``self._session`` for connection pooling so TCP/TLS handshakes
        are reused across polls and the planned parallel scale path.
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
        agentpool_name: str,
        vm_size: str,
        cluster_name: Optional[str] = None,
        timeout: int = 300,
    ) -> None:
        """Convert an existing agentpool to Machines mode via PUT.

        Opens an ``OperationContext`` here, enriches metadata, returns on
        success, re-raises on failure (so the context records ``success=False``
        with traceback before the exception propagates to ``MachineCRUD``).

        Args:
            agentpool_name: Target agentpool name.
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
                        f"agentpool {agentpool_name} did not reach Succeeded within {timeout}s"
                    )
                op.add_metadata("agentpool_info", self.get_node_pool(
                    agentpool_name, cluster_name).as_dict())
                op.add_metadata("cluster_info", self.get_cluster_data(cluster_name))
            except Exception as e:
                logger.error(f"Failed to create machine agentpool {agentpool_name}: {e}")
                raise

    def _wait_for_agentpool_provisioning(self, url: str, timeout: int) -> bool:
        """Poll the agentpool URL until provisioningState is terminal.

        Polls every ``_POLL_INTERVAL_SECONDS`` (10s) using a 30s per-request HTTP
        timeout. Returns True on 'Succeeded'. Returns False on 'Failed' or when
        ``timeout`` seconds have elapsed since invocation. 4xx GETs are raised
        immediately (e.g. 404 'agentpool not found', 401/403) since retrying
        won't change the outcome; 5xx and other transient failures are logged
        and retried until the deadline. Missing ``provisioningState`` (which
        ARM can transiently omit right after PUT acceptance) is tolerated for
        the first half of ``timeout`` and then treated as Failed; this avoids
        false negatives on slower control planes without infinite patience.
        """
        start = time.time()
        deadline = start + timeout
        none_grace_deadline = start + timeout / 2
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
            if state is None and time.time() >= none_grace_deadline:
                logger.warning(
                    f"agentpool provisioningState absent after "
                    f"{time.time() - start:.0f}s (past half-budget grace); "
                    f"treating as Failed."
                )
                return False
            time.sleep(_POLL_INTERVAL_SECONDS)
        logger.error(f"agentpool provisioning timed out after {timeout}s")
        return False

    # ---- scale path: stubbed on this scaffolding PR ----
    # The methods below preserve the public/private signatures so that
    # ``MachineCRUD`` can be wired up against them in a follow-up PR; each
    # raises ``NotImplementedError`` until the implementation lands.

    def _wait_for_machine_node_readiness(
        self,
        agentpool_name: str,
        expected_count: int,
        timeout: int,
        baseline_count: int = 0,
    ) -> Dict[str, Dict[str, Any]]:
        """Wait for ``expected_count`` NEW Ready nodes; return percentile dict.

        Stubbed in this PR; implementation lands in a follow-up.
        """
        raise NotImplementedError(
            "_wait_for_machine_node_readiness lands in a follow-up PR"
        )

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

        Stubbed in this PR; implementation lands in a follow-up.
        """
        raise NotImplementedError(
            "scale_machine lands in a follow-up PR"
        )

    @staticmethod
    def _get_machine_name_prefix(scale_machine_count: int) -> str:
        """Generate the machine-name prefix for a given scale count.

        Stubbed in this PR; implementation lands in a follow-up alongside the
        scale path that consumes it.
        """
        raise NotImplementedError(
            "_get_machine_name_prefix lands in a follow-up PR"
        )
