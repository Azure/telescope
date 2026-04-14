import json
import os
import argparse

from datetime import datetime, timezone
from clusterloader2.utils import parse_xml_to_json, run_cl2_command, process_cl2_reports
from utils.common import str2bool

def configure_clusterloader2(
    fortio_servers_per_deployment,
    fortio_clients_per_deployment,
    fortio_client_queries_per_second,
    fortio_client_connections,
    fortio_namespaces,
    fortio_deployments_per_namespace,
    network_policies_per_namespace,
    generate_container_network_logs,
    label_traffic_pods,
    override_file):

    with open(override_file, 'w', encoding='utf-8') as file:
        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
        file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")
        file.write("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m\n")
        file.write("CL2_NODE_EXPORTER_OPERATION_TIMEOUT: 60m\n")
        file.write("CL2_NODE_EXPORTER_ENABLE_VALIDATION: false\n")
        file.write(f"CL2_LABEL_TRAFFIC_PODS: {label_traffic_pods}\n")

        # topology config
        file.write(f"CL2_FORTIO_SERVERS_PER_DEPLOYMENT: {fortio_servers_per_deployment}\n")
        file.write(f"CL2_FORTIO_CLIENTS_PER_DEPLOYMENT: {fortio_clients_per_deployment}\n")
        file.write(f"CL2_FORTIO_CLIENT_QUERIES_PER_SECOND: {fortio_client_queries_per_second}\n")
        file.write(f"CL2_FORTIO_CLIENT_CONNECTIONS: {fortio_client_connections}\n")
        file.write(f"CL2_FORTIO_NAMESPACES: {fortio_namespaces}\n")
        file.write(f"CL2_FORTIO_DEPLOYMENTS_PER_NAMESPACE: {fortio_deployments_per_namespace}\n")
        file.write("CL2_FORTIO_POD_CPU: 10m\n")
        file.write("CL2_FORTIO_POD_MEMORY: 50Mi\n")
        file.write(f"CL2_NETWORK_POLICIES_PER_NAMESPACE: {network_policies_per_namespace}\n")
        file.write(f"CL2_GENERATE_CONTAINER_NETWORK_LOGS: {generate_container_network_logs}\n")

    with open(override_file, 'r', encoding='utf-8') as file:
        print(f"Content of file {override_file}:\n{file.read()}")

def execute_clusterloader2(
    cl2_image,
    cl2_config_dir,
    cl2_report_dir,
    cl2_config_file,
    kubeconfig,
    provider,
    scrape_containerd
):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider,
                    cl2_config_file=cl2_config_file, overrides=True, enable_prometheus=True,
                    scrape_containerd=scrape_containerd, tear_down_prometheus=True,
                    scrape_kubelets=True, scrape_ksm=True,
                    scrape_metrics_server=True)


def collect_clusterloader2(
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file,
    test_type,
    start_timestamp,
    observability_tool,
    repository,
    repository_ref,
    fortio_servers_per_deployment,
    fortio_clients_per_deployment,
    fortio_client_queries_per_second,
    fortio_client_connections,
    fortio_namespaces,
    fortio_deployments_per_namespace,
    network_policies_per_namespace,
    generate_container_network_logs=False,
    label_traffic_pods=False,
    trigger_reason="",
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    # TODO: Expose optional parameter to include test details
    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        "observability_tool": observability_tool,
        "test_details": {
            # add more details here about tests (e.g. features tested)
            "trigger_reason": trigger_reason,
            "observability_tool": observability_tool,
            "repository": repository,
            "repository_ref": repository_ref,
            "traffic_generator": "fortio",
            "traffic_namespaces": fortio_namespaces,
            "traffic_deployments_per_namespace": fortio_deployments_per_namespace,
            "traffic_servers_per_deployment": fortio_servers_per_deployment,
            "traffic_clients_per_deployment": fortio_clients_per_deployment,
            "traffic_pods": fortio_namespaces * fortio_deployments_per_namespace * (fortio_clients_per_deployment + fortio_servers_per_deployment),
            "network_policies": network_policies_per_namespace,
            "generate_container_network_logs": generate_container_network_logs,
            "label_traffic_pods": label_traffic_pods,
            "requests_per_second": fortio_client_queries_per_second,
            "details": testsuites[0]["testcases"][0].get("failure", None) if testsuites[0].get("testcases") else None,
        },
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
        "start_timestamp": start_timestamp,
        # parameters
        "fortio_servers_per_deployment": fortio_servers_per_deployment,
        "fortio_clients_per_deployment": fortio_clients_per_deployment,
        "fortio_client_queries_per_second": fortio_client_queries_per_second,
        "fortio_client_connections": fortio_client_connections,
        "fortio_namespaces": fortio_namespaces,
        "fortio_deployments_per_namespace": fortio_deployments_per_namespace,
    }
    content = process_cl2_reports(cl2_report_dir, template)

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    parser = argparse.ArgumentParser(description="SLO Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("--fortio-servers-per-deployment", type=int, required=True, help="Number of Fortio servers per deployment")
    parser_configure.add_argument("--fortio-clients-per-deployment", type=int, required=True, help="Number of Fortio clients per deployment")
    parser_configure.add_argument("--fortio-client-queries-per-second", type=int, required=True, help="Queries per second for each Fortio client pod. NOT queries per second per connection")
    parser_configure.add_argument("--fortio-client-connections", type=int, required=True, help="Number of simultaneous connections for each Fortio client")
    parser_configure.add_argument("--fortio-namespaces", type=int, required=True, help="Number of namespaces, each with their own service. Fortio clients query servers in the same namespace. Be wary of integer division causing less pods than expected regarding this parameter, pods, and pods per node.")
    parser_configure.add_argument("--fortio-deployments-per-namespace", type=int, required=True, help="Number of Fortio server deployments (and number of client deployments) per service/partition. Be wary of integer division causing less pods than expected regarding this parameter, namespaces, pods, and pods per node.")
    parser_configure.add_argument("--network-policies-per-namespace", type=int, help="Number of network policies to be created per namespace", default=0, nargs='?')
    parser_configure.add_argument("--generate-container-network-logs", type=str2bool, choices=[True, False], nargs='?', default=False, help="Generate Container Network Logs (default=False)")
    parser_configure.add_argument("--label_traffic_pods", type=str2bool, choices=[True, False], nargs='?', default=False, help="Add/Remove label to client traffic pods(default=False)")
    parser_configure.add_argument("--cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("--cl2-image", type=str, required=True, help="Name of the CL2 image")
    parser_execute.add_argument("--cl2-config-dir", type=str, required=True, help="Path to the CL2 config directory")
    parser_execute.add_argument("--cl2-report-dir", type=str, required=True, help="Path to the CL2 report directory")
    parser_execute.add_argument("--cl2-config-file", type=str, required=True, help="Path to the CL2 config file")
    parser_execute.add_argument("--kubeconfig", type=str, required=True, help="Path to the kubeconfig file")
    parser_execute.add_argument("--provider", type=str, required=True, help="Cloud provider name")
    parser_execute.add_argument("--scrape-containerd", type=str2bool, choices=[True, False], default=False,
                                help="Whether to scrape containerd metrics. Must be either True or False")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("--cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("--cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("--run_id", type=str, help="Run ID")
    parser_collect.add_argument("--run_url", type=str, help="Run URL")
    parser_collect.add_argument("--result_file", type=str, help="Path to the result file")
    parser_collect.add_argument("--test_type", type=str, nargs='?', default="default-config",
                                help="Description of test type")
    parser_collect.add_argument("--start_timestamp", type=str, help="Test start timestamp")
    parser_collect.add_argument("--observability_tool", type=str, help="Observability tool evaluated in the test")
    parser_collect.add_argument("--repository", type=str, help="Repository of observability tool evaluated in the test")
    parser_collect.add_argument("--repository_ref", type=str, help="Repository Ref (branch/tag/SHA) of observability tool evaluated in the test")
    parser_collect.add_argument("--fortio-servers-per-deployment", type=int, required=True, help="Number of Fortio servers per deployment")
    parser_collect.add_argument("--fortio-clients-per-deployment", type=int, required=True, help="Number of Fortio clients per deployment")
    parser_collect.add_argument("--fortio-client-queries-per-second", type=int, required=True, help="Queries per second for each Fortio client pod. NOT queries per second per connection")
    parser_collect.add_argument("--fortio-client-connections", type=int, required=True, help="Number of simultaneous connections for each Fortio client")
    parser_collect.add_argument("--fortio-namespaces", type=int, required=True, help="Number of namespaces, each with their own service. Fortio clients query servers in the same namespace. Be wary of integer division causing less pods than expected regarding this parameter, pods, and pods per node.")
    parser_collect.add_argument("--fortio-deployments-per-namespace", type=int, required=True, help="Number of Fortio server deployments (and number of client deployments) per service/partition. Be wary of integer division causing less pods than expected regarding this parameter, namespaces, pods, and pods per node.")
    parser_collect.add_argument("--network-policies-per-namespace", type=int, help="Number of network policies to be created per namespace", default=0, nargs='?')
    parser_collect.add_argument("--generate-container-network-logs", type=str2bool, choices=[True, False], nargs='?', default=False, help="Generate Container Network Logs (default=False)")
    parser_collect.add_argument("--label_traffic_pods", type=str2bool, choices=[True, False], nargs='?', default=False, help="Add/Remove label to client traffic pods(default=False)")
    parser_collect.add_argument("--trigger_reason", type=str, help="What triggered the test", nargs='?', default="")

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(args.fortio_servers_per_deployment,
                                 args.fortio_clients_per_deployment,
                                 args.fortio_client_queries_per_second,
                                 args.fortio_client_connections,
                                 args.fortio_namespaces,
                                 args.fortio_deployments_per_namespace,
                                 args.network_policies_per_namespace,
                                 args.generate_container_network_logs,
                                 args.label_traffic_pods,
                                 args.cl2_override_file,
                                 )
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.cl2_config_file,
                               args.kubeconfig, args.provider, args.scrape_containerd)
    elif args.command == "collect":
        collect_clusterloader2(args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url,
                               args.result_file, args.test_type, args.start_timestamp,
                               args.observability_tool,
                               args.repository,
                               args.repository_ref,
                               args.fortio_servers_per_deployment,
                               args.fortio_clients_per_deployment,
                               args.fortio_client_queries_per_second,
                               args.fortio_client_connections,
                               args.fortio_namespaces,
                               args.fortio_deployments_per_namespace,
                               args.network_policies_per_namespace,
                               args.generate_container_network_logs,
                               args.label_traffic_pods,
                               args.trigger_reason,
                               )

if __name__ == "__main__":
    main()
