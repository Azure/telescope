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


def custom_feature_headers(
    aks_http_custom_features: Optional[str],
) -> Dict[str, str]:
    """Build optional AKS custom feature headers for Machine PUT requests."""
    if not aks_http_custom_features:
        return {}
    value = aks_http_custom_features.strip()
    if not value:
        return {}
    return {_CUSTOM_FEATURE_HEADER: value}


def machine_failure_detail(machine: Dict[str, Any]) -> Dict[str, Any]:
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


def machine_name_prefix(scale_machine_count: int) -> str:
    """Generate the stable machine-name prefix for a given scale count."""
    if scale_machine_count >= 1000 and scale_machine_count % 1000 == 0:
        return f"scale{scale_machine_count // 1000}k"
    return f"scale{scale_machine_count}"


def scriptless_enabled_value(
    aks_http_custom_features: Optional[str],
) -> str:
    """Return run metadata value for scriptless bootstrap enablement."""
    if not aks_http_custom_features:
        return "yes"
    features = {
        feature.strip()
        for feature in aks_http_custom_features.split(",")
        if feature.strip()
    }
    if _DISABLE_SELF_CONTAINED_VHD_FEATURE in features:
        return "no"
    return "yes"
