"""Static and guard checks for the reusable n=100 debug lifecycle."""

import json
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
REPAIR_SCRIPT = REUSE_DIR / "repair-existing-fleet-overlay.sh"
DELETE_SCRIPT = REUSE_DIR / "delete-preserved-rg.sh"
MANIFEST_SCRIPT = REUSE_DIR / "write-resume-manifest.sh"
BASE_VALIDATE_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "validate-resources.yml"
)
LIVE_OVERLAY_SCRIPT = (
    REPOSITORY_ROOT
    / "modules"
    / "python"
    / "clusterloader2"
    / "clustermesh-scale"
    / "preserved_live_overlay.py"
)
WORKER_RECONCILE_SCRIPT = (
    REPOSITORY_ROOT
    / "modules"
    / "python"
    / "clusterloader2"
    / "clustermesh-scale"
    / "preserved_worker_reconcile.py"
)
SET_RUN_ID_PATH = REPOSITORY_ROOT / "steps" / "set-run-id.yml"
N100_TFVARS_PATH = (
    REPOSITORY_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "terraform-inputs"
    / "azure-100-mock-shared.tfvars"
)
AZURE_TERRAFORM_MAIN = (
    REPOSITORY_ROOT / "modules" / "terraform" / "azure" / "main.tf"
)


def _write_validation_fixture(tmp_path, *, include_second_node_group):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az_log = tmp_path / "az.log"
    fixture_path = tmp_path / "fixture.json"
    parent_rg = "12345-deadbeef"
    cluster_ids = {
        role: (
            f"/subscriptions/test-subscription/resourceGroups/{parent_rg}/"
            "providers/Microsoft.ContainerService/managedClusters/"
            f"clustermesh-{index}"
        )
        for index, role in enumerate(("mesh-1", "mesh-2"), start=1)
    }
    clusters = [
        {
            "name": f"clustermesh-{index}",
            "rg": parent_rg,
            "role": role,
            "location": "eastus2euap",
        }
        for index, role in enumerate(("mesh-1", "mesh-2"), start=1)
    ]
    aks = [
        {
            "id": cluster_ids[role],
            "name": f"clustermesh-{index}",
            "location": "eastus2euap",
            "nodeResourceGroup": (
                f"MC_{parent_rg}_clustermesh-{index}_eastus2euap"
            ),
            "powerState": {"code": "Running"},
            "provisioningState": "Succeeded",
            "tags": {"role": role},
        }
        for index, role in enumerate(("mesh-1", "mesh-2"), start=1)
    ]
    groups = [
        {
            "name": f"MC_{parent_rg}_clustermesh-1_eastus2euap",
            "location": "eastus2euap",
            "managedBy": cluster_ids["mesh-1"],
            "deletion_due_time": "2000-01-01T00:00:00Z",
        }
    ]
    if include_second_node_group:
        groups.append(
            {
                "name": f"MC_{parent_rg}_clustermesh-2_eastus2euap",
                "location": "eastus2euap",
                "managedBy": cluster_ids["mesh-2"],
                "deletion_due_time": "2099-01-01T00:00:00Z",
            }
        )
    fixture_path.write_text(
        json.dumps(
            {
                "parent": {
                    "location": "eastus2euap",
                    "tags": {
                        "clustermesh_debug_preserved": "true",
                        "run_id": parent_rg,
                        "scenario": "perf-eval-clustermesh-scale",
                        "clustermesh_debug_expected_clusters": "2",
                        "clustermesh_debug_tfvars_sha256": "test-sha",
                        "deletion_due_time": "2000-01-01T00:00:00Z",
                    },
                },
                "clusters": clusters,
                "aks": aks,
                "groups": groups,
                "fleet_count": 0,
            }
        ),
        encoding="utf-8",
    )
    fake_az = fake_bin / "az"
    fake_az.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['AZ_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(' '.join(args) + '\\n')\n"
        "with open(os.environ['AZ_FIXTURE'], encoding='utf-8') as handle:\n"
        "    fixture = json.load(handle)\n"
        "if args[:2] == ['account', 'show']:\n"
        "    print('test-subscription')\n"
        "elif args[:2] == ['group', 'show']:\n"
        "    print(json.dumps(fixture['parent']))\n"
        "elif args[:2] == ['resource', 'list']:\n"
        "    resource_type = args[args.index('--resource-type') + 1]\n"
        "    if resource_type == 'Microsoft.ContainerService/managedClusters':\n"
        "        print(json.dumps(fixture['clusters']))\n"
        "    elif resource_type == 'Microsoft.ContainerService/fleets':\n"
        "        print(fixture['fleet_count'])\n"
        "    else:\n"
        "        raise SystemExit(f'unexpected resource type: {resource_type}')\n"
        "elif args[:2] == ['aks', 'list']:\n"
        "    print(json.dumps(fixture['aks']))\n"
        "elif args[:2] == ['group', 'list']:\n"
        "    print(json.dumps(fixture['groups']))\n"
        "elif args[:2] == ['group', 'update']:\n"
        "    print('{}')\n"
        "else:\n"
        "    raise SystemExit(f'unexpected az command: {args}')\n",
        encoding="utf-8",
    )
    fake_az.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "AZ_FIXTURE": str(fixture_path),
            "AZ_LOG": str(az_log),
            "BUILD_BUILDID": "999",
            "CLUSTERMESH_DEBUG_TARGET_RUN_ID": parent_rg,
            "CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID": "test-subscription",
            "CLUSTERMESH_DEBUG_EXPECTED_REGION": "eastus2euap",
            "CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT": "2",
            "CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256": "test-sha",
            "CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS": "24",
            "CLUSTERMESH_DEBUG_REQUIRE_OVERLAY_RESET": "false",
            "CLUSTERMESH_DEBUG_MANIFEST_PATH": str(tmp_path / "manifest.json"),
        }
    )
    return env, az_log, tmp_path / "manifest.json"


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
    assert "- name: scaleDebugRegion" in pipeline
    assert "- name: scaleDebugVmFamilyQuotaName" in pipeline
    assert "- name: scaleDebugTfvarsPath" in pipeline
    assert "- name: scaleDebugTopology" in pipeline
    assert "- name: scaleDebugRequiredFamilyVcpus" in pipeline
    assert "- name: scaleDebugRunWorkload" in pipeline

    assert "CLUSTERMESH_DEBUG_MODE'], 'fresh-preserve'" in fresh
    assert 'SKIP_RESOURCE_DELETION: "true"' in fresh
    assert 'CLUSTERMESH_DEBUG_PRESERVE: "true"' in fresh
    assert "NETWORK_DATAPLANE: cilium" in fresh
    assert "NETWORK_POLICY: cilium" in fresh
    assert "emit_resume_manifest: true" in fresh
    assert 'debug_preserve: "true"' in fresh
    assert "eq(variables['Build.Reason'], 'Manual')" in fresh
    assert "eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '')" in fresh
    assert "parameters.scaleDebugRegion" in fresh
    assert "parameters.lifecycleSubscriptionId" in fresh
    assert "parameters.scaleDebugVmFamilyQuotaName" in fresh
    assert "parameters.scaleDebugTfvarsPath" in fresh
    assert "parameters.scaleDebugClusterCount" in fresh
    assert "parameters.scaleDebugRequiredFamilyVcpus" in fresh
    assert "parameters.scaleDebugTopology" in fresh
    assert "parameters.scaleDebugRunWorkload" in fresh
    assert "suite_total_budget_seconds: 7200" in fresh
    assert "timeout_in_minutes: 600" in fresh
    assert 'cl2_prom_snapshot_storage_account: "cmshscaleprom"' in fresh
    assert 'AKS_AMW_CLUSTERS_PER_WORKSPACE: "1"' in fresh
    assert 'AKS_AMW_FORCE_SHARD_NAMING: "true"' in fresh
    assert 'AKS_AMW_PREFLIGHT_MAX_UTILIZATION_PERCENT: "90"' in fresh
    assert 'AKS_AMW_REGIONAL_WORKSPACE_LIMIT: "100"' in fresh
    assert 'AKS_AMW_MAX_ACTIVE_TIME_SERIES: "1000000"' in fresh
    assert 'AKS_AMW_MAX_EVENTS_PER_MINUTE: "1000000"' in fresh

    assert "CLUSTERMESH_DEBUG_MODE'], 'reset-fleet'" in reset
    assert "CLUSTERMESH_DEBUG_CONFIRM_RESET" in reset
    assert "reset-fleet-overlay.sh" in reset
    assert "eq(variables['Build.Reason'], 'Manual')" in reset
    assert "eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '')" in reset
    assert "region: ${{ parameters.scaleDebugRegion }}" in reset
    assert "parameters.lifecycleSubscriptionId" in reset
    assert "parameters.scaleDebugTfvarsPath" in reset
    assert "parameters.scaleDebugClusterCount" in reset
    assert 'CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS: "168"' in reset

    assert "CLUSTERMESH_DEBUG_MODE'], 'resume'" in resume
    assert "CLUSTERMESH_DEBUG_MODE'], 'resume-existing'" in resume
    assert "and(succeededOrFailed()," in resume
    assert "and(always()," not in resume
    assert "clustermesh-debug-resume.yml" in resume
    assert "CLUSTERMESH_QUOTA_PREFLIGHT_ENABLED: \"false\"" in resume
    assert "eq(variables['Build.Reason'], 'Manual')" in resume
    assert "eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '')" in resume
    assert "region: ${{ parameters.scaleDebugRegion }}" in resume
    assert "parameters.lifecycleSubscriptionId" in resume
    assert "parameters.scaleDebugTfvarsPath" in resume
    assert "parameters.scaleDebugClusterCount" in resume
    assert "parameters.scaleDebugTopology" in resume
    assert "parameters.scaleDebugRunWorkload" in resume
    assert 'cl2_prom_snapshot_storage_account: "cmshscaleprom"' in resume
    assert 'AKS_AMW_CLUSTERS_PER_WORKSPACE: "1"' in resume
    assert 'AKS_AMW_FORCE_SHARD_NAMING: "true"' in resume
    assert 'AKS_AMW_PREFLIGHT_MAX_UTILIZATION_PERCENT: "90"' in resume
    assert 'AKS_AMW_REGIONAL_WORKSPACE_LIMIT: "100"' in resume
    assert 'AKS_MANAGED_PROMETHEUS_REBALANCE_EXISTING: "true"' in resume
    assert 'AKS_AMW_REBALANCE_SETTLE_SECONDS: "600"' in resume
    assert 'AKS_AMW_MAX_ACTIVE_TIME_SERIES: "1000000"' in resume
    assert 'AKS_AMW_MAX_EVENTS_PER_MINUTE: "1000000"' in resume
    assert 'CLUSTERMESH_PRESERVED_WORKER_RECOVERY_ENABLED: "true"' in resume
    assert 'CLUSTERMESH_DEBUG_MAX_WORKER_REPAIR_CLUSTERS: "5"' in resume
    assert 'CLUSTERMESH_LIVE_DATA_PLANE_REPAIR_ENABLED: "true"' in resume
    assert 'CLUSTERMESH_NODE_READINESS_SELECTOR: "type!=kwok"' in resume
    assert "parameters.debugMode" in resume
    assert "overlay_mode: resume-existing" in resume
    assert "overlay_mode: resume" in resume

    assert "CLUSTERMESH_DEBUG_MODE'], 'cleanup'" in cleanup
    assert "CLUSTERMESH_DEBUG_CONFIRM_DELETE" in cleanup
    assert "CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID" in cleanup
    assert "delete-preserved-rg.sh" in cleanup
    assert "eq(variables['Build.Reason'], 'Manual')" in cleanup
    assert "eq(variables['CLUSTERMESH_REUSE_SMOKE_MODE'], '')" in cleanup
    assert (
        "CLUSTERMESH_DEBUG_EXPECTED_REGION: "
        "${{ parameters.scaleDebugRegion }}"
        in cleanup
    )
    assert "parameters.lifecycleSubscriptionId" in cleanup
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
    set_run_id = SET_RUN_ID_PATH.read_text(encoding="utf-8")

    assert "/steps/provision-resources.yml" not in resume
    assert "/steps/cleanup-resources.yml" not in resume
    assert "validate-existing-scale.sh" in resume
    assert "create-staged-fleet-overlay.sh" in resume
    assert "repair-existing-fleet-overlay.sh" in resume
    assert "/steps/validate-resources.yml" in resume
    assert "/steps/execute-tests.yml" in resume
    assert "/steps/publish-results.yml" in resume
    assert "CLUSTERMESH_DEBUG_CONFIRM_RESUME" in resume
    assert "- name: overlay_mode" in resume
    assert "- name: target_run_id" in resume
    assert "run_id: ${{ parameters.target_run_id }}" in resume
    assert "RUN_ID: ${{ parameters.target_run_id }}" in resume
    assert "run_id: $(CLUSTERMESH_DEBUG_TARGET_RUN_ID)" not in resume
    assert "CLUSTERMESH_DEBUG_MAX_REPAIR_MEMBERS" in resume
    assert "requested_run_id='${{ parameters.run_id }}'" in set_run_id
    assert 'elif [ -n "${RUN_ID:-}" ]' in set_run_id
    assert "RUN_ID: ${{ parameters.run_id }}" not in set_run_id
    assert "- name: expected_cluster_count" in resume
    assert "- name: run_workload" in resume
    assert "- name: publish_results" in resume
    assert "${{ if parameters.run_workload }}:" in resume
    assert 'CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS: "168"' in resume
    assert (
        "${{ if and(parameters.run_workload, parameters.publish_results) }}:"
        in resume
    )


def test_fresh_preserve_n100_lease_is_seven_days():
    tfvars = N100_TFVARS_PATH.read_text(encoding="utf-8")

    assert 'deletion_delay = "168h"' in tfvars


def test_fresh_preserve_n100_splits_vm_family_quota():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    tfvars = N100_TFVARS_PATH.read_text(encoding="utf-8")

    assert "default: 1736" in pipeline
    assert tfvars.count('vm_size              = "Standard_D8_v3"') == 101
    assert tfvars.count('vm_size              = "Standard_D8s_v5"') == 100


def test_global_cilium_policy_is_injected_into_aks_cli_configs():
    terraform = AZURE_TERRAFORM_MAIN.read_text(encoding="utf-8")

    assert "local.aks_network_dataplane != null" in terraform
    assert '"network-dataplane"' in terraform
    assert "local.aks_network_policy != null" in terraform
    assert '"network-policy"' in terraform
    assert terraform.count(
        "[for parameter in aks.optional_parameters : parameter.name]"
    ) >= 2


def test_fleet_reset_and_resume_do_not_mutate_aks_lifecycle():
    reset = RESET_SCRIPT.read_text(encoding="utf-8")
    create = CREATE_SCRIPT.read_text(encoding="utf-8")
    repair = REPAIR_SCRIPT.read_text(encoding="utf-8")

    for forbidden in ("az aks delete", "az aks create", "az group delete"):
        assert forbidden not in reset
    assert "az fleet clustermeshprofile delete" in reset
    assert "az fleet member delete" in reset
    assert "az fleet delete" in reset
    assert "does not exactly match" in reset
    assert "CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT" in reset
    assert "--argjson expected_count" in reset
    assert '--slurpfile members "$member_file"' in reset
    assert '--slurpfile clusters "$cluster_file"' in reset
    assert "--argjson members" not in reset
    assert "--argjson clusters" not in reset
    assert "clustermesh-reset-inventory" in reset
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

    for forbidden in ("az aks delete", "az aks create", "az group delete", "az fleet delete"):
        assert forbidden not in repair
    assert "CLUSTERMESH_DEBUG_MAX_REPAIR_MEMBERS" in repair
    assert "Surgically rejoining" in repair
    assert "repair profile apply" in repair.lower()
    assert "ResourceNotFinalState" in repair
    assert "Fleet surgical repair completed" in repair
    assert "CLUSTERMESH_DEBUG_FORCE_REPAIR_ROLES_FILE" in repair
    assert "live-data-plane unhealthy member(s)" in repair
    assert '--slurpfile members "$member_file"' in repair
    assert '--slurpfile applied "$profile_member_file"' in repair
    assert '--slurpfile clusters "$cluster_file"' in repair


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
        "nodeResourceGroup",
        "managedBy",
        "node_resource_group_count",
        "cannot be repaired in place",
    ):
        assert expected in validation

    assert "az group update" not in manifest


def test_preserved_validation_rejects_missing_node_resource_group(tmp_path):
    env, az_log, _ = _write_validation_fixture(
        tmp_path,
        include_second_node_group=False,
    )

    result = subprocess.run(
        ["bash", str(VALIDATE_SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "node resource groups are missing" in result.stderr
    assert "MC_12345-deadbeef_clustermesh-2_eastus2euap" in result.stderr
    assert "cannot be repaired in place" in result.stderr
    assert "group update" not in az_log.read_text(encoding="utf-8")


def test_preserved_validation_extends_child_leases_before_parent(tmp_path):
    env, az_log, manifest_path = _write_validation_fixture(
        tmp_path,
        include_second_node_group=True,
    )

    result = subprocess.run(
        ["bash", str(VALIDATE_SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    updates = [
        line
        for line in az_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("group update ")
    ]
    assert len(updates) == 2
    assert "--name MC_12345-deadbeef_clustermesh-1_eastus2euap" in updates[0]
    assert "--name 12345-deadbeef" in updates[1]
    assert not any("clustermesh-2" in update for update in updates)
    assert "Preserving later existing node RG lease" in result.stdout

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["node_resource_group_count"] == 2
    assert manifest["node_resource_groups_extended"] == 1
    assert len(manifest["node_resource_groups"]) == 2


def test_preserved_resume_recovery_runs_before_authoritative_validation():
    validation = BASE_VALIDATE_PATH.read_text(encoding="utf-8")

    enumerate_pos = validation.index('displayName: "Enumerate clustermesh clusters"')
    worker_pos = validation.index(
        'displayName: "Recover preserved real AKS workers"'
    )
    apiserver_pos = validation.index(
        'displayName: "Wait for clustermesh-apiserver Deployments + LBs (parallel)"'
    )
    live_pos = validation.index(
        'displayName: "Repair stale live ClusterMesh peers"'
    )
    validate_pos = validation.index(
        'displayName: "Validate Cilium + ClusterMesh on every cluster"'
    )

    assert enumerate_pos < worker_pos < apiserver_pos < live_pos < validate_pos
    assert "preserved_worker_reconcile.py" in validation
    assert "preserved_live_overlay.py" in validation
    assert 'node_selector_args=(-l "$node_readiness_selector")' in validation
    assert (
        'get nodes "${node_selector_args[@]}" -o json'
        in validation
    )
    assert "ensure_kubeconfig" in validation


def test_preserved_resume_repair_is_bounded_and_non_destructive():
    worker = WORKER_RECONCILE_SCRIPT.read_text(encoding="utf-8")
    live = LIVE_OVERLAY_SCRIPT.read_text(encoding="utf-8")

    for forbidden in ("az aks delete", "az group delete", "az fleet delete"):
        assert forbidden not in worker
        assert forbidden not in live
    assert "max-repair-clusters" in worker
    assert "delete-instances" in worker
    assert "stale_instance_ids" in worker
    assert "repair_roles_for_drift" in live
    assert "cluster-mesh" in live


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


def test_connected_member_can_be_forced_through_surgical_repair(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az_log = tmp_path / "az.log"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo "$*" >> "$AZ_LOG"\n'
        'case "$*" in\n'
        '  "fleet show "*) echo "{}" ;;\n'
        '  "fleet clustermeshprofile show "*) echo "{}" ;;\n'
        '  "fleet member list "*) cat <<\'JSON\'\n'
        '[{"name":"mesh-1","clusterResourceId":"/subscriptions/s/mesh-1",'
        '"labels":{"mesh":"true"}},'
        '{"name":"mesh-2","clusterResourceId":"/subscriptions/s/mesh-2",'
        '"labels":{"mesh":"true"}}]\n'
        "JSON\n"
        "    ;;\n"
        '  "fleet clustermeshprofile list-members "*) cat <<\'JSON\'\n'
        '[{"name":"mesh-1","meshProperties":{"status":{"state":"Connected"}}},'
        '{"name":"mesh-2","meshProperties":{"status":{"state":"Connected"}}}]\n'
        "JSON\n"
        "    ;;\n"
        '  "resource list "*) cat <<\'JSON\'\n'
        '[{"name":"mesh-1","clusterResourceId":"/subscriptions/s/mesh-1"},'
        '{"name":"mesh-2","clusterResourceId":"/subscriptions/s/mesh-2"}]\n'
        "JSON\n"
        "    ;;\n"
        '  "fleet member update "*|"fleet clustermeshprofile apply "*|'
        '"group update "*) ;;\n'
        '  *) echo "unexpected az command: $*" >&2; exit 98 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_az.chmod(0o755)
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)
    forced_roles = tmp_path / "roles.txt"
    forced_roles.write_text("mesh-2\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "AZ_LOG": str(az_log),
            "CLUSTERMESH_DEBUG_TARGET_RUN_ID": "12345-deadbeef",
            "CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT": "2",
            "CLUSTERMESH_DEBUG_MAX_REPAIR_MEMBERS": "2",
            "CLUSTERMESH_DEBUG_FORCE_REPAIR_ROLES_FILE": str(forced_roles),
            "CLUSTERMESH_DEBUG_REPAIR_DETACH_SETTLE_SECONDS": "1",
            "CLUSTERMESH_DEBUG_REPAIR_WAIT_SECONDS": "2",
            "CLUSTERMESH_DEBUG_REPAIR_POLL_SECONDS": "1",
            "CLUSTERMESH_DEBUG_REPAIR_APPLY_RETRY_SECONDS": "1",
            "CLUSTERMESH_DEBUG_REPAIR_APPLY_ATTEMPTS": "1",
            "BUILD_ARTIFACTSTAGINGDIRECTORY": str(tmp_path / "artifacts"),
        }
    )
    result = subprocess.run(
        ["bash", str(REPAIR_SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    log = az_log.read_text(encoding="utf-8")
    assert log.count("fleet member update") == 2
    assert "fleet member update" in log
    assert "--name mesh-2" in log
    assert "--name mesh-1 --labels" not in log


def test_surgical_repair_restores_labels_when_detach_fails(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az_log = tmp_path / "az.log"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo "$*" >> "$AZ_LOG"\n'
        'case "$*" in\n'
        '  "fleet show "*) echo "{}" ;;\n'
        '  "fleet clustermeshprofile show "*) echo "{}" ;;\n'
        '  "fleet member list "*) cat <<\'JSON\'\n'
        '[{"name":"mesh-1","clusterResourceId":"/subscriptions/s/mesh-1",'
        '"labels":{"mesh":"true"}},'
        '{"name":"mesh-2","clusterResourceId":"/subscriptions/s/mesh-2",'
        '"labels":{"mesh":"true"}}]\n'
        "JSON\n"
        "    ;;\n"
        '  "fleet clustermeshprofile list-members "*) cat <<\'JSON\'\n'
        '[{"name":"mesh-1","meshProperties":{"status":{"state":"Connected"}}},'
        '{"name":"mesh-2","meshProperties":{"status":{"state":"Connected"}}}]\n'
        "JSON\n"
        "    ;;\n"
        '  "resource list "*) cat <<\'JSON\'\n'
        '[{"name":"mesh-1","clusterResourceId":"/subscriptions/s/mesh-1"},'
        '{"name":"mesh-2","clusterResourceId":"/subscriptions/s/mesh-2"}]\n'
        "JSON\n"
        "    ;;\n"
        '  "fleet member update "*"--name mesh-2"*"--labels mesh=repairing"*) '
        "exit 42 ;;\n"
        '  "fleet member update "*|"fleet clustermeshprofile apply "*) ;;\n'
        '  *) echo "unexpected az command: $*" >&2; exit 98 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_az.chmod(0o755)
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)
    forced_roles = tmp_path / "roles.txt"
    forced_roles.write_text("mesh-1\nmesh-2\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "AZ_LOG": str(az_log),
            "CLUSTERMESH_DEBUG_TARGET_RUN_ID": "12345-deadbeef",
            "CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT": "2",
            "CLUSTERMESH_DEBUG_MAX_REPAIR_MEMBERS": "2",
            "CLUSTERMESH_DEBUG_FORCE_REPAIR_ROLES_FILE": str(forced_roles),
            "CLUSTERMESH_DEBUG_REPAIR_DETACH_SETTLE_SECONDS": "1",
            "CLUSTERMESH_DEBUG_REPAIR_WAIT_SECONDS": "2",
            "CLUSTERMESH_DEBUG_REPAIR_POLL_SECONDS": "1",
            "CLUSTERMESH_DEBUG_REPAIR_APPLY_RETRY_SECONDS": "1",
            "CLUSTERMESH_DEBUG_REPAIR_APPLY_ATTEMPTS": "1",
        }
    )
    result = subprocess.run(
        ["bash", str(REPAIR_SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    log = az_log.read_text(encoding="utf-8")
    assert "--name mesh-1 --labels mesh=true" in log
    assert "--name mesh-2 --labels mesh=true" in log
    assert "Repair interrupted; restoring Fleet selector labels" in result.stderr


def test_pipeline_and_debug_templates_parse_as_yaml():
    yaml.safe_load(PIPELINE_PATH.read_text(encoding="utf-8"))
    yaml.safe_load(COMPETITIVE_JOB_PATH.read_text(encoding="utf-8"))
    yaml.safe_load(RESUME_JOB_PATH.read_text(encoding="utf-8"))
    yaml.safe_load(
        (REUSE_DIR / "write-resume-manifest.yml").read_text(encoding="utf-8")
    )
