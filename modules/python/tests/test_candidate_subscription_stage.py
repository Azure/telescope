"""Static checks for the East US 2 candidate-subscription n=2 gate."""

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_PATH = REPOSITORY_ROOT / "pipelines" / "system" / "new-pipeline-test.yml"
COMPETITIVE_TEST_PATH = REPOSITORY_ROOT / "jobs" / "competitive-test.yml"
VALIDATE_RESOURCES_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "validate-resources.yml"
)
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
N99_EUAP_TFVARS_PATH = TFVARS_PATH.with_name(
    "azure-99-mock-shared.tfvars"
)
N99_THRESHOLD_TFVARS_PATH = TFVARS_PATH.with_name(
    "azure-99-shared.tfvars"
)
MOCK_DEPLOY_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale-mock"
    / "deploy-mock-layer.yml"
)
SETUP_TESTS_PATH = REPOSITORY_ROOT / "steps" / "setup-tests.yml"


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
    end = pipeline.index(
        "- stage: azure_eastus2euap_n100_debug_preserve_37deca", start
    )
    return pipeline[start:end]


def _euap_n99_stage_block():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index(
        "- stage: azure_eastus2euap_n99_mock_37deca"
    )
    end = pipeline.index(
        "- stage: azure_eastus2euap_n2_mock_kubelet_smoke", start
    )
    return pipeline[start:end]


def _euap_n99_threshold_stage_block():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index(
        "- stage: azure_eastus2euap_fleet_threshold_n99_g100"
    )
    end = pipeline.index(
        "- stage: azure_eastus2euap_n2_reuse_smoke_preserve_37deca",
        start,
    )
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


def test_setup_can_require_an_exact_subscription():
    setup = SETUP_TESTS_PATH.read_text(encoding="utf-8")

    assert "Verify required ClusterMesh subscription" in setup
    assert "CLUSTERMESH_REQUIRED_SUBSCRIPTION_ID" in setup
    assert "actual_subscription_id=$(az account show" in setup


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
        'CMP_STAGED_JOIN_BATCH_SIZE: "10"',
        'CMP_STAGED_JOIN_BATCH_WAIT_SECONDS: "7200"',
        'CMP_STAGED_JOIN_TOTAL_WAIT_SECONDS: "28800"',
        'CMP_STAGED_JOIN_CHECK_CONCURRENCY: "10"',
        'CMP_STAGED_JOIN_RECOVERY_APPLY_AFTER_SECONDS: "2700"',
        'CMP_STAGED_JOIN_MAX_RECOVERY_APPLIES: "1"',
        'CMP_STAGED_JOIN_RECOVERY_MIN_POST_SECONDS: "1800"',
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
        "suite_total_budget_seconds: 158400",
        "suite_finalization_reserve_seconds: 10800",
        "timeout_in_minutes: 3000",
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


def test_original_subscription_n99_stage_uses_non_s_dv3():
    stage = _euap_n99_stage_block()
    tfvars = N99_EUAP_TFVARS_PATH.read_text(encoding="utf-8")

    for expected in (
        "- eastus2euap",
        "azure-99-mock-shared.tfvars",
        'CLUSTERMESH_REQUIRED_SUBSCRIPTION_ID: '
        '"37deca37-c375-4a14-b90a-043849bd2bf1"',
        "CLUSTERMESH_VM_FAMILY_QUOTA_NAME: standardDv3Family",
        'CLUSTERMESH_REQUIRED_FAMILY_VCPUS: "2512"',
        'CLUSTERMESH_REQUIRED_MANAGED_CLUSTERS: "99"',
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: "
        "cmsh-scale-eastus2euap-n99-amw",
        "AKS_CONTROL_PLANE_LAW_NAME: cmsh-scale-controlplane-law",
        'cl2_prom_snapshot_storage_account: "cmshscaleprom"',
        'CMP_STAGED_JOIN_ENABLED: "true"',
        'CMP_STAGED_JOIN_BATCH_SIZE: "10"',
        "suite_total_budget_seconds: 158400",
        "timeout_in_minutes: 3000",
    ):
        assert expected in stage

    assert "standardDSv3Family" not in stage
    assert "eq(variables['Build.Reason'], 'Manual')" in stage
    assert "cluster_count: 99" in stage
    assert "mesh_size: 99" in stage
    assert tfvars.count('vm_size              = "Standard_D8_v3"') == 199
    assert 'vm_size              = "Standard_D8s_v3"' not in tfvars
    assert tfvars.count('aks_name                      = "clustermesh-') == 99
    assert tfvars.count('name                 = "prompool"') == 99
    assert tfvars.count('name                 = "churnpool"') == 1
    assert tfvars.count('member_name = "mesh-') == 99
    assert 'role                          = "mesh-100"' not in tfvars
    assert 'member_name = "mesh-100"' not in tfvars
    assert 'member_initial_label_value = "staged"' in tfvars
    assert 'deletion_delay = "60h"' in tfvars


def test_original_subscription_n99_threshold_reuses_confirmed_n90_shape():
    stage = _euap_n99_threshold_stage_block()
    tfvars = N99_THRESHOLD_TFVARS_PATH.read_text(encoding="utf-8")

    for expected in (
        "- eastus2euap",
        "azure-99-shared.tfvars",
        'TF_CLI_ARGS_apply: "-parallelism=4"',
        'CLUSTERMESH_NODE_READINESS_REQUIRED: "false"',
        'CLUSTERMESH_CROSS_CLUSTER_SMOKE_ENABLED: "false"',
        'CMP_AUTO_RECOVERY_ENABLED: "false"',
        'CMP_REJOIN_ENABLED: "true"',
        'preserve_state_on_apply_failure: "true"',
        "n99_g100_threshold:",
        "cluster_count: 99",
        "mesh_size: 99",
        'share_infra_scenarios: "event-throughput,'
        'pod-churn-combined,isolation"',
        "max_parallel: 1",
        "timeout_in_minutes: 1200",
        "skip_execute: true",
        "skip_publish: true",
    ):
        assert expected in stage

    assert "azure-90-shared.tfvars" not in stage
    assert "azure-99-mock-shared.tfvars" not in stage
    assert "CMP_STAGED_JOIN" not in stage
    assert "37deca37-c375-4a14-b90a-043849bd2bf1" not in stage

    assert len(
        re.findall(
            r'^\s{8}name\s+= "clustermesh-\d+-node"$',
            tfvars,
            flags=re.MULTILINE,
        )
    ) == 99
    assert len(
        re.findall(
            r'^\s{8}name\s+= "clustermesh-\d+-pod"$',
            tfvars,
            flags=re.MULTILINE,
        )
    ) == 99
    assert tfvars.count('aks_name                      = "clustermesh-') == 99
    assert tfvars.count('vm_size              = "Standard_D4_v3"') == 99
    assert tfvars.count('vm_size              = "Standard_D8_v3"') == 99
    assert tfvars.count('name                 = "prompool"') == 99
    assert tfvars.count('member_name = "mesh-') == 99
    assert 'role                          = "mesh-100"' not in tfvars
    assert 'member_name = "mesh-100"' not in tfvars
    assert 'member_label_value = "true"' in tfvars
    assert "member_initial_label_value" not in tfvars
    assert 'deletion_delay = "48h"' in tfvars


def test_competitive_job_can_skip_workload_execution():
    job = COMPETITIVE_TEST_PATH.read_text(encoding="utf-8")

    assert "- name: skip_execute\n  type: boolean\n  default: false" in job
    assert (
        "- ${{ if not(parameters.skip_execute) }}:\n"
        "    - template: /steps/execute-tests.yml"
        in job
    )
    assert (
        "- ${{ if and(not(parameters.skip_publish), "
        "not(parameters.skip_execute)) }}:\n"
        "    - template: /steps/publish-results.yml"
        in job
    )


def test_threshold_node_readiness_warning_mode_preserves_peer_gate():
    validation = VALIDATE_RESOURCES_PATH.read_text(encoding="utf-8")

    for expected in (
        'CLUSTERMESH_NODE_READINESS_REQUIRED:-true',
        "node_readiness_warnings=0",
        "continuing to authoritative Cilium peer validation",
        "task.complete result=SucceededWithIssues",
        'CLUSTERMESH_CROSS_CLUSTER_SMOKE_ENABLED:-true',
        "Cross-cluster data-path smoke disabled",
    ):
        assert expected in validation

    peer_failure_gate = validation.index('if [ "$failures" -gt 0 ]')
    warning_completion = validation.index(
        'if [ "$node_readiness_warnings" -gt 0 ]'
    )
    assert peer_failure_gate < warning_completion
