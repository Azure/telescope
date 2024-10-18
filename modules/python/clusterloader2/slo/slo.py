import json
import os
import argparse
import time

from datetime import datetime, timezone
from utils import parse_xml_to_json, run_cl2_command, get_measurement
from kubernetes_client import KubernetesClient

DAEMONSETS_PER_NODE = 6
DEFAULT_PODS_PER_NODE = 50
KUBE_CLIENT = KubernetesClient()

def calculate_config(node_count, max_pods):
    calculated_throughput = node_count / 10 + 10
    throughput = min(calculated_throughput, 100)

    nodes_per_namespace = max(node_count, 100)
    max_user_pods = max_pods - DAEMONSETS_PER_NODE
    pods_per_node = min(max_user_pods, DEFAULT_PODS_PER_NODE)

    # assuming 90% of the allocatable CPU cores can be used by test pods
    nodes = KUBE_CLIENT.get_nodes(label_selector="slo=true")
    node = nodes[0]
    allocatable_cpu = int(node.status.allocatable["cpu"][:-1])
    cpu_request = (allocatable_cpu * 0.9) // pods_per_node

    return throughput, nodes_per_namespace, pods_per_node, cpu_request

def configure_clusterloader2(node_count, node_per_step, max_pods, repeats, operation_timeout, override_file):
    steps = node_count // node_per_step
    throughput, nodes_per_namespace, pods_per_node, cpu_request = calculate_config(node_per_step, max_pods)

    with open(override_file, 'w') as file:
        file.write(f"CL2_LOAD_TEST_THROUGHPUT: {throughput}\n")
        file.write(f"CL2_NODES_PER_NAMESPACE: {nodes_per_namespace}\n")
        file.write(f"CL2_PODS_PER_NODE: {pods_per_node}\n")
        file.write(f"CL2_LATENCY_POD_CPU: {cpu_request}\n")
        file.write(f"CL2_REPEATS: {repeats}\n")
        file.write(f"CL2_STEPS: {steps}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write(f"CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write(f"CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"")
    
    with open(override_file, 'r') as file:
        print(f"Content of file {override_file}:\n{file.read()}")

    file.close()

def validate_clusterloader2(node_count, operation_timeout=600):
    timeout = time.time() + operation_timeout
    while time.time() < timeout:
        ready_nodes = KUBE_CLIENT.get_ready_nodes()
        if len(ready_nodes) == node_count:
            break
        print(f"Waiting for {node_count} nodes to be ready. Currently {len(ready_nodes)} nodes are ready.")
        time.sleep(10)

def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, kubeconfig, provider):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, overrides=True, enable_prometheus=True)

def collect_clusterloader2(
    node_count,
    max_pods,
    repeats,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")
    
    _, nodes_per_namespace, pods_per_node, _ = calculate_config(node_count, max_pods)
    pod_count = nodes_per_namespace * pods_per_node

    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "node_count": node_count,
        "pod_count": pod_count,
        "churn_rate": repeats,
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        "test_details": details,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url
    }
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, 'r') as f:
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(f.read())

            if "dataItems" in data:
                items = data["dataItems"]
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
    with open(result_file, 'w') as f:
        f.write(content)

def main():
    parser = argparse.ArgumentParser(description="Autoscale Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("node_count", type=int, help="Number of nodes")
    parser_configure.add_argument("node_per_step", type=int, help="Number of nodes per scaling step")
    parser_configure.add_argument("max_pods", type=int, help="Maximum number of pods per node")
    parser_configure.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_configure.add_argument("operation_timeout", type=str, help="Timeout before failing the scale up test")
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
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("max_pods", type=int, help="Maximum number of pods per node")
    parser_collect.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(args.node_count, args.node_per_step, args.max_pods,
                                 args.repeats, args.operation_timeout, args.cl2_override_file)
    elif args.command == "validate":
        validate_clusterloader2(args.node_count, args.operation_timeout)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir,
                               args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(args.node_count, args.max_pods, args.repeats,
                               args.cl2_report_dir, args.cloud_info,
                               args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()