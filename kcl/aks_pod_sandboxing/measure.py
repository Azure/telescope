#!/usr/bin/env python3
"""Measure pause pod startup timings and write /tmp/run-result.json."""

import datetime
import json
import os
import subprocess
import sys


POD_NAME = os.environ["POD_NAME"]


def kubectl_json(*args):
    return json.loads(subprocess.check_output(["kubectl", *args, "-o", "json"]))


def parse(ts):
    if not ts:
        return None
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


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


pod = kubectl_json("get", "pod", POD_NAME)
ready = None
for c in pod.get("status", {}).get("conditions", []):
    if c.get("type") == "Ready" and c.get("status") == "True":
        ready = c.get("lastTransitionTime")
        break

startup_latency = None
if scheduled and ready:
    startup_latency = (parse(ready) - parse(scheduled)).total_seconds()

result = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    ),
    "run_id": os.environ.get("RUN_ID", ""),
    "run_url": (
        f"{os.environ['SYSTEM_COLLECTIONURI'].rstrip('/')}"
        f"/{os.environ['SYSTEM_TEAMPROJECT']}"
        f"/_build/results?buildId={os.environ['BUILD_BUILDID']}"
    ),
    "result": {
        "cluster": os.environ["CLUSTER"],
        "runtime_class": os.environ["RUNTIME_CLASS"],
        "node_sku": os.environ["NODE_SKU"],
        "k8s_version": os.environ["K8S_VERSION"],
        "pod_name": POD_NAME,
        "image": os.environ["PAUSE_IMAGE"],
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
