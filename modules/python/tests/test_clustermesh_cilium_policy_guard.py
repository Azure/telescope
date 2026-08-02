"""Tests for the AKS Cilium policy drift guard."""

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GUARD_SCRIPT = (
    REPOSITORY_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "telemetry"
    / "ensure-cilium-policy.sh"
)


def _write_inventory(path):
    path.write_text(
        json.dumps(
            [
                {"role": "mesh-1", "name": "cluster-1", "rg": "test-rg"},
                {"role": "mesh-2", "name": "cluster-2", "rg": "test-rg"},
            ]
        ),
        encoding="utf-8",
    )


def _write_fake_commands(fake_bin):
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "az $*" >> "$COMMAND_LOG"
            if [ "${1:-} ${2:-}" = "aks show" ]; then
              printf '%s\\n' '{"networkPolicy":"cilium","networkDataplane":"cilium","provisioningState":"Succeeded"}'
            elif [ "${1:-} ${2:-}" = "aks update" ]; then
              touch "$STATE_FILE"
            else
              echo "Unexpected az command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)

    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "kubectl $*" >> "$COMMAND_LOG"
            if [[ " $* " == *" get configmap cilium-config -o json "* ]]; then
              policy=never
              [ ! -f "$STATE_FILE" ] || policy=default
              printf '{"metadata":{"resourceVersion":"10"},"data":{"enable-policy":"%s"}}\\n' "$policy"
            elif [[ " $* " == *" get daemonset cilium -o json "* ]]; then
              printf '%s\\n' '{"metadata":{"generation":2},"spec":{"template":{"metadata":{"annotations":{"cilium.io/cilium-configmap-checksum":"abc"}}}},"status":{"desiredNumberScheduled":2,"numberReady":2,"updatedNumberScheduled":2,"observedGeneration":2}}'
            else
              echo "Unexpected kubectl command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_kubectl.chmod(fake_kubectl.stat().st_mode | stat.S_IXUSR)


def test_guard_repairs_all_clusters_after_policy_drift(tmp_path):
    inventory = tmp_path / "clusters.json"
    output = tmp_path / "guard.json"
    state_root = tmp_path / "state-root"
    state_file = tmp_path / "reasserted"
    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_inventory(inventory)
    _write_fake_commands(fake_bin)
    environment = os.environ.copy()
    environment.update(
        {
            "CLUSTERS_FILE": str(inventory),
            "OUTPUT_FILE": str(output),
            "STATE_ROOT": str(state_root),
            "TARGET_SUBSCRIPTION_ID": "test-subscription",
            "AKS_CILIUM_POLICY_GUARD_TIMEOUT_SECONDS": "1",
            "AKS_CILIUM_POLICY_GUARD_QUIET_SECONDS": "0",
            "AKS_CILIUM_POLICY_GUARD_POLL_SECONDS": "1",
            "AKS_CILIUM_POLICY_GUARD_REPAIR_ENABLED": "true",
            "STATE_FILE": str(state_file),
            "COMMAND_LOG": str(command_log),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["success"] is True
    assert report["repaired"] is True
    assert report["drift_detected"] is True
    assert command_log.read_text(encoding="utf-8").count("az aks update") == 2


def test_guard_refuses_recurrent_policy_drift(tmp_path):
    inventory = tmp_path / "clusters.json"
    output = tmp_path / "guard.json"
    state_root = tmp_path / "state-root"
    state_root.mkdir()
    (state_root / "repair-used").write_text("previous\n", encoding="utf-8")
    state_file = tmp_path / "reasserted"
    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_inventory(inventory)
    _write_fake_commands(fake_bin)
    environment = os.environ.copy()
    environment.update(
        {
            "CLUSTERS_FILE": str(inventory),
            "OUTPUT_FILE": str(output),
            "STATE_ROOT": str(state_root),
            "TARGET_SUBSCRIPTION_ID": "test-subscription",
            "STATE_FILE": str(state_file),
            "COMMAND_LOG": str(command_log),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 1
    assert "drift recurred" in result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["reason"] == "policy_drift_recurred"
    assert "az aks update" not in command_log.read_text(encoding="utf-8")


def test_guard_fails_closed_without_unsupported_repair(tmp_path):
    inventory = tmp_path / "clusters.json"
    output = tmp_path / "guard.json"
    state_root = tmp_path / "state-root"
    state_file = tmp_path / "reasserted"
    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_inventory(inventory)
    _write_fake_commands(fake_bin)
    environment = os.environ.copy()
    environment.update(
        {
            "CLUSTERS_FILE": str(inventory),
            "OUTPUT_FILE": str(output),
            "STATE_ROOT": str(state_root),
            "TARGET_SUBSCRIPTION_ID": "test-subscription",
            "STATE_FILE": str(state_file),
            "COMMAND_LOG": str(command_log),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["reason"] == "cilium_policy_or_rollout_drift"
    assert "az aks update" not in command_log.read_text(encoding="utf-8")
