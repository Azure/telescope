import base64
import json

# Complete resource profile for the OverrideControlplaneResources custom header.
schema ControlPlaneResourceOverride:
    containerName: str
    cpuLimit: str
    cpuRequest: str
    memoryLimit: str
    memoryRequest: str
    gomaxprocs: int

EncodeControlPlaneResourceOverrides = lambda overrides: [ControlPlaneResourceOverride] -> str {
    payload = json.encode(overrides)
    encoded = base64.encode(payload)
    # AKS CLI rejects '=' padding in custom-header values.
    padding = "  " if encoded.endswith("==") else " " if encoded.endswith("=") else ""
    base64.encode(payload + padding)
}
