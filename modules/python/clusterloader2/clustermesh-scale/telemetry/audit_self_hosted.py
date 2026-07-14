#!/usr/bin/env python3
"""Audit self-hosted Prometheus coverage for ClusterMesh scale runs."""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


METRIC_GROUPS = {
    "kube-apiserver": {
        "prefixes": ("apiserver_",),
        "required": True,
    },
    "api-priority-and-fairness": {
        "prefixes": ("apiserver_flowcontrol_",),
        "required": True,
    },
    "kube-state-metrics": {
        "prefixes": ("kube_",),
        "required": True,
    },
    "kubelet": {
        "prefixes": ("kubelet_",),
        "required": True,
    },
    "cadvisor-cpu": {
        "exact": ("container_cpu_usage_seconds_total",),
        "required": True,
    },
    "cadvisor-memory": {
        "exact": ("container_memory_working_set_bytes",),
        "required": True,
    },
    "cilium": {
        "prefixes": ("cilium_",),
        "required": True,
    },
    "kvstoremesh": {
        "prefixes": ("cilium_kvstoremesh_",),
        "required": False,
    },
    "etcd-client": {
        # This is a histogram family on current AKS releases; the unsuffixed
        # base name is metadata-only and doesn't appear in label-name values.
        "exact": (
            "etcd_request_duration_seconds_count",
            "etcd_request_duration_seconds_sum",
        ),
        "required": True,
    },
    "process-cpu": {
        "exact": ("process_cpu_seconds_total",),
        "required": True,
    },
    "process-memory": {
        "exact": ("process_resident_memory_bytes",),
        "required": True,
    },
    "apiserver-backend-cpu": {
        "exact": ("aks_apiserver_backend_process_cpu_seconds_total",),
        "required": True,
    },
    "apiserver-backend-memory": {
        "exact": ("aks_apiserver_backend_process_resident_memory_bytes",),
        "required": True,
    },
}

PROMETHEUS_PROXY_ROOT = (
    "/api/v1/namespaces/monitoring/services/"
    "http:prometheus-k8s:9090/proxy"
)


def _matching_metrics(metric_names, prefixes=(), exact=()):
    exact_set = set(exact)
    return sorted(
        name
        for name in metric_names
        if name in exact_set or any(name.startswith(prefix) for prefix in prefixes)
    )


def _target_jobs(targets):
    jobs = defaultdict(lambda: {"total": 0, "up": 0, "down": 0, "scrape_urls": []})
    for target in targets:
        labels = target.get("labels", {})
        job = labels.get("job", "<unknown>")
        health = target.get("health", "unknown")
        jobs[job]["total"] += 1
        if health == "up":
            jobs[job]["up"] += 1
        else:
            jobs[job]["down"] += 1
        scrape_url = target.get("scrapeUrl")
        if scrape_url:
            jobs[job]["scrape_urls"].append(scrape_url)
    return dict(sorted(jobs.items()))


def build_audit(
    metric_names,
    targets,
    require_real_node_kubelet=False,
    require_kwok_resource=False,
):
    """Build the self-hosted Prometheus coverage report."""
    checks = []
    for name, definition in METRIC_GROUPS.items():
        matches = _matching_metrics(
            metric_names,
            prefixes=definition.get("prefixes", ()),
            exact=definition.get("exact", ()),
        )
        checks.append(
            {
                "name": name,
                "required": definition["required"],
                "status": "covered" if matches else "missing",
                "metric_count": len(matches),
                "sample_metrics": matches[:20],
            }
        )

    jobs = _target_jobs(targets)
    exporter = jobs.get(
        "apiserver-backend-exporter",
        {"total": 0, "up": 0, "down": 0, "scrape_urls": []},
    )
    exporter_healthy = exporter["total"] > 0 and exporter["down"] == 0
    checks.append(
        {
            "name": "target:apiserver-backend-exporter",
            "required": True,
            "status": "covered" if exporter_healthy else "missing",
            "target_count": exporter["total"],
            "up_targets": exporter["up"],
            "down_targets": exporter["down"],
        }
    )
    if require_real_node_kubelet:
        for job_name in ("kubelet-real-nodes", "cadvisor-real-nodes"):
            target = jobs.get(
                job_name,
                {"total": 0, "up": 0, "down": 0, "scrape_urls": []},
            )
            healthy = target["total"] > 0 and target["down"] == 0
            checks.append(
                {
                    "name": f"target:{job_name}",
                    "required": True,
                    "status": "covered" if healthy else "missing",
                    "target_count": target["total"],
                    "up_targets": target["up"],
                    "down_targets": target["down"],
                }
            )
    if require_kwok_resource:
        for metric_name in (
            "pod_cpu_usage_seconds_total",
            "pod_memory_working_set_bytes",
            "node_cpu_usage_seconds_total",
            "node_memory_working_set_bytes",
        ):
            covered = metric_name in metric_names
            checks.append(
                {
                    "name": f"kwok:{metric_name}",
                    "required": True,
                    "status": "covered" if covered else "missing",
                    "metric_count": 1 if covered else 0,
                    "sample_metrics": [metric_name] if covered else [],
                }
            )
        target = jobs.get(
            "kwok-resource",
            {"total": 0, "up": 0, "down": 0, "scrape_urls": []},
        )
        healthy = target["total"] > 0 and target["down"] == 0
        checks.append(
            {
                "name": "target:kwok-resource",
                "required": True,
                "status": "covered" if healthy else "missing",
                "target_count": target["total"],
                "up_targets": target["up"],
                "down_targets": target["down"],
            }
        )

    complete = all(
        check["status"] == "covered"
        for check in checks
        if check["required"]
    )
    return {
        "schema_version": 1,
        "source": "self-hosted-prometheus",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "metric_name_count": len(metric_names),
        "checks": checks,
        "target_jobs": jobs,
    }


def _markdown(report):
    lines = [
        "# Self-hosted Prometheus telemetry audit",
        "",
        f"**Complete:** {'yes' if report['complete'] else 'no'}",
        "",
        "| Coverage item | Required | Status | Details |",
        "|---|:---:|:---:|---|",
    ]
    for check in report["checks"]:
        details = []
        if "metric_count" in check:
            details.append(f"{check['metric_count']} metric names")
        if "target_count" in check:
            details.append(
                f"{check['up_targets']}/{check['target_count']} targets up"
            )
        required = "yes" if check["required"] else "no"
        detail_text = "; ".join(details) or "-"
        lines.append(
            f"| {check['name']} | {required} | {check['status']} | "
            f"{detail_text} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report, output_prefix):
    """Write JSON and Markdown forms of an audit report."""
    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    markdown_path = prefix.with_suffix(".md")
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _prometheus_get(kubeconfig, api_path):
    path = f"{PROMETHEUS_PROXY_ROOT}{api_path}"
    result = subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "get", "--raw", path],
        check=True,
        capture_output=True,
        text=True,
    )
    response = json.loads(result.stdout)
    if response.get("status") != "success":
        raise RuntimeError(f"Prometheus API returned {response}")
    return response["data"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--require-real-node-kubelet", action="store_true")
    parser.add_argument("--require-kwok-resource", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        metric_names = _prometheus_get(
            args.kubeconfig,
            "/api/v1/label/__name__/values",
        )
        targets = _prometheus_get(
            args.kubeconfig,
            "/api/v1/targets",
        ).get("activeTargets", [])
        report = build_audit(
            metric_names,
            targets,
            require_real_node_kubelet=args.require_real_node_kubelet,
            require_kwok_resource=args.require_kwok_resource,
        )
        json_path, markdown_path = write_report(report, args.output_prefix)
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        print(f"telemetry audit failed: {error}", file=sys.stderr)
        return 1

    print(
        f"telemetry audit complete={report['complete']} "
        f"json={json_path} markdown={markdown_path}"
    )
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
