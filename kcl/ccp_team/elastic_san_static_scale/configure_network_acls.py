#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from esan_common import load_cluster_info, resolve_cluster, write_json
from provision import (
    BURST_WINDOW_SECONDS,
    MAX_WRITES_PER_BURST,
    ArmClient,
    HourlyWriteLimiter,
    utc_now,
)


def existing_allow_rules(volume_group: dict[str, Any]) -> list[dict[str, Any]]:
    acls = (volume_group.get("properties", {}) or {}).get("networkAcls") or {}
    return [rule for rule in (acls.get("virtualNetworkRules") or []) if rule.get("id")]


def missing_subnet_ids(volume_group: dict[str, Any], subnet_ids: tuple[str, ...]) -> list[str]:
    present = {str(rule["id"]).casefold() for rule in existing_allow_rules(volume_group)}
    return [subnet for subnet in subnet_ids if subnet.casefold() not in present]


def merged_network_acls(volume_group: dict[str, Any], added_subnet_ids: list[str]) -> dict[str, Any]:
    rules = existing_allow_rules(volume_group)
    rules += [{"id": subnet, "action": "Allow"} for subnet in added_subnet_ids]
    return {"virtualNetworkRules": rules}


async def find_san_id(client: ArmClient, name: str) -> str:
    sans = await client.list_all(
        f"/subscriptions/{client.subscription_id}/providers/Microsoft.ElasticSan/elasticSans"
    )
    for san in sans:
        if str(san.get("name", "")).casefold() == name.casefold():
            return san["id"]
    raise RuntimeError(f"Elastic SAN {name!r} not found in subscription")


async def ensure_volume_group_acls(
    client: ArmClient,
    limiter: HourlyWriteLimiter,
    *,
    volume_group: dict[str, Any],
    subnet_ids: tuple[str, ...],
) -> str:
    missing = missing_subnet_ids(volume_group, subnet_ids)
    if not missing:
        return "skipped"
    body = {"properties": {"networkAcls": merged_network_acls(volume_group, missing)}}
    await limiter.acquire(1)
    await client.request("PATCH", volume_group["id"], body, retry_reads=False, retry_limiter=limiter)
    return "updated"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add AKS subnet allow rules to existing Elastic SAN volume groups"
    )
    cluster = parser.add_mutually_exclusive_group(required=True)
    cluster.add_argument("--cluster-id", help="Full AKS ARM resource ID")
    cluster.add_argument("--cluster-info", type=Path, help="Resolved cluster JSON from the pipeline")
    parser.add_argument(
        "--san-name", action="append", required=True, help="Elastic SAN name to update (repeatable)"
    )
    parser.add_argument("--subnet-id", action="append", default=[])
    parser.add_argument("--max-volume-writes-per-hour", type=int, default=3_000)
    parser.add_argument("--max-volume-writes-per-burst", type=int, default=MAX_WRITES_PER_BURST)
    parser.add_argument("--burst-window-seconds", type=float, default=BURST_WINDOW_SECONDS)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    cluster = (
        load_cluster_info(args.cluster_info)
        if args.cluster_info
        else resolve_cluster(args.cluster_id)
    )
    subnet_ids = tuple(sorted(set(args.subnet_id) | set(cluster.subnet_ids)))
    if not subnet_ids:
        raise ValueError("no subnet ids resolved; pass --subnet-id or use a cluster with subnets")
    limiter = HourlyWriteLimiter(
        args.max_volume_writes_per_hour,
        burst_limit=args.max_volume_writes_per_burst,
        burst_window_seconds=args.burst_window_seconds,
    )
    started = utc_now()
    started_monotonic = time.monotonic()
    results: list[dict[str, Any]] = []

    async with ArmClient(cluster.subscription_id) as client:
        for san_name in args.san_name:
            san_id = await find_san_id(client, san_name)
            volume_groups = await client.list_all(f"{san_id}/volumeGroups")
            for volume_group in volume_groups:
                if args.dry_run:
                    action = "would-update" if missing_subnet_ids(volume_group, subnet_ids) else "skipped"
                else:
                    action = await ensure_volume_group_acls(
                        client, limiter, volume_group=volume_group, subnet_ids=subnet_ids
                    )
                results.append(
                    {"san": san_name, "volume_group": volume_group["name"], "action": action}
                )
                print(f"[acl] {san_name}/{volume_group['name']}: {action}", flush=True)

    summary = {
        "generated_utc": started,
        "completed_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "cluster": cluster.__dict__,
        "subnet_ids": list(subnet_ids),
        "san_names": args.san_name,
        "dry_run": args.dry_run,
        "volume_groups_total": len(results),
        "updated": sum(record["action"] == "updated" for record in results),
        "would_update": sum(record["action"] == "would-update" for record in results),
        "skipped": sum(record["action"] == "skipped" for record in results),
        "results": results,
    }
    write_json(args.results_dir / "network-acls-summary.json", summary)
    print(json.dumps(summary, indent=2, default=list), flush=True)
    return 0


def main() -> int:
    args = parse_args()
    os.environ.setdefault("AZURE_CORE_ONLY_SHOW_ERRORS", "true")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
