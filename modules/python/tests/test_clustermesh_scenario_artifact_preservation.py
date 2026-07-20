"""Tests for per-scenario ClusterMesh artifact preservation."""

import json
import os
import subprocess
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    REPO_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "telemetry"
    / "preserve-scenario-artifacts.sh"
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _create_snapshot(role_dir: Path, name: str) -> Path:
    source = role_dir / f"{name}-source"
    block = source / "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    block.mkdir(parents=True)
    (block / "meta.json").write_text("{}\n", encoding="utf-8")
    snapshot = role_dir / f"prom-snapshot-{role_dir.name}-{name}.tar.gz"
    with tarfile.open(snapshot, "w:gz") as archive:
        archive.add(source, arcname=name)
    return snapshot


def _write_worker_summary(path: Path, succeeded_roles: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "succeeded_count": len(succeeded_roles),
                "failed_count": 0,
                "succeeded_roles": succeeded_roles,
                "failed_roles": [],
                "results": [
                    {"role": role, "exit_code": 0} for role in succeeded_roles
                ],
            }
        ),
        encoding="utf-8",
    )


def _setup_fakes(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az_log = tmp_path / "az-log.jsonl"
    az_state = tmp_path / "az-state.json"
    relabel_log = tmp_path / "relabel-log.json"
    fake_az = fake_bin / "az"
    _write_executable(
        fake_az,
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log_path = Path(os.environ["FAKE_AZ_LOG"])
state_path = Path(os.environ["FAKE_AZ_STATE"])
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")

if args[:2] == ["account", "set"]:
    sys.exit(0)
if args[:2] == ["account", "show"]:
    print(os.environ["FAKE_AZ_SUBSCRIPTION_ID"])
    sys.exit(0)

def option(name):
    return args[args.index(name) + 1]

state = (
    json.loads(state_path.read_text(encoding="utf-8"))
    if state_path.exists()
    else {}
)
if args[:3] == ["storage", "blob", "upload"]:
    blob_name = option("--name")
    fail_pattern = os.environ.get("FAKE_AZ_FAIL_UPLOAD_PATTERN", "")
    if fail_pattern and fail_pattern in blob_name:
        sys.exit(17)
    state[blob_name] = Path(option("--file")).stat().st_size
    state_path.write_text(json.dumps(state), encoding="utf-8")
    sys.exit(0)
if args[:3] == ["storage", "blob", "show"]:
    blob_name = option("--name")
    if blob_name not in state:
        sys.exit(18)
    print(state[blob_name])
    sys.exit(0)
sys.exit(19)
""",
    )
    relabel = tmp_path / "fake-relabel.sh"
    _write_executable(
        relabel,
        """#!/usr/bin/env bash
set -euo pipefail
jq -n \
  --arg report_dir "$CL2_REPORT_DIR" \
  --arg run "$RUN_ID" \
  --arg build "$BUILD_ID" \
  --arg tier "$SNAPSHOT_TIER" \
  '{report_dir: $report_dir, run: $run, build: $build, tier: $tier}' \
  > "$FAKE_RELABEL_LOG"
""",
    )
    return fake_bin, az_log, relabel_log


def _run_helper(
    tmp_path: Path,
    scenario_dir: Path,
    worker_summary: Path,
    *,
    enabled: str = "true",
    target: str = "blob",
    fail_upload_pattern: str = "",
) -> subprocess.CompletedProcess[str]:
    fake_bin, az_log, relabel_log = _setup_fakes(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "SCENARIO_REPORT_DIR": str(scenario_dir),
            "SCENARIO_NAME": "share-infra-1",
            "RUN_ID": "run-123",
            "BUILD_ID": "build-456",
            "SNAPSHOT_TIER": "tier-100",
            "BUILD_BRANCH": "feature-branch",
            "STORAGE_ACCOUNT_NAME": "snapaccount",
            "CONTAINER_NAME": "snapshots",
            "TARGET_SUBSCRIPTION_ID": "subscription-1",
            "WORKER_SUMMARY_FILE": str(worker_summary),
            "RELABEL_SCRIPT": str(tmp_path / "fake-relabel.sh"),
            "CL2_PROM_SNAPSHOT_ENABLED": enabled,
            "CL2_PROM_SNAPSHOT_TARGET": target,
            "FAKE_AZ_LOG": str(az_log),
            "FAKE_AZ_STATE": str(tmp_path / "az-state.json"),
            "FAKE_AZ_SUBSCRIPTION_ID": "subscription-1",
            "FAKE_AZ_FAIL_UPLOAD_PATTERN": fail_upload_pattern,
            "FAKE_RELABEL_LOG": str(relabel_log),
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _az_calls(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_success_uploads_verifies_and_deletes_snapshots(tmp_path):
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    role_1 = scenario_dir / "mesh-1"
    role_2 = scenario_dir / "mesh-2"
    snapshot_1 = _create_snapshot(role_1, "snapshot-a")
    snapshot_2 = _create_snapshot(role_2, "snapshot-b")
    _write_worker_summary(worker_summary, ["mesh-1", "mesh-2"])
    audit = role_1 / "telemetry" / "telemetry-audit-self-hosted.json"
    audit.parent.mkdir(parents=True)
    audit.write_text('{"complete": true}\n', encoding="utf-8")
    acns = role_2 / "telemetry" / "acns" / "summary.json"
    acns.parent.mkdir(parents=True)
    acns.write_text('{"complete": true}\n', encoding="utf-8")
    scenario_policy = scenario_dir / "scenario-policy.json"
    scenario_policy.write_text('{"success": true}\n', encoding="utf-8")
    node_churn = role_1 / "NodeChurnTimings_mesh-1.json"
    node_churn.write_text('{"operations": []}\n', encoding="utf-8")
    apiserver_failure = role_1 / "ApiserverFailureTimings_mesh-1.json"
    apiserver_failure.write_text('{"operations": []}\n', encoding="utf-8")
    isolation_churn = role_2 / "IsolationChurnTimings_mesh-2.json"
    isolation_churn.write_text('{"operations": []}\n', encoding="utf-8")

    result = _run_helper(tmp_path, scenario_dir, worker_summary)

    assert result.returncode == 0, result.stderr
    assert not snapshot_1.exists()
    assert not snapshot_2.exists()
    assert audit.exists()
    assert acns.exists()
    summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is True
    assert summary["expected_successful_worker_count"] == 2
    assert summary["uploaded_snapshot_count"] == 2
    assert summary["uploaded_snapshot_roles"] == ["mesh-1", "mesh-2"]
    assert summary["missing_snapshot_roles"] == []
    assert summary["uploaded_snapshot_bytes"] > 0
    assert summary["uploaded_audit_count"] == 1
    assert summary["uploaded_acns_count"] == 1
    assert summary["uploaded_lifecycle_count"] == 5
    assert summary["uploaded_lifecycle_bytes"] > 0

    relabel = json.loads(
        (tmp_path / "relabel-log.json").read_text(encoding="utf-8")
    )
    assert relabel == {
        "report_dir": str(scenario_dir),
        "run": "run-123",
        "build": "build-456",
        "tier": "tier-100",
    }
    calls = _az_calls(tmp_path / "az-log.jsonl")
    assert calls[0][:2] == ["account", "set"]
    assert calls[1][:2] == ["account", "show"]
    uploaded_names = {
        call[call.index("--name") + 1]
        for call in calls
        if call[:3] == ["storage", "blob", "upload"]
    }
    assert uploaded_names == {
        "feature-branch/share-infra-1/run-123/"
        "prom-snapshot-mesh-1-snapshot-a.tar.gz",
        "feature-branch/share-infra-1/run-123/"
        "prom-snapshot-mesh-2-snapshot-b.tar.gz",
        "feature-branch/telemetry-audit-self-hosted/share-infra-1/run-123/"
        "telemetry-audit-self-hosted-mesh-1.json",
        "feature-branch/acns/share-infra-1/run-123/mesh-2/summary.json",
        "feature-branch/lifecycle/share-infra-1/run-123/worker-summary.json",
        "feature-branch/lifecycle/share-infra-1/run-123/scenario-policy.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "NodeChurnTimings_mesh-1.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "ApiserverFailureTimings_mesh-1.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "IsolationChurnTimings_mesh-2.json",
    }
    upload_count = sum(
        call[:3] == ["storage", "blob", "upload"] for call in calls
    )
    show_count = sum(call[:3] == ["storage", "blob", "show"] for call in calls)
    assert show_count == upload_count


def test_missing_successful_worker_snapshot_fails(tmp_path):
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    snapshot = _create_snapshot(scenario_dir / "mesh-1", "snapshot-a")
    _write_worker_summary(worker_summary, ["mesh-1", "mesh-2"])

    result = _run_helper(tmp_path, scenario_dir, worker_summary)

    assert result.returncode != 0
    assert not snapshot.exists()
    summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is False
    assert summary["uploaded_snapshot_roles"] == ["mesh-1"]
    assert summary["missing_snapshot_roles"] == ["mesh-2"]


def test_snapshot_upload_failure_preserves_local_file(tmp_path):
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    snapshot = _create_snapshot(scenario_dir / "mesh-1", "snapshot-a")
    _write_worker_summary(worker_summary, ["mesh-1"])

    result = _run_helper(
        tmp_path,
        scenario_dir,
        worker_summary,
        fail_upload_pattern="prom-snapshot-mesh-1",
    )

    assert result.returncode != 0
    assert snapshot.exists()
    summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is False
    assert summary["uploaded_snapshot_count"] == 0
    assert summary["missing_snapshot_roles"] == ["mesh-1"]
    assert any("Upload failed" in error for error in summary["errors"])


def test_disabled_snapshots_are_noop(tmp_path):
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    snapshot = _create_snapshot(scenario_dir / "mesh-1", "snapshot-a")
    _write_worker_summary(worker_summary, ["mesh-1"])

    result = _run_helper(
        tmp_path,
        scenario_dir,
        worker_summary,
        enabled="false",
    )

    assert result.returncode == 0, result.stderr
    assert snapshot.exists()
    assert _az_calls(tmp_path / "az-log.jsonl") == []
    assert not (tmp_path / "relabel-log.json").exists()
    summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is True
    assert summary["no_op_reason"] == "snapshots-disabled"
    assert summary["expected_successful_worker_count"] == 1
    assert summary["uploaded_snapshot_count"] == 0
