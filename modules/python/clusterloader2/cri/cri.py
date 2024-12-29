import json
import os
import argparse
import re

from datetime import datetime, timezone
from utils import parse_xml_to_json, run_cl2_command, get_measurement
from kubernetes_client import KubernetesClient

DAEMONSETS_PER_NODE_MAP = {
    "aws": 3,
    "aks": 6
}

def override_config_clusterloader2(node_count, max_pods, repeats, operation_timeout, provider, override_file):
    client = KubernetesClient(os.path.expanduser("~/.kube/config"))
    nodes = client.get_nodes(label_selector="cri-resource-consume=true")
    if len(nodes) == 0:
        raise Exception("No nodes found with the label cri-resource-consume=true")

    node = nodes[0]
    allocatable_cpu = node.status.allocatable["cpu"]
    allocatable_memory = node.status.allocatable["memory"]
    print(f"Node {node.metadata.name} has allocatable cpu of {allocatable_cpu} and allocatable memory of {allocatable_memory}")

    cpu_value = int(allocatable_cpu.replace("m", ""))
    memory_value = int(allocatable_memory.replace("Ki", ""))
    print(f"Node {node.metadata.name} has cpu value of {cpu_value} and memory value of {memory_value}")

    # Calculate request cpu and memory for each pod
    pod_count = max_pods - DAEMONSETS_PER_NODE_MAP[provider]
    replica = pod_count * node_count
    cpu_request = cpu_value // pod_count - 20
    memory_request = int(memory_value * 1.024 // pod_count - 20)
    print(f"CPU request for each pod: {cpu_request}m, memory request for each pod: {memory_request}K, total replica: {replica}")

    with open(override_file, 'w') as file:
        file.write(f"CL2_DEPLOYMENT_SIZE: {replica}\n")
        file.write(f"CL2_RESOURCE_CONSUME_MEMORY: {memory_request}\n")
        file.write(f"CL2_RESOURCE_CONSUME_CPU: {cpu_request}\n")
        file.write(f"CL2_REPEATS: {repeats}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write(f"CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")

    file.close()

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

    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "node_count": node_count,
        "max_pods": max_pods,
        "churn_rate": repeats,
        "status": status,
        "group": None,
        "measurement": None,
        "percentile": None,
        "data": None,
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

            for percentile, items in data.items():
                template["measurement"] = measurement
                template["group"] = group_name
                template["percentile"] = percentile
                for item in items:
                    template["data"] = item
                    content += json.dumps(template) + "\n"

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w') as f:
        f.write(content)

def main():
    parser = argparse.ArgumentParser(description="CRI Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for override_config_clusterloader2
    parser_override = subparsers.add_parser("override", help="Override CL2 config file")
    parser_override.add_argument("node_count", type=int, help="Number of nodes")
    parser_override.add_argument("max_pods", type=int, help="Number of maximum pods per node")
    parser_override.add_argument("repeats", type=int, help="Number of times to repeat the resource consumer deployment")
    parser_override.add_argument("operation_timeout", type=str, default="2m", help="Operation timeout")
    parser_override.add_argument("provider", type=str, help="Cloud provider name")
    parser_override.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

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
    parser_collect.add_argument("max_pods", type=int, help="Number of maximum pods per node")
    parser_collect.add_argument("repeats", type=int, help="Number of times to repeat the resource consumer deployment")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    if args.command == "override":
        override_config_clusterloader2(args.node_count, args.max_pods, args.repeats, args.operation_timeout, args.provider, args.cl2_override_file)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(args.node_count, args.max_pods, args.repeats, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()