#!/usr/bin/env python3
"""Audit self-hosted Prometheus coverage for ClusterMesh scale runs."""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode


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
IDENTITY_LABEL_ENV = {
    "run_id": "CLUSTERMESH_RUN_ID",
    "cluster_role": "CLUSTERMESH_CLUSTER_ROLE",
    "cluster_name": "CLUSTERMESH_CLUSTER_NAME",
    "cluster_resource_id": "CLUSTERMESH_CLUSTER_RESOURCE_ID",
    "subscription_id": "CLUSTERMESH_SUBSCRIPTION_ID",
    "resource_group": "CLUSTERMESH_RESOURCE_GROUP",
    "region": "CLUSTERMESH_REGION",
    "prometheus_cluster_alias": "CLUSTERMESH_PROMETHEUS_CLUSTER_ALIAS",
}
ACNS_METRICS = (
    "cilium_forward_count_total",
    "cilium_forward_bytes_total",
    "cilium_drop_count_total",
    "cilium_drop_bytes_total",
    "hubble_dns_queries_total",
    "hubble_dns_responses_total",
    "hubble_drop_total",
    "hubble_tcp_flags_total",
    "hubble_flows_processed_total",
)
IDENTITY_LOOKBACK_QUERY = (
    "last_over_time(clustermesh_cluster_identity_info[6h])"
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
    require_kwok_pod_resource=False,
    require_acns=False,
    expected_mock_agent_targets=0,
    identity_series=None,
    expected_identity=None,
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

    identity_series = identity_series or []
    expected_identity = expected_identity or {}
    matching_identity = []
    for labels in identity_series:
        if not all(labels.get(name) for name in IDENTITY_LABEL_ENV):
            continue
        if any(
            expected_value and labels.get(name) != expected_value
            for name, expected_value in expected_identity.items()
        ):
            continue
        matching_identity.append(labels)
    checks.append(
        {
            "name": "cluster-identity",
            "required": True,
            "status": "covered" if matching_identity else "missing",
            "sample_count": len(identity_series),
            "matching_samples": len(matching_identity),
            "expected_identity": expected_identity,
        }
    )

    jobs = _target_jobs(targets)
    exporter = jobs.get(
        "apiserver-backend-exporter",
        {"total": 0, "up": 0, "down": 0, "scrape_urls": []},
    )
    exporter_metrics_present = {
        "aks_apiserver_backend_process_cpu_seconds_total",
        "aks_apiserver_backend_process_resident_memory_bytes",
    }.issubset(metric_names)
    exporter_healthy = (
        exporter["total"] > 0 and exporter["down"] == 0
    ) or exporter_metrics_present
    checks.append(
        {
            "name": "target:apiserver-backend-exporter",
            "required": True,
            "status": "covered" if exporter_healthy else "missing",
            "target_count": exporter["total"],
            "up_targets": exporter["up"],
            "down_targets": exporter["down"],
            "historical_metric_evidence": exporter_metrics_present,
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
            pod_metric = metric_name.startswith("pod_")
            required = not pod_metric or require_kwok_pod_resource
            checks.append(
                {
                    "name": f"kwok:{metric_name}",
                    "required": required,
                    "status": (
                        "covered"
                        if covered
                        else "missing" if required else "not-applicable"
                    ),
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
    if expected_mock_agent_targets > 0:
        mock_targets = [
            target
            for job_name, target in jobs.items()
            if "mock-cilium-agent" in job_name
        ]
        target_count = sum(target["total"] for target in mock_targets)
        up_targets = sum(target["up"] for target in mock_targets)
        down_targets = sum(target["down"] for target in mock_targets)
        healthy = (
            target_count == expected_mock_agent_targets
            and up_targets == expected_mock_agent_targets
            and down_targets == 0
        )
        checks.append(
            {
                "name": "target:mock-cilium-agent",
                "required": True,
                "status": "covered" if healthy else "missing",
                "expected_target_count": expected_mock_agent_targets,
                "target_count": target_count,
                "up_targets": up_targets,
                "down_targets": down_targets,
            }
        )
    if require_acns:
        for metric_name in ACNS_METRICS:
            covered = metric_name in metric_names
            checks.append(
                {
                    "name": f"acns:{metric_name}",
                    "required": True,
                    "status": "covered" if covered else "missing",
                    "metric_count": 1 if covered else 0,
                    "sample_metrics": [metric_name] if covered else [],
                }
            )
        hubble_targets = [
            target
            for job_name, target in jobs.items()
            if "hubble" in job_name.lower()
        ]
        target_count = sum(target["total"] for target in hubble_targets)
        up_targets = sum(target["up"] for target in hubble_targets)
        down_targets = sum(target["down"] for target in hubble_targets)
        checks.append(
            {
                "name": "target:acns-hubble",
                "required": True,
                "status": (
                    "covered"
                    if target_count > 0 and down_targets == 0
                    else "missing"
                ),
                "target_count": target_count,
                "up_targets": up_targets,
                "down_targets": down_targets,
            }
        )

    complete = all(
        check["status"] == "covered"
        for check in checks
        if check["required"]
    )
    acns_checks = [
        check
        for check in checks
        if check["name"].startswith("acns:")
        or check["name"] == "target:acns-hubble"
    ]
    return {
        "schema_version": 1,
        "source": "self-hosted-prometheus",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "acns_complete": (
            all(check["status"] == "covered" for check in acns_checks)
            if require_acns
            else None
        ),
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
        if "sample_count" in check:
            details.append(
                f"{check['matching_samples']}/{check['sample_count']} samples match"
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
    parser.add_argument("--require-kwok-pod-resource", action="store_true")
    parser.add_argument("--require-acns", action="store_true")
    parser.add_argument("--expected-mock-agent-targets", type=int, default=0)
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
        identity_data = _prometheus_get(
            args.kubeconfig,
            "/api/v1/query?"
            + urlencode(
                {
                    "query": IDENTITY_LOOKBACK_QUERY
                }
            ),
        )
        identity_series = [
            sample.get("metric", {})
            for sample in identity_data.get("result", [])
        ]
        expected_identity = {
            label: os.environ.get(environment, "")
            for label, environment in IDENTITY_LABEL_ENV.items()
        }
        report = build_audit(
            metric_names,
            targets,
            require_real_node_kubelet=args.require_real_node_kubelet,
            require_kwok_resource=args.require_kwok_resource,
            require_kwok_pod_resource=args.require_kwok_pod_resource,
            require_acns=args.require_acns,
            expected_mock_agent_targets=args.expected_mock_agent_targets,
            identity_series=identity_series,
            expected_identity=expected_identity,
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
