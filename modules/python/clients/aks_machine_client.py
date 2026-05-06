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
from typing import Any, Dict, Optional

import requests

from clients.aks_client import AKSClient
from utils.logger_config import get_logger

logger = get_logger(__name__)

_ARM_BASE = "https://management.azure.com"
_ARM_SCOPE = "https://management.azure.com/.default"
_AGENTPOOL_API_VERSION = "2024-06-02-preview"  # per ado azure.py
_POLL_INTERVAL_SECONDS = 10


class AKSMachineClient:
    """Composes AKSClient and adds Machine-API-specific REST plumbing."""

    def __init__(
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
        return self.aks_client.get_cluster_name()

    def get_cluster_data(self, cluster_name: str) -> Dict:
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
