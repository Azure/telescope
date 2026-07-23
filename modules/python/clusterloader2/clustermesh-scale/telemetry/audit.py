#!/usr/bin/env python3
"""Audit ClusterMesh telemetry coverage in Prometheus-compatible backends."""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SELF_HOSTED_METRIC_GROUPS = {
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
}

MANAGED_COMPONENTS = {
    "apiserver": {
        "job": "controlplane-apiserver",
        "required": True,
        "metric_prefixes": ("apiserver_",),
        "evidence_metrics": ("apiserver_request_total",),
    },
    "etcd": {
        "job": "controlplane-etcd",
        "required": True,
        "metric_prefixes": ("etcd_",),
        "evidence_metrics": ("etcd_server_has_leader",),
    },
    "kube-scheduler": {
        "job": "controlplane-kube-scheduler",
        "required": True,
        "metric_prefixes": ("scheduler_",),
        "evidence_metrics": ("scheduler_schedule_attempts_total",),
    },
    "kube-controller-manager": {
        "job": "controlplane-kube-controller-manager",
        "required": True,
        "metric_prefixes": (
            "controller_",
            "leader_election_",
            "workqueue_",
        ),
        "evidence_metrics": ("workqueue_depth",),
    },
    "cluster-autoscaler": {
        "job": "controlplane-cluster-autoscaler",
        "required": False,
        "metric_prefixes": ("cluster_autoscaler_",),
        "evidence_metrics": ("cluster_autoscaler_nodes_count",),
    },
    "node-auto-provisioning": {
        "job": "controlplane-node-auto-provisioning",
        "required": False,
        "metric_prefixes": ("nap_", "node_auto_provisioning_"),
        "evidence_metrics": (
            "karpenter_nodes_created_total",
            "node_auto_provisioning_nodes_created_total",
        ),
    },
}

MANAGED_SERIES_METRICS = (
    "up",
    "clustermesh_cluster_identity_info",
    "process_cpu_seconds_total",
    "process_resident_memory_bytes",
    "apiserver_request_total",
    "apiserver_flowcontrol_rejected_requests_total",
    "etcd_server_has_leader",
    "etcd_mvcc_db_total_size_in_bytes",
    "scheduler_schedule_attempts_total",
    "leader_election_master_status",
    "workqueue_depth",
    "cluster_autoscaler_nodes_count",
    "karpenter_nodes_created_total",
    "node_auto_provisioning_nodes_created_total",
)
IDENTITY_LABELS = (
    "run_id",
    "cluster_role",
    "cluster_name",
    "cluster_resource_id",
    "subscription_id",
    "resource_group",
    "region",
    "prometheus_cluster_alias",
)

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


def build_self_hosted_audit(metric_names, targets, require_real_node_kubelet=False):
    """Build the self-hosted Prometheus coverage report."""
    checks = []
    for name, definition in SELF_HOSTED_METRIC_GROUPS.items():
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


def _label_value(labels, *names):
    lowered = {key.lower(): value for key, value in labels.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ""


def _cluster_identity(labels):
    cluster = _label_value(labels, "cluster", "cluster_name")
    if cluster:
        return cluster.lower()
    resource_id = _label_value(
        labels,
        "Microsoft.resourceid",
        "azure_resource_id",
        "resource_id",
    )
    if resource_id:
        return resource_id.rstrip("/").split("/")[-1].lower()
    return ""


def _job_matches(actual_job, expected_job):
    actual = actual_job.lower()
    expected = expected_job.lower()
    return actual == expected or actual.endswith(expected)


def _subscription_id(resource_id):
    parts = resource_id.strip("/").split("/")
    for index, part in enumerate(parts[:-1]):
        if part.lower() == "subscriptions":
            return parts[index + 1]
    return ""


def _expected_identity(manifest, cluster):
    resource_id = cluster.get("id", "")
    return {
        "run_id": manifest.get("run_id", ""),
        "cluster_role": cluster.get("role", ""),
        "cluster_name": cluster.get("name", ""),
        "cluster_resource_id": resource_id,
        "subscription_id": _subscription_id(resource_id),
        "resource_group": cluster.get("rg", ""),
        "region": manifest.get("region", ""),
        "prometheus_cluster_alias": cluster.get(
            "prometheus_cluster_alias",
            cluster.get("name", ""),
        ),
    }


def _identity_matches(labels, expected):
    if not all(_label_value(labels, name) for name in IDENTITY_LABELS):
        return False
    for name, expected_value in expected.items():
        if not expected_value:
            continue
        actual_value = _label_value(labels, name)
        if name in ("cluster_resource_id", "subscription_id"):
            if actual_value.lower() != expected_value.lower():
                return False
        elif actual_value != expected_value:
            return False
    return True


def build_managed_audit(metric_names, series_by_metric, manifest):
    """Build the managed-Prometheus control-plane coverage report."""
    expected_clusters = {
        cluster.get("prometheus_cluster_alias", cluster["name"]).lower(): cluster["role"]
        for cluster in manifest.get("clusters", [])
    }
    expected_names = set(expected_clusters)
    checks = []

    for component, definition in MANAGED_COMPONENTS.items():
        target_clusters = set()
        metric_clusters = set()
        jobs = set()
        evidence_metrics = set()
        for metric_name, series_list in series_by_metric.items():
            for labels in series_list:
                job = _label_value(labels, "job")
                if not _job_matches(job, definition["job"]):
                    continue
                jobs.add(job)
                cluster = _cluster_identity(labels)
                if not cluster:
                    continue
                if metric_name == "up":
                    target_clusters.add(cluster)
                if metric_name in definition["evidence_metrics"]:
                    metric_clusters.add(cluster)
                    evidence_metrics.add(metric_name)

        family_metrics = _matching_metrics(
            metric_names,
            prefixes=definition["metric_prefixes"],
        )
        matched_clusters = metric_clusters & expected_names
        missing_target_clusters = expected_names - target_clusters
        missing_metric_clusters = expected_names - metric_clusters
        status = (
            "covered"
            if not missing_target_clusters and not missing_metric_clusters
            else "missing"
        )
        if not definition["required"] and not target_clusters and not metric_clusters:
            status = "not-applicable"
        checks.append(
            {
                "name": component,
                "required": definition["required"],
                "status": status,
                "expected_job": definition["job"],
                "jobs_seen": sorted(jobs),
                "covered_clusters": sorted(
                    expected_clusters[name] for name in matched_clusters
                ),
                "missing_target_clusters": sorted(
                    expected_clusters[name] for name in missing_target_clusters
                ),
                "missing_metric_clusters": sorted(
                    expected_clusters[name] for name in missing_metric_clusters
                ),
                "metric_family_count": len(family_metrics),
                "sample_metrics": family_metrics[:30],
                "evidence_metrics": sorted(evidence_metrics),
            }
        )

    identity_series = series_by_metric.get(
        "clustermesh_cluster_identity_info",
        [],
    )
    missing_identity = []
    identity_coverage_mode = {}
    managed_query_scope = manifest.get("managed_query_scope", "")
    scoped_cluster = (
        manifest.get("clusters", [None])[0]
        if len(manifest.get("clusters", [])) == 1
        else None
    )
    scoped_identity_available = bool(
        scoped_cluster
        and managed_query_scope
        and managed_query_scope.lower() == scoped_cluster.get("id", "").lower()
        and identity_series
        and all(
            not any(_label_value(labels, name) for name in IDENTITY_LABELS)
            for labels in identity_series
        )
    )
    for cluster in manifest.get("clusters", []):
        expected = _expected_identity(manifest, cluster)
        if any(
            _identity_matches(labels, expected)
            for labels in identity_series
        ):
            identity_coverage_mode[cluster["role"]] = "series-labels"
        elif (
            scoped_identity_available
            and cluster.get("id", "").lower() == managed_query_scope.lower()
        ):
            # Azure Monitor can strip every exporter label while retaining the
            # metric itself. A schema-v2 query is still bound to one exact AKS
            # resource ID by x-ms-azure-scoping and one dedicated workspace, so
            # current-window series presence proves this cluster's identity
            # without weakening legacy/shared-workspace validation.
            identity_coverage_mode[cluster["role"]] = "resource-scope"
        else:
            missing_identity.append(cluster["role"])
    checks.append(
        {
            "name": "cluster-identity",
            "required": True,
            "status": "covered" if not missing_identity else "missing",
            "sample_count": len(identity_series),
            "coverage_mode": identity_coverage_mode,
            "covered_clusters": sorted(
                cluster["role"]
                for cluster in manifest.get("clusters", [])
                if cluster["role"] not in missing_identity
            ),
            "missing_clusters": sorted(missing_identity),
        }
    )

    for metric_name in (
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
    ):
        covered_clusters = defaultdict(set)
        for labels in series_by_metric.get(metric_name, []):
            job = _label_value(labels, "job")
            cluster = _cluster_identity(labels)
            if cluster not in expected_names:
                continue
            for component, definition in MANAGED_COMPONENTS.items():
                if definition["required"] and _job_matches(job, definition["job"]):
                    covered_clusters[component].add(cluster)
        required_components = {
            component
            for component, definition in MANAGED_COMPONENTS.items()
            if definition["required"]
        }
        missing_targets = []
        for component in sorted(required_components):
            for cluster in sorted(expected_names - covered_clusters[component]):
                missing_targets.append(
                    f"{component}:{expected_clusters[cluster]}"
                )
        checks.append(
            {
                "name": f"resource:{metric_name}",
                # AKS hard-drops these process metrics for every managed
                # control-plane target. Aggregate API server/etcd resource
                # percentages are audited separately through platform metrics.
                "required": False,
                "status": "covered" if not missing_targets else "not-exposed",
                "covered_components": sorted(
                    component
                    for component in required_components
                    if covered_clusters[component]
                ),
                "missing_targets": missing_targets,
            }
        )

    complete = all(
        check["status"] == "covered"
        for check in checks
        if check["required"]
    )
    return {
        "schema_version": 1,
        "source": "azure-monitor-managed-prometheus",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "workspace": manifest.get("workspace", {}),
        "window": {
            "start": manifest.get("query_window_start", ""),
            "end": manifest.get("query_window_end", ""),
        },
        "expected_cluster_count": len(expected_clusters),
        "metric_name_count": len(metric_names),
        "checks": checks,
    }


def _markdown(report):
    title = (
        "Self-hosted Prometheus telemetry audit"
        if report["source"] == "self-hosted-prometheus"
        else "AKS control-plane managed Prometheus telemetry audit"
    )
    lines = [
        f"# {title}",
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
        if "metric_family_count" in check:
            details.append(f"{check['metric_family_count']} family metrics")
        if check.get("covered_clusters"):
            details.append(f"{len(check['covered_clusters'])} clusters")
        if check.get("missing_target_clusters"):
            details.append(
                "target missing: "
                + ", ".join(check["missing_target_clusters"])
            )
        if check.get("missing_metric_clusters"):
            details.append(
                "metrics missing: "
                + ", ".join(check["missing_metric_clusters"])
            )
        if check.get("missing_components"):
            details.append("missing: " + ", ".join(check["missing_components"]))
        if check.get("missing_targets"):
            details.append("missing: " + ", ".join(check["missing_targets"]))
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


def _kubectl_prometheus_get(kubeconfig, api_path):
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


def _http_prometheus_get(endpoint, api_path, params=None, scope=""):
    token = os.environ.get("PROMETHEUS_BEARER_TOKEN", "")
    if not token:
        raise RuntimeError("PROMETHEUS_BEARER_TOKEN is required")
    query = f"?{urlencode(params, doseq=True)}" if params else ""
    request = Request(
        f"{endpoint.rstrip('/')}{api_path}{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if scope:
        request.add_header("x-ms-azure-scoping", scope)
    with urlopen(request, timeout=120) as response:
        payload = json.load(response)
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus API returned {payload}")
    return payload["data"]


def run_self_hosted(args):
    metric_names = _kubectl_prometheus_get(
        args.kubeconfig,
        "/api/v1/label/__name__/values",
    )
    targets = _kubectl_prometheus_get(
        args.kubeconfig,
        "/api/v1/targets",
    ).get("activeTargets", [])
    report = build_self_hosted_audit(
        metric_names,
        targets,
        require_real_node_kubelet=args.require_real_node_kubelet,
    )
    return report


def run_managed(args):
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    manifest["query_window_start"] = args.start
    manifest["query_window_end"] = args.end

    clusters = manifest.get("clusters", [])
    if clusters and all(
        cluster.get("workspace", {}).get("prometheus_query_endpoint")
        for cluster in clusters
    ):
        # Each cluster in a schema-v2 manifest owns a dedicated managed
        # Prometheus workspace, so per-cluster queries are independent and
        # safe to parallelize. Every cluster issues ~15 API calls (1
        # label-values request + one /series request per entry in
        # MANAGED_SERIES_METRICS), so at n100 scale serial execution can
        # approach ~1500 calls end-to-end and threaten the 3h finalization
        # reserve. --workers bounds the ThreadPoolExecutor so operators can
        # trade query burstiness (risk of throttling a shared workspace or
        # the Azure Monitor query endpoint) against wall-clock audit time
        # per environment size.
        workers = getattr(args, "workers", 1)

        def _query_cluster(cluster):
            cluster_manifest = dict(manifest)
            cluster_manifest["clusters"] = [cluster]
            cluster_manifest["workspace"] = cluster["workspace"]
            cluster_manifest["managed_query_scope"] = cluster["id"]
            endpoint = cluster["workspace"]["prometheus_query_endpoint"]
            return _run_managed_query(
                args,
                cluster_manifest,
                endpoint,
                cluster["id"],
            )

        # executor.map() preserves input order in its result iterator
        # (results are yielded in the order tasks were submitted, not the
        # order they complete), so wrapping it in list() below yields
        # deterministic, manifest-ordered results regardless of which
        # worker finishes first. Iterating the iterator also re-raises any
        # exception from a worker thread at that position, so a failure in
        # any single cluster query still fails the whole audit instead of
        # being swallowed.
        with ThreadPoolExecutor(max_workers=workers) as executor:
            reports = list(executor.map(_query_cluster, clusters))

        cluster_reports = []
        combined_checks = []
        for cluster, report in zip(clusters, reports):
            role = cluster["role"]
            cluster_reports.append(
                {
                    "role": role,
                    "workspace": cluster["workspace"],
                    "complete": report["complete"],
                    "checks": report["checks"],
                }
            )
            for check in report["checks"]:
                combined = dict(check)
                combined["name"] = f"{role}:{check['name']}"
                combined["cluster_role"] = role
                combined_checks.append(combined)
        return {
            "schema_version": 2,
            "source": "azure-monitor-managed-prometheus",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "complete": all(report["complete"] for report in cluster_reports),
            "workspace": manifest.get("workspace", {}),
            "workspaces": manifest.get("workspaces", []),
            "query_window_start": args.start,
            "query_window_end": args.end,
            "checks": combined_checks,
            "cluster_reports": cluster_reports,
        }

    if not args.endpoint:
        raise ValueError(
            "--endpoint is required for legacy single-workspace manifests"
        )
    return _run_managed_query(
        args,
        manifest,
        args.endpoint,
        args.resource_scope,
    )


def _run_managed_query(args, manifest, endpoint, resource_scope):
    metric_names = _http_prometheus_get(
        endpoint,
        "/api/v1/label/__name__/values",
        scope=resource_scope,
    )
    series_by_metric = {}
    for metric_name in MANAGED_SERIES_METRICS:
        series_by_metric[metric_name] = _http_prometheus_get(
            endpoint,
            "/api/v1/series",
            params=[
                ("match[]", f'{{__name__="{metric_name}"}}'),
                ("start", args.start),
                ("end", args.end),
            ],
            scope=resource_scope,
        )
    return build_managed_audit(metric_names, series_by_metric, manifest)


def _positive_int(value):
    """Argparse type validator requiring a positive integer."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            f"invalid positive int value: {value!r}"
        ) from error
    if parsed < 1:
        raise argparse.ArgumentTypeError(
            f"workers must be a positive integer, got {value!r}"
        )
    return parsed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    self_hosted = subparsers.add_parser(
        "self-hosted",
        help="Audit the CL2-managed Prometheus through the Kubernetes API proxy",
    )
    self_hosted.add_argument("--kubeconfig", required=True)
    self_hosted.add_argument("--output-prefix", required=True)
    self_hosted.add_argument("--require-real-node-kubelet", action="store_true")

    managed = subparsers.add_parser(
        "managed",
        help="Audit AKS control-plane metrics in Azure managed Prometheus",
    )
    managed.add_argument("--endpoint", default="")
    managed.add_argument("--resource-scope", default="")
    managed.add_argument("--manifest", required=True)
    managed.add_argument("--start", required=True)
    managed.add_argument("--end", required=True)
    managed.add_argument("--output-prefix", required=True)
    managed.add_argument(
        "--workers",
        type=_positive_int,
        default=1,
        help=(
            "Number of concurrent worker threads used to query per-cluster "
            "workspaces in schema-v2 manifests (default: 1)"
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        report = run_self_hosted(args) if args.mode == "self-hosted" else run_managed(args)
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
