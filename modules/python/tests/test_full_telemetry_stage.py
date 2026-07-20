"""Static checks for the isolated full-telemetry pipeline stage."""

from pathlib import Path


PIPELINE_PATH = (
    Path(__file__).resolve().parents[3]
    / "pipelines"
    / "system"
    / "new-pipeline-test.yml"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
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
    assert "timeout_in_minutes: 480" in pipeline
    assert (
        'share_infra_scenarios: "pod-churn-combined,node-churn-combined"'
        in stage
    )
    assert "node_churn_recovery_grace_seconds: 900" in stage


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
    assert "finalizer completion is unverifiable" in execute


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
        "AKS_CONTROL_PLANE_AMW_NAME_PREFIX:",
        'AKS_AMW_ARM_BATCH_SIZE: "10"',
        'AKS_CONTROL_PLANE_METRICS_CONCURRENCY: "5"',
        'CL2_ACNS_TELEMETRY_ENABLED: "true"',
        'cl2_prom_snapshot_enabled: "true"',
        'CL2_PROBE_WINDOW_DURATION: "60m"',
        "operation_timeout: 90m",
        'share_infra_scenarios: "propagation-probe,pod-churn-combined,node-churn-combined"',
        "share_infra_settle_seconds: 300",
        "node_churn_combined_duration_seconds: 5400",
        "node_churn_ready_timeout_seconds: 1200",
        "node_churn_recovery_grace_seconds: 1800",
    ):
        assert expected in stage
    assert '"{{$namespaces}}"' in pod_churn
    assert '"{{$globalNamespaces}}"' in pod_churn
    assert "clustermesh.cilium.io/global=true" in pod_churn
    assert 'service.cilium.io/global: "true"' in service
    assert 'io.cilium/global-service: "true"' in service
    assert tfvars.count('{ name = "enable-acns", value = "" }') == 100
    assert tfvars.count('name                 = "prompool"') == 100
    assert 'aks_name                      = "clustermesh-100"' in tfvars
