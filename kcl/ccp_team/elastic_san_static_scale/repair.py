#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from esan_common import (
    MAX_TARGET_TOTAL_VOLUMES,
    canonical_handle,
    cluster_pv_handles,
    geometry_key,
    load_cluster_info,
    parse_handle,
    validate_geometry,
    write_json,
)
from provision import (
    BURST_WINDOW_SECONDS,
    MAX_WRITES_PER_BURST,
    ArmClient,
    HourlyWriteLimiter,
    aggregate_records,
    inventory_managed_sans,
    utc_now,
    validate_volumes,
)


def failed_volume_records(inventories: list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for inventory in inventories:
        for group, volumes in inventory.groups.items():
            for volume in volumes:
                properties = volume.get("properties", {})
                if properties.get("provisioningState") != "Failed":
                    continue
                if properties.get("sizeGiB") is None:
                    raise ValueError(f"sizeGiB is missing for failed volume {volume['id']}")
                records.append(
                    {
                        "san": inventory.san.name,
                        "san_id": inventory.resource_id,
                        "resource_group": inventory.san.resource_group,
                        "group": group,
                        "volume": volume["name"],
                        "resource_id": volume["id"],
                        "size_gib": int(properties["sizeGiB"]),
                        "state": "Failed",
                    }
                )
    return sorted(records, key=lambda record: (record["san"], record["group"], record["volume"]))


def desired_repair_records(
    inventories: list[Any],
    pv_handles: set[str],
    *,
    target_total_volumes: int,
    volumes_per_group: int,
    shard_capacity: int,
    volume_size_gib: int,
) -> list[dict[str, Any]]:
    managed_identities = {
        (inventory.san.resource_group.casefold(), inventory.san.name.casefold())
        for inventory in inventories
    }
    managed_handles = set().union(*(inventory.handles for inventory in inventories)) if inventories else set()
    existing_handles = pv_handles | managed_handles
    if target_total_volumes < len(existing_handles):
        raise ValueError(
            f"target total {target_total_volumes} is below the existing "
            f"{len(existing_handles)} unique ESAN handles; shrinking is not supported"
        )
    external_handles = {
        handle
        for handle in pv_handles
        if (parsed := parse_handle(handle)) is None
        or (parsed[0].casefold(), parsed[1].casefold()) not in managed_identities
    }
    managed_target = target_total_volumes - len(external_handles)
    if managed_target < 0:
        raise ValueError("target total is smaller than existing non-managed ESAN PV handles")

    records: list[dict[str, Any]] = []
    remaining = managed_target
    for inventory in sorted(inventories, key=lambda item: item.san.index):
        if remaining == 0:
            break
        desired_count = min(remaining, shard_capacity)
        current = {
            (group, volume["name"]): volume
            for group, volumes in inventory.groups.items()
            for volume in volumes
        }
        for ordinal in range(desired_count):
            group = f"vg-{ordinal // volumes_per_group:03d}"
            volume_name = f"vol-{ordinal % volumes_per_group:04d}"
            volume = current.get((group, volume_name))
            if volume is None:
                state = "Missing"
                size_gib = volume_size_gib
                resource_id = (
                    f"{inventory.resource_id}/volumeGroups/{quote(group)}"
                    f"/volumes/{quote(volume_name)}"
                )
            else:
                properties = volume.get("properties", {})
                state = properties.get("provisioningState", "Unknown")
                if state == "Succeeded":
                    continue
                if state not in ("Failed", "Missing"):
                    raise RuntimeError(
                        f"volume {volume['id']} is still in nonterminal state {state}"
                    )
                if properties.get("sizeGiB") is None:
                    raise ValueError(f"sizeGiB is missing for failed volume {volume['id']}")
                size_gib = int(properties["sizeGiB"])
                resource_id = volume["id"]
            records.append(
                {
                    "san": inventory.san.name,
                    "san_id": inventory.resource_id,
                    "resource_group": inventory.san.resource_group,
                    "group": group,
                    "volume": volume_name,
                    "resource_id": resource_id,
                    "size_gib": size_gib,
                    "state": state,
                }
            )
        remaining -= desired_count
    if remaining:
        raise RuntimeError(
            f"managed SAN capacity is short by {remaining} volumes; run Provision before Repair"
        )
    return sorted(records, key=lambda record: (record["san"], record["group"], record["volume"]))


async def delete_failed_volumes(
    client: ArmClient,
    records: list[dict[str, Any]],
    limiter: HourlyWriteLimiter,
    batch_size: int = 10,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []

    async def delete(record: dict[str, Any]) -> None:
        try:
            await client.request(
                "DELETE",
                record["resource_id"],
                retry_reads=False,
                retry_limiter=limiter,
            )
        except Exception as error:
            errors.append(
                {
                    "san": record["san"],
                    "group": record["group"],
                    "volume": record["volume"],
                    "error": str(error),
                }
            )

    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        await limiter.acquire(len(batch))
        await asyncio.gather(*(delete(record) for record in batch))
    return errors


async def wait_until_absent(
    client: ArmClient,
    records: list[dict[str, Any]],
    timeout_seconds: int,
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    expected: dict[tuple[str, str], set[str]] = defaultdict(set)
    san_ids: dict[str, str] = {}
    for record in records:
        expected[(record["san"], record["group"])].add(record["volume"])
        san_ids[record["san"]] = record["san_id"]
    pending = {key: set(names) for key, names in expected.items()}
    deadline = time.monotonic() + timeout_seconds
    while pending and time.monotonic() < deadline:
        for san, group in list(pending):
            volumes = await client.list_all(
                f"{san_ids[san]}/volumeGroups/{quote(group)}/volumes"
            )
            present = {volume["name"] for volume in volumes}
            pending[(san, group)].intersection_update(present)
            if not pending[(san, group)]:
                del pending[(san, group)]
            await asyncio.sleep(0.2)
        if pending:
            print(f"[repair-delete] waiting for {len(pending)} volume groups at {utc_now()}")
            await asyncio.sleep(20)
    absent = {
        (record["san"], record["group"], record["volume"])
        for record in records
        if record["volume"] not in pending.get((record["san"], record["group"]), set())
    }
    present = {
        (record["san"], record["group"], record["volume"])
        for record in records
        if record["volume"] in pending.get((record["san"], record["group"]), set())
    }
    return absent, present


async def classify_absence_once(
    client: ArmClient,
    records: list[dict[str, Any]],
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    records_by_group: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_group[(record["san"], record["san_id"], record["group"])].append(record)
    absent: set[tuple[str, str, str]] = set()
    present: set[tuple[str, str, str]] = set()
    for (san, san_id, group), group_records in records_by_group.items():
        volumes = await client.list_all(
            f"{san_id}/volumeGroups/{quote(group)}/volumes"
        )
        present_names = {volume["name"] for volume in volumes}
        for record in group_records:
            key = (san, group, record["volume"])
            (present if record["volume"] in present_names else absent).add(key)
    return absent, present


async def recreate_volumes(
    client: ArmClient,
    records: list[dict[str, Any]],
    limiter: HourlyWriteLimiter,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for record in records:
        await limiter.acquire(1)
        resource_id = (
            f"{record['san_id']}/volumeGroups/{quote(record['group'])}"
            f"/volumes/{quote(record['volume'])}"
        )
        try:
            await client.request(
                "PUT",
                resource_id,
                {"properties": {"sizeGiB": record["size_gib"]}},
                retry_reads=False,
                retry_limiter=limiter,
            )
        except Exception as error:
            errors.append(
                {
                    "san": record["san"],
                    "group": record["group"],
                    "volume": record["volume"],
                    "error": str(error),
                }
            )
        await asyncio.sleep(1)
    return errors


async def validate_recreated(
    client: ArmClient,
    records: list[dict[str, Any]],
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    by_san: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_san[record["san"]].append(record)
    observed: list[dict[str, Any]] = []
    for san, san_records in sorted(by_san.items()):
        states = await validate_volumes(
            client,
            san_id=san_records[0]["san_id"],
            expected=[(record["group"], record["volume"]) for record in san_records],
            timeout_seconds=timeout_seconds,
        )
        sizes = {(record["group"], record["volume"]): record["size_gib"] for record in san_records}
        observed.extend(
            {
                "san": san,
                "san_id": san_records[0]["san_id"],
                "group": state["group"],
                "volume": state["volume"],
                "resource_id": state["resource_id"],
                "size_gib": sizes[(state["group"], state["volume"])],
                "state": state["state"],
            }
            for state in states
        )
    return observed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair failed pipeline-managed ESAN volumes")
    parser.add_argument("--cluster-info", type=Path, required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--max-volume-writes-per-hour", type=int, default=3_000)
    parser.add_argument(
        "--max-volume-writes-per-burst", type=int, default=MAX_WRITES_PER_BURST
    )
    parser.add_argument(
        "--burst-window-seconds", type=float, default=BURST_WINDOW_SECONDS
    )
    parser.add_argument("--target-total-volumes", type=int, required=True)
    parser.add_argument("--volume-groups-per-san", type=int, required=True)
    parser.add_argument("--volumes-per-group", type=int, required=True)
    parser.add_argument("--volume-size-gib", type=int, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    if not 0 <= args.target_total_volumes <= MAX_TARGET_TOTAL_VOLUMES:
        raise ValueError(
            f"target_total_volumes must be between 0 and {MAX_TARGET_TOTAL_VOLUMES}"
        )
    if args.volume_size_gib < 1:
        raise ValueError("volume_size_gib must be positive")
    cluster = load_cluster_info(args.cluster_info)
    shard_capacity = validate_geometry(args.volume_groups_per_san, args.volumes_per_group)
    geometry = geometry_key(args.volume_groups_per_san, args.volumes_per_group)
    limiter = HourlyWriteLimiter(
        args.max_volume_writes_per_hour,
        burst_limit=args.max_volume_writes_per_burst,
        burst_window_seconds=args.burst_window_seconds,
    )
    started_utc = utc_now()
    started = time.monotonic()
    rounds: list[dict[str, Any]] = []

    async with ArmClient(cluster.subscription_id) as client:
        inventories = await inventory_managed_sans(client, cluster.resource_uid)
        indexes = [inventory.san.index for inventory in inventories]
        if any(index < 0 for index in indexes) or len(indexes) != len(set(indexes)):
            raise RuntimeError(f"managed SAN indexes must be unique and non-negative: {indexes}")
        mismatched_geometries = sorted(
            {inventory.san.geometry for inventory in inventories if inventory.san.geometry != geometry}
        )
        if mismatched_geometries:
            raise RuntimeError(
                f"cluster managed SAN geometry is {mismatched_geometries}; requested {geometry}"
            )
        referenced_handles = cluster_pv_handles(args.kubeconfig)
        current = desired_repair_records(
            inventories,
            referenced_handles,
            target_total_volumes=args.target_total_volumes,
            volumes_per_group=args.volumes_per_group,
            shard_capacity=shard_capacity,
            volume_size_gib=args.volume_size_gib,
        )
        initial_failed = sum(record["state"] == "Failed" for record in current)
        initial_missing = sum(record["state"] == "Missing" for record in current)
        unsafe = [
            record
            for record in current
            if canonical_handle(
                record["resource_group"], record["san"], record["group"], record["volume"]
            )
            in referenced_handles
        ]
        if unsafe:
            raise RuntimeError(
                f"refusing to repair {len(unsafe)} failed volumes referenced by cluster PVs"
            )

        write_json(
            args.results_dir / "repair-plan.json",
            {
                "generated_utc": utc_now(),
                "cluster": cluster.__dict__,
                "managed_sans": len(inventories),
                "initial_failed": initial_failed,
                "initial_missing": initial_missing,
                "candidates": current,
                "repair_round_limit": 4,
            },
        )

        for round_number in range(1, 5):
            if not current:
                break
            print(f"[repair] round={round_number} failed={len(current)} at {utc_now()}")
            delete_records = [record for record in current if record["state"] == "Failed"]
            delete_errors = await delete_failed_volumes(client, delete_records, limiter)
            delete_error_keys = {
                (error["san"], error["group"], error["volume"])
                for error in delete_errors
            }
            accepted_delete_records = [
                record
                for record in delete_records
                if (record["san"], record["group"], record["volume"])
                not in delete_error_keys
            ]
            uncertain_delete_records = [
                record
                for record in delete_records
                if (record["san"], record["group"], record["volume"])
                in delete_error_keys
            ]
            absent, still_present = await wait_until_absent(
                client, accepted_delete_records, timeout_seconds=1_800
            )
            uncertain_absent, uncertain_present = await classify_absence_once(
                client, uncertain_delete_records
            )
            absent.update(uncertain_absent)
            still_present.update(uncertain_present)
            create_records = [
                record
                for record in current
                if record["state"] == "Missing"
                or (record["san"], record["group"], record["volume"]) in absent
            ]
            create_errors = await recreate_volumes(client, create_records, limiter)
            observed = await validate_recreated(client, current, timeout_seconds=1_800)
            succeeded = sum(record["state"] == "Succeeded" for record in observed)
            failed = sum(record["state"] == "Failed" for record in observed)
            missing = len(observed) - succeeded - failed
            rounds.append(
                {
                    "round": round_number,
                    "attempted": len(current),
                    "deleted": len(delete_records),
                    "delete_errors": delete_errors,
                    "delete_still_present": len(still_present),
                    "recreated": len(create_records),
                    "create_errors": create_errors,
                    "succeeded": succeeded,
                    "failed": failed,
                    "missing_or_nonterminal": missing,
                    "success_rate": round(succeeded / len(observed), 6),
                    "results_by_san": aggregate_records(observed, ("san",)),
                    "results_by_volume_group": aggregate_records(observed, ("san", "group")),
                }
            )
            current = [record for record in observed if record["state"] != "Succeeded"]

    summary = {
        "started_utc": started_utc,
        "completed_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "initial_failed": initial_failed,
        "initial_missing": initial_missing,
        "remaining_failed_or_missing": len(current),
        "all_repaired": not current,
        "rounds": rounds,
    }
    write_json(args.results_dir / "repair-summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if not current else 2


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())