"""Checks for the intentional-failure n=2 reuse pipeline smoke."""

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_PATH = REPOSITORY_ROOT / "pipelines/system/new-pipeline-test.yml"
REUSE_DIR = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "reuse"
)
PRESERVE_SCRIPT = REUSE_DIR / "run-n2-preserve-smoke.sh"
RESUME_SCRIPT = REUSE_DIR / "resume-n2-preserved-smoke.sh"
RESUME_EXISTING_SCRIPT = REUSE_DIR / "resume-n2-existing-smoke.sh"
RESET_SCRIPT = REUSE_DIR / "reset-fleet-overlay.sh"


def _stage_block(name: str, next_name: str) -> str:
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index(f"- stage: {name}")
    end = pipeline.index(f"- stage: {next_name}", start)
    return pipeline[start:end]


def test_n2_reuse_smoke_stages_are_manual_and_mode_gated():
    preserve = _stage_block(
        "azure_eastus2euap_n2_reuse_smoke_preserve_37deca",
        "azure_eastus2euap_n2_reuse_smoke_reset_37deca",
    )
    reset = _stage_block(
        "azure_eastus2euap_n2_reuse_smoke_reset_37deca",
        "azure_eastus2euap_n2_reuse_smoke_resume_37deca",
    )
    resume = _stage_block(
        "azure_eastus2euap_n2_reuse_smoke_resume_37deca",
        "azure_eastus2euap_n2_reuse_smoke_cleanup_37deca",
    )
    cleanup = _stage_block(
        "azure_eastus2euap_n2_reuse_smoke_cleanup_37deca",
        "n2_reuse_smoke_mode_invalid",
    )
    resume_existing = _stage_block(
        "azure_eastus2euap_n2_reuse_smoke_resume_existing_37deca",
        "azure_eastus2euap_n2_reuse_smoke_cleanup_37deca",
    )

    for block, mode in (
        (preserve, "preserve"),
        (reset, "reset"),
        (resume, "resume"),
        (resume_existing, "resume-existing"),
        (cleanup, "cleanup"),
    ):
        assert "eq(variables['Build.Reason'], 'Manual')" in block
        assert (
            f"eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '{mode}')"
            in block
        )
        assert "eq(variables['CLUSTERMESH_DEBUG_MODE'], '')" in block
        assert "37deca37-c375-4a14-b90a-043849bd2bf1" in block
        assert "eastus2euap" in block

    assert "run-n2-preserve-smoke.sh" in preserve
    assert "reset-fleet-overlay.sh" in reset
    assert "resume-n2-preserved-smoke.sh" in resume
    assert "resume-n2-existing-smoke.sh" in resume_existing
    assert "delete-preserved-rg.sh" in cleanup


def test_preserve_smoke_intentionally_fails_without_cleanup():
    script = PRESERVE_SCRIPT.read_text(encoding="utf-8")

    assert "intentional_failure_after_healthy_mesh" in script
    assert "exit 42" in script
    assert "clustermesh_debug_preserved=true" in script
    assert "clustermesh_debug_expected_clusters=2" in script
    assert "clustermesh_debug_aks_ids_sha256" in script
    assert "az group delete" not in script
    assert "az aks delete" not in script
    assert "private_kube_dir" in script
    assert '$artifact_dir/kube' not in script
    assert "wait_for_stable_cluster" in script
    assert "sustained Succeeded across 3 checks" in script
    assert "aks_stability_timeout" in script
    assert "desired_state_sha" in script
    assert "apply_profile_bounded" in script
    assert "apply is active asynchronously" in script
    assert "fleet_profile_apply_failed" in script


def test_resume_smoke_reuses_same_aks_ids_and_staged_fleet():
    script = RESUME_SCRIPT.read_text(encoding="utf-8")

    assert "clustermesh_debug_aks_ids_sha256" in script
    assert "AKS resource IDs changed before resume" in script
    assert "create-staged-fleet-overlay.sh" in script
    assert "CMP_STAGED_JOIN_BATCH_SIZE=2" in script
    assert "CMP_STAGED_JOIN_RECOVERY_APPLY_AFTER_SECONDS=1500" in script
    assert "CMP_STAGED_JOIN_RESTART_APISERVER_AFTER_APPLY=true" in script
    assert "resume_connected:2" in script
    assert "az group delete" not in script
    assert "az aks create" not in script
    assert "az aks delete" not in script
    assert "private_home" in script
    assert '$artifact_dir/home' not in script


def test_existing_fleet_resume_is_read_only():
    script = RESUME_EXISTING_SCRIPT.read_text(encoding="utf-8")

    assert "existing_fleet_preserved:true" in script
    assert "AKS resource IDs changed" in script
    assert "Expected preserved Fleet to remain 2/2 Connected" in script
    assert "cilium-dbg status" in script
    for forbidden in (
        "az fleet create",
        "az fleet delete",
        "clustermeshprofile apply",
        "az aks create",
        "az aks delete",
        "az group delete",
    ):
        assert forbidden not in script
    assert 'if [ -z "${CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256:-}" ]' in script


def test_reset_script_accepts_guarded_expected_count():
    reset = RESET_SCRIPT.read_text(encoding="utf-8")

    assert 'expected_count="${CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT:-100}"' in reset
    assert "--argjson expected_count" in reset
    assert "mesh-1..mesh-$expected_count" in reset


def test_n2_reuse_smoke_pipeline_parses():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    yaml.safe_load(pipeline)
    assert "- name: reuseSmokeMode" in pipeline
    assert "- name: lifecycleSubscriptionId" in pipeline
    assert "- name: lifecycleDesiredStateSha" in pipeline
    assert (
        "CLUSTERMESH_REUSE_SMOKE_MODE: "
        "${{ parameters.reuseSmokeMode }}"
        in pipeline
    )
    assert pipeline.count(
        "AZURE_SUBSCRIPTION_ID: "
        "${{ parameters.lifecycleSubscriptionId }}"
    ) >= 4
    assert pipeline.count(
        'az account set --subscription '
        '"${{ parameters.lifecycleSubscriptionId }}"'
    ) >= 4
    assert "clustermesh_lifecycle_mode_conflict" in pipeline
    assert (
        "CLUSTERMESH_DEBUG_MODE and CLUSTERMESH_REUSE_SMOKE_MODE "
        "cannot both be set"
        in pipeline
    )
