import json
import math
import os
import argparse
import time

from datetime import datetime, timezone
from clusterloader2.utils import parse_xml_to_json, run_cl2_command, get_measurement
from clients.kubernetes_client import KubernetesClient
from utils.common import str2bool

DEFAULT_NODES_PER_NAMESPACE = 100
CPU_REQUEST_LIMIT_MILLI = 1
DAEMONSETS_PER_NODE = {
    "aws": 2,
    "azure": 6,
    "aks": 6
}
CPU_CAPACITY = {
    "aws": 0.94,
    "azure": 0.87,
    "aks": 0.87
}
# TODO: Remove aks once CL2 update provider name to be azure

def calculate_config(cpu_per_node, node_count, provider, pods_per_node):
    throughput = 100
    nodes_per_namespace = min(node_count, DEFAULT_NODES_PER_NAMESPACE)

    # Different cloud has different reserved values and number of daemonsets
    # Using the same percentage will lead to incorrect nodes number as the number of nodes grow
    # For AWS, see: https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/bootstrap.sh#L290
    # For Azure, see: https://learn.microsoft.com/en-us/azure/aks/node-resource-reservations#cpu-reservations
    capacity = CPU_CAPACITY[provider]
    cpu_request = (cpu_per_node * 1000 * capacity) // pods_per_node
    cpu_request = max(cpu_request, CPU_REQUEST_LIMIT_MILLI)

    return throughput, nodes_per_namespace, cpu_request

def configure_clusterloader2(
    cpu_per_node,
    node_count,
    node_per_step,
    pods_per_node,
    repeats,
    operation_timeout,
    provider,
    cilium_enabled,
    scrape_containerd,
    override_file
):

    steps = node_count // node_per_step
    throughput, nodes_per_namespace, cpu_request = calculate_config(cpu_per_node, node_per_step, provider, pods_per_node)

    with open(override_file, 'w', encoding='utf-8') as file:
        file.write(f"CL2_NODES: {node_count}\n")
        file.write(f"CL2_LOAD_TEST_THROUGHPUT: {throughput}\n")
        file.write(f"CL2_NODES_PER_NAMESPACE: {nodes_per_namespace}\n")
        file.write(f"CL2_NODES_PER_STEP: {node_per_step}\n")
        file.write(f"CL2_PODS_PER_NODE: {pods_per_node}\n")
        file.write(f"CL2_DEPLOYMENT_SIZE: {pods_per_node}\n")
        file.write(f"CL2_LATENCY_POD_CPU: {cpu_request}\n")
        file.write(f"CL2_REPEATS: {repeats}\n")
        file.write(f"CL2_STEPS: {steps}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")
        file.write("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m\n")

        if scrape_containerd:
            file.write(f"CL2_SCRAPE_CONTAINERD: {str(scrape_containerd).lower()}\n")
            file.write("CONTAINERD_SCRAPE_INTERVAL: 5m\n")

        if cilium_enabled:
            file.write("CL2_CILIUM_METRICS_ENABLED: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL: 30s\n")

    with open(override_file, 'r', encoding='utf-8') as file:
        print(f"Content of file {override_file}:\n{file.read()}")

    file.close()

def validate_clusterloader2(node_count, operation_timeout_in_minutes=10, min_ready_percent=100, stable_minutes=0, node_label=None):
    """
    Wait until node_count nodes are ready.

    With min_ready_percent < 100 the validation is loose: it also passes when at least that percentage of
    node_count nodes are ready, either once the ready count has stopped changing for stable_minutes or
    when the timeout is reached. If node_label is set, the number of ready nodes carrying that label is
    exported as the READY_NODE_COUNT pipeline variable so later steps can size the workload to it.
    """
    kube_client = KubernetesClient()
    ready_node_count = 0
    loose = min_ready_percent < 100
    required_node_count = math.ceil(node_count * min_ready_percent / 100) if loose else node_count
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    last_count = None
    stable_since = None
    while time.time() < timeout:
        try:
            ready_nodes = kube_client.get_ready_nodes()
        except Exception as e:
            print(f"Transient error querying nodes, will retry: {e}", flush=True)
            time.sleep(10)
            continue
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.", flush=True)
        if ready_node_count == node_count:
            break
        if loose and stable_minutes > 0 and required_node_count <= ready_node_count <= node_count:
            now = time.time()
            if ready_node_count != last_count:
                last_count = ready_node_count
                stable_since = now
            elif now - stable_since >= stable_minutes * 60:
                print(f"Ready node count has been {ready_node_count} for {stable_minutes} minutes, "
                      f"which meets the {min_ready_percent}% threshold ({required_node_count} of {node_count}).", flush=True)
                break
        else:
            last_count = None
        print(f"Waiting for {node_count} nodes to be ready.", flush=True)
        time.sleep(10)

    meets_loose_threshold = loose and required_node_count <= ready_node_count <= node_count
    if ready_node_count != node_count and not meets_loose_threshold:
        raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")
    if ready_node_count != node_count:
        print(f"##vso[task.logissue type=warning;] Proceeding with {ready_node_count} of {node_count} nodes ready "
              f"(minimum {required_node_count}, {min_ready_percent}%).", flush=True)

    if node_label:
        labeled_ready_count = len(kube_client.get_ready_nodes(label_selector=node_label))
        if labeled_ready_count == 0:
            raise Exception(f"No ready nodes found with label '{node_label}'!")
        print(f"{labeled_ready_count} ready nodes have label '{node_label}'.", flush=True)
        print(f"##vso[task.setvariable variable=READY_NODE_COUNT]{labeled_ready_count}", flush=True)

def execute_clusterloader2(
    cl2_image,
    cl2_config_dir,
    cl2_report_dir,
    cl2_config_file,
    kubeconfig,
    provider,
    scrape_containerd
):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider,
                    cl2_config_file=cl2_config_file, overrides=True, enable_prometheus=True,
                    scrape_containerd=scrape_containerd)

def collect_clusterloader2(
    cpu_per_node,
    node_count,
    pods_per_node,
    repeats,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file,
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    pod_count = node_count * pods_per_node

    # TODO: Expose optional parameter to include test details
    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "cpu_per_node": cpu_per_node,
        "node_count": node_count,
        "pod_count": pod_count,
        "churn_rate": repeats,
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        # "test_details": details,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
    }
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, 'r', encoding='utf-8') as file:
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

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    parser = argparse.ArgumentParser(description="SLO Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("--cpu_per_node", type=int, help="CPU per node")
    parser_configure.add_argument("--node_count", type=int, help="Number of nodes")
    parser_configure.add_argument("--node_per_step", type=int, help="Number of nodes per scaling step")
    parser_configure.add_argument("--pods_per_node", type=int, help="The number of pods per node")
    parser_configure.add_argument("--repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_configure.add_argument("--operation_timeout", type=str, help="Timeout before failing the scale up test")
    parser_configure.add_argument("--provider", type=str, help="Cloud provider name")
    parser_configure.add_argument("--cilium_enabled", type=str2bool, choices=[True, False], default=False,
                                  help="Whether cilium is enabled. Must be either True or False")
    parser_configure.add_argument("--scrape_containerd", type=str2bool, choices=[True, False], default=False,
                                  help="Whether to scrape containerd metrics. Must be either True or False")
    parser_configure.add_argument("--cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for validate_clusterloader2
    parser_validate = subparsers.add_parser("validate", help="Validate cluster setup")
    parser_validate.add_argument("--node_count", type=int, help="Number of desired nodes")
    parser_validate.add_argument("--operation_timeout", type=int, default=600, help="Operation timeout to wait for nodes to be ready")
    parser_validate.add_argument("--min_ready_percent", type=float, default=100,
                                 help="Minimum percentage of node_count that must be ready for validation to pass (100 requires all)")
    parser_validate.add_argument("--stable_minutes", type=float, default=0,
                                 help="With min_ready_percent < 100, pass early once the ready count meets the minimum and has not changed for this many minutes")
    parser_validate.add_argument("--node_label", type=str, default="",
                                 help="Label selector; if set, the number of ready nodes with this label is exported as READY_NODE_COUNT")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("--cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("--cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("--cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("--cl2_config_file", type=str, help="Path to the CL2 config file")
    parser_execute.add_argument("--kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("--provider", type=str, help="Cloud provider name")
    parser_execute.add_argument("--scrape_containerd", type=str2bool, choices=[True, False], default=False,
                                help="Whether to scrape containerd metrics. Must be either True or False")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("--cpu_per_node", type=int, help="CPU per node")
    parser_collect.add_argument("--node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("--pods_per_node", type=int, help="The number of pods per node")
    parser_collect.add_argument("--repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_collect.add_argument("--cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("--cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("--run_id", type=str, help="Run ID")
    parser_collect.add_argument("--run_url", type=str, help="Run URL")
    parser_collect.add_argument("--result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(
            args.cpu_per_node,
            args.node_count,
            args.node_per_step,
            args.pods_per_node,
            args.repeats,
            args.operation_timeout,
            args.provider,
            args.cilium_enabled,
            args.scrape_containerd,
            args.cl2_override_file,
        )
    elif args.command == "validate":
        validate_clusterloader2(
            args.node_count,
            args.operation_timeout,
            args.min_ready_percent,
            args.stable_minutes,
            args.node_label or None,
        )
    elif args.command == "execute":
        execute_clusterloader2(
            args.cl2_image,
            args.cl2_config_dir,
            args.cl2_report_dir,
            args.cl2_config_file,
            args.kubeconfig,
            args.provider,
            args.scrape_containerd,
        )
    elif args.command == "collect":
        collect_clusterloader2(
            args.cpu_per_node,
            args.node_count,
            args.pods_per_node,
            args.repeats,
            args.cl2_report_dir,
            args.cloud_info,
            args.run_id,
            args.run_url,
            args.result_file,
        )

if __name__ == "__main__":
    main()
