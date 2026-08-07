"""Behavior checks for the Azure VNet/subnet stabilization barrier."""

import json
import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPOSITORY_ROOT / "steps" / "terraform" / "wait-for-azure-network.sh"
)
AZURE_MAIN_PATH = (
    REPOSITORY_ROOT / "modules" / "terraform" / "azure" / "main.tf"
)


def _write_fake_az(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
attempt_file="$AZ_ATTEMPT_FILE"
attempt=$(( $(cat "$attempt_file" 2>/dev/null || echo 0) + 1 ))
echo "$attempt" > "$attempt_file"
if [ "$NETWORK_TEST_MODE" = "eventual" ] && [ "$attempt" -ge 2 ]; then
  state="Succeeded"
  delegations='[{"serviceName":"Microsoft.ContainerService/managedClusters"}]'
else
  state="Updating"
  delegations='[]'
fi
printf '{"provisioningState":"%s","subnets":[{"name":"node","provisioningState":"%s","delegations":[]},{"name":"pod","provisioningState":"%s","delegations":%s}]}' \
  "$state" "$state" "$state" "$delegations"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run(tmp_path: Path, mode: str, wait_seconds: int):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_az(bin_dir / "az")
    requirements = [
        {"name": "node", "requiredDelegations": []},
        {
            "name": "pod",
            "requiredDelegations": [
                "Microsoft.ContainerService/managedClusters"
            ],
        },
    ]
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ARM_SUBSCRIPTION_ID": "test-subscription",
            "NETWORK_RESOURCE_GROUP": "test-rg",
            "NETWORK_VNET_NAME": "test-vnet",
            "NETWORK_SUBNET_REQUIREMENTS_JSON": json.dumps(requirements),
            "NETWORK_STABILIZATION_WAIT_SECONDS": str(wait_seconds),
            "NETWORK_STABILIZATION_POLL_SECONDS": "1",
            "NETWORK_STABILIZATION_QUERY_TIMEOUT_SECONDS": "2",
            "NETWORK_TEST_MODE": mode,
            "AZ_ATTEMPT_FILE": str(tmp_path / "attempts"),
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def test_network_barrier_waits_for_subnet_delegation(tmp_path):
    result = _run(tmp_path, "eventual", 5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pending=" in result.stdout
    assert "all required subnets are stable" in result.stdout


def test_network_barrier_times_out_without_delegation(tmp_path):
    result = _run(tmp_path, "stuck", 2)

    assert result.returncode != 0
    assert "missingDelegations" in result.stdout
    assert "did not stabilize" in result.stderr


def test_all_aks_modules_depend_on_network_barrier():
    main = AZURE_MAIN_PATH.read_text(encoding="utf-8")

    assert 'resource "terraform_data" "network_wait_succeeded"' in main
    assert "wait-for-azure-network.sh" in main
    assert main.count("terraform_data.network_wait_succeeded") == 3
