"""Tests for the file-only scenario evidence validator (scenario_evidence.py).

These tests build small on-disk report-dir trees under pytest's `tmp_path`
and drive `scenario_evidence.main()` directly (no subprocess), asserting on
both the process exit code and the written evidence JSON's `checks`/
`reasons`/`counts` fields.
"""

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "scenario_evidence.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "clusterloader2_clustermesh_scenario_evidence",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
scenario_evidence = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(scenario_evidence)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _junit_xml(testcases=(("clustermesh-scale-test overall", False),)) -> str:
    body = "".join(
        f'<testcase name="{name}" classname="ClusterLoaderV2" time="1.0">'
        + ("<failure>boom</failure>" if failed else "")
        + "</testcase>"
        for name, failed in testcases
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<testsuite name="ClusterLoaderV2" tests="{len(testcases)}" '
        f'failures="{sum(1 for _, f in testcases if f)}" errors="0" time="1.0">'
        f"{body}</testsuite>"
    )


def _worker_summary(cluster_count, succeeded_roles, failed_roles=()):
    return {
        "schema_version": 1,
        "total_workers": cluster_count,
        "succeeded_count": len(succeeded_roles),
        "failed_count": len(failed_roles),
        "succeeded_roles": sorted(succeeded_roles),
        "failed_roles": sorted(failed_roles),
    }


def _make_common_fixture(tmp_path, scenario, cluster_count=None, roles=("mesh-1", "mesh-2")):
    """Write worker-summary + valid junit.xml for every role; return (report_dir, worker_summary_path).

    `cluster_count` defaults to `len(roles)` so callers that only care
    about a subset of the contract (e.g. a single-role target-scoped
    scenario) don't have to separately keep two role counts in sync.
    """
    if cluster_count is None:
        cluster_count = len(roles)
    report_dir = tmp_path / scenario
    for role in roles:
        _write_text(report_dir / role / "junit.xml", _junit_xml())
    worker_summary_path = tmp_path / "worker-summary.json"
    _write_json(worker_summary_path, _worker_summary(cluster_count, roles))
    return report_dir, worker_summary_path


def _run(tmp_path, scenario, report_dir, worker_summary_path, cluster_count=2, extra_args=None):
    output_path = tmp_path / "evidence.json"
    argv = [
        "--scenario", scenario,
        "--report-dir", str(report_dir),
        "--worker-summary", str(worker_summary_path),
        "--cluster-count", str(cluster_count),
        "--output", str(output_path),
    ]
    if extra_args:
        argv.extend(extra_args)
    rc = scenario_evidence.main(argv)
    result = json.loads(output_path.read_text(encoding="utf-8"))
    # Any .tmp sibling left behind would indicate the atomic write failed
    # to complete the rename.
    assert not output_path.with_suffix(output_path.suffix + ".tmp").exists()
    return rc, result


# ---------------------------------------------------------------------------
# Common contract
# ---------------------------------------------------------------------------

def test_unknown_scenario_fails_instead_of_using_common_only_as_valid(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "totally-unknown-scenario")
    rc, result = _run(tmp_path, "totally-unknown-scenario", report_dir, worker_summary)

    assert rc == 1
    assert result["measurement_valid"] is False
    assert result["known_scenario"] is False
    assert result["counts"]["contract"] == "common-only"
    assert any("known_scenario_contract" in reason for reason in result["reasons"])


def test_ordinary_junit_sli_failure_does_not_invalidate_common_contract(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "totally-unknown-scenario")
    # Overwrite mesh-1's junit with a failing (but well-formed) testcase —
    # this is measurement data, not a contract violation.
    _write_text(
        report_dir / "mesh-1" / "junit.xml",
        _junit_xml([("clustermesh-scale-test: [step: 01] some SLI check", True)]),
    )
    rc, result = _run(tmp_path, "totally-unknown-scenario", report_dir, worker_summary)

    assert rc == 1
    junit_check = next(
        check for check in result["checks"] if check["name"] == "junit_valid[mesh-1]"
    )
    assert junit_check["passed"] is True
    assert not any("junit_valid" in reason for reason in result["reasons"])


def test_malformed_worker_summary_json_is_a_contract_failure(tmp_path):
    report_dir = tmp_path / "scenario"
    worker_summary = tmp_path / "worker-summary.json"
    _write_text(worker_summary, "{not valid json")
    rc, result = _run(tmp_path, "totally-unknown-scenario", report_dir, worker_summary)

    assert rc == 1
    assert result["measurement_valid"] is False
    assert any("worker_summary_valid_json" in reason for reason in result["reasons"])


def test_total_workers_mismatch_is_a_contract_failure(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "totally-unknown-scenario", cluster_count=2)
    _write_json(worker_summary, _worker_summary(3, ["mesh-1", "mesh-2"]))
    rc, result = _run(tmp_path, "totally-unknown-scenario", report_dir, worker_summary, cluster_count=2)

    assert rc == 1
    assert any("worker_total_matches_cluster_count" in reason for reason in result["reasons"])


def test_inconsistent_succeeded_failed_counts_is_a_contract_failure(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "totally-unknown-scenario")
    bad_summary = _worker_summary(2, ["mesh-1", "mesh-2"])
    bad_summary["failed_count"] = 5  # inconsistent with failed_roles=[]
    _write_json(worker_summary, bad_summary)
    rc, result = _run(tmp_path, "totally-unknown-scenario", report_dir, worker_summary)

    assert rc == 1
    assert any("worker_summary_counts_internally_consistent" in reason for reason in result["reasons"])


def test_missing_junit_for_succeeded_role_is_a_contract_failure(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "totally-unknown-scenario")
    (report_dir / "mesh-2" / "junit.xml").unlink()
    rc, result = _run(tmp_path, "totally-unknown-scenario", report_dir, worker_summary)

    assert rc == 1
    assert any("junit_valid[mesh-2]" in reason for reason in result["reasons"])


def test_malformed_junit_xml_is_a_contract_failure(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "totally-unknown-scenario")
    _write_text(report_dir / "mesh-2" / "junit.xml", "<testsuite not closed")
    rc, result = _run(tmp_path, "totally-unknown-scenario", report_dir, worker_summary)

    assert rc == 1
    assert any("junit_valid[mesh-2]" in reason for reason in result["reasons"])


def test_invalid_invocation_missing_required_argument_exits_2():
    with pytest.raises(SystemExit) as exc_info:
        scenario_evidence.main(["--scenario", "propagation-probe"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# propagation-probe
# ---------------------------------------------------------------------------

def _propagation_row(probe_id, src="mesh-1", peer="mesh-2", timed_out=False):
    return {
        "src_cluster": src,
        "peer_cluster": peer,
        "probe_id": probe_id,
        "peer_timed_out": timed_out,
    }


def test_propagation_probe_valid_row_count_and_probe_ids(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "propagation-probe", cluster_count=3, roles=("mesh-1", "mesh-2", "mesh-3"))
    rows = []
    for probe_idx in range(2):  # probe_count=2
        for peer in ("mesh-2", "mesh-3"):  # min(cluster_count-1=2, peer_sample=5) = 2
            rows.append(_propagation_row(f"probe-{probe_idx}", peer=peer))
    _write_text(
        report_dir / "mesh-1" / "PropagationTimings.jsonl",
        "\n".join(json.dumps(row) for row in rows) + "\n",
    )
    rc, result = _run(
        tmp_path, "propagation-probe", report_dir, worker_summary, cluster_count=3,
        extra_args=["--propagation-probe-count", "2", "--propagation-peer-sample", "5"],
    )

    assert rc == 0
    assert result["counts"]["propagation_rows_total"] == 4
    assert result["counts"]["propagation_distinct_probe_ids"] == 2


def test_propagation_probe_wrong_row_count_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "propagation-probe", cluster_count=3, roles=("mesh-1", "mesh-2", "mesh-3"))
    rows = [_propagation_row("probe-0", peer="mesh-2")]  # only 1 row, expected 2*2=4
    _write_text(
        report_dir / "mesh-1" / "PropagationTimings.jsonl",
        "\n".join(json.dumps(row) for row in rows) + "\n",
    )
    rc, result = _run(
        tmp_path, "propagation-probe", report_dir, worker_summary, cluster_count=3,
        extra_args=["--propagation-probe-count", "2", "--propagation-peer-sample", "5"],
    )

    assert rc == 1
    assert any("propagation_row_count_matches_expected" in reason for reason in result["reasons"])


def test_propagation_probe_requires_exactly_one_file(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "propagation-probe", cluster_count=2)
    for role in ("mesh-1", "mesh-2"):
        _write_text(
            report_dir / role / "PropagationTimings.jsonl",
            json.dumps(_propagation_row("probe-0")) + "\n",
        )
    rc, result = _run(
        tmp_path, "propagation-probe", report_dir, worker_summary, cluster_count=2,
        extra_args=["--propagation-probe-count", "1", "--propagation-peer-sample", "1"],
    )

    assert rc == 1
    assert any("propagation_exactly_one_nonempty_file" in reason for reason in result["reasons"])


def test_propagation_probe_malformed_line_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "propagation-probe", cluster_count=2)
    _write_text(
        report_dir / "mesh-1" / "PropagationTimings.jsonl",
        json.dumps(_propagation_row("probe-0")) + "\n{not valid json\n",
    )
    rc, result = _run(
        tmp_path, "propagation-probe", report_dir, worker_summary, cluster_count=2,
        extra_args=["--propagation-probe-count", "1", "--propagation-peer-sample", "1"],
    )

    assert rc == 1
    assert any("propagation_no_malformed_lines" in reason for reason in result["reasons"])


# ---------------------------------------------------------------------------
# event-throughput
# ---------------------------------------------------------------------------

def _event_throughput_evidence(
    overlap=False,
    restart_generation_verified=True,
    expected_pod_count=8,
    pre_uids=None,
    post_uids=None,
):
    """Build a well-formed EventThroughputEvidence.json payload.

    By default builds exactly `expected_pod_count` distinct UIDs for both
    pre_restart and post_restart (matching what the real
    event-throughput-evidence.sh script emits on a clean run) with
    uid_count/unique_uid_count/query_success populated accordingly. Pass
    `pre_uids`/`post_uids` explicitly to construct partial or
    duplicate-UID snapshots for regression tests.
    """
    if pre_uids is None:
        pre_uids = [f"uid-pre-{i}" for i in range(expected_pod_count)]
    if post_uids is None:
        if overlap:
            post_uids = ["uid-pre-0"] + [f"uid-post-{i}" for i in range(expected_pod_count - 1)]
        else:
            post_uids = [f"uid-post-{i}" for i in range(expected_pod_count)]

    def _query_success():
        return {
            "deployment_count": True,
            "pod_count": True,
            "ready_pod_count": True,
            "pod_uids": True,
        }

    return {
        "capture_valid": True,
        "restart_valid": True,
        "pre_restart": {
            "expected_deployment_count": 4,
            "deployment_count": 4,
            "expected_pod_count": expected_pod_count,
            "pod_count": expected_pod_count,
            "ready_pod_count": expected_pod_count,
            "pod_uids": sorted(pre_uids),
            "uid_count": len(pre_uids),
            "unique_uid_count": len(set(pre_uids)),
            "generation": 0,
            "query_success": _query_success(),
        },
        "post_restart": {
            "deployment_count": 4,
            "pod_count": expected_pod_count,
            "ready_pod_count": expected_pod_count,
            "pod_uids": sorted(post_uids),
            "uid_count": len(post_uids),
            "unique_uid_count": len(set(post_uids)),
            "restart_generation_verified": restart_generation_verified,
            "query_success": _query_success(),
        },
    }


def test_event_throughput_valid_evidence_passes(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "event-throughput")
    _write_json(report_dir / "mesh-1" / "EventThroughputEvidence.json", _event_throughput_evidence())
    _write_json(report_dir / "mesh-2" / "EventThroughputEvidence.json", _event_throughput_evidence())
    rc, result = _run(tmp_path, "event-throughput", report_dir, worker_summary)

    assert rc == 0
    assert result["counts"]["event_throughput_roles_verified"] == 2


def test_event_throughput_uid_overlap_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "event-throughput")
    _write_json(report_dir / "mesh-1" / "EventThroughputEvidence.json", _event_throughput_evidence(overlap=True))
    _write_json(report_dir / "mesh-2" / "EventThroughputEvidence.json", _event_throughput_evidence())
    rc, result = _run(tmp_path, "event-throughput", report_dir, worker_summary)

    assert rc == 1
    assert any("event_throughput_evidence_valid[mesh-1]" in reason for reason in result["reasons"])


def test_event_throughput_partial_uid_snapshot_fails(tmp_path):
    """Regression test: expected_pod_count=8 but only 6 Pod UIDs were
    observed (e.g. a truncated/partial kubectl listing) while pod_count/
    ready_pod_count still (incorrectly) report 8. Previously this
    false-passed because the check only required pod_uids to be non-empty,
    never comparing its length against expected_pod_count."""
    report_dir, worker_summary = _make_common_fixture(tmp_path, "event-throughput", roles=("mesh-1",))
    partial_pre_uids = [f"uid-pre-{i}" for i in range(6)]  # 6, not 8
    _write_json(
        report_dir / "mesh-1" / "EventThroughputEvidence.json",
        _event_throughput_evidence(pre_uids=partial_pre_uids),
    )
    rc, result = _run(tmp_path, "event-throughput", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    reasons = "\n".join(result["reasons"])
    assert "event_throughput_evidence_valid[mesh-1]" in reasons
    assert "pre_restart.pod_uids has 6 entr" in reasons


def test_event_throughput_duplicate_uids_fails(tmp_path):
    """Regression test: expected_pod_count=8 and exactly 8 Pod UID lines
    were returned, but one UID is duplicated (only 7 unique values) — e.g.
    a pod counted twice while another pod's UID was never observed.
    Previously this false-passed because the check never verified
    uniqueness, only that the list was non-empty."""
    report_dir, worker_summary = _make_common_fixture(tmp_path, "event-throughput", roles=("mesh-1",))
    duplicate_pre_uids = [f"uid-pre-{i}" for i in range(7)] + ["uid-pre-0"]  # 8 lines, 7 unique
    _write_json(
        report_dir / "mesh-1" / "EventThroughputEvidence.json",
        _event_throughput_evidence(pre_uids=duplicate_pre_uids),
    )
    rc, result = _run(tmp_path, "event-throughput", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    reasons = "\n".join(result["reasons"])
    assert "event_throughput_evidence_valid[mesh-1]" in reasons
    assert "unique value(s) (duplicates present)" in reasons


def test_event_throughput_restart_generation_not_verified_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "event-throughput", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "EventThroughputEvidence.json",
        _event_throughput_evidence(restart_generation_verified=False),
    )
    rc, result = _run(tmp_path, "event-throughput", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert "restart_generation_verified is not true" in "\n".join(result["reasons"])


def test_event_throughput_missing_evidence_file_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "event-throughput", roles=("mesh-1",))
    rc, result = _run(tmp_path, "event-throughput", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert any("event_throughput_evidence_valid[mesh-1]" in reason for reason in result["reasons"])


# ---------------------------------------------------------------------------
# pod-churn-combined
# ---------------------------------------------------------------------------

POD_CHURN_CRITICAL_TESTCASES = (
    ("clustermesh-pod-churn-combined: [step: 05] Wait for post-scale-cycle pods to be Running", False),
    ("clustermesh-pod-churn-combined: [step: 09] Wait for post-kill pods to be Running", False),
)


def test_pod_churn_combined_valid_evidence_and_critical_testcases_pass(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "pod-churn-combined", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "PodChurnEvidence.json",
        {"stimulus_valid": True, "rounds": 3, "killed_total": 15},
    )
    _write_text(report_dir / "mesh-1" / "junit.xml", _junit_xml(POD_CHURN_CRITICAL_TESTCASES))
    rc, result = _run(tmp_path, "pod-churn-combined", report_dir, worker_summary, cluster_count=1)

    assert rc == 0
    assert result["counts"]["pod_churn_roles_verified"] == 1


def test_pod_churn_combined_critical_testcase_failure_invalidates(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "pod-churn-combined", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "PodChurnEvidence.json",
        {"stimulus_valid": True, "rounds": 3, "killed_total": 15},
    )
    failing_testcases = (
        (POD_CHURN_CRITICAL_TESTCASES[0][0], True),  # post-scale-cycle now FAILS
        POD_CHURN_CRITICAL_TESTCASES[1],
    )
    _write_text(report_dir / "mesh-1" / "junit.xml", _junit_xml(failing_testcases))
    rc, result = _run(tmp_path, "pod-churn-combined", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert any(
        "pod_churn_critical_testcase_passed[mesh-1:post-scale-cycle]" in reason
        for reason in result["reasons"]
    )


def test_pod_churn_combined_missing_critical_testcase_invalidates(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "pod-churn-combined", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "PodChurnEvidence.json",
        {"stimulus_valid": True, "rounds": 3, "killed_total": 15},
    )
    # junit.xml (from _make_common_fixture) has neither critical testcase.
    rc, result = _run(tmp_path, "pod-churn-combined", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert any(
        "pod_churn_critical_testcase_present[mesh-1:post-scale-cycle]" in reason
        for reason in result["reasons"]
    )


def test_pod_churn_combined_zero_killed_total_invalidates(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "pod-churn-combined", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "PodChurnEvidence.json",
        {"stimulus_valid": True, "rounds": 3, "killed_total": 0},
    )
    _write_text(report_dir / "mesh-1" / "junit.xml", _junit_xml(POD_CHURN_CRITICAL_TESTCASES))
    rc, result = _run(tmp_path, "pod-churn-combined", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert any("pod_churn_evidence_valid[mesh-1]" in reason for reason in result["reasons"])


# ---------------------------------------------------------------------------
# apiserver-failure
# ---------------------------------------------------------------------------

def test_apiserver_failure_recovered_with_differing_uids_passes(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "apiserver-failure", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "ApiserverFailureTimings_mesh-1.json",
        {"recovered": True, "killed_pod_uid": "uid-old", "replacement_pod_uid": "uid-new"},
    )
    rc, result = _run(
        tmp_path, "apiserver-failure", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 0
    assert result["measurement_valid"] is True


def test_apiserver_failure_same_uid_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "apiserver-failure", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "ApiserverFailureTimings_mesh-1.json",
        {"recovered": True, "killed_pod_uid": "uid-same", "replacement_pod_uid": "uid-same"},
    )
    rc, result = _run(
        tmp_path, "apiserver-failure", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 1
    assert any("apiserver_failure_uids_differ" in reason for reason in result["reasons"])


def test_apiserver_failure_missing_target_role_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "apiserver-failure", roles=("mesh-1",))
    rc, result = _run(tmp_path, "apiserver-failure", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert any("apiserver_failure_target_role_resolved" in reason for reason in result["reasons"])


def test_apiserver_failure_not_recovered_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "apiserver-failure", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "ApiserverFailureTimings_mesh-1.json",
        {"recovered": False, "killed_pod_uid": "uid-old", "replacement_pod_uid": ""},
    )
    rc, result = _run(
        tmp_path, "apiserver-failure", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 1
    assert any("apiserver_failure_recovered" in reason for reason in result["reasons"])


# ---------------------------------------------------------------------------
# policy-scale
# ---------------------------------------------------------------------------

def _policy_scale_evidence(
    active_verified=True,
    deleted_observed=0,
    repair_delete_requested=False,
):
    return {
        "active": {"expected_total": 250, "observed_total": 250, "verified": active_verified},
        "deleted": {
            "observed_count": deleted_observed,
            "verified": deleted_observed == 0,
            "repair_delete_requested": repair_delete_requested,
        },
    }


def _write_policy_metric_evidence(role_dir, policy_samples=250, regenerations=250):
    _write_json(
        role_dir
        / "GenericPrometheusQuery Cilium Policy Implementation Delay "
        "_clustermesh-policy-scale_ts.json",
        {"dataItems": [{"data": {"TotalSamples": policy_samples}}]},
    )
    _write_json(
        role_dir
        / "GenericPrometheusQuery Cilium Endpoint Regenerations "
        "_clustermesh-policy-scale_ts.json",
        {"dataItems": [{"data": {"TotalIncrease": regenerations}}]},
    )


def test_policy_scale_exact_counts_and_deletion_passes(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "policy-scale", roles=("mesh-1",))
    _write_json(report_dir / "mesh-1" / "PolicyScaleEvidence.json", _policy_scale_evidence())
    _write_policy_metric_evidence(report_dir / "mesh-1")
    rc, result = _run(tmp_path, "policy-scale", report_dir, worker_summary, cluster_count=1)

    assert rc == 0
    assert result["counts"]["policy_scale_roles_verified"] == 1
    assert result["counts"]["policy_scale_delete_repair_roles"] == []


def test_policy_scale_records_auto_repaired_delete_path(tmp_path):
    report_dir, worker_summary = _make_common_fixture(
        tmp_path,
        "policy-scale",
        roles=("mesh-1",),
    )
    _write_json(
        report_dir / "mesh-1" / "PolicyScaleEvidence.json",
        _policy_scale_evidence(repair_delete_requested=True),
    )
    _write_policy_metric_evidence(report_dir / "mesh-1")

    rc, result = _run(
        tmp_path,
        "policy-scale",
        report_dir,
        worker_summary,
        cluster_count=1,
    )

    assert rc == 0
    assert result["counts"]["policy_scale_delete_repair_roles"] == ["mesh-1"]
    check = next(
        check
        for check in result["checks"]
        if check["name"] == "policy_scale_delete_path[mesh-1]"
    )
    assert check["passed"] is True
    assert "repair re-issued" in check["detail"]


def test_policy_scale_deletion_not_fully_removed_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "policy-scale", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "PolicyScaleEvidence.json",
        _policy_scale_evidence(deleted_observed=3),
    )
    _write_policy_metric_evidence(report_dir / "mesh-1")
    rc, result = _run(tmp_path, "policy-scale", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert any("policy_scale_evidence_valid[mesh-1]" in reason for reason in result["reasons"])


def test_policy_scale_active_count_mismatch_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "policy-scale", roles=("mesh-1",))
    evidence = _policy_scale_evidence()
    evidence["active"]["observed_total"] = 200  # short of expected_total=250
    _write_json(report_dir / "mesh-1" / "PolicyScaleEvidence.json", evidence)
    _write_policy_metric_evidence(report_dir / "mesh-1")
    rc, result = _run(tmp_path, "policy-scale", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert any("policy_scale_evidence_valid[mesh-1]" in reason for reason in result["reasons"])


def test_policy_scale_requires_positive_implementation_metrics(tmp_path):
    report_dir, worker_summary = _make_common_fixture(
        tmp_path, "policy-scale", roles=("mesh-1",)
    )
    _write_json(
        report_dir / "mesh-1" / "PolicyScaleEvidence.json",
        _policy_scale_evidence(),
    )
    _write_policy_metric_evidence(
        report_dir / "mesh-1", policy_samples=0, regenerations=0
    )

    rc, result = _run(
        tmp_path, "policy-scale", report_dir, worker_summary, cluster_count=1
    )

    assert rc == 1
    assert any(
        "Policy Implementation Delay" in reason
        or "Endpoint Regenerations" in reason
        for reason in result["reasons"]
    )


# ---------------------------------------------------------------------------
# isolation
# ---------------------------------------------------------------------------

def test_isolation_valid_stimulus_passes(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "isolation", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "IsolationChurnTimings_mesh-1.json",
        {"stimulus_valid": True, "killer_exit_code": 0, "rounds": 5, "killed_total": 25},
    )
    rc, result = _run(
        tmp_path, "isolation", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 0
    assert result["measurement_valid"] is True


def test_isolation_nonzero_killer_exit_code_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "isolation", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "IsolationChurnTimings_mesh-1.json",
        {"stimulus_valid": False, "killer_exit_code": 1, "rounds": 0, "killed_total": 0},
    )
    rc, result = _run(
        tmp_path, "isolation", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 1
    assert any("isolation_killer_exit_code_zero" in reason for reason in result["reasons"])
    assert any("isolation_rounds_positive" in reason for reason in result["reasons"])


# ---------------------------------------------------------------------------
# node-churn-scale / node-churn-replace / node-churn-combined
# ---------------------------------------------------------------------------

def _node_churn_timings(scenario_valid=True, cleanup_failed=False, ops=None):
    return {
        "scenario_valid": scenario_valid,
        "cleanup_failed": cleanup_failed,
        "ops": ops if ops is not None else [
            {"op_index": 0, "op_type": "scale_up", "succeeded": True},
            {"op_index": 1, "op_type": "scale_down", "succeeded": True},
        ],
    }


def test_node_churn_scale_all_ops_succeeded_passes(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "node-churn-scale", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "NodeChurnTimings_mesh-1.json",
        _node_churn_timings(),
    )
    rc, result = _run(
        tmp_path, "node-churn-scale", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 0
    assert result["measurement_valid"] is True


def test_node_churn_scale_failed_op_invalidates(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "node-churn-scale", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "NodeChurnTimings_mesh-1.json",
        _node_churn_timings(ops=[
            {"op_index": 0, "op_type": "scale_up", "succeeded": True},
            {"op_index": 1, "op_type": "scale_down", "succeeded": False, "error": "timeout"},
        ]),
    )
    rc, result = _run(
        tmp_path, "node-churn-scale", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 1
    assert any("node_churn_all_operations_succeeded" in reason for reason in result["reasons"])


def test_node_churn_replace_requires_replace_wait(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "node-churn-replace", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "NodeChurnTimings_mesh-1.json",
        _node_churn_timings(ops=[{"op_index": 0, "op_type": "replace_drain", "succeeded": True}]),
    )
    rc, result = _run(
        tmp_path, "node-churn-replace", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 1
    assert any("node_churn_replace_wait_present" in reason for reason in result["reasons"])


def test_node_churn_replace_new_node_count_below_configured_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "node-churn-replace", roles=("mesh-1",))
    data = _node_churn_timings(ops=[
        {"op_index": 0, "op_type": "replace_drain", "succeeded": True},
        {"op_index": 1, "op_type": "replace_wait", "succeeded": True, "new_node_count": 2},
    ])
    data["replace_count"] = 5
    _write_json(report_dir / "mesh-1" / "NodeChurnTimings_mesh-1.json", data)
    rc, result = _run(
        tmp_path, "node-churn-replace", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 1
    assert any(
        "node_churn_replace_new_node_count_meets_configured" in reason for reason in result["reasons"]
    )


def test_node_churn_replace_without_configured_count_field_does_not_invent_check(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "node-churn-replace", roles=("mesh-1",))
    data = _node_churn_timings(ops=[
        {"op_index": 0, "op_type": "replace_drain", "succeeded": True},
        {"op_index": 1, "op_type": "replace_wait", "succeeded": True, "new_node_count": 2},
    ])
    # No replace_count/target_replace_count/etc field present in the file.
    _write_json(report_dir / "mesh-1" / "NodeChurnTimings_mesh-1.json", data)
    rc, result = _run(
        tmp_path, "node-churn-replace", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 0
    assert result["counts"]["node_churn_replace_count_field_present"] is False
    assert not any(
        "node_churn_replace_new_node_count_meets_configured" in check["name"]
        for check in result["checks"]
    )


def test_node_churn_cleanup_failed_invalidates(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "node-churn-combined", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "NodeChurnTimings_mesh-1.json",
        _node_churn_timings(cleanup_failed=True),
    )
    rc, result = _run(
        tmp_path, "node-churn-combined", report_dir, worker_summary, cluster_count=1,
        extra_args=["--target-role", "mesh-1"],
    )

    assert rc == 1
    assert any("node_churn_cleanup_not_failed" in reason for reason in result["reasons"])


# ---------------------------------------------------------------------------
# upper-bound
# ---------------------------------------------------------------------------

def _kvstore_duration_file_shape_a(perc99):
    return {"dataItems": [{"data": {"Max": 1.0, "Perc99": perc99}, "unit": "s"}]}


def _kvstore_duration_file_shape_b(perc99):
    return {"dataItems": [{"labels": {"Metric": "Perc99"}, "data": {"value": perc99}}]}


def test_upper_bound_both_data_shapes_are_supported(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "upper-bound", roles=("mesh-1", "mesh-2"))
    for role, shape_fn in (("mesh-1", _kvstore_duration_file_shape_a), ("mesh-2", _kvstore_duration_file_shape_b)):
        for rung in (0, 1):
            _write_json(
                report_dir / role / f"GenericPrometheusQuery ClusterMesh Kvstore Operation Duration Rung{rung}_g_ts.json",
                shape_fn(0.25),
            )
            _write_json(
                report_dir / role / f"GenericPrometheusQuery ClusterMesh Kvstore Sync Queue Size Rung{rung}_g_ts.json",
                {"dataItems": [{"data": {"Perc99": 10}}]},
            )
            # The other three verdict-driving signals (apiserver CPU,
            # mesh-failure rate, etcd commit latency) are also required for
            # a rung to be measurement-valid — see REQUIRED_SATURATION_SIGNALS
            # in scenario_evidence.py. Without these, this "both shapes
            # supported" fixture would (correctly) now fail as an
            # incomplete rung.
            _write_json(
                report_dir / role / f"GenericPrometheusQuery ClusterMesh APIServer Pod CPU Rung{rung}_g_ts.json",
                {"dataItems": [{"data": {"PerPodMax": 0.3}}]},
            )
            _write_json(
                report_dir / role / f"GenericPrometheusQuery ClusterMesh Remote Cluster Failure Rate Rung{rung}_g_ts.json",
                {"dataItems": [{"data": {"Max": 0.01}}]},
            )
            _write_json(
                report_dir / role / f"GenericPrometheusQuery ClusterMesh Etcd Backend Write Duration Rung{rung}_g_ts.json",
                {"dataItems": [{"data": {"Perc99": 0.005}}]},
            )
    rc, result = _run(
        tmp_path, "upper-bound", report_dir, worker_summary, cluster_count=2,
        extra_args=["--saturation-qps-list", "100,200"],
    )

    assert rc == 0
    assert result["counts"]["upper_bound_rung_count"] == 2


def test_upper_bound_missing_non_latency_required_signal_is_measurement_invalid(tmp_path):
    """Regression test: latency (and queue_size) present for every rung,
    but the apiserver-CPU/mesh-failure/etcd-commit metric files are never
    written at all. Previously `_check_upper_bound` only verified the
    latency (kvstore-duration) metric per rung, so this shape would
    false-pass as measurement-valid even though 3 of the 5 verdict-driving
    signals never landed."""
    report_dir, worker_summary = _make_common_fixture(tmp_path, "upper-bound", roles=("mesh-1",))
    _write_json(
        report_dir / "mesh-1" / "GenericPrometheusQuery ClusterMesh Kvstore Operation Duration Rung0_g_ts.json",
        _kvstore_duration_file_shape_a(0.25),
    )
    _write_json(
        report_dir / "mesh-1" / "GenericPrometheusQuery ClusterMesh Kvstore Sync Queue Size Rung0_g_ts.json",
        {"dataItems": [{"data": {"Perc99": 10}}]},
    )
    # apiserver_max_cpu_cores / mesh_failure_rate_max / etcd_commit_p99_ms
    # metric files are intentionally NOT written for Rung0.
    rc, result = _run(
        tmp_path, "upper-bound", report_dir, worker_summary, cluster_count=1,
        extra_args=["--saturation-qps-list", "100"],
    )

    assert rc == 1
    reasons = "\n".join(result["reasons"])
    assert "upper_bound_signal_present[mesh-1:Rung0:apiserver_max_cpu_cores]" in reasons
    assert "upper_bound_signal_present[mesh-1:Rung0:mesh_failure_rate_max]" in reasons
    assert "upper_bound_signal_present[mesh-1:Rung0:etcd_commit_p99_ms]" in reasons


def test_upper_bound_missing_later_rung_is_measurement_invalid(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "upper-bound", roles=("mesh-1",))
    # Only Rung0 present; Rung1 is configured but missing entirely.
    _write_json(
        report_dir / "mesh-1" / "GenericPrometheusQuery ClusterMesh Kvstore Operation Duration Rung0_g_ts.json",
        _kvstore_duration_file_shape_a(0.25),
    )
    rc, result = _run(
        tmp_path, "upper-bound", report_dir, worker_summary, cluster_count=1,
        extra_args=["--saturation-qps-list", "100,200"],
    )

    assert rc == 1
    assert any(
        "upper_bound_rung_measurement_present[mesh-1:Rung1]" in reason for reason in result["reasons"]
    )


def test_upper_bound_rung1_does_not_collide_with_rung10_plus(tmp_path):
    # Regression test: with >= 11 rungs configured, a naive `"Rung1" in
    # entry` substring match would let Rung10/Rung11/... filenames satisfy
    # Rung1's presence check even though Rung1's own file is missing. That
    # must not happen — Rung1 must be reported missing (measurement-invalid)
    # while the true owners (Rung10, Rung11) are reported present.
    report_dir, worker_summary = _make_common_fixture(tmp_path, "upper-bound", roles=("mesh-1",))
    qps_list = ",".join(str(100 * (i + 1)) for i in range(12))  # 12 rungs: Rung0..Rung11
    for rung in (0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
        # Every rung except Rung1 has real evidence files.
        _write_json(
            report_dir / "mesh-1" / f"GenericPrometheusQuery ClusterMesh Kvstore Operation Duration Rung{rung}_g_ts.json",
            _kvstore_duration_file_shape_a(0.25),
        )
    rc, result = _run(
        tmp_path, "upper-bound", report_dir, worker_summary, cluster_count=1,
        extra_args=["--saturation-qps-list", qps_list],
    )

    assert rc == 1
    assert result["counts"]["upper_bound_rung_count"] == 12
    assert any(
        "upper_bound_rung_measurement_present[mesh-1:Rung1]" in reason for reason in result["reasons"]
    )
    # Rung1 must be reported missing -- NOT satisfied by Rung10/Rung11's files.
    assert not any(
        "upper_bound_rung_measurement_present[mesh-1:Rung10]" in reason for reason in result["reasons"]
    )
    assert not any(
        "upper_bound_rung_measurement_present[mesh-1:Rung11]" in reason for reason in result["reasons"]
    )
    assert not any(
        "upper_bound_kvstore_duration_perc99[mesh-1:Rung10]" in reason for reason in result["reasons"]
    )
    assert not any(
        "upper_bound_kvstore_duration_perc99[mesh-1:Rung11]" in reason for reason in result["reasons"]
    )


def test_upper_bound_missing_saturation_qps_list_fails(tmp_path):
    report_dir, worker_summary = _make_common_fixture(tmp_path, "upper-bound", roles=("mesh-1",))
    rc, result = _run(tmp_path, "upper-bound", report_dir, worker_summary, cluster_count=1)

    assert rc == 1
    assert any("upper_bound_qps_list_provided" in reason for reason in result["reasons"])
