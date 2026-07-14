"""Tests for managed-Prometheus TSDB reconstruction helpers."""

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "telemetry"
    / "amw_tsdb_snapshot.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "amw_tsdb_snapshot",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
snapshot_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(snapshot_module)


def test_openmetrics_line_sanitizes_azure_resource_labels():
    metric_map = {}
    label_map = {}

    line = snapshot_module.openmetrics_line(
        {
            "__name__": "probe_metric",
            "cluster": "mesh_1",
            "microsoft.resourceid": "/subscriptions/test",
        },
        "2",
        123.5,
        metric_map,
        label_map,
    )

    assert line == (
        'probe_metric{cluster="mesh_1",'
        'microsoft_resourceid="/subscriptions/test"} 2 123.5\n'
    )
    assert label_map == {"microsoft.resourceid": "microsoft_resourceid"}


def test_metric_chunks_cover_every_query_step_once():
    chunks = list(
        snapshot_module.metric_chunks(
            start=0,
            end=120,
            step=15,
            chunk_seconds=30,
        )
    )

    assert chunks == [(0, 30), (45, 75), (90, 120)]


def test_metric_names_are_deduplicated_case_insensitively():
    names, duplicates = snapshot_module.deduplicate_metric_names(
        ["Metric_A", "metric_a", "metric_b"]
    )

    assert names == ["Metric_A", "metric_b"]
    assert duplicates == {"Metric_A": ["metric_a"]}


def test_export_metric_recovers_and_deduplicates_source_timestamps(tmp_path):
    class Api:
        @staticmethod
        def query_range(
            _metric_name,
            _start,
            _end,
            _step,
            timestamps=False,
        ):
            values = (
                [[15, "7"], [30, "22"], [45, "22"]]
                if timestamps
                else [[15, "10"], [30, "20"], [45, "20"]]
            )
            return {
                "result": [
                    {
                        "metric": {
                            "__name__": "probe_metric",
                            "cluster": "mesh",
                        },
                        "values": values,
                    }
                ]
            }

    output = tmp_path / "metric.openmetrics"
    result = snapshot_module.export_metric(
        Api(),
        "probe_metric",
        output,
        start=0,
        end=45,
        step=15,
        chunk_seconds=60,
    )

    assert output.read_text(encoding="utf-8").splitlines() == [
        'probe_metric{cluster="mesh"} 10 7',
        'probe_metric{cluster="mesh"} 20 22',
    ]
    assert result["samples"] == 2
    assert result["timestamp_fallbacks"] == 0
