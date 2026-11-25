#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def parse_ts(value):
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def seconds_between(start, end):
    if not start or not end:
        return None
    return max(0.0, (end - start).total_seconds())


def metric_from_events(events, start_reason, end_reason):
    starts = [event["ts"] for event in events if event["reason"] == start_reason and event["ts"]]
    ends = [event["ts"] for event in events if event["reason"] == end_reason and event["ts"]]
    if not starts or not ends:
        return None
    end = max(ends)
    start_candidates = [ts for ts in starts if ts <= end]
    start = min(start_candidates) if start_candidates else min(starts)
    return seconds_between(start, end)


def last_float(patterns, text):
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if matches:
            return float(matches[-1])
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pod-events", required=True)
    parser.add_argument("--pod-json", required=True)
    parser.add_argument("--server-log", required=True)
    parser.add_argument("--ready-epoch", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.pod_events, encoding="utf-8") as f:
        raw_events = json.load(f).get("items", [])

    events = []
    for event in raw_events:
        ts = parse_ts(event.get("eventTime")) or parse_ts(event.get("lastTimestamp")) or parse_ts(event.get("firstTimestamp"))
        events.append({
            "reason": event.get("reason"),
            "ts": ts,
            "message": event.get("message", ""),
        })

    with open(args.pod_json, encoding="utf-8") as f:
        pod = json.load(f)

    container_statuses = pod.get("status", {}).get("containerStatuses", [])
    container_started_at = None
    if container_statuses:
        container_started_at = parse_ts(container_statuses[0].get("state", {}).get("running", {}).get("startedAt"))
    if not container_started_at:
        started_events = [event["ts"] for event in events if event["reason"] == "Started" and event["ts"]]
        container_started_at = max(started_events) if started_events else None

    try:
        text = Path(args.server_log).read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""

    vllm_ready_at = datetime.fromtimestamp(args.ready_epoch, tz=timezone.utc)

    model_load_to_gpu_seconds = last_float([
        r"Loading model weights took ([0-9.]+) seconds",
        r"Model loading took ([0-9.]+) seconds",
        r"Loaded model .* in ([0-9.]+) seconds",
    ], text)
    engine_init_seconds = last_float([
        r"init engine .* took ([0-9.]+) s",
    ], text)
    cuda_graph_seconds = last_float([
        r"Graph capturing finished in ([0-9.]+) secs",
        r"Graph capturing finished in ([0-9.]+) seconds",
    ], text)

    metrics = {
        "t_image_pull_seconds": metric_from_events(events, "Pulling", "Pulled"),
        "t_container_start_seconds": metric_from_events(events, "Created", "Started"),
        "t_model_download_seconds": last_float([
            r"Downloaded .* in ([0-9.]+) seconds",
            r"Fetching .* took ([0-9.]+) seconds",
            r"snapshot_download.* took ([0-9.]+) seconds",
        ], text),
        "t_model_load_to_gpu_seconds": model_load_to_gpu_seconds,
        "t_engine_warmup_seconds": engine_init_seconds if engine_init_seconds is not None else cuda_graph_seconds,
        "t_readiness_routing_seconds": seconds_between(container_started_at, vllm_ready_at),
        "engine_init_seconds": engine_init_seconds,
        "cuda_graph_capture_seconds": cuda_graph_seconds,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(metrics, f)

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
