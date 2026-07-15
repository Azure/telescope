#!/usr/bin/env python3
"""Reconstruct a local Prometheus TSDB snapshot from Azure Monitor PromQL data.

This is query-equivalent export, not a byte-for-byte AMW snapshot. Azure Monitor
does not expose remote_read or native TSDB snapshots, so samples are evaluated
on a fixed query_range step and backfilled into native Prometheus blocks.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


METRIC_NAME_RE = re.compile(r"[^a-zA-Z0-9_:]")
LABEL_NAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def parse_time(value):
    """Parse Unix seconds or RFC3339 into Unix seconds."""
    try:
        return float(value)
    except ValueError:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp()


def format_rfc3339(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def sanitize_metric_name(name):
    sanitized = METRIC_NAME_RE.sub("_", name)
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def sanitize_label_name(name):
    sanitized = LABEL_NAME_RE.sub("_", name)
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def escape_label_value(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def format_timestamp_seconds(value):
    timestamp = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return timestamp or "0"


def openmetrics_line(labels, value, timestamp, name_map, label_map):
    original_metric = labels.get("__name__", "")
    metric_name = sanitize_metric_name(original_metric)
    if metric_name != original_metric:
        name_map[original_metric] = metric_name

    sanitized_labels = {}
    for original_name, label_value in sorted(labels.items()):
        if original_name == "__name__":
            continue
        sanitized_name = sanitize_label_name(original_name)
        existing = sanitized_labels.get(sanitized_name)
        if existing is not None and existing[0] != original_name:
            suffix = hashlib.sha1(
                original_name.encode("utf-8")
            ).hexdigest()[:8]
            sanitized_name = f"{sanitized_name}_{suffix}"
        sanitized_labels[sanitized_name] = (original_name, label_value)
        if sanitized_name != original_name:
            label_map[original_name] = sanitized_name

    if sanitized_labels:
        rendered_labels = ",".join(
            f'{name}="{escape_label_value(label_value)}"'
            for name, (_, label_value) in sorted(sanitized_labels.items())
        )
        metric = f"{metric_name}{{{rendered_labels}}}"
    else:
        metric = metric_name
    return f"{metric} {value} {format_timestamp_seconds(timestamp)}\n"


class PrometheusApi:
    def __init__(self, endpoint, token, resource_scope="", timeout=120, retries=5):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.resource_scope = resource_scope
        self.timeout = timeout
        self.retries = retries

    def get(self, path, params=None):
        query = f"?{urlencode(params, doseq=True)}" if params else ""
        request = Request(
            f"{self.endpoint}{path}{query}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        if self.resource_scope:
            request.add_header("x-ms-azure-scoping", self.resource_scope)

        for attempt in range(1, self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if payload.get("status") != "success":
                    raise RuntimeError(f"Prometheus API returned {payload}")
                return payload["data"]
            except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
                if attempt == self.retries:
                    raise RuntimeError(
                        f"{path} failed after {self.retries} attempts: {error}"
                    ) from error
                time.sleep(min(2 ** attempt, 30))
        raise AssertionError("unreachable")

    def metric_names(self):
        return self.get("/api/v1/label/__name__/values")

    def query_range(self, metric_name, start, end, step, timestamps=False):
        selector = f'{{__name__="{metric_name}"}}'
        query = f"timestamp({selector})" if timestamps else selector
        return self.get(
            "/api/v1/query_range",
            params={
                "query": query,
                "start": format_rfc3339(start),
                "end": format_rfc3339(end),
                "step": f"{step}s",
            },
        )


def deduplicate_metric_names(metric_names):
    selected = {}
    duplicates = {}
    for name in sorted(metric_names):
        folded = name.casefold()
        if folded in selected:
            duplicates.setdefault(selected[folded], []).append(name)
            continue
        selected[folded] = name
    return sorted(selected.values()), duplicates


def metric_chunks(start, end, step, chunk_seconds):
    samples_per_chunk = max(1, int(chunk_seconds // step))
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + samples_per_chunk * step)
        yield cursor, chunk_end
        cursor = chunk_end + step


def export_metric(
    api,
    metric_name,
    output_path,
    start,
    end,
    step,
    chunk_seconds,
):
    sample_count = 0
    series_count = 0
    timestamp_fallbacks = 0
    name_map = {}
    label_map = {}
    last_timestamps = {}
    with output_path.open("w", encoding="utf-8") as output:
        for chunk_start, chunk_end in metric_chunks(
            start,
            end,
            step,
            chunk_seconds,
        ):
            timestamp_data = api.query_range(
                metric_name,
                chunk_start,
                chunk_end,
                step,
                timestamps=True,
            )
            timestamp_series = {}
            for series in timestamp_data.get("result", []):
                labels = tuple(
                    sorted(
                        (name, value)
                        for name, value in series.get("metric", {}).items()
                        if name != "__name__"
                    )
                )
                timestamp_series[labels] = series.get("values", [])
            del timestamp_data

            data = api.query_range(
                metric_name,
                chunk_start,
                chunk_end,
                step,
            )
            source_values = None
            series = None
            for series in data.get("result", []):
                labels = dict(series.get("metric", {}))
                labels.setdefault("__name__", metric_name)
                series_key = tuple(
                    sorted(
                        (name, value)
                        for name, value in labels.items()
                        if name != "__name__"
                    )
                )
                source_values = timestamp_series.pop(series_key, [])
                source_index = 0
                series_count += 1
                for evaluation_time, value in series.get("values", []):
                    evaluation_time = float(evaluation_time)
                    while (
                        source_index < len(source_values)
                        and float(source_values[source_index][0]) < evaluation_time
                    ):
                        source_index += 1
                    timestamp = None
                    if (
                        source_index < len(source_values)
                        and float(source_values[source_index][0]) == evaluation_time
                    ):
                        timestamp = float(source_values[source_index][1])
                    if timestamp is None:
                        timestamp = evaluation_time
                        timestamp_fallbacks += 1
                    previous_timestamp = last_timestamps.get(series_key)
                    if (
                        previous_timestamp is not None
                        and timestamp <= previous_timestamp
                    ):
                        continue
                    last_timestamps[series_key] = timestamp
                    output.write(
                        openmetrics_line(
                            labels,
                            value,
                            timestamp,
                            name_map,
                            label_map,
                        )
                    )
                    sample_count += 1
            timestamp_series.clear()
            data = None
            source_values = None
            series = None
    return {
        "metric": metric_name,
        "series": series_count,
        "samples": sample_count,
        "timestamp_fallbacks": timestamp_fallbacks,
        "metric_name_map": name_map,
        "label_name_map": label_map,
    }


def create_snapshot(args):
    token = os.environ.get(args.token_env, "")
    if not token:
        raise RuntimeError(f"{args.token_env} is required")

    start = parse_time(args.start)
    end = parse_time(args.end)
    if start > end:
        raise ValueError("start must not be after end")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    api = PrometheusApi(
        args.endpoint,
        token,
        resource_scope=args.resource_scope,
        timeout=args.timeout,
        retries=args.retries,
    )

    all_metric_names = api.metric_names()
    metric_names, case_duplicates = deduplicate_metric_names(all_metric_names)
    if args.metric_regex:
        matcher = re.compile(args.metric_regex)
        metric_names = [name for name in metric_names if matcher.search(name)]
    if args.max_metrics:
        metric_names = metric_names[: args.max_metrics]

    temp_root = Path(tempfile.mkdtemp(prefix="amw-export-", dir=output_dir))
    metric_dir = temp_root / "metrics"
    metric_dir.mkdir()
    results = []
    errors = []

    def run_one(index_name):
        index, metric_name = index_name
        metric_path = metric_dir / f"{index:06d}.openmetrics"
        try:
            result = export_metric(
                api,
                metric_name,
                metric_path,
                start,
                end,
                args.step_seconds,
                args.chunk_seconds,
            )
            result["path"] = str(metric_path)
            return result, None
        except Exception as error:  # pylint: disable=broad-exception-caught
            return None, {"metric": metric_name, "error": str(error)}

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        futures = executor.map(run_one, enumerate(metric_names))
        for index, (result, error) in enumerate(futures, start=1):
            if result:
                results.append(result)
            if error:
                errors.append(error)
            if index % 25 == 0 or index == len(metric_names):
                print(
                    f"queried {index}/{len(metric_names)} metrics; "
                    f"errors={len(errors)}",
                    flush=True,
                )

    if errors and not args.allow_partial:
        error_path = output_dir / "amw-export-errors.json"
        error_path.write_text(
            json.dumps(errors, indent=2) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(temp_root)
        raise RuntimeError(
            f"{len(errors)} metric queries failed; details: {error_path}"
        )

    blocks_dir = output_dir / "data"
    blocks_dir.mkdir(exist_ok=True)
    sorted_results = sorted(results, key=lambda item: item["metric"])
    batch_files = []
    for batch_index, offset in enumerate(
        range(0, len(sorted_results), args.metrics_per_block)
    ):
        batch = sorted_results[offset : offset + args.metrics_per_block]
        batch_path = output_dir / f"snapshot-batch-{batch_index:05d}.openmetrics"
        with batch_path.open("w", encoding="utf-8") as combined:
            if batch_index == 0:
                for extra_path in args.extra_openmetrics:
                    with Path(extra_path).open("r", encoding="utf-8") as source:
                        for line in source:
                            if line.strip() != "# EOF":
                                combined.write(line)
            for result in batch:
                metric_path = Path(result["path"])
                with metric_path.open("r", encoding="utf-8") as source:
                    shutil.copyfileobj(source, combined)
                metric_path.unlink()
            combined.write("# EOF\n")
        subprocess.run(
            [
                str(Path(args.promtool).expanduser()),
                "tsdb",
                "create-blocks-from",
                "openmetrics",
                str(batch_path),
                str(blocks_dir),
            ],
            check=True,
        )
        if args.keep_openmetrics:
            batch_files.append(str(batch_path))
        else:
            batch_path.unlink()

    metric_name_map = {}
    label_name_map = {}
    for result in results:
        result.pop("path")
        metric_name_map.update(result.pop("metric_name_map"))
        label_name_map.update(result.pop("label_name_map"))

    manifest = {
        "schema_version": 1,
        "export_type": "query-range-reconstruction",
        "lossless_native_snapshot": False,
        "limitations": [
            "timestamp() recovers AMW's stored sample times, but samples can be missed if the export step exceeds the source scrape interval.",
            "Staleness markers, exemplars, and native histograms aren't represented.",
            "Azure Monitor is case-insensitive; case-only duplicate metric names are deduplicated.",
            "Label and metric names invalid in legacy OpenMetrics are sanitized.",
            "Metric batches create overlapping blocks with disjoint series.",
        ],
        "endpoint": args.endpoint,
        "resource_scope": args.resource_scope,
        "start": format_rfc3339(start),
        "end": format_rfc3339(end),
        "step_seconds": args.step_seconds,
        "chunk_seconds": args.chunk_seconds,
        "metric_names_discovered": len(all_metric_names),
        "metric_names_exported": len(metric_names),
        "series_fragments": sum(result["series"] for result in results),
        "samples": sum(result["samples"] for result in results),
        "timestamp_fallbacks": sum(
            result["timestamp_fallbacks"] for result in results
        ),
        "errors": errors,
        "case_duplicates": case_duplicates,
        "metric_name_map": metric_name_map,
        "label_name_map": label_name_map,
        "extra_openmetrics": args.extra_openmetrics,
        "openmetrics_batches": batch_files,
        "metrics_per_block": args.metrics_per_block,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = blocks_dir / "amw-export-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [str(Path(args.promtool).expanduser()), "tsdb", "list", str(blocks_dir)],
        check=True,
    )

    snapshot_name = (
        f"prom-snapshot-amw-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    tar_path = output_dir / f"{snapshot_name}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(blocks_dir, arcname=snapshot_name)

    shutil.rmtree(temp_root)
    print(json.dumps({"snapshot": str(tar_path), "manifest": manifest}, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--resource-scope", default="")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--step-seconds", type=int, default=15)
    parser.add_argument("--chunk-seconds", type=int, default=1800)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--metrics-per-block", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--metric-regex", default="")
    parser.add_argument("--max-metrics", type=int, default=0)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--keep-openmetrics", action="store_true")
    parser.add_argument(
        "--extra-openmetrics",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--token-env",
        default="PROMETHEUS_BEARER_TOKEN",
    )
    parser.add_argument(
        "--promtool",
        default="~/.local/bin/promtool",
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    create_snapshot(parse_args())
