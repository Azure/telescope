#!/usr/bin/env python3
"""Measure pod startup latency from pod events and write /tmp/run-result.json."""

import datetime
import json
import os
import subprocess
import sys


POD_NAME = os.environ["POD_NAME"]
CLUSTER = os.environ["CLUSTER"]
RUNTIME_CLASS = os.environ["RUNTIME_CLASS"]
NODE_SKU = os.environ["NODE_SKU"]
K8S_VERSION = os.environ["K8S_VERSION"]
PAUSE_IMAGE = os.environ["PAUSE_IMAGE"]


def kubectl_json(*args):
    out = subprocess.check_output(["kubectl", *args, "-o", "json"])
    return json.loads(out)


def parse(ts):
    if not ts:
        return None
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


pod = kubectl_json("get", "pod", POD_NAME)
events = kubectl_json(
    "get", "events", "--field-selector", f"involvedObject.name={POD_NAME}"
)


def event_time(reason):
    for e in events.get("items", []):
        if e.get("reason") == reason:
            return e.get("firstTimestamp") or e.get("eventTime")
    return None


scheduled = event_time("Scheduled")
pulling = event_time("Pulling")
pulled = event_time("Pulled")
created = event_time("Created")
started = event_time("Started")

ready = None
for c in pod.get("status", {}).get("conditions", []):
    if c.get("type") == "Ready" and c.get("status") == "True":
        ready = c.get("lastTransitionTime")
        break

startup_latency = None
if scheduled and ready:
    startup_latency = (parse(ready) - parse(scheduled)).total_seconds()

run_id = os.environ.get("RUN_ID", "")
build_id = os.environ.get("BUILD_BUILDID", "")
build_uri = os.environ.get("SYSTEM_COLLECTIONURI", "").rstrip("/")
project = os.environ.get("SYSTEM_TEAMPROJECT", "")
run_url = (
    f"{build_uri}/{project}/_build/results?buildId={build_id}"
    if build_id and build_uri and project
    else ""
)

result = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    ),
    "run_id": run_id,
    "run_url": run_url,
    "result": {
        "cluster": CLUSTER,
        "runtime_class": RUNTIME_CLASS,
        "node_sku": NODE_SKU,
        "k8s_version": K8S_VERSION,
        "pod_name": POD_NAME,
        "image": PAUSE_IMAGE,
        "scheduled_time": scheduled,
        "pulling_time": pulling,
        "pulled_time": pulled,
        "created_time": created,
        "started_time": started,
        "ready_time": ready,
        "startup_latency_seconds": startup_latency,
    },
}

with open("/tmp/run-result.json", "w") as f:
    json.dump(result, f, indent=2)

print(json.dumps(result, indent=2))

if startup_latency is None or startup_latency <= 0:
    sys.exit("Startup latency could not be computed")
