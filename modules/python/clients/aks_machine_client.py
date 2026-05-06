"""AKS Machine API client.

Composes the existing AKSClient (auth, ContainerServiceClient, KubernetesClient,
get_cluster_name, get_cluster_data) and adds raw REST methods for the Machine API
which is not exposed in the Azure SDK.

Ported from ado-telescope/modules/python/k8s/cloud_providers/azure.py with bug fixes:
- Truthful type hints (cloud_data Dict, not str).
- No mutation of input config.
- UTC timestamps.
"""
from typing import Any, Dict, Optional

import requests

from clients.aks_client import AKSClient
from utils.logger_config import get_logger

logger = get_logger(__name__)

_ARM_BASE = "https://management.azure.com"
_ARM_SCOPE = "https://management.azure.com/.default"


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
