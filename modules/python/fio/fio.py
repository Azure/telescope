import argparse
import time
import json
import os
from datetime import datetime, timezone
from clients.kubernetes_client import KubernetesClient
from utils.logger_config import get_logger, setup_logging
from utils.retries import execute_with_retries

setup_logging()
logger = get_logger(__name__)

KUBERNETES_CLIENT = KubernetesClient()
FILE_SIZE = 10*1024*1024*1024

def validate(node_count, operation_timeout_in_minutes=10):
    KUBERNETES_CLIENT.wait_for_nodes_ready(node_count, operation_timeout_in_minutes)

def configure(yaml_path, replicas, operation_timeout_in_minutes=10):
    deployment_template = KUBERNETES_CLIENT.create_template(
        yaml_path, {"REPLICAS": replicas}
    )
    deployment_name = KUBERNETES_CLIENT.create_deployment(deployment_template)
    logger.info(f"Deployment {deployment_name} created successfully!")
    pods = KUBERNETES_CLIENT.wait_for_pods_ready(
        label_selector="test=fio", pod_count=replicas, operation_timeout_in_minutes=operation_timeout_in_minutes
    )
    for pod in pods:
        pod_name = pod.metadata.name
        logs = KUBERNETES_CLIENT.get_pod_logs(pod_name)
        logger.info(f"Checking logs for pod {pod_name}:\n{logs}")

def execute(block_size, iodepth, method, runtime, result_dir):
    os.makedirs(result_dir, exist_ok=True)
    logger.info(f"Result directory: {result_dir}")

    pods = KUBERNETES_CLIENT.get_pods_by_namespace(namespace="default", label_selector="test=fio")
    pod_name = pods[0].metadata.name
    mount_path = pods[0].spec.containers[0].volume_mounts[0].mount_path
    logger.info(f"Executing fio benchmark on pod {pod_name} with mount path {mount_path}")

    file_path=f"{mount_path}/benchtest"
    base_command = f"fio --name=benchtest --size={FILE_SIZE} --filename={file_path} --direct=1 --ioengine=libaio --time_based \
--rw={method} --bs={block_size} --iodepth={iodepth} --runtime={runtime} --output-format=json"
    result_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}.json"
    setup_command = f"{base_command} --create_only=1"
    logger.info(f"Run setup command: {setup_command}")
    execute_with_retries(
        KUBERNETES_CLIENT.run_pod_exec_command,
        pod_name=pod_name,
        container_name="fio",
        command=setup_command,
    )
    sleep_time = 30
    logger.info(f"Wait for {sleep_time} seconds to clean any potential throttle/cache")
    time.sleep(sleep_time)

    logger.info(f"Run fio command: {base_command}")
    start_time = time.time()
    execute_with_retries(
        KUBERNETES_CLIENT.run_pod_exec_command,
        pod_name=pod_name,
        container_name="fio",
        command=base_command,
        dest_path=result_path,
    )
    end_time = time.time()
    metadata_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-metadata.json"
    metadata = {
        "block_size": block_size,
        "iodepth": iodepth,
        "method": method,
        "file_size": FILE_SIZE,
        "runtime": runtime,
        "storage_name": "fio",
        "start_time": start_time,
        "end_time": end_time,
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(metadata))
    logger.info(f"Metadata saved to {metadata_path}:\n{metadata}")


def collect(vm_size, block_size, iodepth, method, result_dir, run_url, cloud_info):
    raw_result_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}.json"
    with open(raw_result_path, "r", encoding="utf-8") as f:
        raw_result = json.load(f)
    metadata_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-metadata.json"
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

    # Sub-command for configure
    parser_configure = subparsers.add_parser("configure", help="Configure fio benchmark")
    parser_configure.add_argument("yaml_path", type=str, help="Path to the YAML file")
    parser_configure.add_argument("replicas", type=int, help="Number of replicas")
    parser_configure.add_argument("operation_timeout", type=int, help="Timeout for the operation in seconds")

    # Sub-command for execute_attach_detach
    parser_execute = subparsers.add_parser("execute", help="Execute fio benchmark")
    parser_execute.add_argument("block_size", type=str, help="Block size")
    parser_execute.add_argument("iodepth", type=int, help="IO depth")
    parser_execute.add_argument("method", type=str, help="Method")
    parser_execute.add_argument("runtime", type=int, help="Runtime in seconds")
    parser_execute.add_argument("result_dir", type=str, help="Directory to store results")

    # Sub-command for collect_attach_detach
    parser_collect = subparsers.add_parser("collect", help="Collect attach detach test results")
    parser_collect.add_argument("vm_size", type=str, help="VM size")
    parser_collect.add_argument("block_size", type=str, help="Block size")
    parser_collect.add_argument("iodepth", type=int, help="IO depth")
    parser_collect.add_argument("method", type=str, help="Method")
    parser_collect.add_argument("result_dir", type=str, help="Directory to store results")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")

    args = parser.parse_args()
    if args.command == "validate":
        validate(args.node_count, args.operation_timeout)
    elif args.command == "configure":
        configure(args.yaml_path, args.replicas, args.operation_timeout)
    elif args.command == "execute":
        execute(args.block_size, args.iodepth, args.method, args.runtime, args.result_dir)
    elif args.command == "collect":
        collect(args.vm_size, args.block_size, args.iodepth, args.method,
                args.result_dir, args.run_url, args.cloud_info)

if __name__ == "__main__":
    main()
