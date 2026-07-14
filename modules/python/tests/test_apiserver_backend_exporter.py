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


def load_exporter():
    configmap = yaml.safe_load(CONFIGMAP_PATH.read_text(encoding="utf-8"))
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
    assert values == {
        "cpu_seconds": 123.5,
        "rss_bytes": 456.0,
        "start_time": 789.25,
    }


def test_exporter_renders_each_backend_independently():
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
