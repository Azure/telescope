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


def _setup_fakes(
    tmp_path: Path, *, relabel_should_fail: bool = False
) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az_log = tmp_path / "az-log.jsonl"
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
    if relabel_should_fail:
        _write_executable(
            relabel,
            """#!/usr/bin/env bash
set -euo pipefail
echo "fake relabel: intentional failure" >&2
exit 1
""",
        )
    else:
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
    relabel_should_fail: bool = False,
    lifecycle_only: bool = False,
) -> subprocess.CompletedProcess[str]:
    fake_bin, az_log, relabel_log = _setup_fakes(
        tmp_path, relabel_should_fail=relabel_should_fail
    )
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
            "PRESERVE_LIFECYCLE_ONLY": "true" if lifecycle_only else "false",
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
    worker_status_1 = role_1 / "worker-status-mesh-1.json"
    worker_status_1.write_text(
        '{"workload_valid": true, "telemetry_valid": true}\n',
        encoding="utf-8",
    )
    worker_status_2 = role_2 / "worker-status-mesh-2.json"
    worker_status_2.write_text(
        '{"workload_valid": true, "telemetry_valid": false}\n',
        encoding="utf-8",
    )
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
    scenario_evidence = scenario_dir / "scenario-evidence.json"
    scenario_evidence.write_text('{"measurement_valid": true}\n', encoding="utf-8")
    mock_reconcile_before = scenario_dir / "mock-layer-reconcile-before.json"
    mock_reconcile_before.write_text('{"success": true}\n', encoding="utf-8")
    mock_reconcile_after = scenario_dir / "mock-layer-reconcile-after.json"
    mock_reconcile_after.write_text('{"success": true}\n', encoding="utf-8")
    event_throughput_evidence = role_1 / "EventThroughputEvidence.json"
    event_throughput_evidence.write_text('{"valid": true}\n', encoding="utf-8")
    pod_churn_evidence = role_2 / "PodChurnEvidence.json"
    pod_churn_evidence.write_text('{"valid": true}\n', encoding="utf-8")
    policy_scale_evidence = role_1 / "PolicyScaleEvidence.json"
    policy_scale_evidence.write_text('{"valid": true}\n', encoding="utf-8")

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
    assert summary["uploaded_lifecycle_count"] == 13
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
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "worker-status-mesh-1.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "worker-status-mesh-2.json",
        "feature-branch/lifecycle/share-infra-1/run-123/scenario-policy.json",
        "feature-branch/lifecycle/share-infra-1/run-123/scenario-evidence.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "mock-layer-reconcile-before.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "mock-layer-reconcile-after.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "NodeChurnTimings_mesh-1.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "ApiserverFailureTimings_mesh-1.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "IsolationChurnTimings_mesh-2.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "mesh-1-EventThroughputEvidence.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "mesh-2-PodChurnEvidence.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "mesh-1-PolicyScaleEvidence.json",
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


# --- Fix: failure-scope classification (infrastructure_failure vs.
# scenario_incomplete) ------------------------------------------------------


def test_missing_snapshot_classified_as_scenario_incomplete(tmp_path):
    """A scenario-local missing role snapshot must NOT be reported as an
    infrastructure_failure -- only as scenario_incomplete -- so callers
    (execute.yml) know this scenario's own measurement is invalid without
    treating it as a suite-stopping shared-infrastructure problem."""
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
    assert summary["missing_snapshot_roles"] == ["mesh-2"]
    assert summary["scenario_incomplete"] is True
    assert summary["infrastructure_failure"] is False


def test_invalid_worker_summary_classified_as_scenario_incomplete(tmp_path):
    """A missing/invalid worker summary is a scenario-local artifact gap,
    not a shared-infrastructure failure."""
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"

    result = _run_helper(tmp_path, scenario_dir, worker_summary)

    assert result.returncode != 0
    summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is False
    assert summary["worker_summary_valid"] is False
    assert summary["scenario_incomplete"] is True
    assert summary["infrastructure_failure"] is False
    assert any(
        "Worker summary is missing or invalid" in error
        for error in summary["errors"]
    )


def test_relabel_failure_classified_as_scenario_incomplete(tmp_path):
    """A relabel-script failure is scenario-local (this scenario's own
    snapshot blocks couldn't be relabeled) -- not shared-infrastructure."""
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    _create_snapshot(scenario_dir / "mesh-1", "snapshot-a")
    _write_worker_summary(worker_summary, ["mesh-1"])

    result = _run_helper(
        tmp_path,
        scenario_dir,
        worker_summary,
        relabel_should_fail=True,
    )

    assert result.returncode != 0
    summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is False
    assert summary["scenario_incomplete"] is True
    assert summary["infrastructure_failure"] is False
    assert any(
        "Prometheus snapshot relabeling failed" in error
        for error in summary["errors"]
    )


def test_lifecycle_upload_failure_classified_as_infrastructure_failure(tmp_path):
    """A blob upload failure for a small lifecycle file is a shared
    infrastructure problem (storage account/auth/networking), not a
    scenario-local gap -- callers MUST stop the suite."""
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    _create_snapshot(scenario_dir / "mesh-1", "snapshot-a")
    _write_worker_summary(worker_summary, ["mesh-1"])
    scenario_policy = scenario_dir / "scenario-policy.json"
    scenario_policy.write_text('{"success": true}\n', encoding="utf-8")

    result = _run_helper(
        tmp_path,
        scenario_dir,
        worker_summary,
        fail_upload_pattern="lifecycle/share-infra-1/run-123/scenario-policy.json",
    )

    assert result.returncode != 0
    summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is False
    assert summary["infrastructure_failure"] is True
    assert summary["scenario_incomplete"] is False
    assert any("Upload failed" in error for error in summary["errors"])


def test_snapshot_upload_failure_is_also_infrastructure_failure(tmp_path):
    """Snapshot upload failures are classified infra (per requirement 1),
    even though the resulting "missing verified snapshot" detection also
    marks the scenario incomplete -- both flags may legitimately be true
    at once; infrastructure_failure must still be set so callers stop."""
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    _create_snapshot(scenario_dir / "mesh-1", "snapshot-a")
    _write_worker_summary(worker_summary, ["mesh-1"])

    result = _run_helper(
        tmp_path,
        scenario_dir,
        worker_summary,
        fail_upload_pattern="prom-snapshot-mesh-1",
    )

    assert result.returncode != 0
    summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is False
    assert summary["infrastructure_failure"] is True


# --- Fix: PRESERVE_LIFECYCLE_ONLY final-lifecycle-upload mode --------------


def test_lifecycle_only_mode_success(tmp_path):
    """Lifecycle-only mode uploads only the small, final durable-state
    files -- to a DISTINCT summary file -- skipping worker-summary/
    snapshot/relabel requirements entirely."""
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "scenario-policy.json").write_text(
        '{"suite_continue": true}\n', encoding="utf-8"
    )
    (scenario_dir / "scenario-evidence.json").write_text(
        '{"measurement_valid": true}\n', encoding="utf-8"
    )
    (scenario_dir / "scenario-health-gate.json").write_text(
        '{"healthy": true}\n', encoding="utf-8"
    )
    (scenario_dir / "mock-layer-reconcile-before.json").write_text(
        '{"success": true}\n', encoding="utf-8"
    )
    (scenario_dir / "mock-layer-reconcile-after.json").write_text(
        '{"success": true}\n', encoding="utf-8"
    )
    (scenario_dir / "artifact-preservation-summary.json").write_text(
        '{"success": true}\n', encoding="utf-8"
    )

    result = _run_helper(
        tmp_path, scenario_dir, worker_summary, lifecycle_only=True
    )

    assert result.returncode == 0, result.stderr
    final_summary_path = scenario_dir / "artifact-preservation-final-summary.json"
    assert final_summary_path.exists()
    assert not (scenario_dir / "artifact-preservation-summary.json.partial").exists()
    # The early (non-final) summary file must not have been overwritten by
    # this lifecycle-only pass -- it wrote its own distinct summary file.
    early_summary = json.loads(
        (scenario_dir / "artifact-preservation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert early_summary == {"success": True}

    summary = json.loads(final_summary_path.read_text(encoding="utf-8"))
    assert summary["success"] is True
    assert summary["lifecycle_only"] is True
    assert summary["infrastructure_failure"] is False
    assert summary["scenario_incomplete"] is False
    assert summary["uploaded_snapshot_count"] == 0

    assert not (tmp_path / "relabel-log.json").exists()
    calls = _az_calls(tmp_path / "az-log.jsonl")
    uploaded_names = {
        call[call.index("--name") + 1]
        for call in calls
        if call[:3] == ["storage", "blob", "upload"]
    }
    assert uploaded_names == {
        "feature-branch/lifecycle/share-infra-1/run-123/scenario-policy.json",
        "feature-branch/lifecycle/share-infra-1/run-123/scenario-evidence.json",
        "feature-branch/lifecycle/share-infra-1/run-123/scenario-health-gate.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "mock-layer-reconcile-before.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "mock-layer-reconcile-after.json",
        "feature-branch/lifecycle/share-infra-1/run-123/"
        "artifact-preservation-summary.json",
    }
    # worker-summary.json is already durable from the earlier (non-lifecycle
    # -only) pass -- must NOT be re-uploaded here.
    assert not any(name.endswith("worker-summary.json") for name in uploaded_names)


def test_lifecycle_only_mode_infrastructure_failure(tmp_path):
    """An upload failure during the final lifecycle-only pass must be
    classified infrastructure_failure=true so execute.yml stops the suite,
    even though this pass never touches worker/snapshot state."""
    scenario_dir = tmp_path / "share-infra-1"
    worker_summary = scenario_dir / "worker-summary.json"
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "scenario-policy.json").write_text(
        '{"suite_continue": true}\n', encoding="utf-8"
    )

    result = _run_helper(
        tmp_path,
        scenario_dir,
        worker_summary,
        lifecycle_only=True,
        fail_upload_pattern="scenario-policy.json",
    )

    assert result.returncode != 0
    summary = json.loads(
        (scenario_dir / "artifact-preservation-final-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["success"] is False
    assert summary["lifecycle_only"] is True
    assert summary["infrastructure_failure"] is True
    assert summary["scenario_incomplete"] is False
