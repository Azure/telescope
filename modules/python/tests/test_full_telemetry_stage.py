"""Static checks for the isolated full-telemetry pipeline stage."""

import re
from pathlib import Path

import yaml


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
QUALIFY_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "qualify-platform-metrics.yml"
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
MOCK_EXECUTE_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale-mock"
    / "execute-clusterloader2.yml"
)
MOCK_VALIDATE_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale-mock"
    / "validate-resources.yml"
)
SETUP_TEMPLATE_PATH = REPOSITORY_ROOT / "steps" / "setup-tests.yml"
PROVISION_TEMPLATE_PATH = REPOSITORY_ROOT / "steps" / "provision-resources.yml"
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
    / "azure-2-mock-shared-dsv4.tfvars"
)
N100_TFVARS_PATH = (
    REPOSITORY_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "terraform-inputs"
    / "azure-100-mock-shared-dsv4.tfvars"
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
    start = pipeline.index("- stage: azure_centraluseuap_n2_mock_full_telemetry")
    end = pipeline.index(
        "\n  - stage: azure_eastus2euap_n2_mock\n",
        start,
    )
    stage = pipeline[start:end]

    assert "azure_centraluseuap_n2_mock_full_telemetry" in pipeline
    assert "n2_mock_full_telemetry:" in pipeline
    assert 'AKS_CONTROL_PLANE_METRICS_ENABLED: "true"' in pipeline
    assert (
        "AKS_CONTROL_PLANE_LAW_NAME: cmsh-scale-controlplane-law-cuseuap"
        in pipeline
    )
    assert "AKS_CONTROL_PLANE_LAW_LOCATION: eastus2" in stage
    assert (
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: "
        "cmsh-scale-centraluseuap-amw"
    ) in pipeline
    assert 'AKS_AMW_ARM_BATCH_SIZE: "10"' in pipeline
    assert 'CL2_ACNS_TELEMETRY_ENABLED: "true"' in pipeline
    assert 'kwok_usage_cpu: "25m"' in pipeline
    assert 'kwok_usage_memory: "64Mi"' in pipeline
    assert "AKS_MANAGED_TSDB_CHUNK_SECONDS" not in pipeline[
        pipeline.index("azure_centraluseuap_n2_mock_full_telemetry") :
        pipeline.index("azure_centraluseuap_n2_mock_full_telemetry") + 5000
    ]
    assert "timeout_in_minutes: 840" in stage
    assert "cancel_timeout_in_minutes: 60" in stage
    assert (
        'share_infra_scenarios: "propagation-probe,event-throughput,'
        'pod-churn-combined,apiserver-failure,policy-scale,isolation,'
        'node-churn-combined,upper-bound"'
        in stage
    )
    assert "restart_count: 1" in stage
    assert "suite_total_budget_seconds: 43200" in stage
    assert "suite_finalization_reserve_seconds: 3600" in stage
    assert "suite_job_timeout_buffer_seconds: 7200" in stage
    assert "agent_memory_min_free_gi: 4" in stage
    assert "node_churn_recovery_grace_seconds: 900" in stage
    assert "node_churn_ready_timeout_seconds: 1200" in stage
    assert "node_churn_target_nodepool: churnpool" in stage
    assert "node_replace_batch_size: 2" in stage
    assert "CLUSTERMESH_VM_FAMILY_QUOTA_NAME: standardDSv4Family" in stage
    assert 'CLUSTERMESH_REQUIRED_FAMILY_VCPUS: "112"' in stage
    assert "- centraluseuap" in stage
    assert (
        '- centraluseuap: "scenarios/perf-eval/clustermesh-scale/'
        'terraform-inputs/azure-2-mock-shared-dsv4.tfvars"'
        in stage
    )
    assert "destroy_retry_attempt_count: 0" in stage
    assert 'CMP_AUTO_RECOVERY_ENABLED: "true"' in stage

    tfvars = N2_TFVARS_PATH.read_text(encoding="utf-8")
    assert 'deletion_delay = "24h"' in tfvars
    assert tfvars.count('name                 = "churnpool"') == 1
    assert "node_count           = 3" in tfvars
    assert "clustermesh-churn=true:NoSchedule" in tfvars
    assert tfvars.count('vnet_name          = "clustermesh-shared-vnet"') == 1
    assert tfvars.count("vnet_address_space =") == 1
    assert "vnet_address_space = \"10.0.0.0/8\"" in tfvars
    assert "vnet_peering_config = {\n  enabled = false\n}" in tfvars
    assert "clustermesh-1-vnet" not in tfvars
    assert "clustermesh-2-vnet" not in tfvars
    assert 'name           = "clustermesh-1-node"' in tfvars
    assert 'name           = "clustermesh-1-pod"' in tfvars
    assert 'name           = "clustermesh-2-node"' in tfvars
    assert 'name           = "clustermesh-2-pod"' in tfvars
    assert (
        len(re.findall(r'vm_size\s*=\s*"Standard_D8s_v4"', tfvars))
        == 5
    )
    assert re.search(r'vm_size\s*=\s*"Standard_D8s_v5"', tfvars) is None
    assert (
        tfvars.count(
            '{ name = "service-cidr", value = "192.168.0.0/24" }'
        )
        == 2
    )
    assert (
        tfvars.count(
            '{ name = "dns-service-ip", value = "192.168.0.10" }'
        )
        == 2
    )


def test_n2_full_telemetry_stage_enables_bounded_amw_rotation():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_centraluseuap_n2_mock_full_telemetry")
    end = pipeline.index(
        "\n  - stage: azure_eastus2euap_n2_mock\n",
        start,
    )
    stage = pipeline[start:end]

    assert (
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: cmsh-scale-centraluseuap-amw"
        in stage
    )
    assert 'AKS_AMW_ROTATION_ENABLED: "true"' in stage
    assert 'AKS_AMW_ROTATION_SLOT_COUNT: "8"' in stage
    assert "AKS_CONTROL_PLANE_AMW_NAME:" not in stage
    # n=2 proves the same metricsContainers limit override used by n=100.
    assert 'AKS_AMW_CLUSTERS_PER_WORKSPACE: "1"' in stage
    assert 'AKS_AMW_MAX_ACTIVE_TIME_SERIES: "2000000"' in stage
    assert 'AKS_AMW_MAX_EVENTS_PER_MINUTE: "2000000"' in stage


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
    assert "AKSCapacityHeavyUsage" in aks_module
    assert "capacity_delay=$((240 + capacity_hash % 121))" in aks_module
    assert "sleep \"$capacity_delay\"" in aks_module


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
    assert "AnotherOperationInProgress" in aks_resource
    assert "attempt $i/3" in aks_resource

    fleet_module = FLEET_MODULE_PATH.read_text(encoding="utf-8")
    profile_start = fleet_module.index(
        'resource "terraform_data" "clustermeshprofile"'
    )
    list_command_start = fleet_module.index("cmp_list_applied_count_command")
    profile_resource = fleet_module[profile_start:]
    assert (
        'count_out=$(timeout --foreground 60s bash -c '
        '"${self.input.list_applied_count_command}" 2>&1)'
        in profile_resource
    )
    assert '"--only-show-errors",' in fleet_module[list_command_start:profile_start]
    assert "membership query returned no numeric count" in profile_resource
    assert "membership query failed; skipping the remaining drain wait" in (
        profile_resource
    )
    assert (
        'delete_out=$(timeout --foreground "$${delete_timeout}s" bash -c '
        '"${self.input.delete_command}" 2>&1)'
        in profile_resource
    )
    assert "drain_deadline=$((SECONDS + 1800))" in profile_resource
    assert "delete_deadline=$((SECONDS + 600))" in profile_resource
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
    n100_start = pipeline.index("- stage: azure_centraluseuap_n100_mock")
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
    assert '--arg reconcile_label "$_label"' in execute
    assert "label: $reconcile_label" in execute


def test_mock_layer_is_deployed_after_managed_telemetry_configuration():
    validate = MOCK_VALIDATE_TEMPLATE_PATH.read_text(encoding="utf-8")
    execute = MOCK_EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "deploy-mock-layer.yml" not in validate
    configure_pos = execute.index("configure-control-plane-metrics.yml")
    qualify_pos = execute.index("qualify-platform-metrics.yml")
    deploy_pos = execute.index("deploy-mock-layer.yml")
    cl2_pos = execute.index(
        "/steps/engine/clusterloader2/clustermesh-scale/execute.yml"
    )
    assert configure_pos < qualify_pos < deploy_pos < cl2_pos


def test_full_telemetry_azure_tasks_use_ui_selected_subscription():
    for path in (
        CONFIGURE_TEMPLATE_PATH,
        QUALIFY_TEMPLATE_PATH,
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


def test_resource_lease_outlives_share_infra_suite():
    provision = PROVISION_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "SUITE_TOTAL_BUDGET_SECONDS" in provision
    assert 'RESOURCE_LEASE_BUFFER_SECONDS:-14400' in provision
    assert "CLUSTERMESH_JOB_CANCEL_TIMEOUT_MINUTES" in provision
    assert "job_envelope_seconds" in provision
    assert "Resource lease is too short" in provision
    assert 'elif [ "$cloud" != "gcp" ]' in provision
    assert "task.setvariable variable=SKIP_RESOURCE_MANAGEMENT]true" in provision
    assert "Missing owner in" in provision
    assert "and(succeeded(), ${{ eq(parameters.cloud, 'azure') }}" in provision
    assert provision.index("Resource lease is too short") < provision.index(
        "Create Resource Group"
    )


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
    assert "AKS_PLATFORM_METRICS_PRE_SCENARIO_READY" in template
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
    audit = worker.index("audit_self_hosted.py")
    collect = worker.index("collect-acns-telemetry.sh")
    snapshot = worker.index("prometheus TSDB snapshot -------")
    final_readiness = worker.index("readiness-final.json")
    accepted_gap_check = worker.index(".accepted_gap == true")
    assert setup < audit < collect < snapshot
    assert final_readiness < accepted_gap_check < audit
    assert "--require-acns" in worker
    assert "ACNS_VERIFY_ONLY=true" in worker
    assert "readiness-start.json" in worker
    assert "readiness-final.json" in worker
    assert "accepted_telemetry_gaps" in worker
    assert "acns_gap_accepted" in worker
    assert 'cl2_config_file" = "policy-scale.yaml' in worker
    assert "accept_cilium_policy_gap=false" in worker
    assert "exit 10" in worker
    assert "workload passed but required telemetry is incomplete" in worker


def test_cilium_policy_guard_runs_before_each_scenario():
    execute = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    guard_call = "if ! run_cilium_policy_guard"
    mock_reconcile = 'run_mock_layer_reconcile "before"'
    scenario_banner = 'echo "Scenario [${scenario_idx}/${#SCENARIO_LIST[@]}]: ${SCENARIO}"'
    assert guard_call in execute
    assert execute.index(guard_call) < execute.index(mock_reconcile)
    assert execute.index(guard_call) < execute.index(scenario_banner)
    assert "ensure-cilium-policy.sh" in execute


def test_upper_bound_collection_uses_execution_defaults():
    collect = SNAPSHOT_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert (
        'CL2_SATURATION_QPS_LIST="${SATURATION_QPS_LIST:-'
        '100,500,1500,4000,10000}"'
        in collect
    )
    assert (
        'CL2_SATURATION_RESTARTS_LIST="${SATURATION_RESTARTS_LIST:-'
        '1,2,4,8,15}"'
        in collect
    )
    assert 'sqps="$CL2_SATURATION_QPS_LIST"' in collect
    assert '--saturation-qps-list "$_sqps"' in collect


def test_required_platform_metrics_fail_the_wait_task():
    wait_script = (
        REPOSITORY_ROOT
        / "scenarios"
        / "perf-eval"
        / "clustermesh-scale"
        / "telemetry"
        / "wait-managed-prometheus.sh"
    ).read_text(encoding="utf-8")

    assert "AKS_PLATFORM_METRICS_REQUIRED" in wait_script
    assert "AKS_PLATFORM_METRICS_REQUIRE_WINDOW_COVERAGE" in wait_script
    assert "AKS_PLATFORM_METRICS_MIN_COVERAGE_PERCENT" in wait_script
    assert "Required AKS platform CPU/memory metrics did not cover" in wait_script
    assert '[ "$platform_metrics_ready" != "true" ]' in wait_script


def test_managed_monitoring_convergence_blocks_policy_disable_rollout():
    configure_script = (
        REPOSITORY_ROOT
        / "scenarios"
        / "perf-eval"
        / "clustermesh-scale"
        / "telemetry"
        / "configure-managed-prometheus.sh"
    ).read_text(encoding="utf-8")

    assert "aks-managed-azure-monitor-metrics" in configure_script
    assert "AKS_MANAGED_MONITORING_CONVERGENCE_ENABLED" in configure_script
    assert 'if [ "$policy_after" = "never" ]' in configure_script
    assert "Cilium policy mode changed during managed-monitoring setup" in (
        configure_script
    )
    assert "Cilium remained stable for" in configure_script


def test_native_snapshot_admin_api_is_retried_with_diagnostics():
    worker = (
        REPOSITORY_ROOT
        / "steps"
        / "engine"
        / "clusterloader2"
        / "clustermesh-scale"
        / "run-cl2-on-cluster.sh"
    ).read_text(encoding="utf-8")

    assert 'CL2_PROM_SNAPSHOT_MAX_ATTEMPTS:-5' in worker
    assert 'CL2_PROM_SNAPSHOT_RETRY_SECONDS:-2' in worker
    assert 'CL2_PROM_SNAPSHOT_ERROR_RETRY_SECONDS:-10' in worker
    assert "--max-time 60" in worker
    assert "snapshot_baseline_file" in worker
    assert "list_prom_snapshot_dirs" in worker
    assert "comm -13" in worker
    assert 'done; exit 0' in worker
    assert "refusing to archive or retry" in worker
    assert "snapshot_server_error" in worker
    assert "snapshot_error_cleanup_ok" in worker
    assert "enableAdminAPI=${prom_admin_api:-unknown}" in worker


def test_policy_regeneration_counter_uses_current_cilium_metric_name():
    measurements = (
        REPOSITORY_ROOT
        / "modules"
        / "python"
        / "clusterloader2"
        / "clustermesh-scale"
        / "config"
        / "modules"
        / "measurements"
        / "cilium.yaml"
    ).read_text(encoding="utf-8")

    assert "cilium_endpoint_regenerations_total" in measurements
    assert "cilium_endpoint_regenerations_count" not in measurements


def test_prometheus_patcher_outlives_long_scenarios():
    worker = (
        REPOSITORY_ROOT
        / "steps"
        / "engine"
        / "clusterloader2"
        / "clustermesh-scale"
        / "run-cl2-on-cluster.sh"
    ).read_text(encoding="utf-8")

    assert 'CL2_PROM_PATCH_POLL_SECONDS:-10' in worker
    assert 'CL2_PROM_PATCH_REQUEST_TIMEOUT_SECONDS:-15' in worker
    assert "prom_patcher_kubectl" in worker
    assert "lifetime=worker" in worker
    assert "while true; do" in worker
    assert "setsid bash -c run_prom_patcher" in worker
    assert 'kill -- "-${PROM_PATCH_PID}"' in worker
    assert "timeout --foreground" in worker
    assert "--target-lookback-seconds" in worker
    assert "600 * ${CL2_MAX_ATTEMPTS:-1}" not in worker


def test_node_churn_false_cleanup_value_is_not_defaulted_to_true():
    execute = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert '.cleanup_failed // true' not in execute
    assert 'if has("cleanup_failed") then .cleanup_failed else true end' in execute
    assert "CL2_NODE_CHURN_READY_TIMEOUT_SECONDS +" in execute
    assert "CL2_NODE_CHURN_FINALIZER_TIMEOUT_SECONDS +" in execute
    assert "CL2_NODE_CHURN_RECOVERY_GRACE_SECONDS +" in execute
    for config_name in (
        "node-churn-scale.yaml",
        "node-churn-replace.yaml",
        "node-churn-combined.yaml",
    ):
        config = (
            REPOSITORY_ROOT
            / "modules"
            / "python"
            / "clusterloader2"
            / "clustermesh-scale"
            / "config"
            / config_name
        ).read_text(encoding="utf-8")
        assert "AddInt" in config
        assert "CL2_NODE_CHURN_READY_TIMEOUT_SECONDS" in config


def test_cl2_ado_inline_task_stays_below_execve_string_limit():
    document = yaml.safe_load(EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8"))
    script = next(
        step["script"]
        for step in document["steps"]
        if step.get("displayName") == "Run CL2 across all clustermesh clusters"
    )

    assert len(script.encode("utf-8")) < 120_000


def test_n100_stage_has_complete_workload_and_telemetry_wiring():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_centraluseuap_n100_mock")
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
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: cmsh-scale-centraluseuap-n100-amw",
        "AKS_CONTROL_PLANE_LAW_NAME: cmsh-scale-controlplane-law-cuseuap",
        "AKS_CONTROL_PLANE_LAW_LOCATION: eastus2",
        'AKS_AMW_ARM_BATCH_SIZE: "10"',
        'AKS_CONTROL_PLANE_METRICS_CONCURRENCY: "5"',
        'CL2_ACNS_TELEMETRY_ENABLED: "true"',
        'CL2_ACCEPT_CILIUM_POLICY_GAP: "true"',
        'AKS_CILIUM_POLICY_GUARD_ENABLED: "false"',
        'AKS_PLATFORM_METRICS_REQUIRED: "false"',
        'AKS_PLATFORM_METRICS_REQUIRE_WINDOW_COVERAGE: "false"',
        'AKS_PLATFORM_METRICS_TIMEOUT_SECONDS: "0"',
        'cl2_prom_snapshot_enabled: "true"',
        'CL2_PROBE_WINDOW_DURATION: "60m"',
        "operation_timeout: 90m",
        'share_infra_scenarios: "propagation-probe,event-throughput,'
        'policy-scale,pod-churn-combined,apiserver-failure,isolation,'
        'node-churn-combined,upper-bound"',
        "share_infra_settle_seconds: 300",
        "agent_disk_min_free_gi: 40",
        "agent_memory_min_free_gi: 12",
        "suite_total_budget_seconds: 158400",
        "suite_finalization_reserve_seconds: 10800",
        "suite_job_timeout_buffer_seconds: 21600",
        "restart_count: 1",
        "node_churn_combined_duration_seconds: 5400",
        "node_churn_target_nodepool: churnpool",
        "node_replace_batch_size: 10",
        "node_churn_ready_timeout_seconds: 1200",
        "node_churn_recovery_grace_seconds: 1800",
        "CLUSTERMESH_VM_FAMILY_QUOTA_NAME: standardDSv4Family",
        'CLUSTERMESH_REQUIRED_FAMILY_VCPUS: "2536"',
        "azure-100-mock-shared-dsv4.tfvars",
        'test_type_suffix: "-mock-cuseuap"',
        "timeout_in_minutes: 3000",
        "cancel_timeout_in_minutes: 120",
    ):
        assert expected in stage
    assert (
        '- centraluseuap: "scenarios/perf-eval/clustermesh-scale/'
        'terraform-inputs/azure-100-mock-shared-dsv4.tfvars"'
        in stage
    )
    assert '"{{$namespaces}}"' in pod_churn
    assert '"{{$globalNamespaces}}"' in pod_churn
    assert "clustermesh.cilium.io/global=true" in pod_churn
    assert 'service.cilium.io/global: "true"' in service
    assert 'io.cilium/global-service: "true"' in service
    assert tfvars.count('{ name = "enable-acns", value = "" }') == 100
    assert tfvars.count('name                 = "prompool"') == 100
    assert tfvars.count('name                 = "churnpool"') == 1
    assert (
        len(re.findall(r'vm_size\s*=\s*"Standard_D8s_v4"', tfvars))
        == 201
    )
    assert re.search(r'vm_size\s*=\s*"Standard_D8_v3"', tfvars) is None
    assert "node_count           = 12" in tfvars
    assert "clustermesh-churn=true:NoSchedule" in tfvars
    assert 'aks_name                      = "clustermesh-100"' in tfvars


def test_legacy_centraluseuap_n100_stage_is_disabled():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_centraluseuap_n100_mock")
    end = pipeline.index("- stage: azure_eastus2euap_n1_mock_5k", start)
    stage = pipeline[start:end]

    assert "condition: eq(1, 0)" in stage
    assert "BLOCKED legacy n=100 Central US EUAP" in stage
    assert "/jobs/blocked-legacy-n100.yml" in stage


def test_n100_stage_uses_static_sharded_workspaces_with_no_rotation():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_centraluseuap_n100_mock")
    end = pipeline.index("- stage: azure_eastus2euap_n1_mock_5k", start)
    stage = pipeline[start:end]

    assert (
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX: cmsh-scale-centraluseuap-n100-amw"
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
    assert "cmsh-scale-centraluseuap-amw" not in stage
    assert "AKS_CONTROL_PLANE_AMW_NAME:" not in stage


def test_n100_stage_mock_deploy_is_zero_tolerance():
    """n=100 formation/mock-layer deployment must be zero-tolerance:
    deploy-mock-layer.yml DROPS any tolerated-failure cluster from the CL2
    inventory, so any nonzero MOCK_DEPLOY_MAX_FAILURES here would let a
    100-member inventory silently shrink and masquerade as this n=100 tier.
    Per-cluster provisioning retries (provision-kwok-layer.sh's kretry/apply-
    attempt loops) are a separate mechanism and remain untouched."""
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    start = pipeline.index("- stage: azure_centraluseuap_n100_mock")
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
