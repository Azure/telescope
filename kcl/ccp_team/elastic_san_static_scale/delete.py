#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from esan_common import (
    canonical_handle,
    cluster_pv_handles,
    load_cluster_info,
    write_json,
)
from provision import (
    BURST_WINDOW_SECONDS,
    MAX_WRITES_PER_BURST,
    ArmClient,
    ArmError,
    HourlyWriteLimiter,
    inventory_managed_sans,
    utc_now,
)


def load_provision_manifest(
    summary_path: Path, volumes_path: Path
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[str, str]]], str, str, str]:
    """Parse the provision artifact into the resources this run created."""
    summary = json.loads(summary_path.read_text())
    additions = summary.get("additions", [])
    san_resource_group = summary["san_resource_group"]
    cluster = summary.get("cluster", {})
    subscription_id = cluster.get("subscription_id", "")
    resource_uid = cluster.get("resource_uid", "")
    if not subscription_id or not resource_uid:
        raise ValueError("provision summary is missing cluster subscription_id or resource_uid")

    per_san_volumes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    if volumes_path.exists():
        with volumes_path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                per_san_volumes[row["san"]].append((row["group"], row["volume"]))
    return additions, per_san_volumes, san_resource_group, subscription_id, resource_uid


def plan_deletions(
    additions: list[dict[str, Any]],
    per_san_volumes: dict[str, list[tuple[str, str]]],
) -> tuple[list[str], dict[str, list[tuple[str, str]]]]:
    """Split this run's additions into whole-SAN deletes and per-volume deletes.

    A SAN created by this run (``new_san``) is removed in full; a pre-existing SAN
    that this run only topped up keeps its prior volumes and loses just the volumes
    this run added.
    """
    whole_sans: list[str] = []
    topped_up_volumes: dict[str, list[tuple[str, str]]] = {}
    for addition in additions:
        san_name = addition["san_name"]
        # Fall back to current_count for manifests written before new_san existed.
        created_this_run = addition.get("new_san", addition.get("current_count", 0) == 0)
        if created_this_run:
            whole_sans.append(san_name)
        elif per_san_volumes.get(san_name):
            topped_up_volumes[san_name] = list(per_san_volumes[san_name])
    return whole_sans, topped_up_volumes


async def delete_resource(
    client: ArmClient, resource_id: str, limiter: HourlyWriteLimiter
) -> dict[str, Any] | None:
    try:
        await limiter.acquire(1)
        await client.request(
            "DELETE",
            resource_id,
            retry_reads=False,
            retry_limiter=limiter,
        )
        return None
    except ArmError as error:
        if error.status == 404:
            return None
        return {"resource_id": resource_id, "error": str(error)}
    except Exception as error:  # deletion errors are benchmark output
        return {"resource_id": resource_id, "error": str(error)}


async def delete_resources(
    client: ArmClient,
    resource_ids: list[str],
    limiter: HourlyWriteLimiter,
    batch_size: int = 10,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for start in range(0, len(resource_ids), batch_size):
        batch = resource_ids[start : start + batch_size]
        results = await asyncio.gather(
            *(delete_resource(client, resource_id, limiter) for resource_id in batch)
        )
        errors.extend(error for error in results if error is not None)
    return errors


async def wait_absent(
    client: ArmClient, resource_ids: list[str], timeout_seconds: int
) -> list[str]:
    pending = list(resource_ids)
    deadline = time.monotonic() + timeout_seconds
    while pending and time.monotonic() < deadline:
        still_present: list[str] = []
        for resource_id in pending:
            try:
                await client.request("GET", resource_id)
                still_present.append(resource_id)
            except ArmError as error:
                if error.status != 404:
                    raise
        pending = still_present
        if pending:
            print(f"[delete] waiting for {len(pending)} resources to drain at {utc_now()}")
            await asyncio.sleep(20)
    return pending


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete Elastic SAN resources created by a specific provision run"
    )
    parser.add_argument("--cluster-info", type=Path, required=True)
    parser.add_argument("--provision-summary", type=Path, required=True)
    parser.add_argument("--provision-volumes", type=Path, required=True)
    parser.add_argument("--kubeconfig", default="")
    parser.add_argument("--max-volume-writes-per-hour", type=int, default=3_000)
    parser.add_argument(
        "--max-volume-writes-per-burst", type=int, default=MAX_WRITES_PER_BURST
    )
    parser.add_argument(
        "--burst-window-seconds", type=float, default=BURST_WINDOW_SECONDS
    )
    parser.add_argument("--drain-timeout-seconds", type=int, default=1_800)
    parser.add_argument(
        "--allow-attached",
        action="store_true",
        help="Delete even volumes still referenced by cluster PVs (unsafe)",
    )
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    cluster = load_cluster_info(args.cluster_info)
    additions, per_san_volumes, san_resource_group, subscription_id, resource_uid = (
        load_provision_manifest(args.provision_summary, args.provision_volumes)
    )
    if subscription_id.casefold() != cluster.subscription_id.casefold():
        raise ValueError(
            "provision summary subscription does not match the resolved cluster; "
            "refusing to delete resources from a different run"
        )
    if resource_uid.casefold() != cluster.resource_uid.casefold():
        raise ValueError(
            "provision summary cluster UID does not match the resolved cluster; "
            "refusing to delete resources from a different cluster"
        )

    whole_san_names, topped_up_volumes = plan_deletions(additions, per_san_volumes)

    limiter = HourlyWriteLimiter(
        args.max_volume_writes_per_hour,
        burst_limit=args.max_volume_writes_per_burst,
        burst_window_seconds=args.burst_window_seconds,
    )
    started_utc = utc_now()
    started = time.monotonic()

    async with ArmClient(cluster.subscription_id) as client:
        # Only ever touch SANs tagged as managed for this cluster.
        inventories = await inventory_managed_sans(client, cluster.resource_uid)
        managed = {inventory.san.name.casefold(): inventory for inventory in inventories}

        whole_san_targets = [
            managed[name.casefold()]
            for name in whole_san_names
            if name.casefold() in managed
        ]
        missing_whole_sans = [
            name for name in whole_san_names if name.casefold() not in managed
        ]

        # Volumes to delete: everything inside a whole-SAN target, plus the specific
        # volumes this run added to pre-existing managed SANs.
        volume_records: list[dict[str, Any]] = []
        for inventory in whole_san_targets:
            for group, volumes in inventory.groups.items():
                for volume in volumes:
                    volume_records.append(
                        {
                            "san": inventory.san.name,
                            "resource_group": inventory.san.resource_group,
                            "group": group,
                            "volume": volume["name"],
                            "resource_id": volume["id"],
                        }
                    )
        for san_name, specs in topped_up_volumes.items():
            inventory = managed.get(san_name.casefold())
            if inventory is None:
                missing_whole_sans.append(san_name)
                continue
            for group, volume in specs:
                volume_records.append(
                    {
                        "san": inventory.san.name,
                        "resource_group": inventory.san.resource_group,
                        "group": group,
                        "volume": volume,
                        "resource_id": (
                            f"{inventory.resource_id}/volumeGroups/{quote(group)}"
                            f"/volumes/{quote(volume)}"
                        ),
                    }
                )

        # Never orphan a volume that the cluster still mounts.
        attached = []
        if args.kubeconfig and not args.allow_attached:
            pv_handles = cluster_pv_handles(args.kubeconfig)
            attached = [
                record
                for record in volume_records
                if canonical_handle(
                    record["resource_group"],
                    record["san"],
                    record["group"],
                    record["volume"],
                )
                in pv_handles
            ]
            if attached:
                raise RuntimeError(
                    f"refusing to delete {len(attached)} volumes still referenced by cluster "
                    "PVs; remove the attachments or pass --allow-attached"
                )

        plan = {
            "generated_utc": utc_now(),
            "cluster": cluster.__dict__,
            "san_resource_group": san_resource_group,
            "whole_sans_to_delete": sorted(inv.san.name for inv in whole_san_targets),
            "whole_sans_already_absent": sorted(set(missing_whole_sans)),
            "topped_up_sans": sorted(topped_up_volumes),
            "volumes_to_delete": len(volume_records),
            "dry_run": args.dry_run,
        }
        write_json(args.results_dir / "delete-plan.json", plan)
        print(json.dumps(plan, indent=2, default=list), flush=True)
        if args.dry_run:
            return 0

        volume_errors = await delete_resources(
            client, [record["resource_id"] for record in volume_records], limiter
        )
        volume_error_ids = {error["resource_id"] for error in volume_errors}
        volumes_still_present = await wait_absent(
            client,
            [
                record["resource_id"]
                for record in volume_records
                if record["resource_id"] not in volume_error_ids
            ],
            timeout_seconds=args.drain_timeout_seconds,
        )

        # A whole SAN can only be removed once its volume groups are empty.
        group_ids = sorted(
            {
                group_resource["id"]
                for inventory in whole_san_targets
                for group_resource in inventory.group_resources.values()
            }
        )
        group_errors: list[dict[str, Any]] = []
        san_errors: list[dict[str, Any]] = []
        deleted_sans: list[str] = []
        if group_ids and not volumes_still_present:
            group_errors = await delete_resources(client, group_ids, limiter)
            await wait_absent(client, group_ids, timeout_seconds=args.drain_timeout_seconds)
            for inventory in whole_san_targets:
                error = await delete_resource(client, inventory.resource_id, limiter)
                if error is None:
                    deleted_sans.append(inventory.san.name)
                else:
                    san_errors.append(error)
            await wait_absent(
                client,
                [inv.resource_id for inv in whole_san_targets],
                timeout_seconds=args.drain_timeout_seconds,
            )
        elif volumes_still_present:
            print(
                f"[delete] {len(volumes_still_present)} volumes did not drain; "
                "leaving volume groups and SANs in place",
                flush=True,
            )

        summary = {
            **plan,
            "started_utc": started_utc,
            "completed_utc": utc_now(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "volumes_requested": len(volume_records),
            "volume_delete_errors": volume_errors,
            "volumes_still_present": len(volumes_still_present),
            "volume_groups_requested": len(group_ids),
            "volume_group_delete_errors": group_errors,
            "sans_deleted": sorted(deleted_sans),
            "san_delete_errors": san_errors,
        }
        write_json(args.results_dir / "delete-summary.json", summary)
        print(json.dumps(summary, indent=2, default=list), flush=True)
        failed = (
            bool(volume_errors)
            or bool(group_errors)
            or bool(san_errors)
            or bool(volumes_still_present)
        )
        return 2 if failed else 0


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
