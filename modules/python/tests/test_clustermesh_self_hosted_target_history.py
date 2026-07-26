"""Historical target coverage tests for the self-hosted telemetry audit."""

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "telemetry"
    / "audit_self_hosted.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "clustermesh_self_hosted_target_history",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
audit_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(audit_module)


def test_historical_mock_targets_cover_deleted_monitor():
    historical_targets = [
        {
            "labels": {"job": "monitoring/mock-cilium-agent-0"},
            "health": "up",
        }
        for _ in range(100)
    ]
    report = audit_module.build_audit(
        [],
        [],
        expected_mock_agent_targets=100,
        historical_targets=historical_targets,
    )
    check = next(
        item
        for item in report["checks"]
        if item["name"] == "target:mock-cilium-agent"
    )

    assert check["status"] == "covered"
    assert check["target_count"] == 0
    assert check["historical_target_count"] == 100
    assert check["historical_target_evidence"] is True

    live_down = audit_module.build_audit(
        [],
        [
            {
                "labels": {"job": "monitoring/mock-cilium-agent-0"},
                "health": "down",
            }
        ],
        expected_mock_agent_targets=100,
        historical_targets=historical_targets,
    )
    check = next(
        item
        for item in live_down["checks"]
        if item["name"] == "target:mock-cilium-agent"
    )
    assert check["status"] == "missing"


def test_historical_hubble_target_covers_deleted_monitor():
    report = audit_module.build_audit(
        list(audit_module.ACNS_METRICS),
        [],
        require_acns=True,
        historical_targets=[
            {
                "labels": {"job": "monitoring/hubble-metrics-0"},
                "health": "up",
            }
        ],
    )
    check = next(
        item
        for item in report["checks"]
        if item["name"] == "target:acns-hubble"
    )

    assert check["status"] == "covered"
    assert check["target_count"] == 0
    assert check["historical_target_evidence"] is True
    assert report["acns_complete"] is True
