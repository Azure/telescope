import json
import os
import argparse
import math

from datetime import datetime, timezone
from utils import parse_xml_to_json, run_cl2_command, get_measurement
from kubernetes_client import KubernetesClient, client as k8s_client

DAEMONSETS_PER_NODE_MAP = {
    "aws": 2,
    "aks": 6
}
MEMORY_SCALE_FACTOR = 0.95 # 95% of the total allocatable memory to account for error margin

def _get_daemonsets_pods_allocated_resources(client, node_name):
    pods = client.get_pods_by_namespace("kube-system", field_selector=f"spec.nodeName={node_name}")
    cpu_request = 0
    memory_request = 0
    for pod in pods:
        for container in pod.spec.containers:
            print(f"Pod {pod.metadata.name} has container {container.name} with resources {container.resources.requests}")
            cpu_request += int(container.resources.requests.get("cpu", "0m").replace("m", ""))
            memory_request += int(container.resources.requests.get("memory", "0Mi").replace("Mi", ""))
    return cpu_request, memory_request * 1024

def convert_to_timedelta(time_str):
    if time_str.endswith("m"):  # Check if the string ends with 'm' for minutes
        minutes = int(time_str[:-1])  # Extract the numeric part and convert to integer
        return timedelta(minutes=minutes)
    else:
        raise ValueError(f"Unsupported time format: {time_str}")

def override_config_clusterloader2( node_label, node_count, max_pods, operation_timeout, load_type, provider, override_file):
    client = KubernetesClient(os.path.expanduser("~/.kube/config"))
    node_selector = f"{node_label}=true"
    nodes = client.get_nodes(label_selector=node_selector)
    if len(nodes) == 0:
        raise Exception(f"Invalid node selector: {node_selector}")
    
    node = nodes[0]
    allocatable_cpu = node.status.allocatable["cpu"]
    allocatable_memory = node.status.allocatable["memory"]
    print(f"Node {node.metadata.name} has allocatable cpu of {allocatable_cpu} and allocatable memory of {allocatable_memory}")

    cpu_value = int(allocatable_cpu.replace("m", ""))
    # Bottlerocket OS SKU on EKS has allocatable_memory property in Mi. AKS and Amazon Linux (default SKUs)
    # user Ki. Handling the Mi case here and converting Mi to Ki, if needed.
    if "Mi" in allocatable_memory:
        memory_value = int(allocatable_memory.replace("Mi", "")) * 1024
    elif "Ki" in allocatable_memory:
        memory_value = int(allocatable_memory.replace("Ki", ""))
    else:
        raise Exception(f"Unexpected format of allocatable memory node property: {allocatable_memory}")
    print(f"Node {node.metadata.name} has cpu value of {cpu_value} and memory value of {memory_value}")

    allocated_cpu, allocated_memory = _get_daemonsets_pods_allocated_resources(client, node.metadata.name)
    print(f"Node {node.metadata.name} has allocated cpu of {allocated_cpu} milli and allocated memory of {allocated_memory} Ki")

    cpu_value -= allocated_cpu
    memory_value -= allocated_memory

    # Calculate request cpu and memory for each pod
    pod_count = max_pods - DAEMONSETS_PER_NODE_MAP[provider]

    cpu_request = cpu_value // pod_count
    memory_request_ki = int(memory_value * MEMORY_SCALE_FACTOR // pod_count)
    # greedy behave workload consume memory more than requested to trigger OOM
    memory_consume_mi= int(memory_request_ki * 1.3 // 1024)
    # set workoad to last 90% of the operation timeout, specified in minutes
    operation_timeout_ts = convert_to_timedelta(operation_timeout)
    resouce_stress_duration = int(operation_timeout_ts.total_seconds() * 0.9)
    print(f"CPU request for each pod: {cpu_request}m, memory request for each pod: {memory_request_ki} Ki, pod will try to consume memory: {memory_consume_mi} Mi, total pod per node: {pod_count} \n will run stress test in {resouce_stress_duration} seconds")

    with open(override_file, 'w', encoding='utf-8') as file:
        file.write(f"CL2_DEPLOYMENT_SIZE: {pod_count}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write(f"CL2_NODE_COUNT: {node_count}\n")
        file.write(f"CL2_NODE_LABEL: {node_label}\n")
        file.write(f"CL2_LOAD_TYPE: {load_type}\n")

        file.write(f"CL2_RESOURCE_CONSUME_MEMORY_REQUEST_KI: {memory_request_ki}Ki\n")
        file.write(f"CL2_RESOURCE_CONSUME_MEMORY_CONSUME_MI: {memory_consume_mi}Mi\n")
        file.write(f"CL2_RESOURCE_CONSUME_DURATION_SEC: {resouce_stress_duration}\n")
        file.write(f"CL2_RESOURCE_CONSUME_CPU: {cpu_request}\n")

        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")
        file.write(f"CL2_PROVIDER: {provider}\n")

    file.close()

def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, kubeconfig, provider):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, overrides=True, enable_prometheus=True,
                    tear_down_prometheus=False)

def verify_measurement(node_label):
    client = KubernetesClient(os.path.expanduser("~/.kube/config"))
    node_selector = f"{node_label}=true"
    nodes = client.get_nodes(label_selector=node_selector)
    user_pool = [node.metadata.name for node in nodes]
    print(f"User pool: {user_pool}")
    # Create an API client
    api_client = k8s_client.ApiClient()
    for node_name in user_pool:
        url = f"/api/v1/nodes/{node_name}/proxy/metrics"

        try:
            response = api_client.call_api(
                resource_path=url,
                method="GET",
                auth_settings=['BearerToken'],
                response_type="str",
                _preload_content=True
            )

            metrics = response[0]  # The first item contains the response data
            filtered_metrics = "\n".join(
                line for line in metrics.splitlines() if line.startswith("kubelet_pod_start") or line.startswith("kubelet_runtime_operations")
            )
            print("##[section]Metrics for node:", node_name)
            print(filtered_metrics)

        except k8s_client.ApiException as e:
            print(f"Error fetching metrics: {e}")

def collect_clusterloader2(
    node_label,
    node_count,
    max_pods,
    load_type,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file
):

    verify_measurement(node_label)
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
        "churn_rate": 1,
        "load_type": load_type,
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
        with open(file_path, 'r', encoding='utf-8') as file:
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(file.read())

            if measurement == "ResourceUsageSummary":
                for percentile, items in data.items():
                    template["measurement"] = measurement
                    template["group"] = group_name
                    template["percentile"] = percentile
                    for item in items:
                        template["data"] = item
                        content += json.dumps(template) + "\n"
            elif "dataItems" in data:
                items = data["dataItems"]
                if not items:
                    print(f"No data items found in {file_path}")
                    print(f"Data:\n{data}")
                    continue
                for item in items:
                    template["measurement"] = measurement
                    template["group"] = group_name
                    template["percentile"] = "dataItems"
                    template["data"] = item
                    content += json.dumps(template) + "\n"

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    parser = argparse.ArgumentParser(description="CRI Kubernetes Eviction threshold eval.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for override_config_clusterloader2
    parser_override = subparsers.add_parser("override", help="Override CL2 config file")
    parser_override.add_argument("node_label", type=str, help="Node label selector")
    parser_override.add_argument("node_count", type=int, help="Number of nodes")
    parser_override.add_argument("max_pods", type=int, help="Number of maximum pods per node")
    parser_override.add_argument("operation_timeout", type=str, default="5m", help="Operation timeout")
    parser_override.add_argument("load_type", type=str, choices=["memory", "cpu"],
                                 default="memory", help="Type of load to generate")
    parser_override.add_argument("provider", type=str, help="Cloud provider name")
    parser_override.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute resource consume operation")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect resource consume data")
    parser_collect.add_argument("node_label", type=str, help="Node label selector")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("max_pods", type=int, help="Number of maximum pods per node")
    parser_collect.add_argument("load_type", type=str, choices=["memory", "cpu"],
                                 default="memory", help="Type of load to generate")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")


    args = parser.parse_args()

    if args.command == "override":
        override_config_clusterloader2(args.node_label, args.node_count, args.max_pods, args.operation_timeout, args.load_type, args.provider, args.cl2_override_file)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(args.node_label, args.node_count, args.max_pods, args.load_type, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()
