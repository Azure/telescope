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

def execute(block_size, iodepth, method, runtime, numjobs, file_size, storage_name, kustomize_dir, result_dir):
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
    "--ioengine=libaio",
    "--time_based",
    "--output-format=json",
    "--group_reporting"
    ]
    patch = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": "fio"},
        "spec": {
            "template": {
                "spec": {"containers": [{"name": "fio", "command": fio_command}]}
            }
        },
    }
    patch_file = f"{kustomize_dir}/base/command.yaml"
    with open(patch_file, "w", encoding="utf-8") as f:
        yaml.dump(patch, f)

    create_command = f"kustomize build {kustomize_dir}/overlays/{storage_name}/deployment | kubectl apply -f -"
    logger.info(f"Running command: {create_command}")
    subprocess.run(create_command, shell=True, check=True, capture_output=True)

    os.makedirs(result_dir, exist_ok=True)
    pods = KUBERNETES_CLIENT.wait_for_job_completed(
        job_name="fio",
        timeout=runtime+120,
    )
    result_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}.json"
    pods = KUBERNETES_CLIENT.get_pods_by_namespace(
        namespace="default", label_selector="job-name=fio"
    )
    if not pods:
        raise RuntimeError("No pods found for the fio job.")
    for pod in pods:
        pod_name = pod.metadata.name
        logs = KUBERNETES_CLIENT.get_pod_logs(pod_name)
        parsed_logs = json.loads(logs)
        logger.info(f"Checking logs for pod {pod_name}:\n{parsed_logs}")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(parsed_logs))
        logger.info(f"Results saved to {result_path}")

    delete_command = f"kustomize build {kustomize_dir}/overlays/{storage_name}/deployment | kubectl delete -f -"
    logger.info(f"Running command: {delete_command}")
    subprocess.run(delete_command, shell=True, check=True, capture_output=True)

    metadata_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}-metadata.json"
    metadata = {
        "block_size": block_size,
        "iodepth": iodepth,
        "method": method,
        "file_size": file_size,
        "runtime": runtime,
        "numjobs": numjobs,
        "storage_name": storage_name,
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(metadata))
    logger.info(f"Metadata saved to {metadata_path}:\n{metadata}")

def collect(vm_size, block_size, iodepth, method, numjobs, file_size, result_dir, run_url, cloud_info):
    raw_result_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}.json"
    with open(raw_result_path, "r", encoding="utf-8") as f:
        raw_result = json.load(f)
    metadata_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}-metadata.json"
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

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
    result_path = f"{result_dir}/results.json"
    with open(result_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")
    logger.info(f"Results collected and saved to {result_path}:\n{json.dumps(result, indent=2)}")

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
