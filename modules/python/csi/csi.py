import time
import argparse
import os
import requests
import subprocess
import json
from datetime import datetime, timezone
from client.kubernetes_client import KubernetesClient

STORAGE_TEST_SCRIPT_URL="https://raw.githubusercontent.com/Azure/kubernetes-volume-drivers/master/test/attach_detach_test.sh"

def validate_node_count(node_label, node_count, operation_timeout_in_minutes):
    kube_client = KubernetesClient()
    ready_node_count = 0
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    print(f"Validating {node_count} nodes with label {node_label} are ready.")
    while time.time() < timeout:
        ready_nodes = kube_client.get_ready_nodes(label_selector=node_label)
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.")
        if ready_node_count == node_count:
            break
        print(f"Waiting for {node_count} nodes to be ready.")
        time.sleep(10)
    if ready_node_count != node_count:
        raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")

def execute_attach_detach(disk_number, storage_class, result_dir):
    print(f"Starting running test with {disk_number} disks and {storage_class} storage class")
    if not os.path.exists(result_dir):
        os.mkdir(result_dir)

    script_path = os.path.join(result_dir, "attach_detach_test.sh")
    print(f"Downloading storage test script from {STORAGE_TEST_SCRIPT_URL} to {script_path}")

    response = requests.get(STORAGE_TEST_SCRIPT_URL)
    response.raise_for_status()

    with open(script_path, 'wb') as file:
        file.write(response.content)
    
    # Make the script executable
    os.chmod(script_path, 0o755)

    # Run the script with bash
    result_file = os.path.join(result_dir, f"attachdetach-{disk_number}.txt")
    subprocess.run(
        ["bash", script_path, str(disk_number), storage_class, result_file, "--"],
        check=True
    )

def collect_attach_detach(case_name, node_number, disk_number, storage_class, cloud_info, run_id, run_url, result_dir):
    raw_result_file = os.path.join(result_dir, f"attachdetach-{disk_number}.txt")
    result_file = os.path.join(result_dir, "results.json")
    print(f"Collecting attach detach test results from {raw_result_file} into {result_file}")

    with open(raw_result_file, 'r') as file:
        content = file.read()
        print(content)
    
    # Parse metrics from the result file
    metrics = {}
    for line in content.splitlines():
        if ':' in line:  # Only process lines with key-value pairs
            key, value = map(str.strip, line.split(':', 1))
            metrics[key.replace(' ', '_')] = value
    
    print(f"Parsed metrics: {metrics}")
    
    content = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "case_name": case_name,
        "node_number": node_number,
        "disk_number": disk_number,
        "storage_class": storage_class,
        "result": metrics,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url
    }

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w') as f:
        f.write(json.dumps(content))

def main():
    parser = argparse.ArgumentParser(description="CSI Benchmark.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for validate
    parser_validate = subparsers.add_parser("validate", help="Validate node count")
    parser_validate.add_argument("node_label", type=str, help="Node label selector")
    parser_validate.add_argument("node_count", type=int, help="Number of nodes")
    parser_validate.add_argument("operation_timeout", type=int, help="Timeout for the operation in seconds")

    # Sub-command for execute_attach_detach
    parser_execute = subparsers.add_parser("execute", help="Execute attach detach test")
    parser_execute.add_argument("disk_number", type=int, help="Disk number")
    parser_execute.add_argument("storage_class", type=str, help="Storage class")
    parser_execute.add_argument("result_dir", type=str, help="Result directory")

    # Sub-command for collect_attach_detach
    parser_collect = subparsers.add_parser("collect", help="Collect attach detach test results")
    parser_collect.add_argument("case_name", type=str, help="Case name")
    parser_collect.add_argument("node_number", type=int, help="Node number")
    parser_collect.add_argument("disk_number", type=int, help="Disk number")
    parser_collect.add_argument("storage_class", type=str, help="Storage class")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud info")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_dir", type=str, help="Result directory")

    args = parser.parse_args()
    if args.command == "validate":
        validate_node_count(args.node_label, args.node_count, args.operation_timeout)
    elif args.command == "execute":
        execute_attach_detach(args.disk_number, args.storage_class, args.result_dir)
    elif args.command == "collect":
        collect_attach_detach(args.case_name, args.node_number, args.disk_number, args.storage_class, 
                              args.cloud_info, args.run_id, args.run_url, args.result_dir)

if __name__ == "__main__":
    main()
