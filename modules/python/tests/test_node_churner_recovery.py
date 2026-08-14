"""Local smoke tests for node-churn finalizer recovery."""

import json
import os
from pathlib import Path
import subprocess


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
NODE_CHURNER = (
    REPOSITORY_ROOT
    / "modules"
    / "python"
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "node-churner.sh"
)


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_finalizer_uncordons_surviving_node_and_records_health(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_file = tmp_path / "unschedulable"
    state_file.write_text("1", encoding="utf-8")

    _write_executable(
        fake_bin / "az",
        """#!/bin/bash
set -euo pipefail
args="$*"
case "$args" in
  *"aks nodepool show"*"--query count"*) echo 2 ;;
  *"aks nodepool show"*"--query provisioningState"*) echo Succeeded ;;
  *"aks show"*"--query nodeResourceGroup"*) echo MC_test ;;
  *"vmss list"*) echo aks-default-test ;;
  *"vmss show"*"--query sku.capacity"*) echo 2 ;;
  *"aks nodepool scale"*) exit 0 ;;
  *) exit 0 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "kubectl",
        """#!/bin/bash
set -euo pipefail
args="$*"
if [[ "$args" == *"get nodes -o json"* ]]; then
  unsched=false
  if [[ "$(cat "$FAKE_STATE_FILE")" == "1" ]]; then
    unsched=true
  fi
  cat <<EOF
{"items":[
  {"metadata":{"name":"node-0"},"spec":{
    "providerID":"azure:///virtualMachineScaleSets/aks-default-test/virtualMachines/0",
    "unschedulable":${unsched}},"status":{"conditions":[{"type":"Ready","status":"True"}]}},
  {"metadata":{"name":"node-1"},"spec":{
    "providerID":"azure:///virtualMachineScaleSets/aks-default-test/virtualMachines/1",
    "unschedulable":false},"status":{"conditions":[{"type":"Ready","status":"True"}]}}
]}
EOF
elif [[ "$args" == *"get daemonset cilium -o json"* ]]; then
  echo '{"status":{"desiredNumberScheduled":3,"numberReady":3}}'
elif [[ "$args" == *" uncordon "* ]]; then
  echo 0 > "$FAKE_STATE_FILE"
elif [[ "$args" == *" get node "* ]]; then
  exit 0
else
  exit 0
fi
""",
    )

    report_dir = tmp_path / "report"
    sentinel_dir = tmp_path / "sentinels"
    report_dir.mkdir()
    sentinel_dir.mkdir()
    (sentinel_dir / "ready-clustermesh-1").touch()
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.touch()

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_STATE_FILE": str(state_file),
            "CL2_NODE_CHURN_FINALIZER_TIMEOUT_SECONDS": "2",
            "CL2_NODE_CHURN_RECOVERY_GRACE_SECONDS": "2",
            "CL2_NODE_CHURN_RECOVERY_POLL_SECONDS": "1",
        }
    )
    result = subprocess.run(
        [
            "bash",
            str(NODE_CHURNER),
            "node-churn-scale",
            "clustermesh-1",
            "test-rg",
            "default",
            str(report_dir),
            str(sentinel_dir),
            "1",
            "0",
            "5",
            "0",
            "1",
            "2",
            "10",
            str(kubeconfig),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    timing = json.loads(
        (report_dir / "NodeChurnTimings_clustermesh-1.json").read_text(
            encoding="utf-8"
        )
    )
    assert state_file.read_text(encoding="utf-8").strip() == "0"
    assert timing["cleanup_failed"] is False
    assert timing["final_provisioning_state"] == "Succeeded"
    assert timing["final_vmss_capacity"] == 2
    assert timing["final_node_count"] == 2
    assert timing["final_ready_node_count"] == 2
    assert timing["final_unschedulable_node_count"] == 0
    assert timing["final_cilium_desired"] == 3
    assert timing["final_cilium_ready"] == 3


def test_finalizer_nudges_unchanged_desired_count_to_restore_vmss(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capacity_file = tmp_path / "capacity"
    capacity_file.write_text("0", encoding="utf-8")
    desired_file = tmp_path / "desired"
    desired_file.write_text("2", encoding="utf-8")
    scale_log = tmp_path / "scale.log"

    _write_executable(
        fake_bin / "az",
        """#!/bin/bash
set -euo pipefail
args="$*"
case "$args" in
  *"aks nodepool show"*"--query count"*) cat "$FAKE_DESIRED_FILE" ;;
  *"aks nodepool show"*"--query provisioningState"*) echo Succeeded ;;
  *"aks show"*"--query nodeResourceGroup"*) echo MC_test ;;
  *"vmss list"*) echo aks-churnpool-test ;;
  *"vmss show"*"--query sku.capacity"*) cat "$FAKE_CAPACITY_FILE" ;;
  *"aks nodepool scale"*)
    target=""
    previous=""
    for arg in "$@"; do
      if [ "$previous" = "--node-count" ]; then target="$arg"; break; fi
      previous="$arg"
    done
    echo "$target" >> "$FAKE_SCALE_LOG"
    echo "$target" > "$FAKE_DESIRED_FILE"
    echo "$target" > "$FAKE_CAPACITY_FILE"
    ;;
  *) exit 0 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "kubectl",
        """#!/bin/bash
set -euo pipefail
args="$*"
if [[ "$args" == *"get nodes -o json"* ]]; then
  cat <<'EOF'
{"items":[
  {"metadata":{"name":"node-0"},"spec":{
    "providerID":"azure:///virtualMachineScaleSets/aks-churnpool-test/virtualMachines/0",
    "unschedulable":false},"status":{"conditions":[{"type":"Ready","status":"True"}]}},
  {"metadata":{"name":"node-1"},"spec":{
    "providerID":"azure:///virtualMachineScaleSets/aks-churnpool-test/virtualMachines/1",
    "unschedulable":false},"status":{"conditions":[{"type":"Ready","status":"True"}]}}
]}
EOF
elif [[ "$args" == *"get daemonset cilium -o json"* ]]; then
  echo '{"status":{"desiredNumberScheduled":2,"numberReady":2}}'
elif [[ "$args" == *" get node "* ]] || [[ "$args" == *" uncordon "* ]]; then
  exit 0
else
  exit 0
fi
""",
    )

    report_dir = tmp_path / "report"
    sentinel_dir = tmp_path / "sentinels"
    report_dir.mkdir()
    sentinel_dir.mkdir()
    (sentinel_dir / "ready-clustermesh-1").touch()
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.touch()

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_CAPACITY_FILE": str(capacity_file),
            "FAKE_DESIRED_FILE": str(desired_file),
            "FAKE_SCALE_LOG": str(scale_log),
            "CL2_NODE_CHURN_FINALIZER_TIMEOUT_SECONDS": "5",
            "CL2_NODE_CHURN_POLL_SECONDS": "1",
        }
    )
    result = subprocess.run(
        [
            "bash",
            str(NODE_CHURNER),
            "node-churn-scale",
            "clustermesh-1",
            "test-rg",
            "churnpool",
            str(report_dir),
            str(sentinel_dir),
            "1",
            "0",
            "5",
            "0",
            "1",
            "2",
            "10",
            str(kubeconfig),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert scale_log.read_text(encoding="utf-8").splitlines() == ["3", "2"]
    timing = json.loads(
        (report_dir / "NodeChurnTimings_clustermesh-1.json").read_text(
            encoding="utf-8"
        )
    )
    assert timing["cleanup_failed"] is False
    assert timing["final_vmss_capacity"] == 2


def test_replace_refuses_to_remove_every_node(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az_log = tmp_path / "az.log"

    _write_executable(
        fake_bin / "az",
        """#!/bin/bash
set -euo pipefail
echo "$*" >> "$FAKE_AZ_LOG"
args="$*"
case "$args" in
  *"aks nodepool show"*"--query count"*) echo 2 ;;
  *"aks nodepool show"*"--query provisioningState"*) echo Succeeded ;;
  *"aks show"*"--query nodeResourceGroup"*) echo MC_test ;;
  *"vmss list"*) echo aks-churnpool-test ;;
  *"vmss show"*"--query sku.capacity"*) echo 2 ;;
  *) exit 0 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "kubectl",
        """#!/bin/bash
set -euo pipefail
args="$*"
if [[ "$args" == *"get nodes -o json"* ]]; then
  cat <<'EOF'
{"items":[
  {"metadata":{"name":"node-0"},"spec":{
    "providerID":"azure:///virtualMachineScaleSets/aks-churnpool-test/virtualMachines/0",
    "unschedulable":false},"status":{"conditions":[{"type":"Ready","status":"True"}]}},
  {"metadata":{"name":"node-1"},"spec":{
    "providerID":"azure:///virtualMachineScaleSets/aks-churnpool-test/virtualMachines/1",
    "unschedulable":false},"status":{"conditions":[{"type":"Ready","status":"True"}]}}
]}
EOF
elif [[ "$args" == *"get daemonset cilium -o json"* ]]; then
  echo '{"status":{"desiredNumberScheduled":2,"numberReady":2}}'
else
  exit 0
fi
""",
    )

    report_dir = tmp_path / "report"
    sentinel_dir = tmp_path / "sentinels"
    report_dir.mkdir()
    sentinel_dir.mkdir()
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.touch()
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_AZ_LOG": str(az_log),
            "CL2_NODE_CHURN_FINALIZER_TIMEOUT_SECONDS": "2",
        }
    )
    result = subprocess.run(
        [
            "bash",
            str(NODE_CHURNER),
            "node-churn-replace",
            "clustermesh-1",
            "test-rg",
            "churnpool",
            str(report_dir),
            str(sentinel_dir),
            "1",
            "1",
            "1",
            "0",
            "2",
            "2",
            "10",
            str(kubeconfig),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    timing = json.loads(
        (report_dir / "NodeChurnTimings_clustermesh-1.json").read_text(
            encoding="utf-8"
        )
    )
    assert timing["scenario_valid"] is False
    assert "delete-instances" not in az_log.read_text(encoding="utf-8")
