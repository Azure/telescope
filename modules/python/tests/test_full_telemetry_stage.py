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


def test_dedicated_full_telemetry_stage_is_isolated():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")

    assert "azure_eastus2euap_n2_mock_full_telemetry" in pipeline
    assert "n2_mock_full_telemetry:" in pipeline
    assert 'AKS_CONTROL_PLANE_METRICS_ENABLED: "true"' in pipeline
    assert "AKS_CONTROL_PLANE_LAW_NAME: cmsh-scale-controlplane-law" in pipeline
    assert 'kwok_usage_cpu: "25m"' in pipeline
    assert 'kwok_usage_memory: "64Mi"' in pipeline
    assert 'AKS_MANAGED_TSDB_CHUNK_SECONDS: "600"' in pipeline
    assert 'AKS_MANAGED_TSDB_WORKERS: "4"' in pipeline
    assert "timeout_in_minutes: 480" in pipeline


def test_mock_mode_is_normalized_for_shell_gates():
    execute = EXECUTE_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'export CL2_MOCK_MODE="${cl2_mock_mode_raw,,}"' in execute


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
        "Audit and export AKS telemetry",
        "Reconstruct managed Prometheus TSDB",
        "Upload managed telemetry artifacts",
        "Publish AKS control-plane telemetry artifacts",
    ]

    positions = [template.index(name) for name in display_names]
    assert positions == sorted(positions)
    assert template.count("az account set --subscription") == 4
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
