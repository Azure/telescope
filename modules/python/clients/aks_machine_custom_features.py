"""AKS Machine API custom feature helpers."""
from typing import Dict, Optional

_DISABLE_SELF_CONTAINED_VHD_FEATURE = "DisableSelfContainedVHD"
_CUSTOM_FEATURE_HEADER = "AKSHTTPCustomFeatures"


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
