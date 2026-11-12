"""Submit resource-group deletion, then poll and cancel blocking VMSS upgrades."""

import argparse
from datetime import datetime, timezone
import json
import os
import re
import signal
import subprocess
import sys
import time


class CleanupError(RuntimeError):
    """Cleanup could not complete safely."""


class AzureCliError(CleanupError):
    """Preserve the Azure error code instead of treating failed reads as absence."""

    def __init__(self, command: list[str], message: str):
        super().__init__(f"{' '.join(command)} failed: {message}")
        match = re.search(r"^ERROR:\s*\(([^)]+)\)", message, re.MULTILINE)
        self.code = match.group(1) if match else None


def run_command(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    # az can be a shell wrapper; a timeout must also stop its Python child.
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # The process group exited between the timeout and kill.
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


class AzureCli:
    def __init__(self, subscription: str, timeout_seconds: int):
        self.subscription = subscription
        self.deadline = time.monotonic() + timeout_seconds

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CleanupError("Resource-group cleanup deadline exceeded")
        return remaining

    def sleep(self, seconds: float):
        time.sleep(min(seconds, self.remaining()))

    def run(self, *args: str):
        command = [
            "az", *args, "--subscription", self.subscription,
            "--only-show-errors", "--output", "json",
        ]
        for attempt in range(3):
            try:
                result = run_command(command, timeout=self.remaining())
            except subprocess.TimeoutExpired as error:
                raise CleanupError(f"Azure CLI request timed out: {' '.join(command)}") from error
            if result.returncode == 0:
                return json.loads(result.stdout) if result.stdout.strip() else None
            error = AzureCliError(command, result.stderr.strip() or result.stdout.strip())
            if error.code not in {
                "TooManyRequests", "InternalServerError", "ServiceUnavailable", "GatewayTimeout",
            } or attempt == 2:
                raise error
            print(f"Transient Azure error: {error}; retrying", flush=True)
            self.sleep(5 * (attempt + 1))
        raise AssertionError("Unreachable")

    def get_optional(self, *args: str, missing_codes: set[str]):
        try:
            return self.run(*args)
        except AzureCliError as error:
            if error.code not in missing_codes:
                raise
            print(f"Resource or upgrade no longer present: {error}", flush=True)
            return None


def get_group(cli: AzureCli, name: str):
    return cli.get_optional(
        "group", "show", "--name", name,
        missing_codes={"ResourceGroupNotFound"},
    )


def submit_delete(cli: AzureCli, name: str):
    try:
        cli.run("group", "delete", "--name", name, "--yes", "--no-wait")
    except AzureCliError as error:
        if error.code != "ResourceGroupNotFound":
            raise
        print(f"Resource group already absent: {name}", flush=True)
        return
    print(f"Deletion submitted for {name}", flush=True)


def get_upgrade(cli: AzureCli, vmss_id: str):
    try:
        return cli.get_optional(
            "vmss", "rolling-upgrade", "get-latest", "--ids", vmss_id,
            missing_codes={"ResourceNotFound", "ResourceGroupNotFound", "RollingUpgradeNotFound"},
        )
    except AzureCliError as error:
        # This endpoint also returns NotFound when deletion removes the scale set.
        if error.code != "NotFound" or cli.get_optional(
            "vmss", "show", "--ids", vmss_id,
            missing_codes={"ResourceNotFound", "ResourceGroupNotFound"},
        ) is not None:
            raise
        return None


def upgrade_is_active(upgrade) -> bool:
    if upgrade is None:
        return False
    status = upgrade["runningStatus"]["code"]
    if status == "RollingForward":
        return True
    if status in {"Completed", "Cancelled", "Faulted"}:
        return False
    raise CleanupError(f"Unrecognized rolling upgrade status: {status}")


def cancel_active_vmss_rolling_upgrades(cli: AzureCli, resource_groups: list[str]) -> bool:
    recovered = False
    for group in dict.fromkeys(resource_groups):
        scale_sets = cli.get_optional(
            "vmss", "list", "--resource-group", group,
            missing_codes={"ResourceGroupNotFound"},
        )
        if scale_sets is None:
            continue
        for scale_set in scale_sets:
            vmss_id = scale_set["id"]
            upgrade = get_upgrade(cli, vmss_id)
            print(f"Rolling upgrade for {vmss_id}: {json.dumps(upgrade)}", flush=True)
            if not upgrade_is_active(upgrade):
                continue
            try:
                # Azure CLI waits for cancellation; the shared deadline bounds its waiter.
                cli.run("vmss", "rolling-upgrade", "cancel", "--ids", vmss_id)
            except AzureCliError as error:
                if error.code not in {
                    "ResourceNotFound", "ResourceGroupNotFound", "OperationNotAllowed",
                } or upgrade_is_active(get_upgrade(cli, vmss_id)):
                    raise
                print(f"Upgrade ended before cancellation: {vmss_id}", flush=True)
            print(f"Upgrade cancellation finished: {vmss_id}", flush=True)
            recovered = True
    return recovered


def discover_node_groups(cli: AzureCli, name: str) -> dict[str, list[str]]:
    clusters = cli.get_optional(
        "aks", "list", "--resource-group", name,
        missing_codes={"ResourceGroupNotFound"},
    )
    node_groups: dict[str, list[str]] = {}
    for cluster in clusters or []:
        node_group = cluster["nodeResourceGroup"]
        if not node_group or node_group.lower() == name.lower():
            raise CleanupError(f"Invalid node resource group for {cluster['id']}: {node_group}")
        node_groups.setdefault(node_group, []).append(cluster["id"])
    return node_groups


def owners_allow_upgrade_cancellation(
    cli: AzureCli, owners: list[str], node_group: dict, parent_group, since: str,
) -> bool:
    has_failed_owner = False
    for owner in owners:
        cluster = cli.get_optional(
            "resource", "show", "--ids", owner,
            missing_codes={"ResourceNotFound", "ResourceGroupNotFound"},
        )
        if cluster is None or cluster["properties"]["provisioningState"] == "Deleting":
            continue
        if (
            cluster["properties"]["provisioningState"] == "Failed"
            and cluster["properties"].get("nodeResourceGroup", "").lower()
            == node_group["id"].rsplit("/", 1)[-1].lower()
        ):
            has_failed_owner = True
            continue
        print(f"Not cancelling upgrades for owner not deleting: {owner}", flush=True)
        return False
    if has_failed_owner:
        if parent_group is None or parent_group["properties"]["provisioningState"] != "Deleting":
            return False
        failure = latest_delete_failure(cli, node_group["id"], since)
        if failure is None:
            return False
        # Failed alone is not deletion intent. Require this node group's fresh,
        # explicit VMSS rolling-upgrade deletion blocker while its parent deletes.
        message = json.dumps(failure.get("properties", {}).get("statusMessage", "")).lower()
        return (
            "resourcegroupdeletionblocked" in message
            and "microsoft.compute/virtualmachinescalesets/" in message
            and "operationnotallowed" in message
            and "rolling upgrade in progress" in message
        )
    return True


def latest_delete_failure(cli: AzureCli, resource_id: str, since: str):
    events = cli.run(
        "monitor", "activity-log", "list", "--resource-id", resource_id,
        "--start-time", since, "--max-events", "100",
    )
    deletes = [
        event for event in events
        if event["operationName"]["value"].lower()
        == "microsoft.resources/subscriptions/resourcegroups/delete"
        and event.get("resourceId", "").lower() == resource_id.lower()
        and datetime.fromisoformat(event["eventTimestamp"].replace("Z", "+00:00"))
        > datetime.fromisoformat(since.replace("Z", "+00:00"))
    ]
    if not deletes:
        return None
    latest = max(deletes, key=lambda event: event["eventTimestamp"])
    return latest if latest["status"]["value"] == "Failed" else None


def delete_resource_group(cli: AzureCli, name: str, poll_interval_seconds: int):
    target = get_group(cli, name)
    if target is None:
        print(f"Resource group already absent: {name}", flush=True)
        return
    # Capture ownership before AKS disappears; never derive node groups from MC_* names.
    node_groups = discover_node_groups(cli, name)
    print(f"Associated node groups: {json.dumps(node_groups)}", flush=True)
    submitted_at = datetime.now(timezone.utc).isoformat()
    submit_delete(cli, name)
    recovered_since_submission = False
    retries = 0
    while True:
        cli.remaining()
        remaining = {
            group: snapshot for group in [name, *node_groups]
            if (snapshot := get_group(cli, group)) is not None
        }
        if not remaining:
            print(f"Resource group and associated node groups deleted: {name}", flush=True)
            return
        print(f"Waiting for deletion: {', '.join(remaining)}", flush=True)
        eligible = [name] if name in remaining else []
        eligible.extend(
            group for group, owners in node_groups.items()
            if group in remaining and owners_allow_upgrade_cancellation(
                cli, owners, remaining[group], remaining.get(name), submitted_at,
            )
        )
        recovered = cancel_active_vmss_rolling_upgrades(cli, eligible)
        recovered_since_submission = recovered_since_submission or recovered
        if name in remaining:
            failure = latest_delete_failure(cli, target["id"], submitted_at)
            if failure is not None and remaining[name]["properties"]["provisioningState"] != "Deleting":
                print(f"Resource-group deletion failed: {json.dumps(failure)}", flush=True)
                if not recovered_since_submission or retries >= 2:
                    raise CleanupError(f"Deletion failed without further recovery available: {name}")
                # A failed ARM operation does not resume when its blocker is removed.
                submitted_at = datetime.now(timezone.utc).isoformat()
                submit_delete(cli, name)
                retries += 1
                recovered_since_submission = False
        cli.sleep(poll_interval_seconds)


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    delete = commands.add_parser("delete", help="Delete a resource group with rolling-upgrade recovery")
    delete.add_argument("--subscription", required=True)
    delete.add_argument("--resource-group", required=True)
    delete.add_argument("--timeout-seconds", required=True, type=positive_int)
    delete.add_argument("--poll-interval-seconds", required=True, type=positive_int)
    args = parser.parse_args()
    cli = AzureCli(args.subscription, args.timeout_seconds)
    try:
        delete_resource_group(cli, args.resource_group, args.poll_interval_seconds)
    except CleanupError as error:
        print(f"RESOURCE GROUP CLEANUP FAILED: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
