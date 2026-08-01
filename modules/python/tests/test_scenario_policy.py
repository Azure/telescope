"""Tests for dynamic ClusterMesh scenario continuation policy."""

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "scenario_policy.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "clusterloader2_clustermesh_scenario_policy",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
scenario_policy_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(scenario_policy_module)
evaluate_policy = scenario_policy_module.evaluate_policy


def _summary(cluster_count, failed_roles):
    return {
        "total_workers": cluster_count,
        "failed_count": len(failed_roles),
        "failed_roles": failed_roles,
    }


def test_n100_ordinary_scenario_tolerates_three_hard_worker_failures():
    decision = evaluate_policy(
        "pod-churn-combined",
        100,
        _summary(100, ["mesh-7", "mesh-8", "mesh-9"]),
    )

    assert decision["success"] is True
    assert decision["worker_allowed_failures"] == 3
    assert decision["tolerated_worker_failures"] is True


def test_n100_ordinary_scenario_rejects_four_hard_worker_failures():
    decision = evaluate_policy(
        "pod-churn-combined",
        100,
        _summary(100, ["mesh-7", "mesh-8", "mesh-9", "mesh-10"]),
    )

    assert decision["success"] is False
    assert decision["worker_allowed_failures"] == 3


def test_required_target_failure_is_never_tolerated():
    decision = evaluate_policy(
        "isolation",
        100,
        _summary(100, ["mesh-1"]),
        target_role="mesh-1",
    )

    assert decision["success"] is False
    assert any("required target worker failed" in reason for reason in decision["reasons"])


def test_non_worker_failure_is_never_cleared_by_worker_tolerance():
    decision = evaluate_policy(
        "apiserver-failure",
        100,
        _summary(100, ["mesh-20"]),
        target_role="mesh-1",
        non_worker_failure=True,
        target_stimulus_valid=False,
    )

    assert decision["success"] is False
    assert decision["tolerated_worker_failures"] is False


def test_required_telemetry_failure_invalidates_measurement_without_workload_failure():
    summary = _summary(2, [])
    summary.update(
        {
            "telemetry_failed_count": 1,
            "telemetry_failed_roles": ["mesh-2"],
        }
    )
    decision = evaluate_policy(
        "apiserver-failure",
        2,
        summary,
        target_role="mesh-1",
        target_stimulus_valid=True,
    )

    assert decision["worker_failed_count"] == 0
    assert decision["failed_roles"] == []
    assert decision["telemetry_failed_count"] == 1
    assert decision["telemetry_failed_roles"] == ["mesh-2"]
    assert decision["measurement_valid"] is False
    assert any(
        "required telemetry failed on 1 worker" in reason
        for reason in decision["measurement_reasons"]
    )


def test_upper_bound_allows_ten_percent_hard_worker_loss():
    failed_roles = [f"mesh-{index}" for index in range(1, 11)]
    decision = evaluate_policy(
        "upper-bound",
        100,
        _summary(100, failed_roles),
    )

    assert decision["success"] is True
    assert decision["worker_allowed_failures"] == 10


def test_initial_evaluation_leaves_lifecycle_fields_null():
    """Before cleanup runs, the four recovery signals are unknown."""
    decision = evaluate_policy(
        "pod-churn-combined",
        100,
        _summary(100, []),
    )

    assert decision["measurement_valid"] is True
    assert decision["recovery_valid"] is None
    assert decision["infrastructure_healthy"] is None
    assert decision["artifact_preserved"] is None
    assert decision["mock_reconcile_valid"] is None
    assert decision["suite_continue"] is None
    # Suite continuation is unknown yet, so only this scenario's own
    # measurement validity can decide overall_failure at this point.
    assert decision["overall_failure"] is False


def test_evidence_invalid_fails_measurement_but_not_by_itself_suite_continue():
    decision = evaluate_policy(
        "event-throughput",
        100,
        _summary(100, []),
        evidence_valid=False,
    )

    assert decision["measurement_valid"] is False
    assert decision["success"] is False
    assert any(
        "scenario evidence validation failed" in reason
        for reason in decision["measurement_reasons"]
    )
    assert decision["reasons"] == decision["measurement_reasons"]
    # evidence_valid folds into measurement_valid only, never suite_continue.
    assert decision["suite_continue"] is None


def test_measurement_invalid_with_healthy_recovery_continues_the_suite():
    """An invalid MEASUREMENT (e.g. tolerated worker loss / bad evidence)
    must not by itself stop the suite if the shared infra recovered."""
    decision = evaluate_policy(
        "event-throughput",
        100,
        _summary(100, []),
        evidence_valid=False,
        recovery_valid=True,
        infrastructure_healthy=True,
        artifact_preserved=True,
        mock_reconcile_valid=True,
    )

    assert decision["measurement_valid"] is False
    assert decision["suite_continue"] is True
    assert decision["overall_failure"] is True
    assert decision["suite_stop_reasons"] == []


def test_recovery_failure_stops_the_suite_even_if_measurement_was_valid():
    decision = evaluate_policy(
        "event-throughput",
        100,
        _summary(100, []),
        recovery_valid=False,
        infrastructure_healthy=True,
        artifact_preserved=True,
        mock_reconcile_valid=True,
    )

    assert decision["measurement_valid"] is True
    assert decision["suite_continue"] is False
    assert decision["overall_failure"] is True
    assert (
        "post-scenario recovery/cleanup was not verified"
        in decision["suite_stop_reasons"]
    )


def test_infrastructure_unhealthy_stops_the_suite():
    decision = evaluate_policy(
        "event-throughput",
        100,
        _summary(100, []),
        recovery_valid=True,
        infrastructure_healthy=False,
        artifact_preserved=True,
        mock_reconcile_valid=True,
    )

    assert decision["measurement_valid"] is True
    assert decision["suite_continue"] is False
    assert decision["overall_failure"] is True
    assert (
        "shared infrastructure health gate did not pass"
        in decision["suite_stop_reasons"]
    )


def test_artifact_preservation_failure_stops_the_suite():
    decision = evaluate_policy(
        "event-throughput",
        100,
        _summary(100, []),
        recovery_valid=True,
        infrastructure_healthy=True,
        artifact_preserved=False,
        mock_reconcile_valid=True,
    )

    assert decision["suite_continue"] is False
    assert decision["overall_failure"] is True
    assert (
        "scenario artifact preservation failed" in decision["suite_stop_reasons"]
    )


def test_mock_reconcile_failure_stops_the_suite():
    decision = evaluate_policy(
        "event-throughput",
        100,
        _summary(100, []),
        recovery_valid=True,
        infrastructure_healthy=True,
        artifact_preserved=True,
        mock_reconcile_valid=False,
    )

    assert decision["suite_continue"] is False
    assert decision["overall_failure"] is True
    assert (
        "mock layer reconciliation failed" in decision["suite_stop_reasons"]
    )


def test_tolerated_worker_loss_with_healthy_recovery_fully_continues():
    """A tolerated hard-worker loss plus a clean recovery is the normal,
    fully-green continuation path: measurement_valid AND suite_continue
    are both true, so overall_failure is false."""
    decision = evaluate_policy(
        "pod-churn-combined",
        100,
        _summary(100, ["mesh-7", "mesh-8", "mesh-9"]),
        recovery_valid=True,
        infrastructure_healthy=True,
        artifact_preserved=True,
        mock_reconcile_valid=True,
    )

    assert decision["measurement_valid"] is True
    assert decision["tolerated_worker_failures"] is True
    assert decision["suite_continue"] is True
    assert decision["overall_failure"] is False
    assert decision["suite_stop_reasons"] == []
