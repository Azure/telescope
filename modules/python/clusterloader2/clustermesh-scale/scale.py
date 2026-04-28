"""
ClusterMesh scale-test harness.

Single-cluster invocation. The Telescope pipeline fans out by calling this
script once per fleet member (driven by `az fleet clustermeshprofile list-members`
in steps/topology/clustermesh-scale/execute-clusterloader2.yml). Each invocation
emits one JSONL with a `cluster` attribution column so concatenated results from
N clusters are queryable per-cluster downstream.

Phase 1 is intentionally trivial: deploy a small fixed number of pods, no churn,
no fortio, no network policies. The goal of Phase 1 is to prove the multi-cluster
harness + topology + aggregation works end-to-end. Real measurements
(cross-cluster event throughput, identity propagation, etc.) come in plan.md
Phase 2 by adding measurement modules to config/modules/measurements/ and new
parameters to configure/collect.
"""
import argparse
import json
import os
from datetime import datetime, timezone

from clusterloader2.utils import parse_xml_to_json, run_cl2_command, process_cl2_reports


def configure_clusterloader2(
    namespaces,
    deployments_per_namespace,
    replicas_per_deployment,
    operation_timeout,
    override_file,
):
    with open(override_file, "w", encoding="utf-8") as f:
        # Prometheus stack — match network-scale defaults so cilium-agent +
        # cilium-operator are scraped on each cluster.
        f.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        f.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 100.0\n")
        f.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 100.0\n")
        f.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
        f.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
        f.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
        f.write('CL2_PROMETHEUS_NODE_SELECTOR: "prometheus: \\"true\\""\n')
        f.write("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m\n")

        # Topology knobs — trivial defaults for Phase 1 vertical slice.
        f.write(f"CL2_NAMESPACES: {namespaces}\n")
        f.write(f"CL2_DEPLOYMENTS_PER_NAMESPACE: {deployments_per_namespace}\n")
        f.write(f"CL2_REPLICAS_PER_DEPLOYMENT: {replicas_per_deployment}\n")
        f.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")

    with open(override_file, "r", encoding="utf-8") as f:
        print(f"Content of file {override_file}:\n{f.read()}")


def execute_clusterloader2(
    cl2_image,
    cl2_config_dir,
    cl2_report_dir,
    cl2_config_file,
    kubeconfig,
    provider,
):
    run_cl2_command(
        kubeconfig,
        cl2_image,
        cl2_config_dir,
        cl2_report_dir,
        provider,
        cl2_config_file=cl2_config_file,
        overrides=True,
        enable_prometheus=True,
        tear_down_prometheus=True,
        scrape_kubelets=True,
        scrape_ksm=True,
        scrape_metrics_server=True,
    )


def collect_clusterloader2(
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file,
    test_type,
    start_timestamp,
    cluster_name,
    cluster_count,
    namespaces,
    deployments_per_namespace,
    replicas_per_deployment,
    trigger_reason="",
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent=2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    template = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        "test_details": {
            "trigger_reason": trigger_reason,
            # Cluster attribution — every row emitted for this run is tagged
            # with the cluster it came from, so downstream Kusto queries can
            # group/filter by cluster across an N-cluster mesh test.
            "cluster": cluster_name,
            "cluster_count": cluster_count,
            "namespaces": namespaces,
            "deployments_per_namespace": deployments_per_namespace,
            "replicas_per_deployment": replicas_per_deployment,
            "pods_per_cluster": namespaces * deployments_per_namespace * replicas_per_deployment,
            "details": (
                testsuites[0]["testcases"][0].get("failure", None)
                if testsuites[0].get("testcases")
                else None
            ),
        },
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
        "start_timestamp": start_timestamp,
        # parameters (top-level for Kusto column convenience)
        "cluster": cluster_name,
        "cluster_count": cluster_count,
        "namespaces": namespaces,
        "deployments_per_namespace": deployments_per_namespace,
        "replicas_per_deployment": replicas_per_deployment,
    }
    content = process_cl2_reports(cl2_report_dir, template)

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description="ClusterMesh scale-test harness.")
    subparsers = parser.add_subparsers(dest="command")

    # configure
    pc = subparsers.add_parser("configure", help="Write CL2 overrides file")
    pc.add_argument("--namespaces", type=int, required=True)
    pc.add_argument("--deployments-per-namespace", type=int, required=True)
    pc.add_argument("--replicas-per-deployment", type=int, required=True)
    pc.add_argument("--operation-timeout", type=str, default="15m")
    pc.add_argument("--cl2_override_file", type=str, required=True,
                    help="Path to the overrides of CL2 config file")

    # execute
    pe = subparsers.add_parser("execute", help="Run CL2 against a single cluster")
    pe.add_argument("--cl2-image", type=str, required=True)
    pe.add_argument("--cl2-config-dir", type=str, required=True)
    pe.add_argument("--cl2-report-dir", type=str, required=True)
    pe.add_argument("--cl2-config-file", type=str, required=True)
    pe.add_argument("--kubeconfig", type=str, required=True)
    pe.add_argument("--provider", type=str, required=True)

    # collect
    pco = subparsers.add_parser("collect", help="Collect results for one cluster")
    pco.add_argument("--cl2_report_dir", type=str, required=True)
    pco.add_argument("--cloud_info", type=str, default="")
    pco.add_argument("--run_id", type=str, required=True)
    pco.add_argument("--run_url", type=str, default="")
    pco.add_argument("--result_file", type=str, required=True)
    pco.add_argument("--test_type", type=str, default="default-config")
    pco.add_argument("--start_timestamp", type=str, required=True)
    pco.add_argument("--cluster-name", type=str, required=True,
                     help="Fleet member / AKS cluster identity for attribution")
    pco.add_argument("--cluster-count", type=int, required=True,
                     help="Total clusters in the mesh for this run (N)")
    pco.add_argument("--namespaces", type=int, required=True)
    pco.add_argument("--deployments-per-namespace", type=int, required=True)
    pco.add_argument("--replicas-per-deployment", type=int, required=True)
    pco.add_argument("--trigger_reason", type=str, default="")

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(
            args.namespaces,
            args.deployments_per_namespace,
            args.replicas_per_deployment,
            args.operation_timeout,
            args.cl2_override_file,
        )
    elif args.command == "execute":
        execute_clusterloader2(
            args.cl2_image,
            args.cl2_config_dir,
            args.cl2_report_dir,
            args.cl2_config_file,
            args.kubeconfig,
            args.provider,
        )
    elif args.command == "collect":
        collect_clusterloader2(
            args.cl2_report_dir,
            args.cloud_info,
            args.run_id,
            args.run_url,
            args.result_file,
            args.test_type,
            args.start_timestamp,
            args.cluster_name,
            args.cluster_count,
            args.namespaces,
            args.deployments_per_namespace,
            args.replicas_per_deployment,
            args.trigger_reason,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
