"""Regression checks for the headline n=100 timing envelopes."""

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_PATH = REPOSITORY_ROOT / "pipelines" / "system" / "new-pipeline-test.yml"
EXECUTE_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "engine"
    / "clusterloader2"
    / "clustermesh-scale"
    / "execute.yml"
)
SCALE_PATH = (
    REPOSITORY_ROOT
    / "modules"
    / "python"
    / "clusterloader2"
    / "clustermesh-scale"
    / "scale.py"
)
WORKER_SCRIPT_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "engine"
    / "clusterloader2"
    / "clustermesh-scale"
    / "run-cl2-on-cluster.sh"
)


def test_n100_scenario_budgets_cover_probe_and_worker_waves():
    execute = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    stage_start = pipeline.index("- stage: azure_centraluseuap_n100_mock")
    stage_end = pipeline.index("- stage: azure_eastus2euap_n1_mock_5k", stage_start)
    stage = pipeline[stage_start:stage_end]
    large_tier_start = execute.index('if [ "$cluster_count" -ge 50 ]')
    large_tier_end = execute.index("else", large_tier_start)
    large_tier = execute[large_tier_start:large_tier_end]
    budgets = {
        scenario: int(seconds)
        for scenario, seconds in re.findall(
            r"^\s+([a-z-]+)\) echo (\d+) ;;$", large_tier, re.MULTILINE
        )
    }

    def stage_int(name):
        match = re.search(rf'{name}:\s*"(\d+)"', stage)
        assert match is not None
        return int(match.group(1))

    probe_wait_seconds = (
        stage_int("CL2_PROBE_PREWAIT_S")
        + 1800
        + stage_int("CL2_PROPAGATION_PROBE_COUNT")
        * (
            stage_int("CL2_PROPAGATION_PROBE_INTERVAL_S")
            + stage_int("CL2_PROPAGATION_PROBE_PEER_TIMEOUT")
            + 180
        )
        + 300
    )
    assert budgets["propagation-probe"] > probe_wait_seconds

    # Build 74774 supplied conservative per-wave ceilings for scenarios
    # capped at 12 concurrent workers. N=100 requires nine waves.
    worker_waves = (100 + 12 - 1) // 12
    per_wave_seconds = {
        "event-throughput": 10 * 60,
        "pod-churn-combined": 40 * 60,
        "policy-scale": 15 * 60,
    }
    for scenario, wave_seconds in per_wave_seconds.items():
        assert budgets[scenario] > worker_waves * wave_seconds


def test_n100_wave_workers_have_separate_watchdogs():
    execute = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")
    function_start = execute.index("scenario_worker_timeout_seconds()")
    function_end = execute.index("\n      }\n", function_start)
    function = execute[function_start:function_end]
    worker_timeouts = {
        scenario: int(seconds)
        for scenario, seconds in re.findall(
            r"^\s+([a-z-]+)\) echo (\d+); return ;;$", function, re.MULTILINE
        )
    }

    assert worker_timeouts == {
        "event-throughput": 2400,
        "pod-churn-combined": 7200,
        "policy-scale": 3600,
    }
    assert "scenario_worker_timeout=$(scenario_worker_timeout_seconds" in execute
    assert '--worker-timeout-seconds "$scenario_worker_timeout"' in execute


def test_worker_timeout_owns_and_removes_cl2_container():
    scale = SCALE_PATH.read_text(encoding="utf-8")
    worker = WORKER_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "start_new_session=True" in scale
    assert "_force_remove_worker_containers([container_name], role)" in scale
    assert "CL2_WORKER_CONTAINER_NAME" in worker
    assert 'docker rm --force "${CL2_WORKER_CONTAINER_NAME}"' in worker
