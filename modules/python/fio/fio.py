import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
import yaml
from clients.kubernetes_client import KubernetesClient
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

KUBERNETES_CLIENT = KubernetesClient()

def validate(node_count, operation_timeout_in_minutes=10):
    KUBERNETES_CLIENT.wait_for_nodes_ready(node_count, operation_timeout_in_minutes)

def calculate_pod_startup_latency(pod):
    """
    Calculate the pod startup latency by measuring the time difference between
    pod creation and when the fio container actually started running.

    Args:
        pod: Kubernetes pod object

    Returns:
        float: Pod startup latency in seconds, or None if container start time not found
    """
    try:
        creation_timestamp = pod.metadata.creation_timestamp
        if not creation_timestamp:
            logger.warning(f"Pod {pod.metadata.name} has no creation timestamp")
            return None

        logger.info(f"pod container statuses {pod.status.container_statuses}")
        # Find the fio container's startedAt timestamp
        container_started_time = None
        if pod.status.container_statuses:
            for container_status in pod.status.container_statuses:
                if container_status.name == "fio" and container_status.state and container_status.state.terminated:
                    container_started_time = container_status.state.terminated.started_at
                    break

        if not container_started_time:
            logger.warning(f"Pod {pod.metadata.name} does not have fio container startedAt timestamp")
            return None

        # Calculate the difference in seconds
        startup_latency = (container_started_time - creation_timestamp).total_seconds()
        logger.info(f"Pod {pod.metadata.name} startup latency: {startup_latency:.3f} seconds")

        return startup_latency

    except Exception as e:
        logger.error(f"Error calculating pod startup latency for pod {pod.metadata.name}: {str(e)}")
        return None

def execute(block_size, iodepth, method, runtime, numjobs, file_size, storage_name, kustomize_dir, result_dir):
    fio_nodes = KUBERNETES_CLIENT.get_ready_nodes(label_selector='fio-dedicated=true')
    if not fio_nodes:
        raise RuntimeError("No ready and schedulable nodes found with label 'fio-dedicated=true'.")

    logger.info(f"Found {len(fio_nodes)} fio-dedicated nodes. Creating one job per node.")

    fio_command = [
        "fio",
        "--name=benchtest",
        "--direct=1",
        f"--size={file_size}",
        "--filename=/mnt/data/benchtest",
        f"--rw={method}",
        f"--bs={block_size}",
        f"--iodepth={iodepth}",
        f"--runtime={runtime}",
        f"--numjobs={numjobs}",
        "--unlink=1",
        "--ioengine=io_uring",
        "--time_based",
        "--output-format=json",
        "--group_reporting"
    ]

    os.makedirs(result_dir, exist_ok=True)
    job_node_mapping = []  # Store job names and their corresponding nodes

    for i, node in enumerate(fio_nodes):
        node_name = node.metadata.name
        job_name = f"fio-{i}"
        job_node_mapping.append((job_name, node_name))

        logger.info(f"Creating job {job_name} for node {node_name}")

        patch = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": "$name"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"name": "fio", "command": fio_command}],
                        "nodeSelector": {
                            "kubernetes.io/hostname": node_name
                        },
                        "restartPolicy": "Never"
                    }
                }
            },
        }

        patch_file = f"{kustomize_dir}/base/command.yaml"
        with open(patch_file, "w", encoding="utf-8") as f:
            yaml.dump(patch, f)

        create_command = f"kustomize build {kustomize_dir}/overlays/{storage_name}/deployment | name={job_name} envsubst | kubectl apply -f -"
        logger.info(f"Running command: {create_command}")
        subprocess.run(create_command, shell=True, check=True, capture_output=True)

    metadata_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}-metadata.json"
    result_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}.json"

    for job_name, node_name in job_node_mapping:
        logger.info(f"Waiting for job {job_name} on node {node_name} to complete")

        # Wait for this job to complete
        KUBERNETES_CLIENT.wait_for_job_completed(
            job_name=job_name,
            timeout=runtime+600,
        )

        # Get pods for this job
        pods = KUBERNETES_CLIENT.get_pods_by_namespace(
            namespace="default", label_selector=f"job-name={job_name}"
        )
        if not pods:
            logger.error(f"No pods found for job {job_name} on node {node_name}")
            continue

        if len(pods) != 1:
            logger.error(f"Expected exactly one pod for job {job_name}, found {len(pods)}")
            continue

        pod = pods[0]
        pod_name = pod.metadata.name

        # Get pod logs and process results
        logs = KUBERNETES_CLIENT.get_pod_logs(pod_name)
        parsed_logs = json.loads(logs)
        logger.info(f"Checking logs for pod {pod_name} on node {node_name}:\n{parsed_logs}")

        with open(result_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(parsed_logs) + "\n")
            logger.info(f"Results saved to {result_path}")

        pod_startup_latency = calculate_pod_startup_latency(pod)
        logger.info(f"Calculating startup latency for pod {pod_name} on node {node_name}:\n{pod_startup_latency}")

        metadata = {
            "block_size": block_size,
            "iodepth": iodepth,
            "method": method,
            "file_size": file_size,
            "runtime": runtime,
            "numjobs": numjobs,
            "storage_name": storage_name,
            "pod_startup_latency_seconds": pod_startup_latency,
            "node_name": node_name,
            "job_name": job_name,
            "pod_name": pod_name,
        }

        with open(metadata_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(metadata) + "\n")
            logger.info(f"Metadata saved to {metadata_path}")

        delete_command = f"kustomize build {kustomize_dir}/overlays/{storage_name}/deployment | name={job_name} envsubst | kubectl delete -f -"
        logger.info(f"Running command: {delete_command}")
        subprocess.run(delete_command, shell=True, check=True, capture_output=True)

def collect(vm_size, block_size, iodepth, method, numjobs, file_size, result_dir, run_url, cloud_info):
    raw_result_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}.json"
    metadata_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}-metadata.json"

    logger.info(f"Results read from {raw_result_path}")
    with open(raw_result_path, "r", encoding="utf-8") as f:
        raw_result_lines = f.readlines()

    logger.info(f"Metadata read from {metadata_path}")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata_lines = f.readlines()

    # Ensure both files have the same number of lines
    if len(raw_result_lines) != len(metadata_lines):
        logger.warning(f"Mismatch in number of lines: raw_result has {len(raw_result_lines)}, metadata has {len(metadata_lines)}")

    result_path = f"{result_dir}/results.json"

    # Process each pair of lines
    for i, (raw_result_line, metadata_line) in enumerate(zip(raw_result_lines, metadata_lines)):
        try:
            raw_result = json.loads(raw_result_line.strip())
            metadata = json.loads(metadata_line.strip())

            job_results = raw_result['jobs'][0]

            result = {
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'vm_size': vm_size,
                'cloud_info': cloud_info,
                'read_iops_avg': job_results['read']['iops_mean'],
                'read_bw_avg': job_results['read']['bw_mean'],
                'read_lat_avg': job_results['read']['clat_ns']['mean'],
                'write_iops_avg': job_results['write']['iops_mean'],
                'write_bw_avg': job_results['write']['bw_mean'],
                'write_lat_avg': job_results['write']['clat_ns']['mean'],
                'read_lat_p50': job_results.get('read', {}).get('clat_ns', {}).get('percentile', {}).get('50.000000', 0.0),
                'read_lat_p99': job_results.get('read', {}).get('clat_ns', {}).get('percentile', {}).get('99.000000', 0.0),
                'read_lat_p999': job_results.get('read', {}).get('clat_ns', {}).get('percentile', {}).get('99.900000', 0.0),
                'write_lat_p50': job_results.get('write', {}).get('clat_ns', {}).get('percentile', {}).get('50.000000', 0.0),
                'write_lat_p99': job_results.get('write', {}).get('clat_ns', {}).get('percentile', {}).get('99.000000', 0.0),
                'write_lat_p999': job_results.get('write', {}).get('clat_ns', {}).get('percentile', {}).get('99.900000', 0.0),
                'metadata': metadata,
                'raw_result': raw_result,
                'run_url': run_url,
            }

            with open(result_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result) + "\n")
            logger.info(f"Results for entry {i+1} collected and saved to {result_path}")

        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON at line {i+1}: {str(e)}")
        except KeyError as e:
            logger.error(f"Missing key in data at line {i+1}: {str(e)}")
        except Exception as e:
            logger.error(f"Error processing entry {i+1}: {str(e)}")

    logger.info(f"All results collected and saved to {result_path}")

def main():
    parser = argparse.ArgumentParser(description="Fio Benchmark.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for validate
    parser_validate = subparsers.add_parser("validate", help="Validate node count")
    parser_validate.add_argument("node_count", type=int, help="Number of nodes")
    parser_validate.add_argument("operation_timeout", type=int, help="Timeout for the operation in seconds")

    # Sub-command for execute_attach_detach
    parser_execute = subparsers.add_parser("execute", help="Execute fio benchmark")
    parser_execute.add_argument("--block_size", type=str, help="Block size")
    parser_execute.add_argument("--iodepth", type=int, help="IO depth")
    parser_execute.add_argument("--method", type=str, help="Method")
    parser_execute.add_argument("--runtime", type=int, help="Runtime in seconds")
    parser_execute.add_argument("--numjobs", type=int, help="Number of jobs")
    parser_execute.add_argument("--file_size", type=str, help="File size")
    parser_execute.add_argument("--storage_name", type=str, help="Storage name")
    parser_execute.add_argument("--kustomize_dir", type=str, help="Directory for kustomize")
    parser_execute.add_argument(
        "--result_dir", type=str, help="Directory to store results"
    )

    # Sub-command for collect_attach_detach
    parser_collect = subparsers.add_parser(
        "collect", help="Collect attach detach test results"
    )
    parser_collect.add_argument("--vm_size", type=str, required=False, help="VM size")
    parser_collect.add_argument("--block_size", type=str, help="Block size")
    parser_collect.add_argument("--iodepth", type=int, help="IO depth")
    parser_collect.add_argument("--method", type=str, help="Method")
    parser_collect.add_argument("--numjobs", type=int, help="Number of jobs")
    parser_collect.add_argument("--file_size", type=str, help="File size")
    parser_collect.add_argument(
        "--result_dir", type=str, help="Directory to store results"
    )
    parser_collect.add_argument("--run_url", type=str, help="Run URL")
    parser_collect.add_argument("--cloud_info", type=str, help="Cloud information")

    args = parser.parse_args()
    if args.command == "validate":
        validate(args.node_count, args.operation_timeout)
    elif args.command == "execute":
        execute(
            args.block_size,
            args.iodepth,
            args.method,
            args.runtime,
            args.numjobs,
            args.file_size,
            args.storage_name,
            args.kustomize_dir,
            args.result_dir,
        )
    elif args.command == "collect":
        collect(
            args.vm_size,
            args.block_size,
            args.iodepth,
            args.method,
            args.numjobs,
            args.file_size,
            args.result_dir,
            args.run_url,
            args.cloud_info,
        )

if __name__ == "__main__":
    main()
