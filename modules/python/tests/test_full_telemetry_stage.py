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


def test_dedicated_full_telemetry_stage_is_isolated():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")

    assert "azure_eastus2euap_n2_mock_full_telemetry" in pipeline
    assert "n2_mock_full_telemetry:" in pipeline
    assert 'AKS_CONTROL_PLANE_METRICS_ENABLED: "true"' in pipeline
    assert "AKS_CONTROL_PLANE_LAW_NAME: cmsh-scale-controlplane-law" in pipeline
    assert 'kwok_usage_cpu: "25m"' in pipeline
    assert 'kwok_usage_memory: "64Mi"' in pipeline
    assert "timeout_in_minutes: 480" in pipeline


def test_full_telemetry_azure_tasks_use_ui_selected_subscription():
    for path in (
        CONFIGURE_TEMPLATE_PATH,
        COLLECT_TEMPLATE_PATH,
        SNAPSHOT_TEMPLATE_PATH,
    ):
        template = path.read_text(encoding="utf-8")
        assert 'az account set --subscription "$TARGET_SUBSCRIPTION_ID"' in template
        assert "TARGET_SUBSCRIPTION_ID: $(AZURE_SUBSCRIPTION_ID)" in template


def test_control_plane_artifact_directory_exists_after_configuration_failure():
    template = COLLECT_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "Prepare AKS control-plane telemetry artifact" in template
    assert 'condition: and(succeededOrFailed(),' in template
