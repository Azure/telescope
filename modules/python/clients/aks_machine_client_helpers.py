"""Stateless helpers for the AKS Machine API client."""
from typing import Any, Dict, Optional

_DISABLE_SELF_CONTAINED_VHD_FEATURE = "DisableSelfContainedVHD"
_CUSTOM_FEATURE_HEADER = "AKSHTTPCustomFeatures"


def build_readiness_envelope(
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


def build_custom_feature_headers(
    aks_http_custom_features: Optional[str],
) -> Dict[str, str]:
    """Build optional AKS custom feature headers for Machine PUT requests."""
    if not aks_http_custom_features:
        return {}
    value = aks_http_custom_features.strip()
    if not value:
        return {}
    return {_CUSTOM_FEATURE_HEADER: value}


def get_machine_failure_detail(machine: Dict[str, Any]) -> Dict[str, Any]:
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


def get_machine_name_prefix(scale_machine_count: int) -> str:
    """Generate the stable machine-name prefix for a given scale count."""
    if scale_machine_count >= 1000 and scale_machine_count % 1000 == 0:
        return f"scale{scale_machine_count // 1000}k"
    return f"scale{scale_machine_count}"


def is_scriptless_enabled(
    aks_http_custom_features: Optional[str],
) -> bool:
    """Return whether scriptless bootstrap is enabled for the run."""
    if not aks_http_custom_features:
        return True
    features = {
        feature.strip()
        for feature in aks_http_custom_features.split(",")
        if feature.strip()
    }
    return _DISABLE_SELF_CONTAINED_VHD_FEATURE not in features
