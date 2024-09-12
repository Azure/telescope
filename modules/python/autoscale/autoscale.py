import subprocess
import time
import re
import json
import sys
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

def calculate_request_resource(node_name, node_count, pod_count, input_file, output_file):
    allocatable_cpu = run_command(f"kubectl get node {node_name} -o jsonpath='{{.status.allocatable.cpu}}'")
    allocatable_memory = run_command(f"kubectl get node {node_name} -o jsonpath='{{.status.allocatable.memory}}'")

    print(f"Node {node_name} has allocatable cpu of {allocatable_cpu} and allocatable memory of {allocatable_memory}")

    # Separate CPU value and unit
    cpu_match = re.match(r"([0-9]+)([a-z]*)", allocatable_cpu)
    if cpu_match:
        cpu_value = int(cpu_match.group(1))
        cpu_unit = cpu_match.group(2)

    # Separate memory value and unit
    memory_match = re.match(r"([0-9]+)([a-zA-Z]*)", allocatable_memory)
    if memory_match:
        memory_value = int(memory_match.group(1))
        memory_unit = memory_match.group(2)

    # Calculate request cpu and memory for each pod
    cpu_request = (cpu_value - 400) * node_count // pod_count
    memory_request = memory_value * node_count // pod_count

    print(f"Total number of nodes: {node_count}, total number of pods: {pod_count}")
    print(f"CPU request for each pod: {cpu_request}{cpu_unit}")
    print(f"Memory request for each pod: {memory_request}{memory_unit}")

    with open(input_file, 'r') as file:
        content = file.read()

    content = content.replace("##CPUperJob##", f"{cpu_request}{cpu_unit}")
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
            node_future = executor.submit(check_count, node_count, "kubectl get nodes | grep -c default", "node", timeout, start_time)
            pod_future = executor.submit(check_count, pod_count, "kubectl get pods --selector=app=scale-deployment --ignore-not-found | grep -c Running", "pod", timeout, start_time)

            node_count_status, wait_for_nodes_seconds = node_future.result()
            pod_count_status, wait_for_pod_seconds = pod_future.result()

        scale_status = "success" if node_count_status and pod_count_status else "failure"

        data = {
            "start_time": start_time,
            "node_latency": wait_for_nodes_seconds,
            "pod_latency": wait_for_pod_seconds,
            "scale_status": scale_status
        }

        with open(result_file, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error occurred while running jobs: {e}")
        run_command(f"kubectl delete -f {yaml_file}")

def execute_scale_up(node_name, node_count, pod_count, deployment_template, deployment_file, result_file):
    calculate_request_resource(node_name, node_count, pod_count, deployment_template, deployment_file)
    run_jobs(deployment_file, pod_count, node_count, result_file)

def collect_scale_up(data_file, cloud_info, scale_feature, pod_count, node_count, run_id, run_url, result_file):
    with open(data_file, 'r') as f:
        data = f.read()

    result = {
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "scale_feature": scale_feature,
        "pod_count": pod_count,
        "node_count": node_count,
        "data": data,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url
    }

    with open(result_file, 'w') as f:
        json.dump(result, f)

def main():
    node_name = sys.argv[1]
    node_count = int(sys.argv[2])
    pod_count = int(sys.argv[3])
    deployment_template = sys.argv[4]
    data_file = sys.argv[5]
    cloud_info = sys.argv[6]
    scale_feature = sys.argv[7]
    run_id = sys.argv[8]
    run_url = sys.argv[9]
    result_file = sys.argv[10]
    deployment_file = "deployment.yaml"

    # execute_scale_up(node_name, node_count, pod_count, deployment_template, deployment_file, data_file)
    collect_scale_up(data_file, cloud_info, scale_feature, pod_count, node_count, run_id, run_url, result_file)

if __name__ == "__main__":
    main()