#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CSI_DRIVER = "san.csi.azure.com"
MAX_VOLUMES_PER_SAN = 20_000
MAX_VOLUME_GROUPS_PER_SAN = 200
MAX_VOLUMES_PER_GROUP = 1_000
MAX_SANS_PER_REGION = 10
MAX_TARGET_TOTAL_VOLUMES = 120_000
MANAGED_BY_TAG = "telescopeManagedBy"
MANAGED_BY_VALUE = "elastic-san-static-scale"
CLUSTER_UID_TAG = "telescopeClusterUid"
GEOMETRY_TAG = "telescopeGeometry"
SAN_INDEX_TAG = "telescopeSanIndex"


@dataclass(frozen=True)
class ClusterInfo:
    subscription_id: str
    name: str
    resource_group: str
    node_resource_group: str
    location: str
    resource_uid: str
    subnet_ids: tuple[str, ...]


@dataclass(frozen=True)
class ManagedSan:
    name: str
    resource_group: str
    location: str
    index: int
    geometry: str
    volume_count: int


@dataclass(frozen=True)
class ShardAddition:
    san_name: str | None
    san_index: int
    current_count: int
    target_count: int

    @property
    def add_count(self) -> int:
        return self.target_count - self.current_count


def run_json(command: list[str]) -> Any:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def resolve_cluster(cluster_id: str) -> ClusterInfo:
    match = re.fullmatch(
        r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
        r"Microsoft\.ContainerService/managedClusters/([^/]+)",
        cluster_id,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"cluster_id must be a full AKS ARM resource ID: {cluster_id!r}")
    arm_subscription, resource_group, cluster_name = match.groups()
    cluster = run_json(
        [
            "az",
            "aks",
            "show",
            "--subscription",
            arm_subscription,
            "--resource-group",
            resource_group,
            "--name",
            cluster_name,
            "-o",
            "json",
        ]
    )

    subnet_ids = sorted(
        {
            pool["vnetSubnetId"]
            for pool in cluster.get("agentPoolProfiles", [])
            if pool.get("vnetSubnetId")
        }
    )
    return ClusterInfo(
        subscription_id=arm_subscription,
        name=cluster["name"],
        resource_group=cluster["resourceGroup"],
        node_resource_group=cluster["nodeResourceGroup"],
        location=cluster["location"],
        resource_uid=cluster["resourceUid"],
        subnet_ids=tuple(subnet_ids),
    )


def load_cluster_info(path: Path) -> ClusterInfo:
    payload = json.loads(path.read_text())
    required = (
        "subscription_id",
        "name",
        "resource_group",
        "node_resource_group",
        "location",
        "resource_uid",
        "subnet_ids",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"cluster info is missing fields: {', '.join(missing)}")
    return ClusterInfo(
        subscription_id=str(payload["subscription_id"]),
        name=str(payload["name"]),
        resource_group=str(payload["resource_group"]),
        node_resource_group=str(payload["node_resource_group"]),
        location=str(payload["location"]),
        resource_uid=str(payload["resource_uid"]),
        subnet_ids=tuple(str(subnet) for subnet in payload["subnet_ids"]),
    )


def stable_san_name(prefix: str, cluster_uid: str, index: int) -> str:
    normalized = re.sub(r"[^a-z0-9-]", "-", prefix.casefold()).strip("-")
    normalized = re.sub(r"-+", "-", normalized)
    digest = hashlib.sha256(cluster_uid.encode()).hexdigest()[:8]
    suffix = f"-{digest}-{index:02d}"
    max_prefix_length = 24 - len(suffix)
    normalized = normalized[:max_prefix_length].rstrip("-")
    if len(normalized) < 3:
        raise ValueError("SAN prefix must contain at least three letters or digits")
    return normalized + suffix


def geometry_key(volume_groups_per_san: int, volumes_per_group: int) -> str:
    return f"{volume_groups_per_san}x{volumes_per_group}"


def validate_geometry(volume_groups_per_san: int, volumes_per_group: int) -> int:
    if not 1 <= volume_groups_per_san <= MAX_VOLUME_GROUPS_PER_SAN:
        raise ValueError(
            f"volume_groups_per_san must be between 1 and {MAX_VOLUME_GROUPS_PER_SAN}"
        )
    if not 1 <= volumes_per_group <= MAX_VOLUMES_PER_GROUP:
        raise ValueError(
            f"volumes_per_group must be between 1 and {MAX_VOLUMES_PER_GROUP}"
        )
    capacity = volume_groups_per_san * volumes_per_group
    if capacity > MAX_VOLUMES_PER_SAN:
        raise ValueError(
            f"geometry creates {capacity} volumes per SAN, above the "
            f"{MAX_VOLUMES_PER_SAN} aggregate limit"
        )
    return capacity


def plan_shards(
    *,
    existing_total: int,
    target_total: int,
    matching_sans: Iterable[ManagedSan],
    all_managed_indexes: Iterable[int],
    shard_capacity: int,
) -> list[ShardAddition]:
    if target_total < 0 or existing_total < 0:
        raise ValueError("volume totals must be non-negative")
    if target_total < existing_total:
        raise ValueError(
            f"target total {target_total} is below the existing {existing_total} volumes; "
            "shrinking is not supported"
        )
    if target_total == existing_total:
        return []

    remaining = target_total - existing_total
    additions: list[ShardAddition] = []
    used_indexes = set(all_managed_indexes)

    for san in sorted(matching_sans, key=lambda item: item.index):
        if san.volume_count > shard_capacity:
            continue
        add_count = min(remaining, shard_capacity - san.volume_count)
        if add_count:
            additions.append(
                ShardAddition(
                    san_name=san.name,
                    san_index=san.index,
                    current_count=san.volume_count,
                    target_count=san.volume_count + add_count,
                )
            )
            remaining -= add_count
        if remaining == 0:
            return additions

    next_index = 0
    while remaining:
        while next_index in used_indexes:
            next_index += 1
        target_count = min(remaining, shard_capacity)
        additions.append(
            ShardAddition(
                san_name=None,
                san_index=next_index,
                current_count=0,
                target_count=target_count,
            )
        )
        used_indexes.add(next_index)
        remaining -= target_count

    return additions


def canonical_handle(resource_group: str, san: str, volume_group: str, volume: str) -> str:
    return "#".join((resource_group, san, volume_group, volume)).casefold()


def parse_handle(handle: str) -> tuple[str, str, str, str] | None:
    parts = handle.split("#")
    if len(parts) != 4 or not all(parts):
        return None
    return tuple(parts)  # type: ignore[return-value]


def cluster_pv_handles(kubeconfig: str | None = None) -> set[str]:
    command = ["kubectl"]
    if kubeconfig:
        command.extend(["--kubeconfig", kubeconfig])
    command.extend(["get", "pv", "-o", "json"])
    payload = run_json(command)
    return {
        csi["volumeHandle"].casefold()
        for item in payload.get("items", [])
        if (csi := item.get("spec", {}).get("csi"))
        and csi.get("driver") == CSI_DRIVER
        and csi.get("volumeHandle")
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)