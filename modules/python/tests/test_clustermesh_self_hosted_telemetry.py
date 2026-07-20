"""Tests for the ClusterMesh self-hosted telemetry auditor."""

import importlib.util
import json
import os
import stat
import subprocess
import tarfile
import textwrap
from pathlib import Path

import yaml


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "telemetry"
    / "audit_self_hosted.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "clustermesh_self_hosted_telemetry",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
audit_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(audit_module)
MONITOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "prometheus-additional-monitors"
    / "real-node-kubelet.yaml"
)
KWOK_RESOURCE_PATH = MONITOR_PATH.parent / "00-kwok-resource-usage.yaml"
KWOK_SCRAPE_PATH = MONITOR_PATH.parent / "02-kwok-resource-scrape-secret.yaml"
EVENT_DEPLOYMENT_PATH = (
    MONITOR_PATH.parents[1]
    / "modules"
    / "event-throughput-deployment.yaml"
)
TELEMETRY_DIR = (
    Path(__file__).resolve().parents[3]
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "telemetry"
)
ACNS_PROBE_PATH = TELEMETRY_DIR / "acns" / "probe.yaml"
ACNS_CNL_PATH = TELEMETRY_DIR / "acns" / "container-network-log.yaml"
ACNS_METRIC_PATH = TELEMETRY_DIR / "acns" / "container-network-metric.yaml"
ACNS_COLLECTOR_PATH = TELEMETRY_DIR / "acns" / "log-collector.yaml"
ACNS_SETUP_SCRIPT = TELEMETRY_DIR / "setup-acns-telemetry.sh"
ACNS_COLLECT_SCRIPT = TELEMETRY_DIR / "collect-acns-telemetry.sh"


def test_real_node_monitor_scrapes_kubelet_and_cadvisor():
    monitor = yaml.safe_load(MONITOR_PATH.read_text(encoding="utf-8"))

    assert monitor["spec"]["selector"]["matchLabels"] == {"k8s-app": "cilium"}
    endpoints = monitor["spec"]["podMetricsEndpoints"]
    assert [endpoint["path"] for endpoint in endpoints] == [
        "/metrics",
        "/metrics/cadvisor",
    ]
    assert all(endpoint["port"] == "prometheus" for endpoint in endpoints)
    assert all(
        any(
            relabel.get("sourceLabels") == ["__meta_kubernetes_pod_host_ip"]
            and relabel.get("replacement") == "$1:10250"
            for relabel in endpoint["relabelings"]
        )
        for endpoint in endpoints
    )


def test_kwok_resource_usage_and_node_discovery_are_configured():
    resources = list(
        yaml.safe_load_all(KWOK_RESOURCE_PATH.read_text(encoding="utf-8"))
    )
    kinds = {resource["kind"] for resource in resources}
    metric = next(resource for resource in resources if resource["kind"] == "Metric")
    secret = yaml.safe_load(KWOK_SCRAPE_PATH.read_text(encoding="utf-8"))
    scrape_configs = yaml.safe_load(
        secret["stringData"]["prometheus-additional.yaml"]
    )

    assert kinds == {"Metric", "ClusterResourceUsage"}
    assert metric["spec"]["path"] == "/metrics/nodes/{nodeName}/metrics/resource"
    assert {
        item["name"] for item in metric["spec"]["metrics"]
    } >= {
        "container_cpu_usage_seconds_total",
        "container_memory_working_set_bytes",
        "node_cpu_usage_seconds_total",
        "node_memory_working_set_bytes",
    }
    assert scrape_configs[0]["job_name"] == "kwok-resource"
    assert scrape_configs[0]["kubernetes_sd_configs"] == [{"role": "node"}]


def test_mock_workload_template_includes_synthetic_usage_annotations():
    template = EVENT_DEPLOYMENT_PATH.read_text(encoding="utf-8")

    assert 'kwok.x-k8s.io/usage-cpu: "{{.KwokUsageCPU}}"' in template
    assert 'kwok.x-k8s.io/usage-memory: "{{.KwokUsageMemory}}"' in template


def test_acns_probe_is_real_node_only_and_captures_filtered_logs():
    resources = list(
        yaml.safe_load_all(ACNS_PROBE_PATH.read_text(encoding="utf-8"))
    )
    deployments = {
        resource["metadata"]["name"]: resource
        for resource in resources
        if resource["kind"] == "Deployment"
    }
    policy = next(
        resource
        for resource in resources
        if resource["kind"] == "CiliumNetworkPolicy"
    )
    cnl = yaml.safe_load(ACNS_CNL_PATH.read_text(encoding="utf-8"))
    network_metric = yaml.safe_load(
        ACNS_METRIC_PATH.read_text(encoding="utf-8")
    )
    collector = yaml.safe_load(ACNS_COLLECTOR_PATH.read_text(encoding="utf-8"))

    assert {"acns-client", "acns-server"} <= set(deployments)
    for deployment in deployments.values():
        terms = (
            deployment["spec"]["template"]["spec"]["affinity"]
            ["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
            ["nodeSelectorTerms"]
        )
        expressions = [
            expression
            for term in terms
            for expression in term["matchExpressions"]
        ]
        assert any(
            expression["key"] == "type"
            and (
                expression["operator"] == "DoesNotExist"
                or (
                    expression["operator"] == "NotIn"
                    and expression["values"] == ["kwok"]
                )
            )
            for expression in expressions
        )
    assert any("toFQDNs" in rule for rule in policy["spec"]["egress"])
    assert cnl["spec"]["includefilters"]
    assert network_metric["kind"] == "ContainerNetworkMetric"
    assert network_metric["spec"]["filters"] == [
        {
            "metric": "dns",
            "includeFilters": [
                {
                    "name": "all-dns",
                    "protocol": ["dns"],
                }
            ],
        }
    ]
    assert {
        protocol
        for item in cnl["spec"]["includefilters"]
        for protocol in item["protocol"]
    } == {"tcp", "udp", "dns"}
    volume = collector["spec"]["template"]["spec"]["volumes"][0]
    assert volume["hostPath"]["path"] == "/var/log/acns/hubble"
    assert volume["hostPath"]["type"] == "DirectoryOrCreate"
    collector_terms = (
        collector["spec"]["template"]["spec"]["affinity"]
        ["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
        ["nodeSelectorTerms"]
    )
    assert any(
        any(
            expression["key"] == "type"
            and expression["operator"] == "NotIn"
            and expression["values"] == ["kwok"]
            for expression in term["matchExpressions"]
        )
        for term in collector_terms
    )


def test_acns_setup_and_host_log_collection_smoke(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_logs = tmp_path / "host-logs"
    fake_logs.mkdir()
    (fake_logs / "events.log").write_text(
        '{"verdict":"FORWARDED","protocol":"TCP"}\n',
        encoding="utf-8",
    )
    kubectl_log = tmp_path / "kubectl.log"
    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "$*" >> "$KUBECTL_LOG"
            if [ "${1:-} ${2:-}" = "get crd/containernetworklogs.acn.azure.com" ] ||
               [ "${1:-} ${2:-}" = "get crd/containernetworkmetrics.acn.azure.com" ] ||
               [ "${1:-} ${2:-}" = "get crd/ciliumnetworkpolicies.cilium.io" ]; then
              exit 0
            elif [ "${1:-}" = "apply" ]; then
              exit 0
            elif [[ " $* " == *" rollout status "* ]]; then
              exit 0
            elif [[ " $* " == *" get containernetworklog clustermesh-scale-acns -o jsonpath="* ]]; then
              printf CONFIGURED
            elif [[ " $* " == *" get containernetworkmetric container-network-metric -o jsonpath="* ]]; then
              printf CONFIGURED
            elif [[ " $* " == *" -n kube-system get pods -l k8s-app=cilium -o jsonpath="* ]]; then
              printf 'cilium-a\\tnode-a\\t10.0.0.4\\n'
            elif [[ " $* " == *" -n acns-telemetry get pods -l app=acns-log-collector -o jsonpath="* ]]; then
              printf 'collector-a\\tnode-a\\n'
            elif [[ " $* " == *" exec collector-a -c collector -- wget "* ]]; then
              printf '%s\\n' \
                '# TYPE hubble_dns_queries_total counter' \
                'hubble_dns_queries_total{query="management.azure.com"} 1' \
                '# TYPE hubble_dns_responses_total counter' \
                'hubble_dns_responses_total{rcode="No Error"} 1'
            elif [[ " $* " == *" get containernetworklog clustermesh-scale-acns -o json "* ]]; then
              printf '%s\\n' '{"status":{"state":"CONFIGURED"}}'
            elif [[ " $* " == *" get containernetworkmetric container-network-metric -o json "* ]]; then
              printf '%s\\n' '{"spec":{"filters":[{"metric":"dns"}]}}'
            elif [[ " $* " == *" get pods -o wide "* ]]; then
              printf '%s\\n' 'NAME READY STATUS' 'collector-a 1/1 Running'
            elif [[ " $* " == *" logs deployment/acns-client "* ]]; then
              printf '%s\\n' 'probe running'
            elif [[ " $* " == *" get pods -l app=acns-log-collector -o json "* ]]; then
              cat <<'JSON'
            {"items":[
              {"metadata":{"name":"collector-a"},"spec":{"nodeName":"node-a"}},
              {"metadata":{"name":"collector-b"},"spec":{"nodeName":"node-b"}}
            ]}
            JSON
            elif [[ " $* " == *" exec collector-"* ]]; then
              tar czf - -C "$FAKE_LOG_DIR" .
            elif [ "${1:-}" = "delete" ] || [[ " $* " == *" delete "* ]]; then
              exit 0
            else
              echo "Unexpected kubectl command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_kubectl.chmod(fake_kubectl.stat().st_mode | stat.S_IXUSR)
    output_dir = tmp_path / "output"
    environment = os.environ.copy()
    environment.update(
        {
            "CL2_ACNS_TELEMETRY_ENABLED": "true",
            "CL2_ACNS_METRIC_READY_TIMEOUT_SECONDS": "0",
            "CL2_ACNS_METRIC_POLL_SECONDS": "0",
            "KUBECONFIG": str(tmp_path / "kubeconfig"),
            "KUBECTL_LOG": str(kubectl_log),
            "FAKE_LOG_DIR": str(fake_logs),
            "OUTPUT_DIR": str(output_dir),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    subprocess.run(
        ["bash", str(ACNS_SETUP_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    subprocess.run(
        ["bash", str(ACNS_COLLECT_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    summary = json.loads(
        (output_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["complete"] is True
    assert summary["expected_archives"] == 2
    assert summary["nonempty_log_archives"] == 2
    assert summary["metric_config_captured"] is True
    assert (output_dir / "container-network-metric.json").exists()
    kubectl_calls = kubectl_log.read_text(encoding="utf-8")
    assert "http://10.0.0.4:9965/metrics" in kubectl_calls
    assert {item["node"] for item in summary["archives"]} == {
        "node-a",
        "node-b",
    }
    for item in summary["archives"]:
        with tarfile.open(output_dir / item["file"], "r:gz") as archive:
            assert any(
                member.name.endswith("events.log")
                for member in archive.getmembers()
            )


def test_acns_setup_fails_when_dns_metric_families_remain_absent(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${1:-} ${2:-}" = "get crd/containernetworklogs.acn.azure.com" ] ||
               [ "${1:-} ${2:-}" = "get crd/containernetworkmetrics.acn.azure.com" ] ||
               [ "${1:-} ${2:-}" = "get crd/ciliumnetworkpolicies.cilium.io" ] ||
               [ "${1:-}" = "apply" ] ||
               [[ " $* " == *" rollout status "* ]]; then
              exit 0
            elif [[ " $* " == *" get containernetworklog clustermesh-scale-acns -o jsonpath="* ]] ||
                 [[ " $* " == *" get containernetworkmetric container-network-metric -o jsonpath="* ]]; then
              printf CONFIGURED
            elif [[ " $* " == *" -n kube-system get pods -l k8s-app=cilium -o jsonpath="* ]]; then
              printf 'cilium-a\\tnode-a\\t10.0.0.4\\n'
            elif [[ " $* " == *" -n acns-telemetry get pods -l app=acns-log-collector -o jsonpath="* ]]; then
              printf 'collector-a\\tnode-a\\n'
            elif [[ " $* " == *" exec collector-a -c collector -- wget "* ]]; then
              printf '%s\\n' \
                '# TYPE hubble_flows_processed_total counter' \
                'hubble_flows_processed_total 1'
            elif [[ " $* " == *" get containernetworkmetric container-network-metric -o yaml "* ]]; then
              printf '%s\\n' 'status:' '  state: CONFIGURED'
            elif [[ " $* " == *" describe containernetworkmetric container-network-metric "* ]]; then
              printf '%s\\n' 'Name: container-network-metric'
            elif [[ " $* " == *" get pods "*"-o wide"* ]]; then
              printf '%s\\n' 'NAME READY STATUS' 'cilium-a 1/1 Running'
            else
              echo "Unexpected kubectl command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_kubectl.chmod(fake_kubectl.stat().st_mode | stat.S_IXUSR)
    environment = os.environ.copy()
    environment.update(
        {
            "CL2_ACNS_TELEMETRY_ENABLED": "true",
            "CL2_ACNS_METRIC_READY_TIMEOUT_SECONDS": "0",
            "CL2_ACNS_METRIC_POLL_SECONDS": "0",
            "KUBECONFIG": str(tmp_path / "kubeconfig"),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ACNS_SETUP_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 1
    assert "Timed out waiting for hubble_dns_queries_total" in result.stderr
    assert (
        "http://10.0.0.4:9965/metrics from cilium-a on node-a via collector-a"
        in result.stderr
    )
    assert "hubble_flows_processed_total" in result.stderr
    assert "state: CONFIGURED" in result.stderr


def test_audit_requires_real_node_kubelet_targets():
    metric_names = [
        "apiserver_request_total",
        "apiserver_flowcontrol_rejected_requests_total",
        "kube_pod_info",
        "kubelet_running_pods",
        "container_cpu_usage_seconds_total",
        "container_memory_working_set_bytes",
        "cilium_version",
        "cilium_kvstoremesh_kvstore_events_total",
        "etcd_request_duration_seconds_count",
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
        "aks_apiserver_backend_process_cpu_seconds_total",
        "aks_apiserver_backend_process_resident_memory_bytes",
        "pod_cpu_usage_seconds_total",
        "pod_memory_working_set_bytes",
        "node_cpu_usage_seconds_total",
        "node_memory_working_set_bytes",
        "clustermesh_cluster_identity_info",
    ]
    targets = [
        {"labels": {"job": "apiserver-backend-exporter"}, "health": "up"},
        {"labels": {"job": "kubelet-real-nodes"}, "health": "up"},
        {"labels": {"job": "cadvisor-real-nodes"}, "health": "up"},
        {"labels": {"job": "kwok-resource"}, "health": "up"},
    ]

    report = audit_module.build_audit(
        metric_names,
        targets,
        require_real_node_kubelet=True,
        require_kwok_resource=True,
        identity_series=[
            {
                "run_id": "run-1",
                "cluster_role": "mesh-1",
                "cluster_name": "clustermesh-1",
                "cluster_resource_id": "/subscriptions/sub-1/clustermesh-1",
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "region": "eastus2euap",
                "prometheus_cluster_alias": "run_1_mesh_1",
            }
        ],
    )

    assert report["complete"] is True
    assert {check["status"] for check in report["checks"]} == {"covered"}

    post_teardown = audit_module.build_audit(
        metric_names,
        [target for target in targets if target["labels"]["job"] != "apiserver-backend-exporter"],
        require_real_node_kubelet=True,
        require_kwok_resource=True,
        identity_series=[
            {
                "run_id": "run-1",
                "cluster_role": "mesh-1",
                "cluster_name": "clustermesh-1",
                "cluster_resource_id": "/subscriptions/sub-1/clustermesh-1",
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "region": "eastus2euap",
                "prometheus_cluster_alias": "run_1_mesh_1",
            }
        ],
    )
    exporter_check = next(
        check
        for check in post_teardown["checks"]
        if check["name"] == "target:apiserver-backend-exporter"
    )
    assert exporter_check["status"] == "covered"
    assert exporter_check["historical_metric_evidence"] is True


def test_audit_fails_when_cadvisor_target_is_down():
    metric_names = [
        "apiserver_request_total",
        "apiserver_flowcontrol_rejected_requests_total",
        "kube_pod_info",
        "kubelet_running_pods",
        "container_cpu_usage_seconds_total",
        "container_memory_working_set_bytes",
        "cilium_version",
        "etcd_request_duration_seconds_count",
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
        "aks_apiserver_backend_process_cpu_seconds_total",
        "aks_apiserver_backend_process_resident_memory_bytes",
        "pod_cpu_usage_seconds_total",
        "pod_memory_working_set_bytes",
        "node_cpu_usage_seconds_total",
        "node_memory_working_set_bytes",
        "clustermesh_cluster_identity_info",
    ]
    targets = [
        {"labels": {"job": "apiserver-backend-exporter"}, "health": "up"},
        {"labels": {"job": "kubelet-real-nodes"}, "health": "up"},
        {"labels": {"job": "cadvisor-real-nodes"}, "health": "down"},
        {"labels": {"job": "kwok-resource"}, "health": "up"},
    ]

    report = audit_module.build_audit(
        metric_names,
        targets,
        require_real_node_kubelet=True,
        require_kwok_resource=True,
        identity_series=[
            {
                "run_id": "run-1",
                "cluster_role": "mesh-1",
                "cluster_name": "clustermesh-1",
                "cluster_resource_id": "/subscriptions/sub-1/clustermesh-1",
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "region": "eastus2euap",
                "prometheus_cluster_alias": "run_1_mesh_1",
            }
        ],
    )

    cadvisor = next(
        check
        for check in report["checks"]
        if check["name"] == "target:cadvisor-real-nodes"
    )
    assert report["complete"] is False
    assert cadvisor["status"] == "missing"


def test_audit_requires_acns_metric_families_and_hubble_target():
    metric_names = list(audit_module.ACNS_METRICS)
    targets = [
        {
            "labels": {"job": "monitoring/hubble-metrics-0"},
            "health": "up",
        },
        {
            "labels": {"job": "apiserver-backend-exporter"},
            "health": "up",
        },
    ]

    report = audit_module.build_audit(
        metric_names,
        targets,
        require_acns=True,
        identity_series=[
            {
                "run_id": "run-1",
                "cluster_role": "mesh-1",
                "cluster_name": "clustermesh-1",
                "cluster_resource_id": "/subscriptions/sub-1/clustermesh-1",
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "region": "eastus2euap",
                "prometheus_cluster_alias": "run_1_mesh_1",
            }
        ],
    )

    acns_checks = [
        check for check in report["checks"] if check["name"].startswith("acns:")
    ]
    assert acns_checks
    assert {check["status"] for check in acns_checks} == {"covered"}
    target = next(
        check
        for check in report["checks"]
        if check["name"] == "target:acns-hubble"
    )
    assert target["status"] == "covered"
