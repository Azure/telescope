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


def test_block_labels_are_validated_and_added_to_promtool_command(tmp_path):
    labels = snapshot_module.parse_block_labels(
        ["run=run-1", "build=123", "tier=n2_sharded"]
    )
    command = snapshot_module.promtool_import_command(
        "/usr/bin/promtool",
        tmp_path / "input.openmetrics",
        tmp_path / "data",
        labels,
    )

    assert labels == {
        "run": "run-1",
        "build": "123",
        "tier": "n2_sharded",
    }
    assert "--label=build=123" in command
    assert "--label=run=run-1" in command
    assert "--label=tier=n2_sharded" in command


def test_block_label_collisions_are_rejected(tmp_path):
    try:
        snapshot_module.parse_block_labels(["run=a", "run=b"])
    except ValueError as error:
        assert "more than once" in str(error)
    else:
        raise AssertionError("duplicate block label was accepted")

    extra = tmp_path / "extra.openmetrics"
    extra.write_text(
        'probe_metric{note="contains,run=value",tier="existing"} 1\n# EOF\n',
        encoding="utf-8",
    )
    try:
        snapshot_module.validate_extra_openmetrics(
            [extra],
            {"run": "new", "tier": "n2"},
        )
    except ValueError as error:
        assert "tier" in str(error)
        assert "run" not in str(error)
    else:
        raise AssertionError("extra OpenMetrics collision was accepted")

    try:
        snapshot_module.openmetrics_line(
            {"__name__": "probe_metric", "run": "existing"},
            "1",
            1,
            {},
            {},
            block_labels={"run": "new"},
        )
    except ValueError as error:
        assert "run" in str(error)
    else:
        raise AssertionError("queried metric collision was accepted")


def test_export_metric_recovers_and_deduplicates_source_timestamps(tmp_path):
    class Api:
        calls = []

        @staticmethod
        def query_range(
            _metric_name,
            _start,
            _end,
            _step,
            timestamps=False,
        ):
            Api.calls.append(timestamps)
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
    assert Api.calls == [True, False]


def test_export_metric_releases_chunk_before_next_query(tmp_path):
    released = []

    class Response(dict):
        def __init__(self, name, payload):
            super().__init__(payload)
            self.name = name

        def __del__(self):
            released.append(self.name)

    class Api:
        @staticmethod
        def query_range(
            _metric_name,
            start,
            _end,
            _step,
            timestamps=False,
        ):
            chunk = int(start)
            if chunk > 0 and timestamps:
                assert "data-0" in released
            value = str(chunk + 1)
            return Response(
                f"{'timestamps' if timestamps else 'data'}-{chunk}",
                {
                    "result": [
                        {
                            "metric": {
                                "__name__": "probe_metric",
                                "cluster": "mesh",
                            },
                            "values": [[start, value]],
                        }
                    ]
                },
            )

    output = tmp_path / "metric.openmetrics"
    snapshot_module.export_metric(
        Api(),
        "probe_metric",
        output,
        start=0,
        end=45,
        step=15,
        chunk_seconds=15,
    )

    assert "data-0" in released
    assert "timestamps-0" in released
