import subprocess
import time
import json
import os
import argparse

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

def run_command(command):
    """Utility function to run a shell command and capture the output."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout.strip()

def check_count(desired_count, command, resource_type, timeout, start_time):
    """Utility function to check the desired count of resources."""
    count = 0
    while time.time() - start_time < timeout:
        count = int(run_command(command))
        if count == desired_count:
            return True, time.time() - start_time
        print(f"Current {resource_type} count: {count}")
        time.sleep(5)

    return False, -1

def calculate_request_resource(cpu_per_node, node_count, pod_count, input_file, output_file):
    # assuming 90% of the CPU cores can be used by test pods
    cpu_request = (cpu_per_node * 1000 * 0.9) * node_count // pod_count

    print(f"Total number of nodes: {node_count}, total number of pods: {pod_count}")
    print(f"CPU request for each pod: {cpu_request}m")

    with open(input_file, 'r') as file:
        content = file.read()

    content = content.replace("##CPUperJob##", f"{cpu_request}m")
    content = content.replace("##Replicas##", str(pod_count))

    with open(output_file, 'w') as file:
        file.write(content)

def run_jobs(yaml_file, pod_count, node_count, result_file):
    timeout = 1800
    start_time = time.time()
    print(f"Start time: {start_time}")
    run_command(f"kubectl apply -f {yaml_file}")

    pod_count_status = False
    node_count_status = False
    wait_for_nodes_seconds = -1
    wait_for_pod_seconds = -1

    try:
        with ThreadPoolExecutor() as executor:
            # expose node selector and pod selector as arguments
            node_future = executor.submit(check_count, node_count, "kubectl get nodes --selector=karpenter.sh/nodepool=default --ignore-not-found | grep -c Ready", "node", timeout, start_time)
            pod_future = executor.submit(check_count, pod_count, "kubectl get pods --selector=app=inflate --ignore-not-found | grep -c Running", "pod", timeout, start_time)

            node_count_status, wait_for_nodes_seconds = node_future.result()
            pod_count_status, wait_for_pod_seconds = pod_future.result()

        autoscale_result = "success" if node_count_status and pod_count_status else "failure"

        data = {
            "wait_for_nodes_seconds": wait_for_nodes_seconds,
            "wait_for_pod_seconds": wait_for_pod_seconds,
            "autoscale_result": autoscale_result
        }

        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        with open(result_file, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error occurred while running jobs: {e}")
        run_command(f"kubectl delete -f {yaml_file}")

def execute_scale_up(node_name, node_count, pod_count, deployment_template, deployment_file, result_file):
    calculate_request_resource(node_name, node_count, pod_count, deployment_template, deployment_file)
    run_jobs(deployment_file, pod_count, node_count, result_file)

def collect_scale_up(cpu_per_node, node_count, pod_count, autoscale_type, data_file, cloud_info, run_id, run_url, result_file):
    with open(data_file, 'r') as f:
        data = f.read()

    result = {
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "autoscale_type": autoscale_type,
        "cpu_per_node": cpu_per_node,
        "node_count": node_count,
        "pod_count": pod_count,
        "data": data,
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

    # Sub-command for execute_scale_up
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cpu_per_node", type=int, help="Name of cpu cores per node")
    parser_execute.add_argument("node_count", type=int, help="Number of nodes")
    parser_execute.add_argument("pod_count", type=int, help="Number of pods")
    parser_execute.add_argument("deployment_template", type=str, help="Path to the deployment template")
    parser_execute.add_argument("result_file", type=str, help="Path to the result file")

    # Sub-command for collect_scale_up
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("cpu_per_node", type=int, help="Name of cpu cores per node")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("pod_count", type=int, help="Number of pods")
    parser_collect.add_argument("autoscale_type", type=str, help="Autoscale type")
    parser_collect.add_argument("data_file", type=str, help="Path to the data file")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    if args.command == "execute":
        execute_scale_up(args.cpu_per_node, args.node_count, args.pod_count, args.deployment_template, "deployment.yml", args.result_file)
    elif args.command == "collect":
        collect_scale_up(args.cpu_per_node, args.node_count, args.pod_count, args.autoscale_type, args.data_file, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()