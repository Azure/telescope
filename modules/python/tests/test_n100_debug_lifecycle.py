"""Static and guard checks for the reusable n=100 debug lifecycle."""

import os
import subprocess
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_PATH = REPOSITORY_ROOT / "pipelines/system/new-pipeline-test.yml"
COMPETITIVE_JOB_PATH = REPOSITORY_ROOT / "jobs/competitive-test.yml"
RESUME_JOB_PATH = REPOSITORY_ROOT / "jobs/clustermesh-debug-resume.yml"
REUSE_DIR = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "reuse"
)
VALIDATE_SCRIPT = REUSE_DIR / "validate-existing-n100.sh"
RESET_SCRIPT = REUSE_DIR / "reset-fleet-overlay.sh"
CREATE_SCRIPT = REUSE_DIR / "create-staged-fleet-overlay.sh"
DELETE_SCRIPT = REUSE_DIR / "delete-preserved-rg.sh"
MANIFEST_SCRIPT = REUSE_DIR / "write-resume-manifest.sh"


def _stage_block(name: str, next_name: str) -> str:
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index(f"- stage: {name}")
    end = pipeline.index(f"- stage: {next_name}", start)
    return pipeline[start:end]


def test_debug_stages_are_explicitly_mode_gated():
    active = _stage_block(
        "azure_eastus2_n100_mock_aksstandalone2",
        "azure_eastus2euap_n100_debug_preserve_37deca",
    )
    fresh = _stage_block(
        "azure_eastus2euap_n100_debug_preserve_37deca",
        "azure_eastus2euap_n100_debug_reset_fleet_37deca",
    )
    reset = _stage_block(
        "azure_eastus2euap_n100_debug_reset_fleet_37deca",
        "azure_eastus2euap_n100_debug_resume_37deca",
    )
    resume = _stage_block(
        "azure_eastus2euap_n100_debug_resume_37deca",
        "azure_eastus2euap_n100_debug_cleanup_37deca",
    )
    cleanup = _stage_block(
        "azure_eastus2euap_n100_debug_cleanup_37deca",
        "azure_centraluseuap_n100_mock",
    )

    assert "eq(variables['CLUSTERMESH_DEBUG_MODE'], '')" in active
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    assert "CLUSTERMESH_DEBUG_MODE: ${{ parameters.debugMode }}" in pipeline
    assert "- name: debugMode" in pipeline
    assert "- name: debugTargetRunId" in pipeline
    assert "- name: debugConfirmReset" in pipeline
    assert "- name: debugConfirmResume" in pipeline
    assert "- name: debugConfirmDelete" in pipeline
    assert "- name: scaleDebugClusterCount" in pipeline
    assert "- name: scaleDebugTfvarsPath" in pipeline
    assert "- name: scaleDebugTopology" in pipeline
    assert "- name: scaleDebugRequiredFamilyVcpus" in pipeline
    assert "- name: scaleDebugRunWorkload" in pipeline

    assert "CLUSTERMESH_DEBUG_MODE'], 'fresh-preserve'" in fresh
    assert 'SKIP_RESOURCE_DELETION: "true"' in fresh
    assert 'CLUSTERMESH_DEBUG_PRESERVE: "true"' in fresh
    assert "emit_resume_manifest: true" in fresh
    assert 'debug_preserve: "true"' in fresh
    assert "eq(variables['Build.Reason'], 'Manual')" in fresh
    assert "eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '')" in fresh
    assert "- eastus2euap" in fresh
    assert "parameters.scaleDebugTfvarsPath" in fresh
    assert "parameters.scaleDebugClusterCount" in fresh
    assert "parameters.scaleDebugRequiredFamilyVcpus" in fresh
    assert "parameters.scaleDebugTopology" in fresh
    assert "parameters.scaleDebugRunWorkload" in fresh
    assert "standardDv3Family" in fresh
    assert "standardDSv3Family" not in fresh
    assert 'cl2_prom_snapshot_storage_account: "cmshscaleprom"' in fresh

    assert "CLUSTERMESH_DEBUG_MODE'], 'reset-fleet'" in reset
    assert "CLUSTERMESH_DEBUG_CONFIRM_RESET" in reset
    assert "reset-fleet-overlay.sh" in reset
    assert "eq(variables['Build.Reason'], 'Manual')" in reset
    assert "eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '')" in reset
    assert "region: eastus2euap" in reset
    assert "parameters.scaleDebugTfvarsPath" in reset
    assert "parameters.scaleDebugClusterCount" in reset
    assert 'CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS: "168"' in reset

    assert "CLUSTERMESH_DEBUG_MODE'], 'resume'" in resume
    assert "clustermesh-debug-resume.yml" in resume
    assert "CLUSTERMESH_QUOTA_PREFLIGHT_ENABLED: \"false\"" in resume
    assert "eq(variables['Build.Reason'], 'Manual')" in resume
    assert "eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '')" in resume
    assert "region: eastus2euap" in resume
    assert "parameters.scaleDebugTfvarsPath" in resume
    assert "parameters.scaleDebugClusterCount" in resume
    assert "parameters.scaleDebugTopology" in resume
    assert "parameters.scaleDebugRunWorkload" in resume
    assert 'cl2_prom_snapshot_storage_account: "cmshscaleprom"' in resume

    assert "CLUSTERMESH_DEBUG_MODE'], 'cleanup'" in cleanup
    assert "CLUSTERMESH_DEBUG_CONFIRM_DELETE" in cleanup
    assert "CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID" in cleanup
    assert "delete-preserved-rg.sh" in cleanup
    assert "eq(variables['Build.Reason'], 'Manual')" in cleanup
    assert "eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '')" in cleanup
    assert "CLUSTERMESH_DEBUG_EXPECTED_REGION: eastus2euap" in cleanup
    assert "parameters.scaleDebugTfvarsPath" in cleanup
    assert "parameters.scaleDebugClusterCount" in cleanup

    invalid_start = pipeline.index("- stage: n100_debug_mode_invalid")
    invalid_end = pipeline.index(
        "- stage: azure_centraluseuap_n100_mock", invalid_start
    )
    invalid = pipeline[invalid_start:invalid_end]
    assert "Unsupported CLUSTERMESH_DEBUG_MODE" in invalid


def test_resume_job_skips_terraform_and_preserves_resources():
    resume = RESUME_JOB_PATH.read_text(encoding="utf-8")

    assert "/steps/provision-resources.yml" not in resume
    assert "/steps/cleanup-resources.yml" not in resume
    assert "validate-existing-scale.sh" in resume
    assert "create-staged-fleet-overlay.sh" in resume
    assert "/steps/validate-resources.yml" in resume
    assert "/steps/execute-tests.yml" in resume
    assert "/steps/publish-results.yml" in resume
    assert "CLUSTERMESH_DEBUG_CONFIRM_RESUME" in resume
    assert "- name: expected_cluster_count" in resume
    assert "- name: run_workload" in resume
    assert "- name: publish_results" in resume
    assert "${{ if parameters.run_workload }}:" in resume
    assert 'CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS: "168"' in resume
    assert (
        "${{ if and(parameters.run_workload, parameters.publish_results) }}:"
        in resume
    )


def test_fleet_reset_and_resume_do_not_mutate_aks_lifecycle():
    reset = RESET_SCRIPT.read_text(encoding="utf-8")
    create = CREATE_SCRIPT.read_text(encoding="utf-8")

    for forbidden in ("az aks delete", "az aks create", "az group delete"):
        assert forbidden not in reset
    assert "az fleet clustermeshprofile delete" in reset
    assert "az fleet member delete" in reset
    assert "az fleet delete" in reset
    assert "does not exactly match" in reset
    assert "CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT" in reset
    assert "--argjson expected_count" in reset
    assert "issuing bounded apply nudge" in reset
    assert "deferring apply nudge" in reset
    assert "Removing residual ClusterMesh Kubernetes resources" in reset
    assert "cilium-ca" in reset
    assert "cilium-root-ca.crt" in reset
    assert "cilium-kvstoremesh" in reset
    assert "cilium-clustermesh" in reset
    assert "clustermesh-apiserver-server-cert" in reset
    assert "Cluster-side overlay reset complete" in reset

    assert "az aks create" not in create
    assert "az group create" not in create
    assert "az fleet create" in create
    assert "--labels \"${label_key}=${initial_value}\"" in create
    assert "Expected empty staged profile" in create


def test_preserved_rg_validation_is_fail_closed():
    validation = VALIDATE_SCRIPT.read_text(encoding="utf-8")
    manifest = MANIFEST_SCRIPT.read_text(encoding="utf-8")

    for expected in (
        "clustermesh_debug_preserved",
        "perf-eval-clustermesh-scale",
        "mesh-1..mesh-$expected_count",
        "provisioningState",
        "powerState",
        "CLUSTERMESH_DEBUG_REQUIRE_OVERLAY_RESET",
        "clustermesh_debug_tfvars_sha256",
        "clustermesh_debug_expected_clusters",
        "exactly $expected_count total AKS clusters",
        "outside $expected_region",
        "Preserving later existing lease",
        "requested_deletion_due_time",
        "existing_deletion_due_time",
    ):
        assert expected in validation

    assert "az group update" not in manifest


def test_destructive_scripts_require_exact_confirmation(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az_log = tmp_path / "az.log"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$AZ_LOG"\n'
        "exit 99\n",
        encoding="utf-8",
    )
    fake_az.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "AZ_LOG": str(az_log),
            "CLUSTERMESH_DEBUG_TARGET_RUN_ID": "12345-deadbeef",
            "CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID": "test-subscription",
        }
    )

    delete_env = env | {"CLUSTERMESH_DEBUG_CONFIRM_DELETE": "wrong"}
    delete_result = subprocess.run(
        ["bash", str(DELETE_SCRIPT)],
        env=delete_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert delete_result.returncode != 0
    assert "confirmation mismatch" in delete_result.stderr.lower()

    reset_env = env | {"CLUSTERMESH_DEBUG_CONFIRM_RESET": "wrong"}
    reset_result = subprocess.run(
        ["bash", str(RESET_SCRIPT)],
        env=reset_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert reset_result.returncode != 0
    assert "confirmation mismatch" in reset_result.stderr.lower()
    assert not az_log.exists()


def test_pipeline_and_debug_templates_parse_as_yaml():
    yaml.safe_load(PIPELINE_PATH.read_text(encoding="utf-8"))
    yaml.safe_load(COMPETITIVE_JOB_PATH.read_text(encoding="utf-8"))
    yaml.safe_load(RESUME_JOB_PATH.read_text(encoding="utf-8"))
    yaml.safe_load(
        (REUSE_DIR / "write-resume-manifest.yml").read_text(encoding="utf-8")
    )
