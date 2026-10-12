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
    # AKS CLI rejects '=' padding in custom-header values.
    remainder = len(payload) % 3
    padding = "  " if remainder == 1 else " " if remainder == 2 else ""
    base64.encode(payload + padding)
}
