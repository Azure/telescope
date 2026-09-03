#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import re
import subprocess
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

from esan_common import (
    CLUSTER_UID_TAG,
    GEOMETRY_TAG,
    MANAGED_BY_TAG,
    MANAGED_BY_VALUE,
    MAX_SANS_PER_REGION,
    MAX_TARGET_TOTAL_VOLUMES,
    SAN_INDEX_TAG,
    ManagedSan,
    canonical_handle,
    cluster_pv_handles,
    geometry_key,
    load_cluster_info,
    plan_shards,
    resolve_cluster,
    stable_san_name,
    validate_geometry,
    write_json,
)


API_VERSION = "2023-01-01"
ARM_ENDPOINT = "https://management.azure.com"
MAX_SUBSCRIPTION_WRITES_PER_HOUR = 3_600
MAX_WRITES_PER_BURST = 20
BURST_WINDOW_SECONDS = 1.1
# List/read throttles (e.g. List_ObservationWindow_00:05:00) need retries that outlast a 5-min window.
READ_RETRY_ATTEMPTS = 24
WRITE_RETRY_ATTEMPTS = 8
# Keep LIST operations under SanRP's empirical ~100-lists-per-5-min observation window.
LIST_RATE_LIMIT = 90
LIST_RATE_WINDOW_SECONDS = 300


@dataclass
class SanInventory:
    san: ManagedSan
    resource_id: str
    tags: dict[str, str]
    resource: dict[str, Any]
    group_resources: dict[str, dict[str, Any]]
    groups: dict[str, list[dict[str, Any]]]

    @property
    def handles(self) -> set[str]:
        return {
            canonical_handle(self.san.resource_group, self.san.name, group, volume["name"])
            for group, volumes in self.groups.items()
            for volume in volumes
        }


class ArmError(RuntimeError):
    def __init__(self, status: int, method: str, url: str, body: str):
        super().__init__(f"ARM {method} {url} returned {status}: {body[:500]}")
        self.status = status
        self.body = body


class ArmClient:
    def __init__(self, subscription_id: str, api_version: str = API_VERSION):
        self.subscription_id = subscription_id
        self.api_version = api_version
        self._token = ""
        self._token_time = 0.0
        self._token_lock = asyncio.Lock()
        self.session: aiohttp.ClientSession | None = None
        self.read_limiter: "ReadRateLimiter | None" = None

    async def __aenter__(self) -> "ArmClient":
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=500, ttl_dns_cache=300),
            timeout=aiohttp.ClientTimeout(total=900),
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.session:
            await self.session.close()

    async def _access_token(self) -> str:
        async with self._token_lock:
            if self._token and time.monotonic() - self._token_time < 2_700:
                return self._token

            def get_token() -> str:
                completed = subprocess.run(
                    [
                        "az",
                        "account",
                        "get-access-token",
                        "--resource",
                        ARM_ENDPOINT,
                        "--query",
                        "accessToken",
                        "-o",
                        "tsv",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return completed.stdout.strip()

            self._token = await asyncio.to_thread(get_token)
            self._token_time = time.monotonic()
            return self._token

    def url(self, resource_id: str) -> str:
        separator = "&" if "?" in resource_id else "?"
        return f"{ARM_ENDPOINT}{resource_id}{separator}api-version={self.api_version}"

    async def request(
        self,
        method: str,
        resource_id_or_url: str,
        payload: dict[str, Any] | None = None,
        *,
        retry_reads: bool = True,
        retry_limiter: HourlyWriteLimiter | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        if not self.session:
            raise RuntimeError("ArmClient must be used as an async context manager")
        url = (
            resource_id_or_url
            if resource_id_or_url.startswith("https://")
            else self.url(resource_id_or_url)
        )
        method = method.upper()
        if method == "GET" and retry_reads:
            attempts = READ_RETRY_ATTEMPTS
        elif retry_limiter is not None:
            attempts = WRITE_RETRY_ATTEMPTS
        else:
            attempts = 1
        for attempt in range(attempts):
            token = await self._access_token()
            async with self.session.request(
                method,
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                text = await response.text()
                headers = {key.casefold(): value for key, value in response.headers.items()}
                if 200 <= response.status < 300:
                    try:
                        body = json.loads(text) if text else {}
                    except json.JSONDecodeError as error:
                        raise ArmError(response.status, method, url, text) from error
                    return response.status, body, headers
                if response.status in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                    try:
                        delay = float(headers["retry-after"])
                    except (KeyError, ValueError):
                        try:
                            delay = float(headers["x-ms-retry-after-ms"]) / 1_000
                        except (KeyError, ValueError):
                            delay = min(2**attempt, 30)
                    print(
                        f"[arm-retry] {method} status={response.status} "
                        f"attempt={attempt + 1}/{attempts} delay={delay:.3f}s",
                        flush=True,
                    )
                    await asyncio.sleep(delay)
                    if retry_limiter is not None:
                        await retry_limiter.acquire(1)
                    continue
                raise ArmError(response.status, method, url, text)
        raise AssertionError("unreachable")

    async def list_all(self, resource_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = self.url(resource_id)
        while next_url:
            if self.read_limiter is not None:
                await self.read_limiter.acquire()
            _, page, _ = await self.request("GET", next_url)
            items.extend(page.get("value", []))
            next_url = page.get("nextLink")
        return items


class ReadRateLimiter:
    """Paces LIST operations under SanRP's List observation window (sliding window)."""

    def __init__(
        self,
        limit: int = LIST_RATE_LIMIT,
        window_seconds: int = LIST_RATE_WINDOW_SECONDS,
    ):
        if limit < 1 or window_seconds <= 0:
            raise ValueError("read limit and window must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._clock = time.monotonic
        self._sleep = asyncio.sleep

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                cutoff = now - self.window_seconds
                while self.timestamps and self.timestamps[0] <= cutoff:
                    self.timestamps.popleft()
                if len(self.timestamps) < self.limit:
                    self.timestamps.append(now)
                    return
                await self._sleep(max(self.timestamps[0] + self.window_seconds - now, 0.0))


class HourlyWriteLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: int = 3_610,
        burst_limit: int = MAX_WRITES_PER_BURST,
        burst_window_seconds: float = BURST_WINDOW_SECONDS,
    ):
        if (
            limit < 1
            or window_seconds < 1
            or burst_limit < 1
            or burst_window_seconds <= 0
        ):
            raise ValueError(
                "write limit, write windows, and burst limit must be positive"
            )
        self.limit = limit
        self.window_seconds = window_seconds
        self.burst_limit = burst_limit
        self.burst_window_seconds = burst_window_seconds
        self.timestamps: deque[float] = deque()
        self.burst_timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._clock = time.monotonic
        self._sleep = asyncio.sleep

    async def acquire(self, count: int) -> None:
        if count > self.limit or count > self.burst_limit:
            raise ValueError(
                f"batch of {count} exceeds hourly limit {self.limit} "
                f"or burst limit {self.burst_limit}"
            )
        async with self._lock:
            while True:
                now = self._clock()
                while self.timestamps and now - self.timestamps[0] >= self.window_seconds:
                    self.timestamps.popleft()
                while (
                    self.burst_timestamps
                    and now - self.burst_timestamps[0] >= self.burst_window_seconds
                ):
                    self.burst_timestamps.popleft()

                hourly_blocked = len(self.timestamps) + count > self.limit
                burst_blocked = len(self.burst_timestamps) + count > self.burst_limit
                if not hourly_blocked and not burst_blocked:
                    self.timestamps.extend([now] * count)
                    self.burst_timestamps.extend([now] * count)
                    return

                waits = []
                if hourly_blocked:
                    waits.append(self.window_seconds - (now - self.timestamps[0]) + 1)
                if burst_blocked:
                    waits.append(
                        self.burst_window_seconds - (now - self.burst_timestamps[0])
                    )
                wait_seconds = max(waits)
                print(
                    f"[rate-limit] hourly={len(self.timestamps)}/{self.limit} "
                    f"burst={len(self.burst_timestamps)}/{self.burst_limit}; "
                    f"waiting {wait_seconds:.3f}s",
                    flush=True,
                )
                await self._sleep(wait_seconds)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resource_group_from_id(resource_id: str) -> str:
    match = re.search(r"/resourceGroups/([^/]+)", resource_id, re.IGNORECASE)
    if not match:
        raise ValueError(f"resource group not found in {resource_id}")
    return match.group(1)


def tag_value(tags: dict[str, Any] | None, key: str, default: str = "") -> str:
    for tag_key, value in (tags or {}).items():
        if tag_key.casefold() == key.casefold():
            return str(value)
    return default


async def inventory_san(client: ArmClient, san: dict[str, Any]) -> SanInventory:
    groups = await client.list_all(f"{san['id']}/volumeGroups")
    group_resources = {group["name"]: group for group in groups}
    group_volumes: dict[str, list[dict[str, Any]]] = {}
    for group in groups:
        group_volumes[group["name"]] = await client.list_all(f"{group['id']}/volumes")
        await asyncio.sleep(0.1)
    tags = {str(key): str(value) for key, value in (san.get("tags") or {}).items()}
    return SanInventory(
        san=ManagedSan(
            name=san["name"],
            resource_group=resource_group_from_id(san["id"]),
            location=san["location"],
            index=int(tag_value(tags, SAN_INDEX_TAG, "-1")),
            geometry=tag_value(tags, GEOMETRY_TAG),
            volume_count=sum(len(volumes) for volumes in group_volumes.values()),
        ),
        resource_id=san["id"],
        tags=tags,
        resource=san,
        group_resources=group_resources,
        groups=group_volumes,
    )


async def inventory_managed_sans(
    client: ArmClient,
    cluster_uid: str,
    sans: list[dict[str, Any]] | None = None,
) -> list[SanInventory]:
    if sans is None:
        sans = await client.list_all(
            f"/subscriptions/{client.subscription_id}/providers/Microsoft.ElasticSan/elasticSans"
        )
    managed = [
        san
        for san in sans
        if tag_value(san.get("tags"), MANAGED_BY_TAG) == MANAGED_BY_VALUE
        and tag_value(san.get("tags"), CLUSTER_UID_TAG).casefold() == cluster_uid.casefold()
    ]
    inventories: list[SanInventory] = []
    for san in managed:
        inventories.append(await inventory_san(client, san))
    return inventories


async def inventory_named_sans(
    client: ArmClient,
    names: list[str],
    sans: list[dict[str, Any]] | None = None,
) -> list[SanInventory]:
    if sans is None:
        sans = await client.list_all(
            f"/subscriptions/{client.subscription_id}/providers/Microsoft.ElasticSan/elasticSans"
        )
    wanted = {name.casefold() for name in names}
    matched = [san for san in sans if str(san.get("name", "")).casefold() in wanted]
    inventories: list[SanInventory] = []
    for san in matched:
        inventories.append(await inventory_san(client, san))
    return inventories


async def wait_succeeded(client: ArmClient, resource_id: str, timeout_seconds: int = 1_800) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        _, resource, _ = await client.request("GET", resource_id)
        state = resource.get("properties", {}).get("provisioningState")
        if state == "Succeeded":
            return
        if state in ("Failed", "Canceled"):
            raise RuntimeError(f"{resource_id} reached {state}")
        await asyncio.sleep(10)
    raise TimeoutError(f"timed out waiting for {resource_id}")


def validate_san_resource(
    resource: dict[str, Any],
    *,
    location: str,
    base_size_tib: int,
    extended_size_tib: int,
    availability_zone: str,
) -> None:
    properties = resource.get("properties", {})
    expected_zones = [availability_zone] if availability_zone else []
    checks = {
        "location": (str(resource.get("location", "")).casefold(), location.casefold()),
        "sku": (properties.get("sku", {}).get("name"), "Premium_LRS"),
        "baseSizeTiB": (properties.get("baseSizeTiB"), base_size_tib),
        "extendedCapacitySizeTiB": (
            properties.get("extendedCapacitySizeTiB", 0),
            extended_size_tib,
        ),
        "availabilityZones": (
            sorted(properties.get("availabilityZones") or []),
            expected_zones,
        ),
        "provisioningState": (properties.get("provisioningState"), "Succeeded"),
    }
    mismatches = [
        f"{key}={actual!r} (expected {expected!r})"
        for key, (actual, expected) in checks.items()
        if actual != expected
    ]
    if mismatches:
        raise RuntimeError(
            f"existing SAN {resource.get('id', resource.get('name', '<unknown>'))} "
            f"configuration mismatch: {', '.join(mismatches)}"
        )


def validate_volume_group_resource(
    resource: dict[str, Any], subnet_ids: tuple[str, ...]
) -> None:
    properties = resource.get("properties", {})
    actual_subnets = {
        str(rule.get("id", "")).casefold()
        for rule in properties.get("networkAcls", {}).get("virtualNetworkRules", [])
        if str(rule.get("action", "Allow")).casefold() == "allow"
    }
    expected_subnets = {subnet.casefold() for subnet in subnet_ids}
    mismatches = []
    if str(properties.get("provisioningState", "")).casefold() != "succeeded":
        mismatches.append(f"provisioningState={properties.get('provisioningState')!r}")
    if str(properties.get("protocolType", "")).casefold() != "iscsi":
        mismatches.append(f"protocolType={properties.get('protocolType')!r}")
    if properties.get("encryption") != "EncryptionAtRestWithPlatformKey":
        mismatches.append(f"encryption={properties.get('encryption')!r}")
    missing_subnets = sorted(expected_subnets - actual_subnets)
    if missing_subnets:
        mismatches.append(f"missing subnet ACLs={missing_subnets!r}")
    if mismatches:
        raise RuntimeError(
            f"existing volume group {resource.get('id', resource.get('name', '<unknown>'))} "
            f"configuration mismatch: {', '.join(mismatches)}"
        )


def validate_managed_inventory(
    inventory: SanInventory,
    *,
    location: str,
    base_size_tib: int,
    extended_size_tib: int,
    availability_zone: str,
    subnet_ids: tuple[str, ...],
) -> None:
    validate_san_resource(
        inventory.resource,
        location=location,
        base_size_tib=base_size_tib,
        extended_size_tib=extended_size_tib,
        availability_zone=availability_zone,
    )
    for group in inventory.group_resources.values():
        validate_volume_group_resource(group, subnet_ids)


async def ensure_san(
    client: ArmClient,
    limiter: HourlyWriteLimiter,
    *,
    resource_group: str,
    name: str,
    location: str,
    base_size_tib: int,
    extended_size_tib: int,
    availability_zone: str,
    tags: dict[str, str],
) -> str:
    resource_id = (
        f"/subscriptions/{client.subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.ElasticSan/elasticSans/{quote(name)}"
    )
    payload = {
        "location": location,
        "tags": tags,
        "properties": {
            "sku": {"name": "Premium_LRS", "tier": "Premium"},
            "baseSizeTiB": base_size_tib,
            "extendedCapacitySizeTiB": extended_size_tib,
        },
    }
    if availability_zone:
        payload["properties"]["availabilityZones"] = [availability_zone]
    try:
        _, existing, _ = await client.request("GET", resource_id)
    except ArmError as error:
        if error.status != 404:
            raise
    else:
        existing_tags = existing.get("tags", {})
        if any(tag_value(existing_tags, key) != value for key, value in tags.items()):
            raise RuntimeError(
                f"refusing to update existing unmanaged or mismatched SAN {resource_id}"
            )
        await wait_succeeded(client, resource_id)
        _, existing, _ = await client.request("GET", resource_id)
        validate_san_resource(
            existing,
            location=location,
            base_size_tib=base_size_tib,
            extended_size_tib=extended_size_tib,
            availability_zone=availability_zone,
        )
        return resource_id
    print(f"[san] creating {name} at {utc_now()}", flush=True)
    await limiter.acquire(1)
    await client.request(
        "PUT",
        resource_id,
        payload,
        retry_reads=False,
        retry_limiter=limiter,
    )
    await wait_succeeded(client, resource_id)
    return resource_id


async def ensure_volume_group(
    client: ArmClient,
    limiter: HourlyWriteLimiter,
    *,
    san_id: str,
    name: str,
    subnet_ids: tuple[str, ...],
) -> str:
    resource_id = f"{san_id}/volumeGroups/{quote(name)}"
    properties: dict[str, Any] = {
        "protocolType": "iSCSI",
        "encryption": "EncryptionAtRestWithPlatformKey",
    }
    if subnet_ids:
        properties["networkAcls"] = {
            "virtualNetworkRules": [{"id": subnet, "action": "Allow"} for subnet in subnet_ids]
        }
    await limiter.acquire(1)
    await client.request(
        "PUT",
        resource_id,
        {"properties": properties},
        retry_reads=False,
        retry_limiter=limiter,
    )
    await wait_succeeded(client, resource_id)
    return resource_id


def desired_volume_specs(
    *,
    target_count: int,
    volumes_per_group: int,
    existing_names: set[tuple[str, str]],
    add_count: int,
) -> list[tuple[str, str]]:
    missing: list[tuple[str, str]] = []
    ordinal = 0
    while len(missing) < add_count:
        if ordinal >= target_count:
            raise RuntimeError("could not allocate deterministic volume names")
        group = f"vg-{ordinal // volumes_per_group:03d}"
        volume = f"vol-{ordinal % volumes_per_group:04d}"
        if (group, volume) not in existing_names:
            missing.append((group, volume))
        ordinal += 1
    return missing


async def submit_volumes(
    client: ArmClient,
    *,
    san_id: str,
    specs: list[tuple[str, str]],
    volume_size_gib: int,
    batch_size: int,
    batch_delay_seconds: float,
    limiter: HourlyWriteLimiter,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    accepted: list[tuple[str, str]] = []
    errors: list[dict[str, Any]] = []
    by_group: dict[str, list[str]] = defaultdict(list)
    for group, volume in specs:
        by_group[group].append(volume)

    async def create(group: str, volume: str) -> None:
        resource_id = f"{san_id}/volumeGroups/{quote(group)}/volumes/{quote(volume)}"
        try:
            await limiter.acquire(1)
            status, _, _ = await client.request(
                "PUT",
                resource_id,
                {"properties": {"sizeGiB": volume_size_gib}},
                retry_reads=False,
                retry_limiter=limiter,
            )
            accepted.append((group, volume))
            if status not in (200, 201, 202):
                print(f"[volume-submit] {group}/{volume} status={status}", flush=True)
        except Exception as error:  # submission errors are benchmark output
            errors.append({"group": group, "volume": volume, "error": str(error)})
            print(f"[volume-submit-error] {group}/{volume}: {error}", flush=True)

    for group in sorted(by_group):
        volumes = sorted(by_group[group])
        for start in range(0, len(volumes), batch_size):
            batch = volumes[start : start + batch_size]
            print(
                f"[batch] {group} {start // batch_size + 1}: submitting {len(batch)} at {utc_now()}",
                flush=True,
            )
            await asyncio.gather(*(create(group, volume) for volume in batch))
            print(
                f"[batch] {group} {start // batch_size + 1}: "
                f"accepted={len(accepted)} errors={len(errors)}",
                flush=True,
            )
            if start + batch_size < len(volumes):
                await asyncio.sleep(batch_delay_seconds)
    return accepted, errors


async def validate_volumes(
    client: ArmClient,
    *,
    san_id: str,
    expected: list[tuple[str, str]],
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    expected_by_group: dict[str, set[str]] = defaultdict(set)
    for group, volume in expected:
        expected_by_group[group].add(volume)
    deadline = time.monotonic() + timeout_seconds
    observed: dict[tuple[str, str], dict[str, Any]] = {}
    pending_groups = set(expected_by_group)

    while pending_groups and time.monotonic() < deadline:
        for group in list(pending_groups):
            names = expected_by_group[group]
            volumes = await client.list_all(f"{san_id}/volumeGroups/{quote(group)}/volumes")
            for volume in volumes:
                if volume["name"] in names:
                    observed[(group, volume["name"])] = volume
            states = [
                observed.get((group, name), {}).get("properties", {}).get("provisioningState")
                for name in names
            ]
            if all(state in ("Succeeded", "Failed") for state in states):
                pending_groups.remove(group)
            await asyncio.sleep(0.2)
        if not pending_groups:
            continue
        terminal = sum(
            volume.get("properties", {}).get("provisioningState") in ("Succeeded", "Failed")
            for volume in observed.values()
        )
        print(
            f"[validate] terminal={terminal}/{len(expected)} "
            f"pending-vgs={len(pending_groups)} at {utc_now()}",
            flush=True,
        )
        await asyncio.sleep(20)

    records: list[dict[str, Any]] = []
    for group, volume in expected:
        item = observed.get((group, volume))
        records.append(
            {
                "group": group,
                "volume": volume,
                "state": (
                    item.get("properties", {}).get("provisioningState", "Unknown")
                    if item
                    else "Missing"
                ),
                "resource_id": item.get("id", "") if item else "",
            }
        )
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision static Elastic SAN volumes")
    cluster = parser.add_mutually_exclusive_group(required=True)
    cluster.add_argument("--cluster-id", help="Full AKS ARM resource ID")
    cluster.add_argument("--cluster-info", type=Path, help="Resolved cluster JSON from the pipeline")
    parser.add_argument("--san-prefix", default="tel-esan")
    parser.add_argument("--target-total-volumes", type=int, required=True)
    parser.add_argument("--volume-groups-per-san", type=int, default=200)
    parser.add_argument("--volumes-per-group", type=int, default=100)
    parser.add_argument("--volume-size-gib", type=int, default=1)
    parser.add_argument("--base-size-tib", type=int, default=3)
    parser.add_argument("--extended-size-tib", type=int, default=17)
    parser.add_argument("--availability-zone", default="")
    parser.add_argument("--subnet-id", action="append", default=[])
    parser.add_argument("--max-volume-writes-per-hour", type=int, default=3_000)
    parser.add_argument(
        "--max-volume-writes-per-burst", type=int, default=MAX_WRITES_PER_BURST
    )
    parser.add_argument(
        "--burst-window-seconds", type=float, default=BURST_WINDOW_SECONDS
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--batch-delay-seconds", type=float, default=1.0)
    parser.add_argument("--validation-timeout-seconds", type=int, default=1_800)
    parser.add_argument("--not-before-utc", default="")
    parser.add_argument("--kubeconfig", default="")
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def aggregate_records(records: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[tuple(str(record[key]) for key in keys)].append(record)
    aggregates = []
    for group_key, group_records in sorted(grouped.items()):
        succeeded = sum(record["state"] == "Succeeded" for record in group_records)
        failed = sum(record["state"] == "Failed" for record in group_records)
        total = len(group_records)
        aggregates.append(
            {
                **dict(zip(keys, group_key, strict=True)),
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "missing_or_nonterminal": total - succeeded - failed,
                "success_rate": round(succeeded / total, 6) if total else 1.0,
            }
        )
    return aggregates


async def async_main(args: argparse.Namespace) -> int:
    shard_capacity = validate_geometry(args.volume_groups_per_san, args.volumes_per_group)
    if args.target_total_volumes < 0 or args.volume_size_gib < 1:
        raise ValueError("target and volume size must be non-negative/positive")
    if args.target_total_volumes > MAX_TARGET_TOTAL_VOLUMES:
        raise ValueError(
            f"target_total_volumes exceeds the supported {MAX_TARGET_TOTAL_VOLUMES} target"
        )
    if args.base_size_tib < 1 or args.extended_size_tib < 0:
        raise ValueError("SAN capacity must have positive base and non-negative extended TiB")
    total_capacity_gib = (args.base_size_tib + args.extended_size_tib) * 1_024
    if shard_capacity * args.volume_size_gib > total_capacity_gib:
        raise ValueError(
            f"geometry needs {shard_capacity * args.volume_size_gib} GiB per SAN, "
            f"but configured capacity is {total_capacity_gib} GiB"
        )
    if args.batch_size < 1:
        raise ValueError("batch size must be positive")

    cluster = (
        load_cluster_info(args.cluster_info)
        if args.cluster_info
        else resolve_cluster(args.cluster_id)
    )
    resource_group = cluster.node_resource_group
    subnet_ids = tuple(sorted(set(args.subnet_id) | set(cluster.subnet_ids)))
    pv_handles = cluster_pv_handles(args.kubeconfig or None)
    geometry = geometry_key(args.volume_groups_per_san, args.volumes_per_group)

    async with ArmClient(cluster.subscription_id) as client:
        subscription_sans = await client.list_all(
            f"/subscriptions/{client.subscription_id}/providers/Microsoft.ElasticSan/elasticSans"
        )
        inventories = await inventory_managed_sans(
            client, cluster.resource_uid, subscription_sans
        )
        mismatched_geometries = sorted(
            {inventory.san.geometry for inventory in inventories if inventory.san.geometry != geometry}
        )
        if mismatched_geometries:
            raise RuntimeError(
                f"cluster already has managed SAN geometry {mismatched_geometries}; "
                f"requested {geometry}. Reuse the original VG configuration"
            )
        for inventory in inventories:
            validate_managed_inventory(
                inventory,
                location=cluster.location,
                base_size_tib=args.base_size_tib,
                extended_size_tib=args.extended_size_tib,
                availability_zone=args.availability_zone,
                subnet_ids=subnet_ids,
            )
        managed_handles = set().union(*(inventory.handles for inventory in inventories)) if inventories else set()
        existing_handles = pv_handles | managed_handles
        matching = [inventory.san for inventory in inventories if inventory.san.geometry == geometry]
        additions = plan_shards(
            existing_total=len(existing_handles),
            target_total=args.target_total_volumes,
            matching_sans=matching,
            all_managed_indexes=(inventory.san.index for inventory in inventories),
            shard_capacity=shard_capacity,
        )
        regional_san_count = sum(
            san.get("location", "").casefold() == cluster.location.casefold()
            for san in subscription_sans
        )
        new_san_count = sum(addition.san_name is None for addition in additions)
        if regional_san_count + new_san_count > MAX_SANS_PER_REGION:
            raise RuntimeError(
                f"plan needs {new_san_count} new SANs in {cluster.location}, but "
                f"{regional_san_count}/{MAX_SANS_PER_REGION} SAN slots are already used"
            )

        planned_additions = [
            {
                **item.__dict__,
                "san_name": item.san_name
                or stable_san_name(args.san_prefix, cluster.resource_uid, item.san_index),
                "add_count": item.add_count,
            }
            for item in additions
        ]
        plan = {
            "generated_utc": utc_now(),
            "cluster": cluster.__dict__,
            "san_resource_group": resource_group,
            "geometry": geometry,
            "shard_capacity": shard_capacity,
            "cluster_pv_handles": len(pv_handles),
            "managed_volume_handles": len(managed_handles),
            "existing_unique_handles": len(existing_handles),
            "target_total_volumes": args.target_total_volumes,
            "regional_san_count": regional_san_count,
            "regional_san_quota": MAX_SANS_PER_REGION,
            "planned_new_sans": new_san_count,
            "planned_new_volume_objects": sum(item.add_count for item in additions),
            "additions": planned_additions,
            "dry_run": args.dry_run,
            "not_before_utc": args.not_before_utc,
        }
        write_json(args.results_dir / "provision-plan.json", plan)
        print(json.dumps(plan, indent=2, default=list), flush=True)
        if args.dry_run or not additions:
            return 0

        if args.not_before_utc:
            not_before = datetime.fromisoformat(args.not_before_utc.replace("Z", "+00:00"))
            if not_before.tzinfo is None:
                raise ValueError("--not-before-utc must include a UTC offset or Z")
            wait_seconds = (not_before.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
            if wait_seconds > 0:
                print(f"[not-before] waiting {wait_seconds:.0f}s until {not_before.isoformat()}")
                await asyncio.sleep(wait_seconds)

        inventory_by_name = {inventory.san.name: inventory for inventory in inventories}
        all_records: list[dict[str, Any]] = []
        submit_errors: list[dict[str, Any]] = []
        validation_work: list[tuple[str, str, list[tuple[str, str]]]] = []
        limiter = HourlyWriteLimiter(
            args.max_volume_writes_per_hour,
            burst_limit=args.max_volume_writes_per_burst,
            burst_window_seconds=args.burst_window_seconds,
        )
        run_started = utc_now()
        submit_started_monotonic = time.monotonic()
        submit_started = utc_now()

        for addition, planned_addition in zip(additions, planned_additions, strict=True):
            san_name = planned_addition["san_name"]
            inventory = inventory_by_name.get(san_name)
            if inventory:
                san_id = inventory.resource_id
                groups = inventory.groups
            else:
                tags = {
                    MANAGED_BY_TAG: MANAGED_BY_VALUE,
                    CLUSTER_UID_TAG: cluster.resource_uid,
                    GEOMETRY_TAG: geometry,
                    SAN_INDEX_TAG: str(addition.san_index),
                }
                san_id = await ensure_san(
                    client,
                    limiter,
                    resource_group=resource_group,
                    name=san_name,
                    location=cluster.location,
                    base_size_tib=args.base_size_tib,
                    extended_size_tib=args.extended_size_tib,
                    availability_zone=args.availability_zone,
                    tags=tags,
                )
                groups = {}

            existing_names = {
                (group_name, volume["name"])
                for group_name, volumes in groups.items()
                for volume in volumes
            }
            specs = desired_volume_specs(
                target_count=addition.target_count,
                volumes_per_group=args.volumes_per_group,
                existing_names=existing_names,
                add_count=addition.add_count,
            )
            needed_groups = sorted({group for group, _ in specs})
            for group in needed_groups:
                if group not in groups:
                    print(f"[vg] creating {san_name}/{group} at {utc_now()}", flush=True)
                    await ensure_volume_group(
                        client,
                        limiter,
                        san_id=san_id,
                        name=group,
                        subnet_ids=subnet_ids,
                    )
                    groups[group] = []

            accepted, errors = await submit_volumes(
                client,
                san_id=san_id,
                specs=specs,
                volume_size_gib=args.volume_size_gib,
                batch_size=args.batch_size,
                batch_delay_seconds=args.batch_delay_seconds,
                limiter=limiter,
            )
            submit_errors.extend({"san": san_name, **error} for error in errors)
            validation_work.append((san_name, san_id, specs))
            print(
                f"[shard-submit] {san_name}: accepted={len(accepted)} errors={len(errors)}",
                flush=True,
            )

        submit_completed = utc_now()
        submit_elapsed = time.monotonic() - submit_started_monotonic
        validation_started_monotonic = time.monotonic()
        for san_name, san_id, specs in validation_work:
            records = await validate_volumes(
                client,
                san_id=san_id,
                expected=specs,
                timeout_seconds=args.validation_timeout_seconds,
            )
            all_records.extend({"san": san_name, **record} for record in records)
            print(
                f"[shard-validate] {san_name}: validated={len(records)}",
                flush=True,
            )

        validation_elapsed = time.monotonic() - validation_started_monotonic
        terminal_elapsed = time.monotonic() - submit_started_monotonic
        completed = utc_now()
        succeeded = sum(record["state"] == "Succeeded" for record in all_records)
        failed = sum(record["state"] == "Failed" for record in all_records)
        missing = len(all_records) - succeeded - failed
        summary = {
            **plan,
            "dry_run": False,
            "run_started_utc": run_started,
            "submit_started_utc": submit_started,
            "submit_completed_utc": submit_completed,
            "completed_utc": completed,
            "submit_elapsed_seconds": round(submit_elapsed, 3),
            "validation_elapsed_seconds": round(validation_elapsed, 3),
            "terminal_elapsed_seconds": round(terminal_elapsed, 3),
            "submitted_without_error": sum(item.add_count for item in additions)
            - len(submit_errors),
            "submit_errors": submit_errors,
            "planned_result": {
                "total": len(all_records),
                "succeeded": succeeded,
                "failed": failed,
                "missing_or_nonterminal": missing,
                "success_rate": round(succeeded / len(all_records), 6) if all_records else 1.0,
            },
            "results_by_san": aggregate_records(all_records, ("san",)),
            "results_by_volume_group": aggregate_records(all_records, ("san", "group")),
        }
        write_json(args.results_dir / "provision-summary.json", summary)
        with (args.results_dir / "provision-volumes.csv").open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["san", "group", "volume", "state", "resource_id"])
            writer.writeheader()
            writer.writerows(all_records)
        print(json.dumps(summary, indent=2, default=list), flush=True)
        return 0 if not missing else 2


def main() -> int:
    args = parse_args()
    os.environ.setdefault("AZURE_CORE_ONLY_SHOW_ERRORS", "true")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())