"""Static checks for the East US 2 candidate-subscription n=2 gate."""

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_PATH = REPOSITORY_ROOT / "pipelines" / "system" / "new-pipeline-test.yml"
TFVARS_PATH = (
    REPOSITORY_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "terraform-inputs"
    / "azure-2-mock-shared-dsv3.tfvars"
)
N100_TFVARS_PATH = TFVARS_PATH.with_name(
    "azure-100-mock-shared-dsv3.tfvars"
)
N100_DSV4_TFVARS_PATH = TFVARS_PATH.with_name(
    "azure-100-mock-shared-dsv4.tfvars"
)
MOCK_DEPLOY_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale-mock"
    / "deploy-mock-layer.yml"
)


def _stage_block():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index(
        "- stage: azure_eastus2_n2_mock_full_telemetry_aksstandalone2"
    )
    end = pipeline.index(
        "- stage: azure_centraluseuap_n2_mock_full_telemetry", start
    )
    return pipeline[start:end]


def _n100_stage_block():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index(
        "- stage: azure_eastus2_n100_mock_aksstandalone2"
    )
    end = pipeline.index("- stage: azure_centraluseuap_n100_mock", start)
    return pipeline[start:end]


def test_candidate_stage_has_isolated_subscription_dependencies():
    stage = _stage_block()

    for expected in (
        "- eastus2",
        "azure-2-mock-shared-dsv3.tfvars",
        "standardDSv3Family",
        'CLUSTERMESH_REQUIRED_FAMILY_VCPUS: "112"',
        'CLUSTERMESH_REQUIRED_MANAGED_CLUSTERS: "2"',
        'CLUSTERMESH_MANAGED_CLUSTER_QUOTA_HEADROOM: "2"',
        "MOCK_ACR_HOST: mockmeshshared11225.azurecr.io",
        'MOCK_ACR_SUBSCRIPTION_ID: "37deca37-c375-4a14-b90a-043849bd2bf1"',
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: cmsh-scale-eastus2-aksstand2-amw",
        "AKS_CONTROL_PLANE_LAW_NAME: cmsh-scale-controlplane-law-aksstand2",
        'AKS_CONTROL_PLANE_FORCE_PROVIDER_REREGISTRATION: "true"',
        'AKS_MANAGED_MONITORING_CONVERGENCE_ENABLED: "true"',
        'AKS_CILIUM_POLICY_GUARD_ENABLED: "false"',
        'AKS_CILIUM_POLICY_GUARD_REPAIR_ENABLED: "false"',
        'AKS_CILIUM_POLICY_GUARD_TIMEOUT_SECONDS: "1800"',
        'AKS_CILIUM_POLICY_GUARD_QUIET_SECONDS: "300"',
        'AKS_PLATFORM_METRICS_REQUIRED: "false"',
        'AKS_PLATFORM_METRICS_REQUIRE_WINDOW_COVERAGE: "false"',
        'AKS_PLATFORM_METRICS_MIN_COVERAGE_PERCENT: "80"',
        'AKS_PLATFORM_METRICS_TIMEOUT_SECONDS: "0"',
        'CL2_REQUIRED_SELF_HOSTED_TELEMETRY: "true"',
        'CL2_ACCEPT_CILIUM_POLICY_GAP: "true"',
        "cl2_prom_snapshot_storage_account: \"cmshscaleaksst2\"",
        'test_type_suffix: "-mock-full-telemetry-eus2-aksstand2"',
        'saturation_qps_list: "100,500,1500,4000,10000"',
        'saturation_restarts_list: "1,2,4,8,15"',
        'saturation_ops_per_sec_list: "0,0,0,0,0"',
    ):
        assert expected in stage

    assert "18153b17-4e27-4b58-863e-f8105b8892a2" not in stage
    assert "cmshscaleprom" not in stage
    assert "AKS_PLATFORM_METRICS_READINESS_" not in stage


def test_candidate_stage_runs_complete_eight_scenario_gate():
    stage = _stage_block()

    assert (
        'share_infra_scenarios: "propagation-probe,event-throughput,'
        'policy-scale,pod-churn-combined,apiserver-failure,isolation,'
        'node-churn-combined,upper-bound"'
        in stage
    )
    assert "suite_total_budget_seconds: 43200" in stage
    assert "timeout_in_minutes: 840" in stage
    assert "cancel_timeout_in_minutes: 60" in stage
    assert "destroy_retry_attempt_count: 0" in stage


def test_candidate_dsv3_topology_matches_n2_shape():
    tfvars = TFVARS_PATH.read_text(encoding="utf-8")

    assert tfvars.count('aks_name                      = "clustermesh-') == 2
    assert tfvars.count('{ name = "enable-acns", value = "" }') == 2
    assert tfvars.count('vm_size              = "Standard_D8s_v3"') == 5
    assert tfvars.count('name                 = "prompool"') == 2
    assert tfvars.count('name                 = "churnpool"') == 1
    assert "node_count           = 3" in tfvars
    assert "vnet_address_space = \"10.0.0.0/8\"" in tfvars
    assert "vnet_peering_config = {\n  enabled = false\n}" in tfvars
    assert re.search(r'vm_size\s*=\s*"Standard_D8s_v4"', tfvars) is None


def test_mock_acr_preflight_supports_cross_subscription_lookup():
    deploy = MOCK_DEPLOY_PATH.read_text(encoding="utf-8")

    assert "MOCK_ACR_SUBSCRIPTION_ID" in deploy
    assert 'acr_subscription_args=(--subscription "$acr_subscription_id")' in deploy
    assert 'az acr show "${acr_subscription_args[@]}"' in deploy
    assert 'az acr repository show "${acr_subscription_args[@]}"' in deploy


def test_candidate_n100_stage_inherits_n2_findings():
    stage = _n100_stage_block()

    for expected in (
        "- eastus2",
        "azure-100-mock-shared-dsv3.tfvars",
        "standardDSv3Family",
        'CLUSTERMESH_REQUIRED_FAMILY_VCPUS: "2536"',
        'CLUSTERMESH_REQUIRED_MANAGED_CLUSTERS: "100"',
        'CLUSTERMESH_MANAGED_CLUSTER_QUOTA_HEADROOM: "5"',
        'CMP_STAGED_JOIN_ENABLED: "true"',
        'CMP_STAGED_JOIN_BATCH_SIZE: "20"',
        'CMP_STAGED_JOIN_BATCH_WAIT_SECONDS: "7200"',
        'CMP_STAGED_JOIN_TOTAL_WAIT_SECONDS: "21600"',
        'CMP_STAGED_JOIN_CHECK_CONCURRENCY: "10"',
        'CMP_STAGED_JOIN_STALL_REAPPLY_SECONDS: "1800"',
        "MOCK_ACR_HOST: mockmeshshared11225.azurecr.io",
        'MOCK_ACR_SUBSCRIPTION_ID: "37deca37-c375-4a14-b90a-043849bd2bf1"',
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: "
        "cmsh-scale-eastus2-aksstand2-n100-amw",
        "AKS_CONTROL_PLANE_LAW_NAME: cmsh-scale-controlplane-law-aksstand2",
        'AKS_CONTROL_PLANE_FORCE_PROVIDER_REREGISTRATION: "true"',
        'AKS_MANAGED_MONITORING_CONVERGENCE_ENABLED: "true"',
        'AKS_PLATFORM_METRICS_REQUIRED: "false"',
        'AKS_PLATFORM_METRICS_REQUIRE_WINDOW_COVERAGE: "false"',
        'AKS_PLATFORM_METRICS_TIMEOUT_SECONDS: "0"',
        'CL2_ACCEPT_CILIUM_POLICY_GAP: "true"',
        'CL2_REQUIRED_SELF_HOSTED_TELEMETRY: "true"',
        'AKS_CILIUM_POLICY_GUARD_ENABLED: "false"',
        "cl2_prom_snapshot_storage_account: \"cmshscaleaksst2\"",
        'test_type_suffix: "-mock-cuse2-aksstand2"',
        'share_infra_scenarios: "propagation-probe,event-throughput,'
        'policy-scale,pod-churn-combined,apiserver-failure,isolation,'
        'node-churn-combined,upper-bound"',
        "suite_total_budget_seconds: 151200",
        "suite_finalization_reserve_seconds: 10800",
        "timeout_in_minutes: 2880",
        "cancel_timeout_in_minutes: 120",
    ):
        assert expected in stage

    assert "18153b17-4e27-4b58-863e-f8105b8892a2" not in stage
    assert "centraluseuap" not in stage


def test_candidate_n100_dsv3_topology_matches_dsv4_shape():
    dsv3 = N100_TFVARS_PATH.read_text(encoding="utf-8")
    dsv4 = N100_DSV4_TFVARS_PATH.read_text(encoding="utf-8")
    expected = (
        dsv4.replace("DSv4", "DSv3")
        .replace("dsv4", "dsv3")
        .replace("D8s_v4", "D8s_v3")
        .replace("Standard_D8s_v4", "Standard_D8s_v3")
    )

    assert dsv3 == expected
    assert dsv3.count('vm_size              = "Standard_D8s_v3"') == 201
    assert 'vm_size              = "Standard_D8s_v4"' not in dsv3
    assert dsv3.count('name                 = "churnpool"') == 1
    assert "node_count           = 12" in dsv3
    assert 'member_initial_label_value = "staged"' in dsv3
    assert 'deletion_delay = "60h"' in dsv3
