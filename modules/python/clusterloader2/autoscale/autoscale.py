import json
import os
import argparse
import re
import subprocess
import time

from datetime import datetime, timezone
from utils import parse_xml_to_json, run_cl2_command
from kubernetes_client import KubernetesClient

def warmup_deployment_for_karpeneter():
    print("WarmUp Deployment Started")
    deployment_file = "autoscale/config/warmup_deployment.yaml"
    subprocess.run(["kubectl", "apply", "-f", deployment_file], check=True)

def cleanup_warmup_deployment_for_karpeneter():
    deployment_file = "autoscale/config/warmup_deployment.yaml"
    subprocess.run(["kubectl", "delete", "-f", deployment_file], check=True)
    print("WarmUp Deployment Deleted")
    try:
        subprocess.run(["kubectl", "delete", "nodeclaims", "--all"], check=True)
    except Exception as e:
        print(f"Error while deleting node: {e}")

def _get_daemonsets_pods_allocated_resources(client, node_name):
    pods = client.get_pods_by_namespace("kube-system", field_selector=f"spec.nodeName={node_name}")
    cpu_request = 0
    for pod in pods:
        for container in pod.spec.containers:
            print(f"Pod {pod.metadata.name} has container {container.name} with resources {container.resources.requests}")
            if container.resources.requests is not None:
                cpu_request += int(container.resources.requests.get("cpu", "0m").replace("m", ""))
    return cpu_request

def calculate_cpu_request_for_clusterloader2(node_label_selector, node_count, pod_count, warmup_deployment):
    client = KubernetesClient(os.path.expanduser("~/.kube/config"))
    timeout = 600  # 10 minutes
    interval = 30  # 30 seconds
    elapsed = 0

    try:
        while elapsed < timeout:
            nodes = client.get_ready_nodes(label_selector=node_label_selector)
            if len(nodes) > 0:
                break
            print(f"No nodes found with the label {node_label_selector}. Retrying in {interval} seconds...")
            time.sleep(interval)
            elapsed += interval
    except Exception as e:
        print(f"Error while getting nodes: {e}")
        print(f"Retrying in {interval} seconds...")
        time.sleep(interval)

    if len(nodes) == 0:
        raise Exception(f"No nodes found with the label {node_label_selector} after {timeout} seconds")

    node = nodes[0]
    allocatable_cpu = node.status.allocatable["cpu"]
    print(f"Node {node.metadata.name} has allocatable cpu of {allocatable_cpu}")

    cpu_value = int(allocatable_cpu.replace("m", ""))
    allocated_cpu = _get_daemonsets_pods_allocated_resources(client, node.metadata.name)
    print(f"Node {node.metadata.name} has allocated cpu of {allocated_cpu}")

    cpu_value -= allocated_cpu
    # Remove warmup deployment cpu request from the total cpu value
    if warmup_deployment in ["true", "True"]:
        cpu_value -= 100
        cleanup_warmup_deployment_for_karpeneter()

    # Calculate the cpu request for each pod
    pods_per_node = pod_count // node_count
    cpu_request = cpu_value // pods_per_node
    return cpu_request

def override_config_clusterloader2(cpu_per_node, node_count, pod_count, scale_up_timeout, scale_down_timeout, loop_count, node_label_selector, node_selector, override_file, warmup_deployment):
    print(f"CPU per node: {cpu_per_node}")
    desired_node_count = 1
    if warmup_deployment in ["true", "True"]:
        warmup_deployment_for_karpeneter()
        desired_node_count = 0

    cpu_request = calculate_cpu_request_for_clusterloader2(node_label_selector, node_count, pod_count, warmup_deployment)

    print(f"Total number of nodes: {node_count}, total number of pods: {pod_count}")
    print(f"CPU request for each pod: {cpu_request}m")

    # assuming the number of surge nodes is no more than 10
    with open(override_file, 'w', encoding='utf-8') as file:
        file.write(f"CL2_DEPLOYMENT_CPU: {cpu_request}m\n")
        file.write(f"CL2_MIN_NODE_COUNT: {node_count}\n")
        file.write(f"CL2_MAX_NODE_COUNT: {node_count + 10}\n")
        file.write(f"CL2_DESIRED_NODE_COUNT: {desired_node_count}\n")
        file.write(f"CL2_DEPLOYMENT_SIZE: {pod_count}\n")
        file.write(f"CL2_SCALE_UP_TIMEOUT: {scale_up_timeout}\n")
        file.write(f"CL2_SCALE_DOWN_TIMEOUT: {scale_down_timeout}\n")
        file.write(f"CL2_LOOP_COUNT: {loop_count}\n")
        file.write(f"CL2_NODE_LABEL_SELECTOR: {node_label_selector}\n")
        file.write(f"CL2_NODE_SELECTOR: \"{node_selector}\"\n")

    file.close()

def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, kubeconfig, provider):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, overrides=True)

def collect_clusterloader2(
    cpu_per_node,
    capacity_type,
    node_count,
    pod_count,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file
):
    index_pattern = re.compile(r'(\d+)$')

    raw_data = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(raw_data)
    testsuites = json_data["testsuites"]
    summary = {}
    metric_mappings = {
        "WaitForRunningPodsUp": ("up", "wait_for_pods_seconds"),
        "WaitForNodesUpPerc50": ("up", "wait_for_50Perc_nodes_seconds"),
        "WaitForNodesUpPerc70": ("up", "wait_for_70Perc_nodes_seconds"),
        "WaitForNodesUpPerc90": ("up", "wait_for_90Perc_nodes_seconds"),
        "WaitForNodesUpPerc99": ("up", "wait_for_99Perc_nodes_seconds"),
        "WaitForNodesUpPerc100": ("up", "wait_for_nodes_seconds"),
        "WaitForRunningPodsDown": ("down", "wait_for_pods_seconds"),
        "WaitForNodesDownPerc50": ("down", "wait_for_50Perc_nodes_seconds"),
        "WaitForNodesDownPerc70": ("down", "wait_for_70Perc_nodes_seconds"),
        "WaitForNodesDownPerc90": ("down", "wait_for_90Perc_nodes_seconds"),
        "WaitForNodesDownPerc99": ("down", "wait_for_99Perc_nodes_seconds"),
        "WaitForNodesDownPerc100": ("down", "wait_for_nodes_seconds"),
    }

    if testsuites:
        # Process each loop
        for testcase in testsuites[0]["testcases"]:
            name = testcase["name"]
            index = -1
            match = index_pattern.search(name)
            if match:
                index = match.group()
                if index not in summary:
                    summary[index] = {
                        "up": { "failures": 0 },
                        "down": { "failures": 0 }
                    }
            else:
                continue

            failure = testcase["failure"]
            for test_key, (category, summary_key) in metric_mappings.items():
                if test_key in name:
                    summary[index][category][summary_key] = -1 if failure else testcase["time"]
                    summary[index][category]["failures"] += 1 if failure else 0
                    break  # Exit loop once matched

        content = ""
        for index, inner_dict in summary.items():
            for key, value in inner_dict.items():
                data = {
                    "wait_for_nodes_seconds": value["wait_for_nodes_seconds"],
                    "wait_for_50Perc_nodes_seconds": value["wait_for_50Perc_nodes_seconds"],
                    "wait_for_70Perc_nodes_seconds": value["wait_for_70Perc_nodes_seconds"],
                    "wait_for_90Perc_nodes_seconds": value["wait_for_90Perc_nodes_seconds"],
                    "wait_for_99Perc_nodes_seconds": value["wait_for_99Perc_nodes_seconds"],
                    "wait_for_pods_seconds": value["wait_for_pods_seconds"],
                    "autoscale_result": "success" if value["failures"] == 0 else "failure"
                }
                # TODO: Expose optional parameter to include test details
                result = {
                    "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "autoscale_type": key,
                    "cpu_per_node": cpu_per_node,
                    "capacity_type": capacity_type,
                    "node_count": node_count,
                    "pod_count": pod_count,
                    "data": data,
                    # "raw_data": raw_data,
                    "cloud_info": cloud_info,
                    "run_id": run_id,
                    "run_url": run_url
                }
                content += json.dumps(result) + "\n"

    else:
        raise Exception(f"No testsuites found in the report! Raw data: {raw_data}")

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    parser = argparse.ArgumentParser(description="Autoscale Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for override_config_clusterloader2
    parser_override = subparsers.add_parser("override", help="Override CL2 config file")
    parser_override.add_argument("cpu_per_node", type=int, help="Name of cpu cores per node")
    parser_override.add_argument("node_count", type=int, help="Number of nodes")
    parser_override.add_argument("pod_count", type=int, help="Number of pods")
    parser_override.add_argument("scale_up_timeout", type=str, help="Timeout before failing the scale up test")
    parser_override.add_argument("scale_down_timeout", type=str, help="Timeout before failing the scale down test")
    parser_override.add_argument("loop_count", type=int, help="Number of times to repeat the test")
    parser_override.add_argument("node_label_selector", type=str, help="Node label selector")
    parser_override.add_argument("node_selector", type=str, help="Node selector for the test pods")
    parser_override.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")
    parser_override.add_argument("warmup_deployment", type=str, help="Warmup deployment to get the cpu request")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("cpu_per_node", type=int, help="Name of cpu cores per node")
    parser_collect.add_argument("capacity_type", type=str, help="Capacity type", choices=["on-demand", "spot"], default="on-demand")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("pod_count", type=int, help="Number of pods")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    if args.command == "override":
        override_config_clusterloader2(args.cpu_per_node, args.node_count, args.pod_count, args.scale_up_timeout, args.scale_down_timeout, args.loop_count, args.node_label_selector, args.node_selector, args.cl2_override_file, args.warmup_deployment)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(args.cpu_per_node, args.capacity_type, args.node_count, args.pod_count, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()
