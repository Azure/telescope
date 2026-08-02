"""Tests for ClusterMesh job timeout and agent-capacity preflights."""

import os
import subprocess
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SETUP_TEMPLATE_PATH = REPOSITORY_ROOT / "steps" / "setup-tests.yml"
COMPETITIVE_JOB_PATH = REPOSITORY_ROOT / "jobs" / "competitive-test.yml"
EXECUTE_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "engine"
    / "clusterloader2"
    / "clustermesh-scale"
    / "execute.yml"
)
PROVISION_TEMPLATE_PATH = REPOSITORY_ROOT / "steps" / "provision-resources.yml"
TERRAFORM_RUN_COMMAND_PATH = (
    REPOSITORY_ROOT / "steps" / "terraform" / "run-command.yml"
)
AZURE_LOGIN_PATH = REPOSITORY_ROOT / "steps" / "cloud" / "azure" / "login.yml"
AZURE_UPLOAD_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "cloud"
    / "azure"
    / "upload-storage-account.yml"
)
METADATA_PATH = REPOSITORY_ROOT / "steps" / "collect-telescope-metadata.yml"


def _step_script(display_name):
    document = yaml.safe_load(SETUP_TEMPLATE_PATH.read_text(encoding="utf-8"))
    for step in document["steps"]:
        if step.get("displayName") == display_name:
            return step["script"]
    raise AssertionError(f"step {display_name!r} not found")


def _run(script, env):
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        check=False,
        env={**os.environ, **env},
        text=True,
        timeout=10,
    )


def test_job_template_exposes_timeout_and_cancellation_envelopes():
    template = COMPETITIVE_JOB_PATH.read_text(encoding="utf-8")

    assert "CLUSTERMESH_JOB_TIMEOUT_MINUTES:" in template
    assert "CLUSTERMESH_JOB_CANCEL_TIMEOUT_MINUTES:" in template
    assert "timeoutInMinutes: ${{ parameters.timeout_in_minutes }}" in template
    assert (
        "cancelTimeoutInMinutes: ${{ parameters.cancel_timeout_in_minutes }}"
        in template
    )


def test_only_terraform_destroy_can_start_during_cancellation():
    template = TERRAFORM_RUN_COMMAND_PATH.read_text(encoding="utf-8")

    assert (
        "or(succeeded(), eq('${{ parameters.command }}', 'destroy'))"
        in template
    )
    assert "ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')" in template


def test_publish_path_skips_cancellation_before_cleanup():
    login = AZURE_LOGIN_PATH.read_text(encoding="utf-8")
    upload = AZURE_UPLOAD_PATH.read_text(encoding="utf-8")
    metadata = METADATA_PATH.read_text(encoding="utf-8")

    assert "condition: ${{ parameters.condition }}" in login
    assert "condition: succeededOrFailed()" in upload
    assert "condition: always()" not in metadata
    assert metadata.count("condition: succeededOrFailed()") >= 2


def test_job_timeout_guard_accepts_headline_envelopes():
    script = _step_script("Record ClusterMesh job start")

    for suite_seconds, buffer_seconds, timeout_minutes in (
        ("43200", "7200", "840"),
        ("129600", "21600", "2520"),
        ("151200", "21600", "2880"),
    ):
        result = _run(
            script,
            {
                "SUITE_TOTAL_BUDGET_SECONDS": suite_seconds,
                "SUITE_JOB_TIMEOUT_BUFFER_SECONDS": buffer_seconds,
                "CLUSTERMESH_JOB_TIMEOUT_MINUTES": timeout_minutes,
            },
        )
        assert result.returncode == 0, result.stderr
        assert "ClusterMesh job timeout envelope:" in result.stdout


def test_job_timeout_guard_rejects_cap_equal_to_suite_budget():
    script = _step_script("Record ClusterMesh job start")
    result = _run(
        script,
        {
            "SUITE_TOTAL_BUDGET_SECONDS": "43200",
            "SUITE_JOB_TIMEOUT_BUFFER_SECONDS": "7200",
            "CLUSTERMESH_JOB_TIMEOUT_MINUTES": "720",
        },
    )

    assert result.returncode == 1
    assert "need at least 840m, got 720m" in result.stderr
    assert "variable=SKIP_RESOURCE_MANAGEMENT]true" in result.stdout


def test_job_timeout_guard_rejects_noncanonical_or_oversized_values():
    script = _step_script("Record ClusterMesh job start")

    for suite_seconds in ("08", "999999999999999999999999"):
        result = _run(
            script,
            {
                "SUITE_TOTAL_BUDGET_SECONDS": suite_seconds,
                "SUITE_JOB_TIMEOUT_BUFFER_SECONDS": "7200",
                "CLUSTERMESH_JOB_TIMEOUT_MINUTES": "840",
            },
        )
        assert result.returncode == 1
        assert "variable=SKIP_RESOURCE_MANAGEMENT]true" in result.stdout


def test_agent_capacity_preflight_and_per_scenario_memory_gate(tmp_path):
    script = _step_script("Preflight ClusterMesh agent capacity")
    result = _run(
        script,
        {
            "PIPELINE_WORKSPACE": str(tmp_path),
            "AGENT_DISK_MIN_FREE_GI": "0",
            "AGENT_MEMORY_MIN_FREE_GI": "0",
        },
    )
    execute = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert result.returncode == 0, result.stderr
    assert "ClusterMesh agent capacity:" in result.stdout
    assert "CL2_AGENT_MEMORY_MIN_FREE_GI" in execute
    assert "check_agent_memory_headroom" in execute


def test_agent_capacity_preflight_rejects_noncanonical_threshold(tmp_path):
    script = _step_script("Preflight ClusterMesh agent capacity")
    result = _run(
        script,
        {
            "PIPELINE_WORKSPACE": str(tmp_path),
            "AGENT_DISK_MIN_FREE_GI": "08",
            "AGENT_MEMORY_MIN_FREE_GI": "0",
        },
    )

    assert result.returncode == 1
    assert "canonical non-negative integer" in result.stderr
    assert "variable=SKIP_RESOURCE_MANAGEMENT]true" in result.stdout


def test_resource_lease_covers_job_cancellation_tail(tmp_path):
    document = yaml.safe_load(PROVISION_TEMPLATE_PATH.read_text(encoding="utf-8"))
    script = next(
        step["script"]
        for step in document["steps"]
        if step.get("displayName") == "Validate Resource Lease and Get Owner"
    )
    tfvars = tmp_path / "input.tfvars"
    tfvars.write_text(
        'deletion_delay = "36h" # valid HCL comment\nowner = "test-owner"\n',
        encoding="utf-8",
    )
    config = (
        '{"canadacentral":{"TERRAFORM_INPUT_FILE":"'
        + str(tfvars)
        + '"}}'
    )
    result = _run(
        script,
        {
            "TERRAFORM_REGIONAL_CONFIG": config,
            "region": "canadacentral",
            "cloud": "azure",
            "SUITE_TOTAL_BUDGET_SECONDS": "129600",
            "RESOURCE_LEASE_BUFFER_SECONDS": "14400",
            "CLUSTERMESH_JOB_TIMEOUT_MINUTES": "2520",
            "CLUSTERMESH_JOB_CANCEL_TIMEOUT_MINUTES": "120",
        },
    )

    assert result.returncode == 1
    assert "job_with_cancel=158400s" in result.stdout
    assert "required=158400s" in result.stdout
    assert "variable=SKIP_RESOURCE_MANAGEMENT]true" in result.stdout


def test_headline_resource_leases_cover_complete_envelopes(tmp_path):
    document = yaml.safe_load(PROVISION_TEMPLATE_PATH.read_text(encoding="utf-8"))
    script = next(
        step["script"]
        for step in document["steps"]
        if step.get("displayName") == "Validate Resource Lease and Get Owner"
    )

    for lease_hours, suite_seconds, job_minutes, cancel_minutes in (
        (24, 43200, 840, 60),
        (48, 129600, 2520, 120),
        (60, 151200, 2880, 120),
    ):
        tfvars = tmp_path / f"input-{lease_hours}.tfvars"
        tfvars.write_text(
            f'deletion_delay = "{lease_hours}h"\nowner = "test-owner"\n',
            encoding="utf-8",
        )
        config = (
            '{"canadacentral":{"TERRAFORM_INPUT_FILE":"'
            + str(tfvars)
            + '"}}'
        )
        result = _run(
            script,
            {
                "TERRAFORM_REGIONAL_CONFIG": config,
                "region": "canadacentral",
                "cloud": "azure",
                "SUITE_TOTAL_BUDGET_SECONDS": str(suite_seconds),
                "RESOURCE_LEASE_BUFFER_SECONDS": "14400",
                "CLUSTERMESH_JOB_TIMEOUT_MINUTES": str(job_minutes),
                "CLUSTERMESH_JOB_CANCEL_TIMEOUT_MINUTES": str(cancel_minutes),
            },
        )

        assert result.returncode == 0, result.stderr
        assert f"Deletion Delay: {lease_hours} hr" in result.stdout
