#!/usr/bin/env python3
"""Export all AKS Azure Monitor platform metrics as OpenMetrics samples."""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from amw_tsdb_snapshot import (
    escape_label_value,
    format_timestamp_seconds,
    parse_time,
    sanitize_label_name,
    sanitize_metric_name,
)


def run_az(arguments):
    result = subprocess.run(
        ["az", *arguments, "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def metadata_labels(values):
    labels = {}
    for item in values or []:
        name = (
            item.get("name", {}).get("value")
            or item.get("name", {}).get("localizedValue")
            or ""
        )
        if name:
            labels[sanitize_label_name(name)] = item.get("value", "")
    return labels


def render_labels(labels):
    if not labels:
        return ""
    rendered = ",".join(
        f'{name}="{escape_label_value(value)}"'
        for name, value in sorted(labels.items())
    )
    return f"{{{rendered}}}"


def export_aggregation(output, definition, aggregation, args, start, end):
    metric_name = definition["name"]["value"]
    value_key = aggregation.lower()
    local_name = sanitize_metric_name(
        f"azure_platform_{metric_name}_{value_key}"
    )
    interval = definition.get("metricAvailabilities", [{}])[0].get(
        "timeGrain",
        "PT1M",
    )
    response = run_az(
        [
            "monitor",
            "metrics",
            "list",
            "--resource",
            args.resource,
            "--metric",
            metric_name,
            "--interval",
            interval,
            "--aggregation",
            aggregation,
            "--start-time",
            start,
            "--end-time",
            end,
        ]
    )

    sample_count = 0
    output.write(f"# TYPE {local_name} gauge\n")
    for metric in response.get("value", []):
        for series in metric.get("timeseries", []):
            labels = metadata_labels(series.get("metadatavalues"))
            labels.update(
                {
                    "cluster": args.cluster_label,
                    "source": "azure-monitor-platform",
                    "unit": definition.get("unit", ""),
                }
            )
            rendered_labels = render_labels(labels)
            for point in series.get("data", []):
                value = point.get(value_key)
                if value is None:
                    continue
                timestamp = parse_time(point["timeStamp"])
                output.write(
                    f"{local_name}{rendered_labels} {value} "
                    f"{format_timestamp_seconds(timestamp)}\n"
                )
                sample_count += 1
    return local_name, interval, sample_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--cluster-label", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    start = datetime.fromtimestamp(parse_time(args.start), timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end = datetime.fromtimestamp(parse_time(args.end), timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    definitions = run_az(
        [
            "monitor",
            "metrics",
            "list-definitions",
            "--resource",
            args.resource,
        ]
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    exported = []
    no_data = []
    errors = []
    with output_path.open("w", encoding="utf-8") as output:
        for index, definition in enumerate(definitions, start=1):
            metric_name = definition["name"]["value"]
            aggregations = (
                definition.get("supportedAggregationTypes")
                or [definition.get("primaryAggregationType") or "Average"]
            )
            for aggregation in aggregations:
                interval = definition.get("metricAvailabilities", [{}])[0].get(
                    "timeGrain",
                    "PT1M",
                )
                try:
                    local_name, interval, sample_count = export_aggregation(
                        output,
                        definition,
                        aggregation,
                        args,
                        start,
                        end,
                    )
                except subprocess.CalledProcessError as error:
                    errors.append(
                        {
                            "metric": metric_name,
                            "aggregation": aggregation,
                            "interval": interval,
                            "error": error.stderr.strip(),
                        }
                    )
                    continue

                key = f"{metric_name}:{aggregation}"
                if sample_count:
                    exported.append(
                        {
                            "source_metric": metric_name,
                            "local_metric": local_name,
                            "aggregation": aggregation,
                            "interval": interval,
                            "samples": sample_count,
                        }
                    )
                else:
                    no_data.append(key)
                print(
                    f"platform metrics {index}/{len(definitions)}: "
                    f"{key} samples={sample_count}",
                    flush=True,
                )
        output.write("# EOF\n")

    manifest = {
        "schema_version": 1,
        "resource": args.resource,
        "cluster_label": args.cluster_label,
        "start": start,
        "end": end,
        "definitions": len(definitions),
        "exported": exported,
        "no_data": no_data,
        "errors": errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    Path(args.manifest).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
