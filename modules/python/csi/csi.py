import time
import argparse
import os
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from clusterloader2.kubernetes_client import KubernetesClient, client

KUBERNETERS_CLIENT=KubernetesClient()

# TODO: Move to utils folder later to be shared with other modules
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

def calculate_percentiles(disk_number):
    """Calculate percentile values for pods."""
    p50 = disk_number // 2
    p90 = disk_number * 9 // 10
    p99 = disk_number * 99 // 100
    return p50, p90, p99, disk_number

def create_statefulset(namespace, replicas, storage_class):
    """Create a StatefulSet dynamically."""
    statefulset = client.V1StatefulSet(
        api_version="apps/v1",
        kind="StatefulSet",
        metadata=client.V1ObjectMeta(name="statefulset-local"),
        spec=client.V1StatefulSetSpec(
            pod_management_policy="Parallel", # Default is OrderedReady
            replicas=replicas,
            selector=client.V1LabelSelector(match_labels={"app": "nginx"}),
            service_name="statefulset-local",
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "nginx"}),
                spec=client.V1PodSpec(
                    node_selector={"kubernetes.io/os": "linux"},
                    containers=[
                        client.V1Container(
                            name="statefulset-local",
                            image="mcr.microsoft.com/oss/nginx/nginx:1.19.5",
                            command=[
                                "/bin/bash",
                                "-c",
                                "set -euo pipefail; while true; do echo $(date) >> /mnt/local/outfile; sleep 1; done",
                            ],
                            volume_mounts=[
                                client.V1VolumeMount(name="persistent-storage", mount_path="/mnt/local")
                            ],
                        )
                    ],
                ),
            ),
            volume_claim_templates=[
                client.V1PersistentVolumeClaimTemplate(
                    metadata=client.V1ObjectMeta(
                        name="persistent-storage",
                        annotations={"volume.beta.kubernetes.io/storage-class": storage_class},
                    ),
                    spec=client.V1PersistentVolumeClaimSpec(
                        access_modes=["ReadWriteOnce"],
                        resources=client.V1ResourceRequirements(requests={"storage": "1Gi"}),
                    ),
                )
            ],
        ),
    )
    app_client = KUBERNETERS_CLIENT.get_app_client()
    statefulset_obj  = app_client.create_namespaced_stateful_set(namespace, statefulset)
    return statefulset_obj

def log_duration(description, start_time, log_file):
    """Log the time duration of an operation."""
    end_time = datetime.now()
    duration = int((end_time - start_time).total_seconds())
    if ":" in description:
        raise Exception("Description cannot contain a colon ':' character!")
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"{description}: {duration}\n")
    print(f"{description}: {duration}s")

def wait_for_condition(check_function, target, comparison="gte", interval=1):
    """
    Wait for a condition using a given check function.
    The check function should return a list of items.
    The condition is satisfied when the length of the list meets the target.
    """
    while True:
        current_list = check_function()
        current = len(current_list)
        print(f"Current: {current}, Target: {target}")
        if (comparison == "gte" and current >= target) or (comparison == "lte" and current <= target):
            return current
        time.sleep(interval)

def monitor_thresholds(description, monitor_function, thresholds, comparison, start_time, log_file):
    """Monitor thresholds and log their completion."""
    for target, threshold_desc in thresholds:
        wait_for_condition(monitor_function, target, comparison)
        log_duration(f"{description} {threshold_desc}", start_time, log_file)

def execute_attach_detach(disk_number, storage_class, wait_time, result_dir):
    """Execute the attach detach test."""
    print(f"Starting running test with {disk_number} disks and {storage_class} storage class")

    # Create the result directory and log file
    if not os.path.exists(result_dir):
        os.mkdir(result_dir)
    log_file = os.path.join(result_dir, f"attachdetach-{disk_number}.txt")

    namespace = f"test-{time.time_ns()}"

    p50, p90, p99, p100 = calculate_percentiles(disk_number)
    print(f"Percentiles: p50={p50}, p90={p90}, p99={p99}, p100={p100}")
    attach_thresholds = [(p50, "p50"), (p90, "p90"), (p99, "p99"), (p100, "p100")]
    detach_thresholds = [(p100 - p50, "p50"), (p100 - p90, "p90"), (p100 - p99, "p99"), (0, "p100")]

    # Create a namespace
    namespace_obj  = KUBERNETERS_CLIENT.create_namespace(namespace)
    print(f"Created namespace {namespace_obj .metadata.name}")

    # Start the timer
    creation_start_time = datetime.now()

    # Create StatefulSet
    statefulset_obj = create_statefulset(namespace, disk_number, storage_class)
    print(f"Created StatefulSet {statefulset_obj.metadata.name}")

    # Measure PVC creation and attachment
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        futures.append(
            executor.submit(
                monitor_thresholds,
                "PV creation",
                lambda: KUBERNETERS_CLIENT.get_bound_persistent_volume_claims_by_namespace(namespace),
                attach_thresholds,
                "gte",
                creation_start_time,
                log_file
            )
        )
        futures.append(
            executor.submit(
                monitor_thresholds,
                "PV attachment",
                lambda: KUBERNETERS_CLIENT.get_running_pods_by_namespace(namespace),
                attach_thresholds,
                "gte",
                creation_start_time,
                log_file
            )
        )

        # Wait for all threads to complete
        for future in as_completed(futures):
            future.result() # Blocks until the thread finishes execution

    print(f"Measuring creation and attachment of PVCs completed! Waiting for {wait_time} seconds before starting deletion.")
    time.sleep(wait_time)

    # Start the timer
    deletion_start_time = datetime.now()

    # Delete StatefulSet
    KUBERNETERS_CLIENT.app.delete_namespaced_stateful_set(statefulset_obj.metadata.name, namespace)
    KUBERNETERS_CLIENT.delete_persistent_volume_claim_by_namespace(namespace)

    # Measure PVC detachment
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(
            monitor_thresholds,
            "PV detachment",
            lambda: KUBERNETERS_CLIENT.get_attached_volume_attachments(),
            detach_thresholds,
            "lte",
            deletion_start_time,
            log_file
        )
        future.result()

    KUBERNETERS_CLIENT.delete_namespace(namespace)
    print("Measuring detachment of PVCs completed.")

def collect_attach_detach(case_name, node_number, disk_number, storage_class, cloud_info, run_id, run_url, result_dir):
    raw_result_file = os.path.join(result_dir, f"attachdetach-{disk_number}.txt")
    result_file = os.path.join(result_dir, "results.json")
    print(f"Collecting attach detach test results from {raw_result_file} into {result_file}")

    with open(raw_result_file, 'r', encoding='utf-8') as file:
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
    with open(result_file, 'w', encoding='utf-8') as f:
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
    parser_execute.add_argument("wait_time", type=int, help="Wait time before deletion")
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
        execute_attach_detach(args.disk_number, args.storage_class, args.wait_time, args.result_dir)
    elif args.command == "collect":
        collect_attach_detach(args.case_name, args.node_number, args.disk_number, args.storage_class,
                              args.cloud_info, args.run_id, args.run_url, args.result_dir)

if __name__ == "__main__":
    main()
