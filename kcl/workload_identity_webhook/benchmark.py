"""Prepare and observe the scenario without changing kperf's traffic contract."""

import argparse
import copy
import json
import math
import re
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import yaml


ROOT = Path(__file__).parent
BEGIN = "KPERF_RESULT_BEGIN"
END = "KPERF_RESULT_END"
PHASES = ("smoke", "warmup", "measure")


def kubectl(*args, stdin=None):
    return subprocess.run(
        ["kubectl", "--request-timeout=30s", *args],
        input=stdin, text=True, capture_output=True, check=True, timeout=90,
    ).stdout


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def render(value, replacements):
    if isinstance(value, dict):
        return {key: render(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, replacements) for item in value]
    if isinstance(value, str):
        for key, replacement in replacements.items():
            value = value.replace(f"__{key}__", replacement)
        if re.search(r"__[A-Z_]+__", value):
            raise ValueError(f"Unresolved placeholder: {value}")
    return value


def profile_for_phase(template, run_id, phase):
    profile = render(copy.deepcopy(template), {
        "RUN_NAMESPACE": run_id, "RUN_ID": run_id,
    })
    spec = profile["specs"][0]
    spec["requests"][0]["postDel"]["pod"]["labels"]["benchmark-phase"] = phase
    if phase == "smoke":
        spec.update(rate=1, total=3, duration=0, client=1, conns=1)
    elif phase == "warmup":
        spec.update(rate=5, total=0, duration=30, client=5, conns=1)
    elif phase != "measure":
        raise ValueError(f"Unknown phase: {phase}")
    return profile


def extract_result(log):
    if log.count(BEGIN) != 1 or log.count(END) != 1:
        raise ValueError("Missing or repeated kperf result delimiters")
    start = log.index(BEGIN) + len(BEGIN)
    stop = log.index(END)
    if stop <= start:
        raise ValueError("Invalid kperf result delimiter order")
    result = json.loads(log[start:stop])
    if not isinstance(result, dict):
        raise ValueError("kperf result must be an object")
    return result


def evaluate_result(result, duration):
    specs = result.get("perSpecResults")
    aggregate = result.get("aggregated")
    if not isinstance(specs, list) or len(specs) != 1 or not isinstance(aggregate, dict):
        raise ValueError("Expected one perSpecResults entry and an aggregated report")
    for report in [specs[0], aggregate]:
        if not isinstance(report, dict):
            raise ValueError("Invalid report object")
        for field in ("total", "duration", "totalReceivedBytes"):
            if field not in report:
                raise ValueError(f"Missing report field: {field}")
        if any(type(report[field]) is not int or report[field] < 0
               for field in ("total", "totalReceivedBytes")):
            raise ValueError("Invalid report total or received bytes")
        errors = report.get("errorStats", {})
        if not isinstance(errors, dict) or any(
            type(count) is not int or count < 0 for count in errors.values()
        ):
            raise ValueError("Invalid errorStats")
        if sum(errors.values()):
            raise ValueError(f"kperf reported request failures: {errors}")
        latencies = report.get("percentileLatencies")
        if not isinstance(latencies, list) or not latencies:
            raise ValueError("No successful-request latency observations")
        if any(not isinstance(pair, list) or len(pair) != 2 or any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in pair
        ) or pair[0] > 1 for pair in latencies):
            raise ValueError("Invalid latency percentile pairs")
        elapsed = parse_duration(report["duration"])
        if elapsed < duration:
            raise ValueError(f"Runner duration {elapsed}s is shorter than {duration}s")
    if specs[0] != aggregate:
        raise ValueError("Single-spec and aggregate reports disagree")
    return {
        "classification": "exploratory-completed",
        "sustained_rate_acceptance": "not-evaluated",
        "configured_rate_per_second": 600 if duration == 600 else None,
        "runner_reported_total": aggregate["total"],
        "runner_total_semantics": "configured total, NOT observed successful requests",
        "runner_duration_including_drain": aggregate["duration"],
        "error_stats": aggregate.get("errorStats", {}),
        "percentile_latencies_seconds": aggregate["percentileLatencies"],
        "limitations": [
            "No per-interval dispatch rate, inflight backlog, or WI invocation count.",
            "Retained Pod count is an observation, not successful-response accounting.",
            "Submitted body size and exact generation/drain boundaries are unavailable.",
        ],
    }


def parse_duration(value):
    if not isinstance(value, str):
        raise ValueError("Runner duration must be a Go duration string")
    parts = re.findall(r"(\d+(?:\.\d+)?)(ns|us|\u00b5s|ms|s|m|h)", value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        raise ValueError(f"Invalid runner duration: {value}")
    scales = {"ns": 1e-9, "us": 1e-6, "\u00b5s": 1e-6, "ms": 1e-3,
              "s": 1, "m": 60, "h": 3600}
    return sum(float(number) * scales[unit] for number, unit in parts)


def verify_pod(pod, run_id, phase, client_id):
    metadata, spec = pod["metadata"], pod["spec"]
    expected = {
        "azure.workload.identity/use": "true",
        "benchmark": "workload-identity-webhook",
        "benchmark-run": run_id,
        "benchmark-phase": phase,
    }
    if any(metadata.get("labels", {}).get(key) != value for key, value in expected.items()):
        raise ValueError("Generated Pod labels do not match the benchmark")
    if spec.get("schedulerName") != "kperf-admission-only" or spec.get("nodeName"):
        raise ValueError("Benchmark Pod is bound or uses the wrong scheduler")
    if spec.get("serviceAccountName") != "pod-benchmark" or len(spec["containers"]) != 1:
        raise ValueError("Unexpected ServiceAccount or container count")
    if spec.get("initContainers"):
        raise ValueError("Unexpected init containers")
    container = spec["containers"][0]
    env = {item["name"]: item.get("value") for item in container.get("env", [])}
    if env.get("AZURE_CLIENT_ID") != client_id or not all(env.get(key) for key in (
        "AZURE_TENANT_ID", "AZURE_AUTHORITY_HOST", "AZURE_FEDERATED_TOKEN_FILE",
    )):
        raise ValueError("Missing or incorrect WI environment mutation")
    token_file = env["AZURE_FEDERATED_TOKEN_FILE"]
    for volume in spec.get("volumes", []):
        for source in volume.get("projected", {}).get("sources", []):
            token = source.get("serviceAccountToken", {})
            if token.get("audience") != "api://AzureADTokenExchange":
                continue
            for mount in container.get("volumeMounts", []):
                if (mount["name"] == volume["name"] and mount.get("readOnly")
                        and token_file == mount["mountPath"].rstrip("/") + "/" + token["path"]):
                    return
    raise ValueError("Missing WI projected token volume/mount")


def prepare(args):
    nodes = json.loads(kubectl("get", "nodes", "-o", "json"))
    for pool, sku in (("systempool", "Standard_D2_v4"), ("workerpool", "Standard_D8s_v5")):
        members = [node for node in nodes["items"]
                   if node["metadata"]["labels"].get("kubernetes.azure.com/agentpool") == pool]
        if len(members) != 3 or any(
            node["metadata"]["labels"].get("node.kubernetes.io/instance-type") != sku
            or not any(c["type"] == "Ready" and c["status"] == "True"
                       for c in node["status"]["conditions"])
            for node in members
        ):
            raise ValueError(f"Expected three Ready {sku} nodes in {pool}")
    write_json(args.artifacts / "nodes-before.json", nodes)
    scheduler_pods = json.loads(kubectl("get", "pods", "-A", "-o", "json"))
    for pod in scheduler_pods["items"]:
        for container in pod["spec"].get("containers", []):
            command = container.get("command", []) + container.get("args", [])
            if any("kperf-admission-only" in part for part in command):
                raise ValueError("An existing container references the benchmark scheduler")
    write_json(args.artifacts / "platform-pods-before.json", scheduler_pods)
    template = yaml.safe_load((ROOT / "load-profile.yaml").read_text())
    manifests = list(yaml.safe_load_all((ROOT / "workload.yaml").read_text()))
    for phase in PHASES:
        profile = profile_for_phase(template, args.run_id, phase)
        profile_text = yaml.safe_dump(profile, sort_keys=False)
        (args.artifacts / f"{phase}-load-profile.yaml").write_text(profile_text)
        name = f"kperf-{phase}"
        rendered = render(manifests, {
            "RUN_NAMESPACE": args.run_id, "RUNNER_NAMESPACE": args.run_id + "-runner",
            "RUN_ID": args.run_id, "CLIENT_ID": args.client_id,
            "JOB_NAME": name, "RUNNER_IMAGE": args.image,
        })
        prerequisites = [doc for doc in rendered if doc["kind"] != "Job"]
        job = next(doc for doc in rendered if doc["kind"] == "Job")
        if phase != "measure":
            job["spec"]["activeDeadlineSeconds"] = 180
        config_map = {
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": args.run_id + "-runner"},
            "data": {"load-profile.yaml": profile_text},
        }
        write_json(args.artifacts / f"{phase}-job.json", job)
        kubectl("apply", "-f", "-", stdin=yaml.safe_dump_all(prerequisites + [config_map]))
    write_json(args.artifacts / "inputs.json", {
        "run_id": args.run_id, "image": args.image, "client_id": args.client_id,
        "profile": profile_for_phase(template, args.run_id, "measure"),
        "webhook_resources": "unchanged; managed control-plane visibility requires ASI telemetry",
    })


def pod_snapshot(args, phase):
    count, samples, continuation = 0, [], ""
    deadline = time.monotonic() + 900
    while True:
        query = urlencode({
            "labelSelector": f"benchmark-run={args.run_id},benchmark-phase={phase}",
            "limit": 500, "continue": continuation,
        })
        page = json.loads(kubectl(
            "get", "--raw", f"/api/v1/namespaces/{args.run_id}/pods?{query}",
        ))
        count += len(page["items"])
        samples.extend(page["items"][:max(0, 3 - len(samples))])
        continuation = page["metadata"].get("continue", "")
        if not continuation:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Retained Pod snapshot exceeded its 900-second budget")
    write_json(args.artifacts / f"{phase}-pods.json", {
        "retained_pod_count": count,
        "sample_admitted_json_bytes": [len(json.dumps(pod, separators=(",", ":")).encode())
                                      for pod in samples],
        "samples": samples,
    })
    if count == 0 or (phase == "smoke" and count != 3):
        raise ValueError(f"Unexpected retained Pod count for {phase}: {count}")
    for pod in samples:
        verify_pod(pod, args.run_id, phase, args.client_id)
    return count


def run_phase(args):
    phase = args.phase
    namespace, name = args.run_id + "-runner", f"kperf-{phase}"
    timing = {"orchestration_start": timestamp()}
    try:
        kubectl("create", "-f", str(args.artifacts / f"{phase}-job.json"))
        deadline = time.monotonic() + (960 if phase == "measure" else 240)
        while True:
            job = json.loads(kubectl("get", "job", name, "-n", namespace, "-o", "json"))
            write_json(args.artifacts / f"{phase}-job-status.json", job)
            conditions = {c["type"]: c for c in job.get("status", {}).get("conditions", [])
                          if c["status"] == "True"}
            if "Failed" in conditions:
                raise RuntimeError(f"Job failed: {conditions['Failed']}")
            if "Complete" in conditions:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{name} exceeded its observation deadline")
            time.sleep(5)
        log = kubectl("logs", f"job/{name}", "-n", namespace, "-c", "kperf")
        (args.artifacts / f"{phase}.log").write_text(log)
        result = extract_result(log)
        write_json(args.artifacts / f"{phase}-result.json", result)
        summary = evaluate_result(result, {"smoke": 0, "warmup": 30, "measure": 600}[phase])
        summary["retained_pod_count"] = pod_snapshot(args, phase)
        write_json(args.artifacts / f"{phase}-summary.json", summary)
    finally:
        timing["orchestration_end"] = timestamp()
        write_json(args.artifacts / f"{phase}-timestamps.json", timing)


def collect(args):
    failures = []

    def capture(name, *command):
        try:
            output = kubectl(*command)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            message = f"{name}: {error}; {getattr(error, 'stderr', '')}"
            print(message, file=sys.stderr)
            failures.append(message)
            (args.artifacts / f"{name}.error.txt").write_text(message)
            return None
        (args.artifacts / name).write_text(output)
        return output

    capture("nodes-after.json", "get", "nodes", "-o", "json")
    capture("admission-webhooks.json", "get", "mutatingwebhookconfigurations", "-o", "json")
    capture("platform-pods-after.json", "get", "pods", "-n", "kube-system", "-o", "json")
    namespace = args.run_id + "-runner"
    jobs = capture("jobs-final.json", "get", "jobs", "-n", namespace, "-o", "json")
    capture("runner-pods.json", "get", "pods", "-n", namespace, "-o", "json")
    capture("runner-events.json", "get", "events", "-n", namespace, "-o", "json")
    if jobs is not None:
        for job in json.loads(jobs)["items"]:
            if job["metadata"].get("labels", {}).get("benchmark-run") != args.run_id:
                continue
            name = job["metadata"]["name"]
            capture(f"{name}-final.log", "logs", f"job/{name}", "-n", namespace, "-c", "kperf")
            conditions = job.get("status", {}).get("conditions", [])
            terminal = any(c["type"] in ("Complete", "Failed") and c["status"] == "True"
                           for c in conditions)
            if not terminal:
                capture(f"{name}-stop.json", "patch", "job", name, "-n", namespace,
                        "--type=merge", "-p", '{"spec":{"suspend":true}}', "-o", "json")
    write_json(args.artifacts / "collection.json", {"failures": failures})
    if failures:
        raise RuntimeError("Artifact collection incomplete; see collection.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "collect"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--client-id")
    parser.add_argument("--image")
    parser.add_argument("--phase", choices=PHASES)
    args = parser.parse_args()
    if not re.fullmatch(r"wi-[0-9]+-[0-9]+", args.run_id):
        parser.error("run-id must be wi-<Build.BuildId>-<setup attempt>")
    if args.action != "collect":
        if not args.client_id:
            parser.error("--client-id is required")
        uuid.UUID(args.client_id)
    if args.action == "prepare" and not args.image:
        parser.error("--image is required for prepare")
    if args.action == "run" and not args.phase:
        parser.error("--phase is required for run")
    args.artifacts.mkdir(parents=True, exist_ok=True)

    def interrupted(signum, _frame):
        raise InterruptedError(f"Benchmark orchestration interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        {"prepare": prepare, "run": run_phase, "collect": collect}[args.action](args)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError,
            subprocess.SubprocessError) as error:
        message = f"{error}\n{getattr(error, 'stderr', '')}"
        print(f"WI BENCHMARK FAILED: {message}", file=sys.stderr)
        write_json(args.artifacts / f"{args.action}-{args.phase or 'all'}-failure.json",
                   {"error": message, "timestamp": timestamp()})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
