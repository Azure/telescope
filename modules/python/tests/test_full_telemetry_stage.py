"""Static checks for the isolated full-telemetry pipeline stage."""

from pathlib import Path


PIPELINE_PATH = (
    Path(__file__).resolve().parents[3]
    / "pipelines"
    / "system"
    / "new-pipeline-test.yml"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COMPETITIVE_JOB_PATH = REPOSITORY_ROOT / "jobs" / "competitive-test.yml"
TERRAFORM_RUN_COMMAND_PATH = (
    REPOSITORY_ROOT / "steps" / "terraform" / "run-command.yml"
)
FAILED_AKS_CLEANUP_PATH = (
    REPOSITORY_ROOT / "steps" / "terraform" / "cleanup-failed-aks.sh"
)
ORPHANED_VNET_RECONCILE_PATH = (
    REPOSITORY_ROOT / "steps" / "terraform" / "reconcile-orphaned-vnets.sh"
)
CONFIGURE_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "configure-control-plane-metrics.yml"
)
COLLECT_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "collect-control-plane-metrics.yml"
)
SNAPSHOT_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "engine"
    / "clusterloader2"
    / "clustermesh-scale"
    / "collect.yml"
)
EXECUTE_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "engine"
    / "clusterloader2"
    / "clustermesh-scale"
    / "execute.yml"
)
SETUP_TEMPLATE_PATH = REPOSITORY_ROOT / "steps" / "setup-tests.yml"
AKS_CLI_MODULE_PATH = (
    REPOSITORY_ROOT
    / "modules"
    / "terraform"
    / "azure"
    / "aks-cli"
    / "main.tf"
)
FLEET_MODULE_PATH = (
    REPOSITORY_ROOT
    / "modules"
    / "terraform"
    / "azure"
    / "fleet"
    / "main.tf"
)
N2_TFVARS_PATH = (
    REPOSITORY_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "terraform-inputs"
    / "azure-2-mock.tfvars"
)
N100_TFVARS_PATH = (
    REPOSITORY_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "terraform-inputs"
    / "azure-100-mock-shared.tfvars"
)
POD_CHURN_PATH = (
    REPOSITORY_ROOT
    / "modules"
    / "python"
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "pod-churn-combined.yaml"
)
GLOBAL_SERVICE_PATH = POD_CHURN_PATH.parent / "modules" / "event-throughput-service.yaml"


def test_dedicated_full_telemetry_stage_is_isolated():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_eastus2euap_n2_mock_full_telemetry")
    end = pipeline.index(
        "\n  - stage: azure_eastus2euap_n2_mock\n",
        start,
    )
    stage = pipeline[start:end]

    assert "azure_eastus2euap_n2_mock_full_telemetry" in pipeline
    assert "n2_mock_full_telemetry:" in pipeline
    assert 'AKS_CONTROL_PLANE_METRICS_ENABLED: "true"' in pipeline
    assert "AKS_CONTROL_PLANE_LAW_NAME: cmsh-scale-controlplane-law" in pipeline
    assert (
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: "
        "cmsh-scale-eastus2euap-amw"
    ) in pipeline
    assert 'AKS_AMW_ARM_BATCH_SIZE: "10"' in pipeline
    assert 'CL2_ACNS_TELEMETRY_ENABLED: "true"' in pipeline
    assert 'kwok_usage_cpu: "25m"' in pipeline
    assert 'kwok_usage_memory: "64Mi"' in pipeline
    assert "AKS_MANAGED_TSDB_CHUNK_SECONDS" not in pipeline[
        pipeline.index("azure_eastus2euap_n2_mock_full_telemetry") :
        pipeline.index("azure_eastus2euap_n2_mock_full_telemetry") + 5000
    ]
    assert "timeout_in_minutes: 720" in stage
    assert (
        'share_infra_scenarios: "propagation-probe,event-throughput,'
        'pod-churn-combined,apiserver-failure,policy-scale,isolation,'
        'node-churn-combined,upper-bound"'
        in stage
    )
    assert "restart_count: 1" in stage
    assert "suite_total_budget_seconds: 43200" in stage
    assert "suite_finalization_reserve_seconds: 3600" in stage
    assert "node_churn_recovery_grace_seconds: 900" in stage
    assert "node_churn_target_nodepool: churnpool" in stage
    assert "node_replace_batch_size: 2" in stage
    assert "CLUSTERMESH_VM_FAMILY_QUOTA_NAME: standardDSv5Family" in stage
    assert 'CLUSTERMESH_REQUIRED_FAMILY_VCPUS: "112"' in stage
    assert "destroy_retry_attempt_count: 0" in stage
    assert 'CMP_AUTO_RECOVERY_ENABLED: "true"' in stage

    tfvars = N2_TFVARS_PATH.read_text(encoding="utf-8")
    assert tfvars.count('name                 = "churnpool"') == 1
    assert "node_count           = 3" in tfvars
    assert "clustermesh-churn=true:NoSchedule" in tfvars


def test_n2_full_telemetry_stage_enables_bounded_amw_rotation():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_eastus2euap_n2_mock_full_telemetry")
    end = pipeline.index(
        "\n  - stage: azure_eastus2euap_n2_mock\n",
        start,
    )
    stage = pipeline[start:end]

    assert "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: cmsh-scale-eastus2euap-amw" in stage
    assert 'AKS_AMW_ROTATION_ENABLED: "true"' in stage
    assert 'AKS_AMW_ROTATION_SLOT_COUNT: "8"' in stage
    assert "AKS_CONTROL_PLANE_AMW_NAME:" not in stage
    # n=2 keeps one workspace per cluster at the default 1M ingestion limits.
    assert 'AKS_AMW_CLUSTERS_PER_WORKSPACE: "1"' in stage
    assert 'AKS_AMW_MAX_ACTIVE_TIME_SERIES: "1000000"' in stage
    assert 'AKS_AMW_MAX_EVENTS_PER_MINUTE: "1000000"' in stage


def test_extra_nodepool_operations_are_serialized_and_recoverable():
    module = AKS_CLI_MODULE_PATH.read_text(encoding="utf-8")
    start = module.index('resource "terraform_data" "aks_nodepool_cli"')
    end = module.index("\n}\n\n# Grant AKS identity", start)
    nodepool_resource = module[start:end]

    lock = 'lock_file="/tmp/telescope-aks-nodepool-$rg-$cluster.lock"'
    add = 'out=$(eval "$cmd" 2>&1)'
    assert lock in nodepool_resource
    assert 'flock -x -w "$lock_wait_seconds" 9' in nodepool_resource
    assert nodepool_resource.index(lock) < nodepool_resource.index(add)
    assert nodepool_resource.index("flock -x") < nodepool_resource.index(
        "operation_deadline=$((SECONDS + 7200))"
    )
    assert "--no-wait --only-show-errors" in nodepool_resource
    assert "FailedToDeleteVMSSInstances" in nodepool_resource
    assert "Failed|Canceled" in nodepool_resource
    assert "Operation was canceled" in nodepool_resource
    assert 'while [ "$SECONDS" -lt "$operation_deadline" ]' in nodepool_resource
    assert "--yes" not in nodepool_resource


def test_preserved_apply_cleans_failed_aks_before_terraform_refresh():
    run_command = TERRAFORM_RUN_COMMAND_PATH.read_text(encoding="utf-8")
    cleanup = FAILED_AKS_CLEANUP_PATH.read_text(encoding="utf-8")

    cleanup_call = (
        'bash "$(Pipeline.Workspace)/s/steps/terraform/cleanup-failed-aks.sh"'
    )
    terraform_apply = (
        'terraform ${{ parameters.command }} --auto-approve '
        '${{ parameters.arguments }} -var-file $terraform_input_file '
        '-var json_input="$terraform_input_variables" 2>&1 | tee'
    )
    assert cleanup_call in run_command
    assert run_command.index(cleanup_call) < run_command.index(terraform_apply)
    assert "preserve_state_on_apply_failure" in run_command

    assert (
        "[?location=='$REGION' && "
        "tags.telescope_provisioner=='aks-cli'].[name,tags.role,"
        "provisioningState]"
    ) in cleanup
    assert '--subscription "$ARM_SUBSCRIPTION_ID"' in cleanup
    assert "--no-wait" in cleanup
    assert "delete_transition_timeout" in cleanup
    assert "cleanup_concurrency" in cleanup
    assert 'cleaned_clusters+=("${cleanup_batch_clusters[$index]}")' in cleanup
    assert 'for cluster in "${cleaned_clusters[@]}"; do' in cleanup
    assert 'marker_root="$HOME/.telescope/aks-recovery/$RUN_ID"' in cleanup
    assert 'if [ ! -s "$marker_file" ]' in cleanup
    assert "No state file was found" in cleanup
    assert 'state_prefix="module.aks-cli[\\"$role\\"].terraform_data."' in cleanup
    assert 'terraform state rm "$address"' in cleanup
    assert "Azure resource is absent but Terraform create state remains" in cleanup
    assert "terraform show -json" in cleanup
    assert "AKS inventory attempt $inventory_attempt/5" in cleanup

    aks_module = AKS_CLI_MODULE_PATH.read_text(encoding="utf-8")
    assert '"telescope_provisioner" = "aks-cli"' in aks_module
    assert "aks_name                = var.aks_cli_config.aks_name" in aks_module
    assert "role                    = var.aks_cli_config.role" in aks_module
    assert "Request to Subnet Handler Failed" in aks_module
    assert "transient_sku_lookup" in aks_module


def test_preserved_apply_recovers_and_imports_orphaned_vnets():
    run_command = TERRAFORM_RUN_COMMAND_PATH.read_text(encoding="utf-8")
    reconcile = ORPHANED_VNET_RECONCILE_PATH.read_text(encoding="utf-8")

    failed_aks_call = "cleanup-failed-aks.sh"
    vnet_call = "reconcile-orphaned-vnets.sh"
    terraform_apply = (
        'terraform ${{ parameters.command }} --auto-approve '
        '${{ parameters.arguments }} -var-file $terraform_input_file '
        '-var json_input="$terraform_input_variables" 2>&1 | tee'
    )
    assert failed_aks_call in run_command
    assert vnet_call in run_command
    assert run_command.index(failed_aks_call) < run_command.index(vnet_call)
    assert run_command.index(vnet_call) < run_command.index(terraform_apply)

    assert (
        "[?location=='$REGION' && "
        "tags.run_id=='$RUN_ID'].[name,tags.role,id,provisioningState]"
    ) in reconcile
    assert 'az network vnet update \\' in reconcile
    assert 'tags.telescope_recovery=$RUN_ID' in reconcile
    assert 'update_rc" -eq 124' in reconcile
    assert "reconcile_concurrency" in reconcile
    assert 'address="module.virtual_network[\\"$role\\"].azurerm_virtual_network.vnet"' in (
        reconcile
    )
    assert "terraform import" in reconcile
    assert '-var "json_input=$TERRAFORM_INPUT_VARIABLES"' in reconcile


def test_terraform_destroy_treats_missing_aks_and_fleet_as_success():
    aks_module = AKS_CLI_MODULE_PATH.read_text(encoding="utf-8")
    aks_resource_start = aks_module.index('resource "terraform_data" "aks_cli"')
    aks_resource_end = aks_module.index(
        "\n}\n\n# Gate any subsequent", aks_resource_start
    )
    aks_resource = aks_module[aks_resource_start:aks_resource_end]
    assert "[aks_cli destroy] cluster or resource group already absent" in aks_resource
    assert "ResourceGroupNotFound" in aks_resource

    fleet_module = FLEET_MODULE_PATH.read_text(encoding="utf-8")
    profile_start = fleet_module.index(
        'resource "terraform_data" "clustermeshprofile"'
    )
    list_command_start = fleet_module.index("cmp_list_applied_count_command")
    profile_resource = fleet_module[profile_start:]
    assert 'count_out=$(eval "${self.input.list_applied_count_command}" 2>&1)' in (
        profile_resource
    )
    assert '"--only-show-errors",' in fleet_module[list_command_start:profile_start]
    assert "membership query returned no numeric count" in profile_resource
    assert "membership query failed; skipping the remaining drain wait" in (
        profile_resource
    )
    assert 'delete_out=$(eval "${self.input.delete_command}" 2>&1)' in (
        profile_resource
    )
    assert profile_resource.count("ResourceGroupNotFound") >= 2


def test_fleet_apply_waits_for_stable_profile_and_recovery_requires_delete():
    fleet_module = FLEET_MODULE_PATH.read_text(encoding="utf-8")
    validate = (
        REPOSITORY_ROOT
        / "steps"
        / "topology"
        / "clustermesh-scale"
        / "validate-resources.yml"
    ).read_text(encoding="utf-8")

    assert "cmp_apply_wait_seconds = length(var.members) >= 50 ? 5400 : 2700" in (
        fleet_module
    )
    assert "--query properties.provisioningState" in fleet_module
    assert "Succeeded|Failed|Applying|Updating|Creating" in fleet_module
    assert "apply stable in Succeeded" in fleet_module
    assert "apply did not reach stable Succeeded" in fleet_module

    assert "profile_deleted=false" in validate
    assert "ResourceNotFinalState" in validate
    assert "profile_delete_attempts=90" in validate
    assert "refusing recreate" in validate
    assert validate.index('if [ "$profile_deleted" != "true" ]') < validate.index(
        "# Step 2: recreate with the same selector."
    )


def test_long_clustermesh_stages_do_not_replay_terraform_destroy():
    job = COMPETITIVE_JOB_PATH.read_text(encoding="utf-8")
    assert "- name: destroy_retry_attempt_count" in job
    assert (
        "retry_attempt_count: ${{ parameters.destroy_retry_attempt_count }}" in job
    )

    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    n100_start = pipeline.index("- stage: azure_eastus2euap_n100_mock")
    n100_end = pipeline.index("- stage: azure_eastus2euap_n1_mock_5k", n100_start)
    assert "destroy_retry_attempt_count: 0" in pipeline[n100_start:n100_end]


def test_configure_control_plane_metrics_passes_build_id():
    configure = CONFIGURE_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "BUILD_ID: $(Build.BuildId)" in configure


def test_mock_mode_is_normalized_for_shell_gates():
    execute = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'export CL2_MOCK_MODE="${cl2_mock_mode_raw,,}"' in execute
    assert (
        'export CL2_ACNS_TELEMETRY_ENABLED='
        '"${CL2_ACNS_TELEMETRY_ENABLED:-false}"'
    ) in execute
    assert "end_timestamp: $scenario_end" in execute
    assert "result_code: $result" in execute
    assert (
        '-name "NodeChurnTimings_${CL2_NODE_CHURN_TARGET_CONTEXT}.json"'
        in execute
    )
    assert "cleanup_recovered: $cleanup_recovered" in execute
    assert "NODE_CHURNER_WAIT_RC" in execute
    assert (
        'export CL2_NODE_CHURN_TARGET_NODEPOOL='
        '"${NODE_CHURN_TARGET_NODEPOOL:-default}"'
    ) in execute
    assert '"$CL2_NODE_CHURN_TARGET_NODEPOOL"' in execute
    assert "cleanup completion is unverifiable" in execute
    assert "ado_set_variable SHARE_INFRA_META" in execute
    assert "ado_complete_with_issues" in execute
    assert "scenario_policy.py" in execute
    assert "worker_failure_rate_percent" in execute
    assert '--summary-file "$worker_summary"' in execute
    assert "scenario-health-gate.sh" in execute
    assert "preserve-scenario-artifacts.sh" in execute
    assert "CL2_SUITE_FINALIZATION_RESERVE_SECONDS" in execute
    assert "timeout --signal=TERM --kill-after=60s" in execute
    assert "start_logged_process_group" in execute
    assert "terminate_process_group" in execute
    assert "IsolationChurnTimings_" in execute


def test_full_telemetry_azure_tasks_use_ui_selected_subscription():
    for path in (
        CONFIGURE_TEMPLATE_PATH,
        COLLECT_TEMPLATE_PATH,
        SNAPSHOT_TEMPLATE_PATH,
    ):
        template = path.read_text(encoding="utf-8")
        assert 'az account set --subscription "$TARGET_SUBSCRIPTION_ID"' in template
        assert "TARGET_SUBSCRIPTION_ID: $(AZURE_SUBSCRIPTION_ID)" in template
    configure = CONFIGURE_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "AKS_TELEMETRY_CONFIGURED]true" in configure


def test_clustermesh_quota_preflight_uses_selected_subscription():
    setup = SETUP_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "Preflight ClusterMesh VM quota" in setup
    assert 'actual_subscription_id=$(az account show --query id -o tsv)' in setup
    assert 'AZURE_SUBSCRIPTION_ID' in setup
    assert 'az vm list-usage --location "$REGION"' in setup
    assert "CLUSTERMESH_REQUIRED_FAMILY_VCPUS" in setup
    assert "CLUSTERMESH_QUOTA_HEADROOM_VCPUS" in setup


def test_control_plane_artifact_directory_exists_after_configuration_failure():
    template = COLLECT_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "Prepare AKS control-plane telemetry artifact" in template
    assert 'condition: and(succeededOrFailed(),' in template


def test_managed_collection_phases_are_separate_visible_tasks():
    template = COLLECT_TEMPLATE_PATH.read_text(encoding="utf-8")
    display_names = [
        "Wait for AKS telemetry ingestion",
        "Audit managed telemetry and export platform metrics",
        "Upload managed telemetry artifacts",
        "Publish AKS control-plane telemetry artifacts",
    ]

    positions = [template.index(name) for name in display_names]
    assert positions == sorted(positions)
    assert template.count("az account set --subscription") == 3
    assert "Reconstruct managed Prometheus TSDB" not in template
    assert "AKS_TELEMETRY_WINDOW_READY" in template
    assert "AKS_TELEMETRY_CONFIGURED" in template
    assert template.count("succeededOrFailed()") >= 4


def test_native_snapshots_are_relabelled_before_publish_and_upload():
    template = SNAPSHOT_TEMPLATE_PATH.read_text(encoding="utf-8")

    relabel_position = template.index(
        "Relabel Prometheus TSDB snapshot blocks"
    )
    stage_position = template.index("Stage Prometheus TSDB snapshots")
    upload_position = template.index(
        "Upload Prometheus TSDB snapshots to our storage account"
    )
    assert relabel_position < stage_position < upload_position
    assert "relabel-prometheus-snapshots.sh" in template
    assert "BUILD_ID: $(Build.BuildId)" in template
    assert "SNAPSHOT_TIER: $(System.JobName)" in template
    assert template.count("SNAPSHOT_RELABEL_READY") >= 2
    assert 'ln "$snap" "$dest_path"' in template
    assert "Released uploaded native snapshot tarballs" in template
    assert "eq(variables['cl2_prom_snapshot_target'], 'artifact')" in template
    assert "/telemetry/acns/" in template
    assert 'blob_name="${BUILD_BRANCH}/acns/' in template
    assert 'blob_name="${BUILD_BRANCH}/lifecycle/' in template


def test_acns_probe_runs_before_snapshot_and_is_collected_before_teardown():
    worker = (
        REPOSITORY_ROOT
        / "steps"
        / "engine"
        / "clusterloader2"
        / "clustermesh-scale"
        / "run-cl2-on-cluster.sh"
    ).read_text(encoding="utf-8")

    setup = worker.index("setup-acns-telemetry.sh")
    collect = worker.index("collect-acns-telemetry.sh")
    snapshot = worker.index("prometheus TSDB snapshot -------")
    assert setup < collect < snapshot
    assert "--require-acns" in worker


def test_n100_stage_has_complete_workload_and_telemetry_wiring():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_eastus2euap_n100_mock")
    end = pipeline.index("- stage: azure_eastus2euap_n1_mock_5k", start)
    stage = pipeline[start:end]
    pod_churn = POD_CHURN_PATH.read_text(encoding="utf-8")
    service = GLOBAL_SERVICE_PATH.read_text(encoding="utf-8")
    tfvars = N100_TFVARS_PATH.read_text(encoding="utf-8")

    for expected in (
        "cluster_count: 100",
        "mesh_size: 100",
        "MOCK_NODE_COUNT: 100",
        "global_namespace_count: 5",
        "namespaces: 5",
        "deployments_per_namespace: 2",
        "replicas_per_deployment: 5",
        'kwok_usage_cpu: "25m"',
        'kwok_usage_memory: "64Mi"',
        'AKS_CONTROL_PLANE_METRICS_ENABLED: "true"',
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: cmsh-scale-eastus2euap-n100-amw",
        'AKS_AMW_ARM_BATCH_SIZE: "10"',
        'AKS_CONTROL_PLANE_METRICS_CONCURRENCY: "5"',
        'CL2_ACNS_TELEMETRY_ENABLED: "true"',
        'cl2_prom_snapshot_enabled: "true"',
        'CL2_PROBE_WINDOW_DURATION: "60m"',
        "operation_timeout: 90m",
        'share_infra_scenarios: "propagation-probe,event-throughput,'
        'pod-churn-combined,apiserver-failure,policy-scale,isolation,'
        'node-churn-combined,upper-bound"',
        "share_infra_settle_seconds: 300",
        "agent_disk_min_free_gi: 40",
        "suite_total_budget_seconds: 108000",
        "suite_finalization_reserve_seconds: 10800",
        "restart_count: 1",
        "node_churn_combined_duration_seconds: 5400",
        "node_churn_target_nodepool: churnpool",
        "node_replace_batch_size: 10",
        "node_churn_ready_timeout_seconds: 1200",
        "node_churn_recovery_grace_seconds: 1800",
        "CLUSTERMESH_VM_FAMILY_QUOTA_NAME: standardDv3Family",
        'CLUSTERMESH_REQUIRED_FAMILY_VCPUS: "2536"',
        "timeout_in_minutes: 1800",
    ):
        assert expected in stage
    assert '"{{$namespaces}}"' in pod_churn
    assert '"{{$globalNamespaces}}"' in pod_churn
    assert "clustermesh.cilium.io/global=true" in pod_churn
    assert 'service.cilium.io/global: "true"' in service
    assert 'io.cilium/global-service: "true"' in service
    assert tfvars.count('{ name = "enable-acns", value = "" }') == 100
    assert tfvars.count('name                 = "prompool"') == 100
    assert tfvars.count('name                 = "churnpool"') == 1
    assert "node_count           = 12" in tfvars
    assert "clustermesh-churn=true:NoSchedule" in tfvars
    assert 'aks_name                      = "clustermesh-100"' in tfvars


def test_n100_stage_uses_static_sharded_workspaces_with_no_rotation():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_eastus2euap_n100_mock")
    end = pipeline.index("- stage: azure_eastus2euap_n1_mock_5k", start)
    stage = pipeline[start:end]

    assert (
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: cmsh-scale-eastus2euap-n100-amw"
        in stage
    )
    # n=100 uses static clusters-per-workspace sharding + raised ingestion
    # limits instead of the one-workspace-per-cluster default (100 clusters
    # would need 100 workspaces on its own, see the comment in the stage).
    assert 'AKS_AMW_CLUSTERS_PER_WORKSPACE: "2"' in stage
    assert 'AKS_AMW_MAX_ACTIVE_TIME_SERIES: "2000000"' in stage
    assert 'AKS_AMW_MAX_EVENTS_PER_MINUTE: "2000000"' in stage
    # No automatic rotation for n=100: an immediate retry of a saturated run
    # must stay blocked on preflight headroom (an explicit quota/retention
    # decision), not silently create another 50 shard workspaces.
    assert "AKS_AMW_ROTATION_ENABLED:" not in stage
    assert "AKS_AMW_ROTATION_SLOT_COUNT:" not in stage
    # Distinct from the n=2 full-telemetry stage's base prefix so the two
    # tiers never share (or rotate into) each other's workspaces.
    assert "cmsh-scale-eastus2euap-amw" not in stage
    assert "AKS_CONTROL_PLANE_AMW_NAME:" not in stage


def test_n100_stage_mock_deploy_is_zero_tolerance():
    """n=100 formation/mock-layer deployment must be zero-tolerance:
    deploy-mock-layer.yml DROPS any tolerated-failure cluster from the CL2
    inventory, so any nonzero MOCK_DEPLOY_MAX_FAILURES here would let a
    100-member inventory silently shrink and masquerade as this n=100 tier.
    Per-cluster provisioning retries (provision-kwok-layer.sh's kretry/apply-
    attempt loops) are a separate mechanism and remain untouched."""
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_eastus2euap_n100_mock")
    end = pipeline.index("- stage: azure_eastus2euap_n1_mock_5k", start)
    stage = pipeline[start:end]

    assert "MOCK_DEPLOY_MAX_FAILURES: 0" in stage
    assert "MOCK_DEPLOY_MAX_FAILURES: 3" not in stage
    # Bounded concurrency remains; only the failure tolerance changed.
    assert "MOCK_DEPLOY_CONCURRENCY: 8" in stage

    deploy_mock_layer = (
        REPOSITORY_ROOT
        / "steps"
        / "topology"
        / "clustermesh-scale-mock"
        / "deploy-mock-layer.yml"
    ).read_text(encoding="utf-8")
    # The strict-by-default behavior (and the masquerade-as-n=N risk of
    # raising it) lives in deploy-mock-layer.yml, shared by every mock stage.
    assert 'MAX_FAILURES="${MOCK_DEPLOY_MAX_FAILURES:-0}"' in deploy_mock_layer
    assert "masquerade as n=N" in deploy_mock_layer


def test_execute_yml_classifies_early_artifact_preservation_summary():
    """Fix: execute.yml must parse the early preservation summary
    (authoritative) rather than treat every nonzero exit code as a
    shared-infrastructure failure. A scenario-local incomplete
    preservation folds into evidence_valid/measurement_valid but must
    NOT by itself flip artifact_preserved to false."""
    template = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "artifact-preservation-summary.json" in template
    assert "artifact_infrastructure_failure" in template
    assert "artifact_scenario_incomplete" in template
    infra_pos = template.index('if [ "$artifact_infrastructure_failure" = "true" ]')
    incomplete_pos = template.index('if [ "$artifact_scenario_incomplete" = "true" ]')
    artifact_preserved_false_pos = template.index(
        "artifact_preserved=false", infra_pos
    )
    evidence_invalid_pos = template.index("evidence_valid=false", incomplete_pos)
    # infrastructure_failure must be the ONLY path that flips
    # artifact_preserved to false; scenario_incomplete must fold into
    # evidence/measurement validity instead.
    assert infra_pos < artifact_preserved_false_pos < incomplete_pos
    assert incomplete_pos < evidence_invalid_pos
    assert "measurement invalidated, later scenarios are not stopped" in template
    assert "this will stop later scenarios" in template


def test_execute_yml_final_lifecycle_preservation_wiring():
    """Fix: execute.yml must invoke PRESERVE_LIFECYCLE_ONLY=true after the
    final scenario-policy.py call/SHARE_INFRA_META write for each
    scenario, using a distinct artifact-preservation-final-summary.json,
    and must re-finalize policy/metadata + stop the suite if that final
    upload hits an infrastructure failure."""
    template = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    final_policy_call_pos = template.index("B.8: finalize the scenario policy decision")
    lifecycle_section_pos = template.index(
        "B.8.5: final lifecycle-only artifact upload"
    )
    measurement_section_pos = template.index("B.9: measurement validity")
    assert final_policy_call_pos < lifecycle_section_pos < measurement_section_pos

    lifecycle_section = template[lifecycle_section_pos:measurement_section_pos]
    assert "PRESERVE_LIFECYCLE_ONLY=true" in lifecycle_section
    assert "artifact-preservation-final-summary.json" in lifecycle_section
    assert "final_lifecycle_infrastructure_failure" in lifecycle_section
    assert "re-finalizing policy and stopping later scenarios" in lifecycle_section
    # On final-upload infra failure, must re-run scenario_policy.py with
    # artifact_preserved=false and persist the recomputed suite_continue.
    assert '--artifact-preserved "$artifact_preserved"' in lifecycle_section
    assert "suite_continue=false" in lifecycle_section
    assert "SHARE_INFRA_META" in lifecycle_section

    # Fix: the final lifecycle budget must be computed and folded into the
    # pre-flight suite budget check so a scenario isn't started without
    # enough remaining time to run this final upload.
    assert "scenario_final_lifecycle_budget_seconds" in template
    assert "final_lifecycle_budget" in template


def test_execute_yml_wait_propagation_probe_is_bounded():
    """Fix: wait_propagation_probe must never use an unbounded shell
    `wait` on the host-side propagation-probe orchestrator's PID -- it
    must poll the PID against a conservative, computed deadline and, if
    that deadline expires, terminate the whole process group via the
    existing terminate_process_group helper and return rc=124 (the
    coreutils `timeout` convention already used elsewhere in this file).
    On normal completion the already-finalized PropagationTimings.jsonl
    must be left untouched -- this function only observes exit status."""
    template = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    budget_fn_pos = template.index("propagation_probe_wait_budget_seconds()")
    wait_fn_pos = template.index("wait_propagation_probe() {")
    assert budget_fn_pos < wait_fn_pos, (
        "propagation_probe_wait_budget_seconds must be defined before "
        "wait_propagation_probe uses it"
    )

    # Budget must be scale/config-aware: workload-ready timeout (explicit
    # override or scale-aware default), probe count, peer timeout,
    # interval, and a margin.
    budget_fn_end = template.index("\n\n", budget_fn_pos)
    budget_fn_body = template[budget_fn_pos:budget_fn_end]
    assert "propagation_probe_workload_ready_timeout_seconds" in budget_fn_body
    assert "CL2_PROPAGATION_PROBE_COUNT" in budget_fn_body
    assert "CL2_PROPAGATION_PROBE_PEER_TIMEOUT" in budget_fn_body
    assert "CL2_PROPAGATION_PROBE_INTERVAL_S" in budget_fn_body
    assert "margin" in budget_fn_body.lower()

    wait_fn_end = template.index("\n      }\n", wait_fn_pos)
    wait_fn_body = template[wait_fn_pos:wait_fn_end]

    # The ONLY `wait "$PROBE_PID"` call must be reached after the bounded
    # polling loop breaks (i.e. it must not be the unconditional first
    # thing the function does) -- guard against a regression back to a
    # bare blocking wait.
    assert 'wait "$PROBE_PID"' in wait_fn_body
    deadline_check_pos = wait_fn_body.index('"$_deadline"')
    plain_wait_pos = wait_fn_body.index('wait "$PROBE_PID"')
    assert deadline_check_pos < plain_wait_pos, (
        "wait_propagation_probe must check its computed deadline before "
        "reaping PROBE_PID -- an unbounded `wait \"$PROBE_PID\"` as the "
        "first statement would defeat the whole bound"
    )
    assert "propagation_probe_wait_budget_seconds" in wait_fn_body
    assert 'terminate_process_group "$PROBE_PID"' in wait_fn_body
    assert "PROBE_WAIT_RC=124" in wait_fn_body
    assert "return 124" in wait_fn_body


def test_collect_yml_aggregated_rows_are_annotated_with_scenario_policy():
    """Fix: aggregated JSONL rows in share-infra collect must be
    annotated with the scenario policy's authoritative validity fields
    -- both top-level and under test_details -- so invalid rows are
    explicitly filterable and never indistinguishable from valid
    successes. Must fail safe to measurement_valid=false if the final
    scenario-policy.json is missing or malformed."""
    template = SNAPSHOT_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "annotate_row_with_policy" in template
    definition_pos = template.index("annotate_row_with_policy() {")
    call_pos = template.index("annotate_row_with_policy ", definition_pos + 1)
    collect_one_pos = template.index('if collect_one "${SCENARIO}', call_pos - 2000)
    cat_pos = template.index(
        'cat "$per_cluster_result" >> "$TEST_RESULTS_FILE"', collect_one_pos
    )
    # annotate_row_with_policy must run on the per-cluster result BEFORE
    # it is appended into the aggregated TEST_RESULTS_FILE.
    assert collect_one_pos < call_pos < cat_pos

    for field in (
        "measurement_valid",
        "measurement_invalid_reasons",
        "suite_continue",
        "infrastructure_healthy",
        "recovery_valid",
    ):
        assert field in template
    assert ".test_details = ((.test_details // {})" in template
    assert "scenario-policy.json" in template
    assert "scenario policy output missing or malformed" in template


def test_collect_yml_lifecycle_files_stage_unconditionally_when_snapshots_disabled():
    """Fix: small lifecycle/evidence files must stage even when
    Prometheus TSDB snapshots are disabled -- only TSDB-tarball-specific
    work (and its "relabeling failed" warning) stays conditional on
    snapshots actually being enabled, checked inside the script."""
    template = SNAPSHOT_TEMPLATE_PATH.read_text(encoding="utf-8")

    stage_display_pos = template.index('displayName: "Stage Prometheus TSDB snapshots"')
    stage_condition_pos = template.index("condition:", stage_display_pos)
    stage_condition = template[stage_condition_pos : stage_condition_pos + 60]
    assert stage_condition.startswith("condition: succeededOrFailed()")

    assert 'SNAPSHOT_ENABLED: $(cl2_prom_snapshot_enabled)' in template
    assert 'if [ "$SNAPSHOT_ENABLED" = "true" ]; then' in template
    assert (
        "Prometheus TSDB snapshots disabled; skipping TSDB tarball staging"
        in template
    )

    # A dedicated publish step must cover the "snapshots disabled" case so
    # the unconditionally-staged lifecycle files still leave the agent.
    publish_disabled_pos = template.index(
        'displayName: "Publish lifecycle/evidence files as pipeline artifact '
        '(snapshots disabled)"'
    )
    publish_disabled_condition = template[
        publish_disabled_pos : publish_disabled_pos + 200
    ]
    assert "ne(variables['cl2_prom_snapshot_enabled'], 'true')" in publish_disabled_condition

    # The existing snapshot-specific artifact publish/blob-upload steps
    # must remain gated on snapshots actually being enabled -- requirement
    # 5 explicitly forbids making those unconditional.
    publish_enabled_pos = template.index(
        'displayName: "Publish Prometheus TSDB snapshots as pipeline artifact"'
    )
    publish_enabled_condition = template[
        publish_enabled_pos : publish_enabled_pos + 250
    ]
    assert "eq(variables['cl2_prom_snapshot_enabled'], 'true')" in publish_enabled_condition
    upload_pos = template.index(
        'displayName: "Upload Prometheus TSDB snapshots to our storage account"'
    )
    upload_condition = template[upload_pos : upload_pos + 250]
    assert "eq(variables['cl2_prom_snapshot_enabled'], 'true')" in upload_condition


def test_collect_yml_lifecycle_glob_patterns_include_final_summary():
    """Fix: both lifecycle glob loops (local staging + blob upload) must
    pick up the new artifact-preservation-final-summary.json file."""
    template = SNAPSHOT_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert (
        template.count(
            '"$CL2_REPORT_DIR"/**/artifact-preservation-final-summary.json'
        )
        == 2
    )
    assert (
        template.count('"$CL2_REPORT_DIR"/**/artifact-preservation-summary.json')
        == 2
    )
