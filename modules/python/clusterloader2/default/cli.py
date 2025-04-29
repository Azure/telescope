import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Tuple

from clients.kubernetes_client import KubernetesClient
from clusterloader2.utils import (get_measurement, parse_xml_to_json,
                                  run_cl2_command, str2bool)

DEFAULT_PODS_PER_NODE = 40

DEFAULT_NODES_PER_NAMESPACE = 100
CPU_REQUEST_LIMIT_MILLI = 1
DAEMONSETS_PER_NODE = {"aws": 2, "azure": 6, "aks": 6}
CPU_CAPACITY = {"aws": 0.94, "azure": 0.87, "aks": 0.87}
# TODO: Remove aks once CL2 update provider name to be azure


def calculate_config(
    cpu_per_node: int,
    node_count: int,
    max_pods: int,
    provider: str,
    service_test: bool,
    cnp_test: bool,
    ccnp_test: bool,
) -> Tuple[int, int, int, int]:
    throughput = 100
    nodes_per_namespace = min(node_count, DEFAULT_NODES_PER_NAMESPACE)

    pods_per_node = DEFAULT_PODS_PER_NODE
    if service_test:
        pods_per_node = max_pods

    if cnp_test or ccnp_test:
        pods_per_node = max_pods
    # Different cloud has different reserved values and number of daemonsets
    # Using the same percentage will lead to incorrect nodes number as the number of nodes grow
    # For AWS, see: https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/bootstrap.sh#L290
    # For Azure, see: https://learn.microsoft.com/en-us/azure/aks/node-resource-reservations#cpu-reservations
    capacity = CPU_CAPACITY[provider]
    cpu_request = (cpu_per_node * 1000 * capacity) // pods_per_node
    cpu_request = max(cpu_request, CPU_REQUEST_LIMIT_MILLI)

    return throughput, nodes_per_namespace, pods_per_node, cpu_request


def configure_clusterloader2(
    cpu_per_node: int,
    node_count: int,
    node_per_step: int,
    max_pods: int,
    repeats: int,
    operation_timeout: str,
    provider: str,
    cilium_enabled: bool,
    scrape_containerd: bool,
    service_test: bool,
    cnp_test: bool,
    ccnp_test: bool,
    num_cnps: int,
    num_ccnps: int,
    dualstack: bool,
    cl2_override_file: str,
    workload_type: str,
    job_count: int,
    job_parallelism: int,
    job_completions: int,
    job_throughput: int,
) -> None:

    # Calculate steps
    steps = node_count // node_per_step

    # Initialize throughput and workload-specific configurations
    if workload_type == "job":
        throughput = job_count // repeats if job_throughput == -1 else job_throughput
    elif workload_type == "pod":
        throughput, nodes_per_namespace, pods_per_node, cpu_request = calculate_config(
            cpu_per_node,
            node_count,
            max_pods,
            provider,
            service_test,
            cnp_test,
            ccnp_test,
        )
    else:
        raise ValueError("Invalid workload_type. Must be 'pod' or 'job'.")

    # Write configurations to the override file
    with open(cl2_override_file, "w", encoding="utf-8") as file:
        file.write(f"CL2_NODES: {node_count}\n")
        file.write(f"CL2_NODES_PER_STEP: {node_per_step}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write(f"CL2_REPEATS: {repeats}\n")
        file.write(f"CL2_STEPS: {steps}\n")

        if workload_type == "job":
            # Job-specific configurations
            file.write(f"CL2_JOBS: {job_count}\n")
            file.write(f"CL2_JOB_PARALLELISM: {job_parallelism}\n")
            file.write(f"CL2_JOB_COMPLETIONS: {job_completions}\n")
            file.write(f"CL2_LOAD_TEST_THROUGHPUT: {throughput}\n")
        elif workload_type == "pod":
            # Pod-specific configurations
            file.write(f"CL2_LOAD_TEST_THROUGHPUT: {throughput}\n")
            file.write(f"CL2_NODES_PER_NAMESPACE: {nodes_per_namespace}\n")
            file.write(f"CL2_PODS_PER_NODE: {pods_per_node}\n")
            file.write(f"CL2_DEPLOYMENT_SIZE: {pods_per_node}\n")
            file.write(f"CL2_LATENCY_POD_CPU: {cpu_request}\n")

        if scrape_containerd:
            file.write(f"CL2_SCRAPE_CONTAINERD: {str(scrape_containerd).lower()}\n")
            file.write("CONTAINERD_SCRAPE_INTERVAL: 5m\n")

        if cilium_enabled:
            file.write("CL2_CILIUM_METRICS_ENABLED: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL: 30s\n")

        if service_test:
            file.write("CL2_SERVICE_TEST: true\n")
        else:
            file.write("CL2_SERVICE_TEST: false\n")

        if cnp_test:
            file.write("CL2_CNP_TEST: true\n")
            file.write(f"CL2_CNPS_PER_NAMESPACE: {num_cnps}\n")
            file.write(f"CL2_DUALSTACK: {dualstack}\n")
            file.write("CL2_GROUP_NAME: cnp-ccnp\n")

        if ccnp_test:
            file.write("CL2_CCNP_TEST: true\n")
            file.write(f"CL2_CCNPS: {num_ccnps}\n")
            file.write(f"CL2_DUALSTACK: {dualstack}\n")
            file.write("CL2_GROUP_NAME: cnp-ccnp\n")

    # Print the generated configuration for debugging
    with open(cl2_override_file, "r", encoding="utf-8") as file:
        print(f"Content of file {cl2_override_file}:\n{file.read()}")


def validate_clusterloader2(node_count: int, operation_timeout_in_minutes: int = 10) -> None:
    kube_client = KubernetesClient()
    ready_node_count = 0
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    while time.time() < timeout:
        ready_nodes = kube_client.get_ready_nodes()
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.")
        if ready_node_count >= node_count:
            print(f"All {node_count} nodes are ready.")
            break
        print(f"Waiting for {node_count} nodes to be ready.")
        time.sleep(10)
    if ready_node_count < node_count:
        raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")


def execute_clusterloader2(
    cl2_image: str,
    cl2_config_dir: str,
    cl2_report_dir: str,
    cl2_config_file: str,
    kubeconfig: str,
    prometheus_enabled: bool,
    provider: str,
    scrape_containerd: bool,
) -> None:
    run_cl2_command(
        kubeconfig,
        cl2_image,
        cl2_config_dir,
        cl2_report_dir,
        provider,
        cl2_config_file=cl2_config_file,
        overrides=True,
        enable_prometheus=prometheus_enabled,
        scrape_containerd=scrape_containerd,
    )


def process_pod_workload(template, cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test):
    _, _, pods_per_node, _ = calculate_config(cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test)
    pod_count = node_count * pods_per_node
    template["pod_count"] = pod_count
    return template


def process_job_workload(template, job_count, job_parallelism, job_completions, job_throughput):
    if job_count is None or job_parallelism is None or job_completions is None or job_throughput is None:
        raise ValueError("For job workloads, job_count, job_parallelism, job_completions, and job_throughput must be provided.")
    template.update(
        {
            "job_count": job_count,
            "job_parallelism": job_parallelism,
            "job_completions": job_completions,
            "job_throughput": job_throughput,
        }
    )
    return template


def process_cl2_reports(cl2_report_dir, template):
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, "r", encoding="utf-8") as file:
            print(f"Processing {file_path}")
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(file.read())

            if "dataItems" in data:
                items = data["dataItems"]
                if not items:
                    print(f"No data items found in {file_path}")
                    print(f"Data:\n{data}")
                    continue
                for item in items:
                    result = template.copy()
                    result["group"] = group_name
                    result["measurement"] = measurement
                    result["result"] = item
                    content += json.dumps(result) + "\n"
            else:
                result = template.copy()
                result["group"] = group_name
                result["measurement"] = measurement
                result["result"] = data
                content += json.dumps(result) + "\n"
    return content


def collect_clusterloader2(
    cpu_per_node: int,
    node_count: int,
    max_pods: int,
    repeats: int,
    cl2_report_dir: str,
    cloud_info: str,
    run_id: str,
    run_url: str,
    service_test: bool,
    cnp_test: bool,
    ccnp_test: bool,
    result_file: str,
    test_type: str,
    start_timestamp: str,
    workload_type: str,
    job_count: int,
    job_parallelism: int,
    job_completions: int,
    job_throughput: int,
) -> None:

    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent=2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]
    provider = json.loads(cloud_info)["cloud"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    # Initialize the template
    template = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "node_count": node_count,
        "churn_rate": repeats,
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
        "start_timestamp": start_timestamp,
    }

    # Conditionally include cpu_per_node if provided
    if cpu_per_node is not None:
        template["cpu_per_node"] = cpu_per_node

    # Process workload type
    if workload_type == "pod":
        template = process_pod_workload(template, cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test)
    elif workload_type == "job":
        template = process_job_workload(template, job_count, job_parallelism, job_completions, job_throughput)
    else:
        raise ValueError("Invalid workload_type. Must be 'pod' or 'job'.")

    # Process CL2 report files
    content = process_cl2_reports(cl2_report_dir, template)

    # Write results to the result file
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as file:
        file.write(content)


def main():
    parser = argparse.ArgumentParser(description="CLI Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("--cpu_per_node", type=int, help="CPU per node")
    parser_configure.add_argument("--node_count", type=int, help="Number of nodes")
    parser_configure.add_argument("--node_per_step", type=int, default=1, help="Number of nodes per scaling step")
    parser_configure.add_argument("--max_pods", type=int, nargs="?", default=0, help="Maximum number of pods per node")
    parser_configure.add_argument("--repeats", type=int, default=1, help="Number of times to repeat the deployment churn")
    parser_configure.add_argument("--operation_timeout", type=str, help="Timeout before failing the scale up test")
    parser_configure.add_argument("--provider", type=str, help="Cloud provider name")
    parser_configure.add_argument("--cilium_enabled", type=str2bool, choices=[True, False], default=False, help="Whether cilium is enabled. Must be either True or False")
    parser_configure.add_argument("--scrape_containerd", type=str2bool, choices=[True, False], default=False, help="Whether to scrape containerd metrics. Must be either True or False")
    parser_configure.add_argument("--service_test", type=str2bool, choices=[True, False], default=False, help="Whether service test is running. Must be either True or False")
    parser_configure.add_argument("--cnp_test", type=str2bool, choices=[True, False], nargs="?", default=False, help="Whether cnp test is running. Must be either True or False")
    parser_configure.add_argument("--ccnp_test", type=str2bool, choices=[True, False], nargs="?", default=False, help="Whether ccnp test is running. Must be either True or False")
    parser_configure.add_argument("--num_cnps", type=int, nargs="?", default=0, help="Number of cnps")
    parser_configure.add_argument("--num_ccnps", type=int, nargs="?", default=0, help="Number of ccnps")
    parser_configure.add_argument("--dualstack", type=str2bool, choices=[True, False], nargs="?", default=False, help="Whether cluster is dualstack. Must be either True or False")
    parser_configure.add_argument("--cl2_override_file", type=str, help="Path to the overrides of CL2 config file")
    parser_configure.add_argument("--workload_type", type=str, choices=["pod", "job"], default="pod", help="Type of workload to run")
    parser_configure.add_argument("--job_count", type=int, default=1000, help="Number of jobs to run")
    parser_configure.add_argument("--job_parallelism", type=int, default=1, help="Number of jobs to run in parallel")
    parser_configure.add_argument("--job_completions", type=int, default=1, help="Number of job completions")
    parser_configure.add_argument("--job_throughput", type=int, default=-1, help="Job throughput")

    # Sub-command for validate_clusterloader2
    parser_validate = subparsers.add_parser("validate", help="Validate cluster setup")
    parser_validate.add_argument("--node_count", type=int, help="Number of desired nodes")
    parser_validate.add_argument("--operation_timeout_in_minutes", type=int, default=600, help="Operation timeout to wait for nodes to be ready")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("--cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("--cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("--cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("--cl2_config_file", type=str, help="Path to the CL2 config file")
    parser_execute.add_argument("--kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("--provider", type=str, help="Cloud provider name")
    parser_execute.add_argument("--prometheus_enabled", type=str2bool, choices=[True, False], default=False, help="Whether to enable Prometheus scraping. Must be either True or False")
    parser_execute.add_argument("--scrape_containerd", type=str2bool, choices=[True, False], default=False, help="Whether to scrape containerd metrics. Must be either True or False")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale-up data")
    parser_collect.add_argument("--cpu_per_node", type=int, help="CPU per node")
    parser_collect.add_argument("--node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("--max_pods", type=int, nargs="?", default=0, help="Maximum number of pods per node")
    parser_collect.add_argument("--repeats", type=int, default=1, help="Number of times to repeat the deployment churn")
    parser_collect.add_argument("--cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("--cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("--run_id", type=str, help="Run ID")
    parser_collect.add_argument("--run_url", type=str, help="Run URL")
    parser_collect.add_argument("--service_test", type=str2bool, choices=[True, False], default=False, help="Whether service test is running. Must be either True or False")
    parser_collect.add_argument("--cnp_test", type=str2bool, choices=[True, False], nargs="?", default=False, help="Whether cnp test is running. Must be either True or False")
    parser_collect.add_argument("--ccnp_test", type=str2bool, choices=[True, False], nargs="?", default=False, help="Whether ccnp test is running. Must be either True or False")
    parser_collect.add_argument("--result_file", type=str, help="Path to the result file")
    parser_collect.add_argument("--test_type", type=str, nargs="?", default="default-config", help="Description of test type")
    parser_collect.add_argument("--start_timestamp", type=str, help="Test start timestamp")
    parser_collect.add_argument("--workload_type", type=str, choices=["pod", "job"], default="pod", help="Type of workload to run")
    parser_collect.add_argument("--job_count", type=int, default=1000, help="Number of jobs to run")
    parser_collect.add_argument("--job_parallelism", type=int, default=1, help="Number of jobs to run in parallel")
    parser_collect.add_argument("--job_completions", type=int, default=1, help="Number of job completions")
    parser_collect.add_argument("--job_throughput", type=int, default=-1, help="Job throughput")

    args = parser.parse_args()
    args_dict = vars(args)

    command = args_dict.pop("command")

    if command == "configure":
        configure_clusterloader2(**args_dict)
    elif command == "validate":
        validate_clusterloader2(**args_dict)
    elif command == "execute":
        execute_clusterloader2(**args_dict)
    elif command == "collect":
        collect_clusterloader2(**args_dict)
    else:
        raise ValueError(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
