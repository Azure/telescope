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


def test_upper_bound_allows_ten_percent_hard_worker_loss():
    failed_roles = [f"mesh-{index}" for index in range(1, 11)]
    decision = evaluate_policy(
        "upper-bound",
        100,
        _summary(100, failed_roles),
    )

    assert decision["success"] is True
    assert decision["worker_allowed_failures"] == 10
