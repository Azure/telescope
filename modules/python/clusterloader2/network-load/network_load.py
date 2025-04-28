import json
import os
import argparse

from datetime import datetime, timezone
from clusterloader2.utils import str2bool, parse_xml_to_json, run_cl2_command, get_measurement

DEFAULT_NODES_PER_NAMESPACE = 100
CPU_REQUEST_LIMIT_MILLI = 1
DAEMONSETS_PER_NODE = {
    "aws": 2,
    "azure": 6,
    "aks": 6
}
CPU_CAPACITY = {
    "aws": 0.94,
    "azure": 0.87,
    "aks": 0.87
}
# TODO: Remove aks once CL2 update provider name to be azure

def configure_clusterloader2(
    override_file,
    operation_timeout,
    provider,
    deployment_recreation_count,
    cpu_per_node,
    node_count,
    fortio_servers_per_node,
    fortio_clients_per_node,
    fortio_client_queries_per_second,
    fortio_client_connections,
    fortio_namespaces,
    fortio_deployments_per_namespace,
    apply_fqdn_cnp):

    # calculate CPU request per Pod based on pods/node and node CPU capacity
    # Different cloud has different reserved values and number of daemonsets
    # Using the same percentage will lead to incorrect nodes number as the number of nodes grow
    # For AWS, see: https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/bootstrap.sh#L290
    # For Azure, see: https://learn.microsoft.com/en-us/azure/aks/node-resource-reservations#cpu-reservations
    pods_per_node = fortio_servers_per_node + fortio_clients_per_node
    capacity = CPU_CAPACITY[provider]
    cpu_request = (cpu_per_node * 1000 * capacity) // pods_per_node
    cpu_request = max(cpu_request, CPU_REQUEST_LIMIT_MILLI)

    with open(override_file, 'w', encoding='utf-8') as file:
        # generic config
        file.write("CL2_GROUP_NAME: cilium-acns-network-load\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write("CL2_API_SERVER_CALLS_PER_SECOND: 100\n")

        # repetition config
        file.write(f"CL2_DEPLOYMENT_RECREATION_COUNT: {deployment_recreation_count}\n")

        # scale logistics
        # file.write(f"CL2_NODES_PER_STEP: {node_per_step}\n")
        file.write("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m\n")

        # topology config
        file.write(f"CL2_NODES: {node_count}\n")
        file.write(f"CL2_FORTIO_SERVERS_PER_NODE: {fortio_servers_per_node}\n")
        file.write(f"CL2_FORTIO_CLIENTS_PER_NODE: {fortio_clients_per_node}\n")
        file.write(f"CL2_FORTIO_CLIENT_QUERIES_PER_SECOND: {fortio_client_queries_per_second}\n")
        file.write(f"CL2_FORTIO_CLIENT_CONNECTIONS: {fortio_client_connections}\n")
        file.write(f"CL2_FORTIO_NAMESPACES: {fortio_namespaces}\n")
        file.write(f"CL2_FORTIO_DEPLOYMENTS_PER_NAMESPACE: {fortio_deployments_per_namespace}\n")
        file.write("CL2_FORTIO_POD_CPU: 10\n")
        file.write("CL2_FORTIO_POD_MEMORY: 50\n")

        # other test toggles
        # creates Hubble DNS metrics
        file.write(f"CL2_APPLY_FQDN_CNP: {apply_fqdn_cnp}\n")

        # prometheus scrape config
        file.write("CL2_CILIUM_METRICS_ENABLED: true\n")
        file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
        file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
        file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_HUBBLE: true\n")

        # prometheus server config
        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")

    with open(override_file, 'r', encoding='utf-8') as file:
        print(f"Content of file {override_file}:\n{file.read()}")

    file.close()

def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, cl2_config_file, kubeconfig, provider):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, cl2_config_file=cl2_config_file, overrides=True, enable_prometheus=True)

def collect_clusterloader2(
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file,
    deployment_recreation_count,
    cpu_per_node,
    node_count,
    fortio_servers_per_node,
    fortio_clients_per_node,
    fortio_client_queries_per_second,
    fortio_client_connections,
    fortio_namespaces,
    fortio_deployments_per_namespace,
    apply_fqdn_cnp,
    test_type="default_config"
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    # FIXME this is not working. always failure
    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        # includes provider
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        # parameters
        "deployment_recreation_count": deployment_recreation_count,
        "cpu_per_node": cpu_per_node,
        "node_count": node_count,
        "fortio_servers_per_node": fortio_servers_per_node,
        "fortio_clients_per_node": fortio_clients_per_node,
        "fortio_client_queries_per_second": fortio_client_queries_per_second,
        "fortio_client_connections": fortio_client_connections,
        "fortio_namespaces": fortio_namespaces,
        "fortio_deployments_per_namespace": fortio_deployments_per_namespace,
        "apply_fqdn_cnp": apply_fqdn_cnp,
    }
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, 'r', encoding='utf-8') as f:
            print(f"Processing {file_path}")
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(f.read())

            if "dataItems" in data:
                items = data["dataItems"]
                if not items:
                    print(f"No data items found in {file_path}")
                    print(f"Data:\n{data}")
                    continue
                for item in items:
                    result = template.copy()
                    result["group"] = group_name
                    result["measurement"] = measurement
                    result["result"] = item
                    content += json.dumps(result) + "\n"
            else:
                result = template.copy()
                result["group"] = group_name
                result["measurement"] = measurement
                result["result"] = data
                content += json.dumps(result) + "\n"

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w', encoding='utf-8') as f:
        f.write(content)

def main():
    parser = argparse.ArgumentParser(description="network-load test")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("--cl2-override-file", type=str, required=True, help="Path to the overrides of CL2 config file")
    parser_configure.add_argument("--operation-timeout", type=str, required=True, help="Timeout before failing the scale up test")
    parser_configure.add_argument("--provider", type=str, required=True, help="Cloud provider name")
    parser_configure.add_argument("--deployment-recreation-count", type=int, required=True, help="Number of times to recreate deployments")
    parser_configure.add_argument("--cpu-per-node", type=int, required=True, help="CPU per node")
    parser_configure.add_argument("--node-count", type=int, required=True, help="Number of nodes")
    parser_configure.add_argument("--fortio-servers-per-node", type=int, required=True, help="Number of Fortio servers per node")
    parser_configure.add_argument("--fortio-clients-per-node", type=int, required=True, help="Number of Fortio clients per node")
    parser_configure.add_argument("--fortio-client-queries-per-second", type=int, required=True, help="Queries per second for each Fortio client pod. NOT queries per second per connection")
    parser_configure.add_argument("--fortio-client-connections", type=int, required=True, help="Number of simultaneous connections for each Fortio client")
    parser_configure.add_argument("--fortio-namespaces", type=int, required=True, help="Number of namespaces, each with their own service. Fortio clients query servers in the same namespace. Be weary of integer division causing less pods than expected regarding this parameter, pods, and pods per node.")
    parser_configure.add_argument("--fortio-deployments-per-namespace", type=int, required=True, help="Number of Fortio server deployments (and number of client deployments) per service/partition. Be weary of integer division causing less pods than expected regarding this parameter, namespaces, pods, and pods per node.")
    parser_configure.add_argument("--apply-fqdn-cnp", type=str2bool, choices=[True, False], default=False, help="Apply CNP that will generate DNS metrics")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("--cl2-image", type=str, required=True, help="Name of the CL2 image")
    parser_execute.add_argument("--cl2-config-dir", type=str, required=True, help="Path to the CL2 config directory")
    parser_execute.add_argument("--cl2-report-dir", type=str, required=True, help="Path to the CL2 report directory")
    parser_execute.add_argument("--cl2-config-file", type=str, required=True, help="Path to the CL2 config file")
    parser_execute.add_argument("--kubeconfig", type=str, required=True, help="Path to the kubeconfig file")
    parser_execute.add_argument("--provider", type=str, required=True, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("--cl2-report-dir", type=str, required=True, help="Path to the CL2 report directory")
    parser_collect.add_argument("--cloud-info", type=str, required=True, help="Cloud information")
    parser_collect.add_argument("--run-id", type=str, required=True, help="Run ID")
    parser_collect.add_argument("--run-url", type=str, required=True, help="Run URL")
    parser_collect.add_argument("--result-file", type=str, required=True, help="Path to the result file")
    parser_collect.add_argument("--test-type", type=str, default="default-config", help="Description of test type")
    parser_collect.add_argument("--deployment-recreation-count", type=int, required=True, help="Number of times to recreate deployments")
    parser_collect.add_argument("--cpu-per-node", type=int, required=True, help="CPU per node")
    parser_collect.add_argument("--node-count", type=int, required=True, help="Number of nodes")
    parser_collect.add_argument("--fortio-servers-per-node", type=int, required=True, help="Number of Fortio servers per node")
    parser_collect.add_argument("--fortio-clients-per-node", type=int, required=True, help="Number of Fortio clients per node")
    parser_collect.add_argument("--fortio-client-queries-per-second", type=int, required=True, help="Queries per second for each Fortio client pod. NOT queries per second per connection")
    parser_collect.add_argument("--fortio-client-connections", type=int, required=True, help="Number of simultaneous connections for each Fortio client")
    parser_collect.add_argument("--fortio-namespaces", type=int, required=True, help="Number of namespaces, each with their own service. Fortio clients query servers in the same namespace. Be weary of integer division causing less pods than expected regarding this parameter, pods, and pods per node.")
    parser_collect.add_argument("--fortio-deployments-per-namespace", type=int, required=True, help="Number of Fortio server deployments (and number of client deployments) per service/partition. Be weary of integer division causing less pods than expected regarding this parameter, namespaces, pods, and pods per node.")
    parser_collect.add_argument("--apply-fqdn-cnp", type=str2bool, choices=[True, False], default=False, help="Apply CNP that will generate DNS metrics")

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(
            args.cl2_override_file,
            args.operation_timeout,
            args.provider,
            args.deployment_recreation_count,
            args.cpu_per_node,
            args.node_count,
            args.fortio_servers_per_node,
            args.fortio_clients_per_node,
            args.fortio_client_queries_per_second,
            args.fortio_client_connections,
            args.fortio_namespaces,
            args.fortio_deployments_per_namespace,
            args.apply_fqdn_cnp
        )
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.cl2_config_file,
                               args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(
            args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file,
            args.deployment_recreation_count,
            args.cpu_per_node,
            args.node_count,
            args.fortio_servers_per_node,
            args.fortio_clients_per_node,
            args.fortio_client_queries_per_second,
            args.fortio_client_connections,
            args.fortio_namespaces,
            args.fortio_deployments_per_namespace,
            args.apply_fqdn_cnp,
            test_type=args.test_type,
        )

if __name__ == "__main__":
    main()
