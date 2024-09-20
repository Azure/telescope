import json
import os
import argparse

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from utils import parse_xml_to_json, run_cl2_command

def calculate_request_resource(cpu_per_node, node_count, pod_count, override_file):
    # assuming 90% of the CPU cores can be used by test pods
    cpu_request = (cpu_per_node * 1000 * 0.9) * node_count // pod_count

    print(f"Total number of nodes: {node_count}, total number of pods: {pod_count}")
    print(f"CPU request for each pod: {cpu_request}m")

    # assuming the number of surge nodes is no more than 10
    with open(override_file, 'w') as file:
        file.write(f"CL2_DEPLOYMENT_CPU: {cpu_request}m\n")
        file.write(f"CL2_MIN_NODE_COUNT: {node_count}\n")
        file.write(f"CL2_MAX_NODE_COUNT: {node_count + 10}\n")
        file.write(f"CL2_DEPLOYMENT_SIZE: {pod_count}\n")

    file.close()

def execute_clusterloader2(cpu_per_node, node_count, pod_count, cl2_image, cl2_override_file, cl2_config_dir, cl2_report_dir, kubeconfig, provider):
    calculate_request_resource(cpu_per_node, node_count, pod_count, cl2_override_file)
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, overrides=True)

def collect_clusterloader2(cpu_per_node, node_count, pod_count, autoscale_type, cl2_report_dir, cloud_info, run_id, run_url, result_file):
    raw_data = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"))
    json_data = json.loads(raw_data)
    testsuites = json_data["testsuites"]
    wait_for_nodes_seconds = -1
    wait_for_pods_seconds = -1
    if testsuites:
        if testsuites[0]["failures"] == 0:
            autoscale_result = "success"
            wait_for_pods_seconds = testsuites[0]["testcases"][2]["time"]
            wait_for_nodes_seconds = testsuites[0]["testcases"][3]["time"]
        else:
            autoscale_result = "failure"
        
        data = {
            "wait_for_nodes_seconds": wait_for_nodes_seconds,
            "wait_for_pods_seconds": wait_for_pods_seconds,
            "autoscale_result": autoscale_result
        }
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {raw_data}")

    result = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "autoscale_type": autoscale_type,
        "cpu_per_node": cpu_per_node,
        "node_count": node_count,
        "pod_count": pod_count,
        "data": data,
        "raw_data": raw_data,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url
    }

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w') as f:
        json.dump(result, f)

def main():
    parser = argparse.ArgumentParser(description="Autoscale Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cpu_per_node", type=int, help="Name of cpu cores per node")
    parser_execute.add_argument("node_count", type=int, help="Number of nodes")
    parser_execute.add_argument("pod_count", type=int, help="Number of pods")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("cpu_per_node", type=int, help="Name of cpu cores per node")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("pod_count", type=int, help="Number of pods")
    parser_collect.add_argument("autoscale_type", type=str, help="Autoscale type")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    if args.command == "execute":
        execute_clusterloader2(args.cpu_per_node, args.node_count, args.pod_count, args.cl2_override_file, args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(args.cpu_per_node, args.node_count, args.pod_count, args.autoscale_type, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()