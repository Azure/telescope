"""Static tests for the managed-Prometheus telemetry wiring."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
TELEMETRY_DIR = (
    REPO_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "telemetry"
)


def test_maximal_settings_disable_minimal_ingestion_safely():
    config = yaml.safe_load(
        (TELEMETRY_DIR / "ama-metrics-settings-configmap.yaml").read_text(
            encoding="utf-8"
        )
    )

    cluster = config["data"]["cluster-metrics"]
    control_plane = config["data"]["controlplane-metrics"]
    ksm = yaml.safe_load(config["data"]["ksm-config"])

    assert "enabled = false" in cluster
    assert "enabled = false" in control_plane
    assert "kube-scheduler = true" in control_plane
    assert "kube-controller-manager = true" in control_plane
    assert ksm["labels_allow_list"]["pods"] == ["*"]
    assert "configmaps" not in ksm["annotations_allow_list"]


def test_custom_scrapes_cover_hidden_and_mock_targets():
    config = yaml.safe_load(
        (TELEMETRY_DIR / "ama-metrics-custom-scrapes.yaml").read_text(
            encoding="utf-8"
        )
    )
    scrape_config = yaml.safe_load(config["data"]["prometheus-config"])
    jobs = {job["job_name"] for job in scrape_config["scrape_configs"]}

    assert jobs == {
        "cilium-hubble-full",
        "clustermesh-apiserver-full",
        "kvstoremesh-full",
        "kwok-resource",
    }


def test_scripts_use_current_aks_profile_and_full_export():
    configure = (
        TELEMETRY_DIR / "configure-managed-prometheus.sh"
    ).read_text(encoding="utf-8")
    collect = (
        TELEMETRY_DIR / "collect-managed-prometheus.sh"
    ).read_text(encoding="utf-8")

    assert "azureMonitorProfile.metrics.enabled" in configure
    assert "azureMonitorProfile.metrics.controlPlane.enabled" in configure
    assert "Microsoft.OperationalInsights" in configure
    assert "az monitor diagnostic-settings categories list" in configure
    assert "--export-to-resource-specific true" in configure
    assert "aks_platform_to_openmetrics.py" not in collect
    assert '"$PLATFORM_EXPORT_SCRIPT"' in collect
    assert '"$TSDB_EXPORT_SCRIPT"' in collect
    assert "wait_for_platform_metrics" in collect
    assert "AKSControlPlane" in collect
    assert "AKSAudit" in collect
    assert "AKSAuditAdmin" in collect
    assert "wait_for_logs" in collect
