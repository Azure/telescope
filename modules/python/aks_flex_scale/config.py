"""Configuration loading and validation for the Flex scale test."""

from __future__ import annotations

import ipaddress
import json
import math
import re
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "nodeCount": 1000,
    "maxPods": 110,
    "joinTimeoutSeconds": 3600,
    "bootstrapMode": "local-config",
    "vmCreateConcurrency": 50,
    "vmCreateBatchSize": 100,
    "vmBatchDeploymentConcurrency": 2,
    "pollIntervalSeconds": 5,
    "joinNoProgressTimeoutSeconds": 300,
    "vmPrepareNoProgressTimeoutSeconds": 300,
    "workloadValidationTimeoutSeconds": 600,
    "cleanupTimeoutSeconds": 3600,
    "aksRegion": "eastus2",
    "vmRegion": "centralus",
    "aksNodeVmSize": "Standard_D4s_v5",
    "aksSystemPoolName": "systempool",
    "agentPoolName": "flexnodes",
    "vmAdminUser": "azureuser",
    "vmImage": "Canonical:ubuntu-24_04-lts:server:latest",
    "vmOsDiskSizeGb": 32,
    "aksVnetCidr": "10.64.0.0/16",
    "aksSubnetCidr": "10.64.0.0/20",
    "flexVnetCidr": "10.65.0.0/16",
    "flexSubnetCidr": "10.65.0.0/20",
    "serviceCidr": "10.66.0.0/16",
    "dnsServiceIp": "10.66.0.10",
    "aksPodCidr": "10.67.0.0/16",
    "flexPodCidr": "10.68.0.0/15",
    "aksVnetName": "aks-vnet",
    "aksSubnetName": "aks-subnet",
    "flexVnetName": "flex-vnet",
    "flexSubnetName": "flex-subnet",
    "sharedIdentityName": "flex-scale-mi",
    "managedClusterApiVersion": "2026-01-02-preview",
    "bootstrapDataApiVersion": "2026-05-02-preview",
    "centralArtifactsEndpoint": "https://unbounded-azure-mirror-ejd3aeefdrhncchk.b01.azurefd.net",
    "bootstrapRootfsName": "rootfs-agent-ubuntu2404-v20260619.oci.tar.gz",
    "bootstrapScriptRepository": "Azure/AKSFlexNode",
    "unboundedRepository": "Azure/unbounded",
    "retainOnFailure": False,
    "hostValidation": False,
}

REQUIRED = ("subscriptionId", "flexVmSize")


def load_config(path: str | Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be an object")
    config = {**DEFAULTS, **raw, **(overrides or {})}
    validate_config(config)
    return config


def required_prefix(node_count: int, max_pods: int) -> int:
    """Return the smallest IPv4 prefix able to hold node_count * max_pods."""
    required = node_count * max_pods
    return 32 - math.ceil(math.log2(required)) if required > 1 else 32


def validate_config(config: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED if not str(config.get(key, "")).strip()]
    if missing:
        raise ValueError(f"missing required configuration: {', '.join(missing)}")
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
                        str(config["subscriptionId"])):
        raise ValueError("subscriptionId must be a UUID")

    for key in ("nodeCount", "maxPods", "joinTimeoutSeconds", "vmCreateConcurrency", "vmCreateBatchSize",
                "vmBatchDeploymentConcurrency", "joinNoProgressTimeoutSeconds",
                "vmPrepareNoProgressTimeoutSeconds", "workloadValidationTimeoutSeconds",
                "cleanupTimeoutSeconds"):
        if not isinstance(config.get(key), int) or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if config["joinTimeoutSeconds"] > 3600:
        raise ValueError("joinTimeoutSeconds must not exceed the current one-hour cap")
    if config["nodeCount"] > 1000:
        raise ValueError("nodeCount must not exceed the current 1,000-node target")
    if config["maxPods"] != 110:
        raise ValueError("this scenario currently requires maxPods=110")
    if config.get("bootstrapMode") not in {"local-config", "rp"}:
        raise ValueError("bootstrapMode must be local-config or rp")

    cidr_keys = ("aksVnetCidr", "aksSubnetCidr", "flexVnetCidr", "flexSubnetCidr",
                 "serviceCidr", "aksPodCidr", "flexPodCidr")
    networks: dict[str, ipaddress.IPv4Network] = {}
    for key in cidr_keys:
        value = ipaddress.ip_network(str(config[key]), strict=True)
        if not isinstance(value, ipaddress.IPv4Network):
            raise ValueError(f"{key} must be IPv4")
        networks[key] = value
    if not networks["aksSubnetCidr"].subnet_of(networks["aksVnetCidr"]):
        raise ValueError("aksSubnetCidr must be inside aksVnetCidr")
    if not networks["flexSubnetCidr"].subnet_of(networks["flexVnetCidr"]):
        raise ValueError("flexSubnetCidr must be inside flexVnetCidr")
    # Azure reserves five subnet addresses. Keep 10% headroom above the requested fleet.
    usable = networks["flexSubnetCidr"].num_addresses - 5
    if usable < math.ceil(config["nodeCount"] * 1.1):
        raise ValueError(f"flexSubnetCidr has {usable} usable addresses; at least 10% headroom is required")
    pod_capacity = networks["flexPodCidr"].num_addresses
    required_pods = config["nodeCount"] * config["maxPods"]
    if pod_capacity < required_pods:
        raise ValueError(f"flexPodCidr has {pod_capacity} addresses but {required_pods} are required")

    independent = ("aksVnetCidr", "flexVnetCidr", "serviceCidr", "aksPodCidr", "flexPodCidr")
    for index, left in enumerate(independent):
        for right in independent[index + 1:]:
            if networks[left].overlaps(networks[right]):
                raise ValueError(f"{left} overlaps {right}")
    if ipaddress.ip_address(str(config["dnsServiceIp"])) not in networks["serviceCidr"]:
        raise ValueError("dnsServiceIp must be inside serviceCidr")
    if config["aksSystemPoolName"] == config["agentPoolName"]:
        raise ValueError("managed system and FlexNodes pool names must differ")
    gate_container = str(config.get("gateContainer", ""))
    if gate_container.lower() == "$web":
        raise ValueError("the static website $web container is forbidden")


def node_names(config: dict[str, Any]) -> list[str]:
    width = max(4, len(str(config["nodeCount"] - 1)))
    prefix = str(config.get("nodeNamePrefix", "flex-scale"))
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,43}[a-z0-9])?", prefix):
        raise ValueError("nodeNamePrefix must be a lowercase Kubernetes-safe prefix up to 45 characters")
    return [f"{prefix}-{index:0{width}d}" for index in range(config["nodeCount"])]
