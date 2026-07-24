"""Tests for the API server HA backend resource exporter."""

import time
from pathlib import Path

import yaml


CONFIGMAP_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "modules"
    / "apiserver-backend-exporter"
    / "configmap.yaml"
)
MODULE_PATH = CONFIGMAP_PATH.parents[1] / "clustermesh.yaml"
EXPORTER_DIR = CONFIGMAP_PATH.parent
WORKER_PATH = (
    Path(__file__).resolve().parents[3]
    / "steps"
    / "engine"
    / "clusterloader2"
    / "clustermesh-scale"
    / "run-cl2-on-cluster.sh"
)
AZURE_MONITORS_PATH = (
    Path(__file__).resolve().parents[3]
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "telemetry"
    / "azure-monitor-control-plane-monitors.yaml"
)


def load_exporter():
    rendered = CONFIGMAP_PATH.read_text(encoding="utf-8").replace(
        "{{.Name}}",
        "apiserver-backend-exporter-test",
    )
    configmap = yaml.safe_load(rendered)
    source = configmap["data"]["exporter.py"]
    namespace = {"__name__": "apiserver_backend_exporter_test"}
    exec(compile(source, str(CONFIGMAP_PATH), "exec"), namespace)
    return source, namespace


def test_exporter_script_compiles_and_parses_process_metrics():
    source, exporter = load_exporter()

    values = exporter["parse_process_metrics"](
        "\n".join(
            [
                "process_cpu_seconds_total 123.5",
                "process_resident_memory_bytes 456",
                "process_start_time_seconds 789.25",
            ]
        )
    )

    assert "ThreadingHTTPServer" in source
    assert "{{" not in source
    assert "}}" not in source
    assert values == {
        "cpu_seconds": 123.5,
        "rss_bytes": 456.0,
        "start_time": 789.25,
    }


def test_exporter_renders_each_backend_independently(monkeypatch):
    for environment in (
        "CLUSTERMESH_RUN_ID",
        "CLUSTERMESH_CLUSTER_ROLE",
        "CLUSTERMESH_CLUSTER_NAME",
        "CLUSTERMESH_CLUSTER_RESOURCE_ID",
        "CLUSTERMESH_SUBSCRIPTION_ID",
        "CLUSTERMESH_RESOURCE_GROUP",
        "CLUSTERMESH_REGION",
        "CLUSTERMESH_PROMETHEUS_CLUSTER_ALIAS",
    ):
        monkeypatch.delenv(environment, raising=False)
    _, exporter = load_exporter()
    now = time.time()
    exporter["BACKENDS"].update(
        {
            "1000": {
                "backend_id": "1000",
                "cpu_seconds": 12.5,
                "rss_bytes": 256,
                "start_time": 1,
                "last_seen": now,
                "observations": 3,
            },
            "2000": {
                "backend_id": "2000",
                "cpu_seconds": 22.5,
                "rss_bytes": 512,
                "start_time": 2,
                "last_seen": now,
                "observations": 4,
            },
        }
    )

    metrics = exporter["render_metrics"]()

    assert "aks_apiserver_backend_discovered 2" in metrics
    assert (
        'aks_apiserver_backend_process_cpu_seconds_total{backend_id="1000"} 12.5'
        in metrics
    )
    assert (
        'aks_apiserver_backend_process_resident_memory_bytes'
        '{backend_id="2000"} 512'
        in metrics
    )
    assert "clustermesh_cluster_identity_info" not in metrics


def test_exporter_renders_cluster_identity(monkeypatch):
    identity = {
        "CLUSTERMESH_RUN_ID": "73599-a1b2",
        "CLUSTERMESH_CLUSTER_ROLE": "mesh-1",
        "CLUSTERMESH_CLUSTER_NAME": "clustermesh-1",
        "CLUSTERMESH_CLUSTER_RESOURCE_ID": (
            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
            "Microsoft.ContainerService/managedClusters/clustermesh-1"
        ),
        "CLUSTERMESH_SUBSCRIPTION_ID": "sub-1",
        "CLUSTERMESH_RESOURCE_GROUP": "rg-1",
        "CLUSTERMESH_REGION": "eastus2euap",
        "CLUSTERMESH_PROMETHEUS_CLUSTER_ALIAS": "73599_a1b2_mesh_1",
    }
    for name, value in identity.items():
        monkeypatch.setenv(name, value)

    _, exporter = load_exporter()
    metrics = exporter["render_metrics"]()

    assert (
        'clustermesh_cluster_identity_info{cluster_name="clustermesh-1",'
        'cluster_resource_id="/subscriptions/sub-1/resourceGroups/rg-1/'
        'providers/Microsoft.ContainerService/managedClusters/clustermesh-1",'
        'cluster_role="mesh-1",prometheus_cluster_alias="73599_a1b2_mesh_1",'
        'region="eastus2euap",resource_group="rg-1",run_id="73599-a1b2",'
        'subscription_id="sub-1"} 1'
        in metrics
    )


def test_worker_injects_identity_into_exporter():
    worker = WORKER_PATH.read_text(encoding="utf-8")

    assert "deployment -l app=apiserver-backend-exporter" in worker
    assert '"deployment/$_identity_deployment_name"' in worker
    for environment in (
        "CLUSTERMESH_RUN_ID",
        "CLUSTERMESH_CLUSTER_ROLE",
        "CLUSTERMESH_CLUSTER_NAME",
        "CLUSTERMESH_CLUSTER_RESOURCE_ID",
        "CLUSTERMESH_SUBSCRIPTION_ID",
        "CLUSTERMESH_RESOURCE_GROUP",
        "CLUSTERMESH_REGION",
        "CLUSTERMESH_PROMETHEUS_CLUSTER_ALIAS",
    ):
        assert f'{environment}="${environment}"' in worker


def test_exporter_cluster_scoped_rbac_is_not_namespaced():
    module = MODULE_PATH.read_text(encoding="utf-8")

    assert "DefaultParam .CL2_MOCK_MODE false" in module
    assert "DefaultParam .mockMode $globalMockMode" in module
    assert '- namespaceList:\n        - ""' in module
    assert (
        'objectTemplatePath: "modules/apiserver-backend-exporter/clusterrole.yaml"'
        in module
    )
    assert (
        "objectTemplatePath: "
        '"modules/apiserver-backend-exporter/clusterrolebinding.yaml"'
        in module
    )
    for path in EXPORTER_DIR.glob("*.yaml"):
        template = path.read_text(encoding="utf-8")
        assert "name: {{.Name}}" in template


def test_managed_exporter_monitor_survives_monitoring_namespace_retry():
    monitors = list(
        yaml.safe_load_all(AZURE_MONITORS_PATH.read_text(encoding="utf-8"))
    )
    exporter_monitor = next(
        monitor
        for monitor in monitors
        if monitor["metadata"]["name"] == "apiserver-backend-exporter"
    )

    assert exporter_monitor["metadata"]["namespace"] == "kube-system"
    assert exporter_monitor["spec"]["namespaceSelector"]["matchNames"] == [
        "monitoring"
    ]
