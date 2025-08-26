import json
import os
import argparse
import time

from datetime import datetime, timezone
from clusterloader2.utils import parse_xml_to_json, run_cl2_command, get_measurement
from clients.kubernetes_client import KubernetesClient
from utils.common import str2bool

DEFAULT_PODS_PER_NODE = 40

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

def calculate_config(cpu_per_node, node_count, max_pods, provider, service_test):
    throughput = 100
    nodes_per_namespace = min(node_count, DEFAULT_NODES_PER_NAMESPACE)

    pods_per_node = DEFAULT_PODS_PER_NODE
    if service_test:
        pods_per_node = max_pods

    # Different cloud has different reserved values and number of daemonsets
    # Using the same percentage will lead to incorrect nodes number as the number of nodes grow
    # For AWS, see: https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/bootstrap.sh#L290
    # For Azure, see: https://learn.microsoft.com/en-us/azure/aks/node-resource-reservations#cpu-reservations
    capacity = CPU_CAPACITY[provider]
    cpu_request = (cpu_per_node * 1000 * capacity) // pods_per_node
    cpu_request = max(cpu_request, CPU_REQUEST_LIMIT_MILLI)

    return throughput, nodes_per_namespace, pods_per_node, cpu_request

def configure_clusterloader2(
    cpu_per_node,
    node_count,
    node_per_step,
    max_pods,
    repeats,
    operation_timeout,
    provider,
    cilium_enabled,
    scrape_containerd,
    service_test,
    num_cnps,
    num_ccnps,
    dualstack,
    override_file):

    steps = node_count // node_per_step
    throughput, nodes_per_namespace, pods_per_node, cpu_request = calculate_config(cpu_per_node, node_per_step, max_pods, provider, service_test)

    with open(override_file, 'w', encoding='utf-8') as file:
        file.write(f"CL2_NODES: {node_count}\n")
        file.write(f"CL2_LOAD_TEST_THROUGHPUT: {throughput}\n")
        file.write(f"CL2_NODES_PER_NAMESPACE: {nodes_per_namespace}\n")
        file.write(f"CL2_NODES_PER_STEP: {node_per_step}\n")
        file.write(f"CL2_PODS_PER_NODE: {pods_per_node}\n")
        file.write(f"CL2_DEPLOYMENT_SIZE: {pods_per_node}\n")
        file.write(f"CL2_LATENCY_POD_CPU: {cpu_request}\n")
        file.write(f"CL2_REPEATS: {repeats}\n")
        file.write(f"CL2_STEPS: {steps}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")
        file.write("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m\n")

        if scrape_containerd:
            file.write(f"CL2_SCRAPE_CONTAINERD: {str(scrape_containerd).lower()}\n")
            file.write("CONTAINERD_SCRAPE_INTERVAL: 5m\n")

        if cilium_enabled:
            file.write("CL2_CILIUM_METRICS_ENABLED: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL: 30s\n")

        if service_test:
            file.write("CL2_SERVICE_TEST: true\n")
        else:
            file.write("CL2_SERVICE_TEST: false\n")

    with open(override_file, 'r', encoding='utf-8') as file:
        print(f"Content of file {override_file}:\n{file.read()}")

    file.close()

def validate_clusterloader2(node_count, operation_timeout_in_minutes=10):
    kube_client = KubernetesClient()
    ready_node_count = 0
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    while time.time() < timeout:
        ready_nodes = kube_client.get_ready_nodes()
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.")
        if ready_node_count == node_count:
            break
        print(f"Waiting for {node_count} nodes to be ready.")
        time.sleep(10)
    if ready_node_count != node_count:
        raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")

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
                    scrape_containerd=scrape_containerd)

def collect_clusterloader2(
    cpu_per_node,
    node_count,
    max_pods,
    repeats,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    service_test,
    result_file,
    test_type,
    start_timestamp,
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]
    provider = json.loads(cloud_info)["cloud"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    _, _, pods_per_node, _ = calculate_config(cpu_per_node, node_count, max_pods, provider, service_test)
    pod_count = node_count * pods_per_node

    # TODO: Expose optional parameter to include test details
    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "cpu_per_node": cpu_per_node,
        "node_count": node_count,
        "pod_count": pod_count,
        "churn_rate": repeats,
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        # "test_details": details,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
        "start_timestamp": start_timestamp,
    }
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, 'r', encoding='utf-8') as file:
            print(f"Processing {file_path}")
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(file.read())

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
    with open(result_file, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    parser = argparse.ArgumentParser(description="SLO Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("cpu_per_node", type=int, help="CPU per node")
    parser_configure.add_argument("node_count", type=int, help="Number of nodes")
    parser_configure.add_argument("node_per_step", type=int, help="Number of nodes per scaling step")
    parser_configure.add_argument("max_pods", type=int, nargs='?', default=0, help="Maximum number of pods per node")
    parser_configure.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_configure.add_argument("operation_timeout", type=str, help="Timeout before failing the scale up test")
    parser_configure.add_argument("provider", type=str, help="Cloud provider name")
    parser_configure.add_argument("cilium_enabled", type=str2bool, choices=[True, False], default=False,
                                  help="Whether cilium is enabled. Must be either True or False")
    parser_configure.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False,
                                  help="Whether to scrape containerd metrics. Must be either True or False")
    parser_configure.add_argument("service_test", type=str2bool, choices=[True, False], default=False,
                                  help="Whether service test is running. Must be either True or False")
    parser_configure.add_argument("num_cnps", type=int, nargs='?', default=0, help="Number of cnps")
    parser_configure.add_argument("num_ccnps", type=int, nargs='?', default=0, help="Number of ccnps")
    parser_configure.add_argument("dualstack", type=str2bool, choices=[True, False], nargs='?', default=False,
                                  help="Whether cluster is dualstack. Must be either True or False")
    parser_configure.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for validate_clusterloader2
    parser_validate = subparsers.add_parser("validate", help="Validate cluster setup")
    parser_validate.add_argument("node_count", type=int, help="Number of desired nodes")
    parser_validate.add_argument("operation_timeout", type=int, default=600, help="Operation timeout to wait for nodes to be ready")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("cl2_config_file", type=str, help="Path to the CL2 config file")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")
    parser_execute.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False,
                                help="Whether to scrape containerd metrics. Must be either True or False")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("cpu_per_node", type=int, help="CPU per node")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("max_pods", type=int, nargs='?', default=0, help="Maximum number of pods per node")
    parser_collect.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("service_test", type=str2bool, choices=[True, False], default=False,
                                  help="Whether service test is running. Must be either True or False")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")
    parser_collect.add_argument("test_type", type=str, nargs='?', default="default-config",
                                help="Description of test type")
    parser_collect.add_argument("start_timestamp", type=str, help="Test start timestamp")

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(args.cpu_per_node, args.node_count, args.node_per_step, args.max_pods,
                                 args.repeats, args.operation_timeout, args.provider,
                                 args.cilium_enabled, args.scrape_containerd,
                                 args.service_test, args.num_cnps, args.num_ccnps, args.dualstack, args.cl2_override_file)
    elif args.command == "validate":
        validate_clusterloader2(args.node_count, args.operation_timeout)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.cl2_config_file,
                               args.kubeconfig, args.provider, args.scrape_containerd)
    elif args.command == "collect":
        collect_clusterloader2(args.cpu_per_node, args.node_count, args.max_pods, args.repeats,
                               args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url,
                               args.service_test, args.result_file, args.test_type, args.start_timestamp)

if __name__ == "__main__":
    main()
