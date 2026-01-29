import json
import os
import argparse
import time

from datetime import datetime, timezone
from clusterloader2.utils import parse_xml_to_json, run_cl2_command, get_measurement, str2bool
from clients.kubernetes_client import KubernetesClient

DEFAULT_NODES_PER_NAMESPACE = 100
CPU_REQUEST_LIMIT_MILLI = 1
CPU_CAPACITY = {
    "aws": 0.94,
    "azure": 0.87,
    "aks": 0.87
}


def calculate_config(cpu_per_node, node_count, max_pods, provider):
    throughput = 100
    nodes_per_namespace = node_count if node_count < DEFAULT_NODES_PER_NAMESPACE else DEFAULT_NODES_PER_NAMESPACE

    capacity = CPU_CAPACITY[provider]
    if not max_pods:
        max_pods = 15
    cpu_request = (cpu_per_node * 1000 * capacity) // max_pods
    cpu_request = max(cpu_request, CPU_REQUEST_LIMIT_MILLI)
    return throughput, nodes_per_namespace, cpu_request


def configure_clusterloader2(
    cpu_per_node,
    node_count,
    pods_per_step,
    pods_per_node,
    max_pods,
    repeats,
    operation_timeout,
    provider,
    cilium_enabled,
    scrape_containerd,
    service_test,
    cnp_test,
    ccnp_test,
    ds_test,
    num_cnps,
    num_ccnps,
    dualstack,
    pods_per_pni,
    existing_pods,
    override_file):

    total_pods = node_count * pods_per_node
    delta_pods = total_pods - existing_pods
    steps = delta_pods // pods_per_step if pods_per_step else 1
    throughput, nodes_per_namespace, cpu_request = calculate_config(cpu_per_node, node_count, max_pods, provider)

    with open(override_file, 'w', encoding='utf-8') as file:
        file.write(f"CL2_NODES: {node_count}\n")
        file.write(f"CL2_LOAD_TEST_THROUGHPUT: {throughput}\n")
        file.write(f"CL2_NODES_PER_NAMESPACE: {nodes_per_namespace}\n")
        file.write(f"CL2_PODS_PER_NODE: {pods_per_node}\n")
        file.write(f"CL2_PODS_PER_STEP: {pods_per_step}\n")
        file.write(f"CL2_PODS_PER_PNI: {pods_per_pni}\n")
        file.write(f"CL2_TOTAL_PODS: {total_pods}\n")
        file.write(f"CL2_EXISTING_PODS: {existing_pods}\n")
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

        location = os.environ.get("REGION") or os.environ.get("LOCATION")
        if location:
            file.write(f"CL2_LOCATION: {location.lower()}\n")

        device_plugin_env = os.environ.get("CL2_DEVICE_PLUGIN")
        if device_plugin_env is not None and str(device_plugin_env).strip() != "":
            file.write(f"CL2_DEVICE_PLUGIN: {str(str2bool(device_plugin_env)).lower()}\n")

        # Pass image environment variables to CL2
        datapath_reporter_image = os.environ.get("CL2_DATAPATH_REPORTER_IMAGE")
        if datapath_reporter_image:
            file.write(f"CL2_DATAPATH_REPORTER_IMAGE: {datapath_reporter_image}\n")
        
        nginx_image = os.environ.get("CL2_NGINX_IMAGE")
        if nginx_image:
            file.write(f"CL2_NGINX_IMAGE: {nginx_image}\n")

        # Pass probe configuration to CL2
        probe_target_url = os.environ.get("CL2_PROBE_TARGET_URL")
        if probe_target_url:
            file.write(f"CL2_PROBE_TARGET_URL: {probe_target_url}\n")
        
        probe_timeout = os.environ.get("CL2_PROBE_TIMEOUT")
        if probe_timeout:
            file.write(f"CL2_PROBE_TIMEOUT: {probe_timeout}\n")

        # Pass job index for unique namespace naming across parallel runs
        job_index = os.environ.get("CL2_JOB_INDEX")
        if job_index:
            file.write(f"CL2_JOB_INDEX: {job_index}\n")

        if scrape_containerd:
            file.write(f"CL2_SCRAPE_CONTAINERD: {str(scrape_containerd).lower()}\n")
            file.write("CONTAINERD_SCRAPE_INTERVAL: 5m\n")

        if cilium_enabled:
            file.write("CL2_CILIUM_METRICS_ENABLED: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL: 30s\n")

        file.write(f"CL2_SERVICE_TEST: {str(service_test).lower()}\n")

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
        file.write(f"CL2_DS_TEST: {str(ds_test).lower()}\n")

    with open(override_file, 'r', encoding='utf-8') as f:
        print(f"Content of file {override_file}:\n{f.read()}")


def validate_clusterloader2(node_count, operation_timeout_in_minutes=10, node_label=""):
    kube_client = KubernetesClient()
    ready_node_count = 0
    expected_node_count = node_count
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    while time.time() < timeout:
        ready_nodes = kube_client.get_ready_nodes(label_selector=node_label)
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.")
        if ready_node_count == expected_node_count:
            break
        print(f"Waiting for {expected_node_count} nodes to be ready.")
        time.sleep(10)
    if ready_node_count != expected_node_count:
        raise Exception(f"Only {ready_node_count} nodes are ready, expected {expected_node_count} nodes!")


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
                    cl2_config_file=cl2_config_file, overrides=True, enable_prometheus=False,
                    scrape_containerd=scrape_containerd)


def collect_clusterloader2(
    cpu_per_node,
    node_count,
    pods_per_step,
    pods_per_node,
    max_pods,
    repeats,
    pods_per_pni,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    service_test,
    cnp_test,
    ccnp_test,
    ds_test,
    result_file,
    test_type,
    start_timestamp
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent=2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]
    provider = json.loads(cloud_info)["cloud"]
    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    pod_count = node_count * pods_per_node

    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "cpu_per_node": cpu_per_node,
        "node_count": node_count,
        "pod_count": pod_count,
        "pods_per_pni": pods_per_pni,
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
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, 'r', encoding='utf-8') as jf:
            print(f"Processing {file_path}")
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(jf.read())
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
    with open(result_file, 'w', encoding='utf-8') as rf:
        rf.write(content)


def main():
    parser = argparse.ArgumentParser(description="SwiftV2 clusterloader2 orchestration.")
    subparsers = parser.add_subparsers(dest="command")

    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("cpu_per_node", type=int)
    parser_configure.add_argument("node_count", type=int)
    parser_configure.add_argument("pods_per_step", type=int)
    parser_configure.add_argument("pods_per_node", type=int)
    parser_configure.add_argument("max_pods", type=int, nargs='?', default=0)
    parser_configure.add_argument("repeats", type=int)
    parser_configure.add_argument("operation_timeout", type=str)
    parser_configure.add_argument("provider", type=str)
    parser_configure.add_argument("cilium_enabled", type=str2bool, choices=[True, False], default=False)
    parser_configure.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False)
    parser_configure.add_argument("service_test", type=str2bool, choices=[True, False], default=False)
    parser_configure.add_argument("cnp_test", type=str2bool, choices=[True, False], nargs='?', default=False)
    parser_configure.add_argument("ccnp_test", type=str2bool, choices=[True, False], nargs='?', default=False)
    parser_configure.add_argument("ds_test", type=str2bool, choices=[True, False], nargs='?', default=False)
    parser_configure.add_argument("num_cnps", type=int, nargs='?', default=0)
    parser_configure.add_argument("num_ccnps", type=int, nargs='?', default=0)
    parser_configure.add_argument("dualstack", type=str2bool, choices=[True, False], nargs='?', default=False)
    parser_configure.add_argument("pods_per_pni", type=int, nargs='?', default=0)
    parser_configure.add_argument("existing_pods", type=int, nargs='?', default=0)
    parser_configure.add_argument("cl2_override_file", type=str)

    parser_validate = subparsers.add_parser("validate", help="Validate cluster setup")
    parser_validate.add_argument("node_count", type=int)
    parser_validate.add_argument("operation_timeout", type=int, default=600)
    parser_validate.add_argument("node_label", type=str)

    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cl2_image", type=str)
    parser_execute.add_argument("cl2_config_dir", type=str)
    parser_execute.add_argument("cl2_report_dir", type=str)
    parser_execute.add_argument("cl2_config_file", type=str)
    parser_execute.add_argument("kubeconfig", type=str)
    parser_execute.add_argument("provider", type=str)
    parser_execute.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False)

    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("cpu_per_node", type=int)
    parser_collect.add_argument("node_count", type=int)
    parser_collect.add_argument("pods_per_step", type=int)
    parser_collect.add_argument("pods_per_node", type=int)
    parser_collect.add_argument("max_pods", type=int, nargs='?', default=0)
    parser_collect.add_argument("repeats", type=int)
    parser_collect.add_argument("pods_per_pni", type=int, nargs='?', default=0)
    parser_collect.add_argument("cl2_report_dir", type=str)
    parser_collect.add_argument("cloud_info", type=str)
    parser_collect.add_argument("run_id", type=str)
    parser_collect.add_argument("run_url", type=str)
    parser_collect.add_argument("service_test", type=str2bool, choices=[True, False], default=False)
    parser_collect.add_argument("cnp_test", type=str2bool, choices=[True, False], nargs='?', default=False)
    parser_collect.add_argument("ccnp_test", type=str2bool, choices=[True, False], nargs='?', default=False)
    parser_collect.add_argument("ds_test", type=str2bool, choices=[True, False], nargs='?', default=False)
    parser_collect.add_argument("result_file", type=str)
    parser_collect.add_argument("test_type", type=str, nargs='?', default="default-config")
    parser_collect.add_argument("start_timestamp", type=str)

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(args.cpu_per_node, args.node_count, args.pods_per_step, args.pods_per_node, args.max_pods,
                                 args.repeats, args.operation_timeout, args.provider,
                                 args.cilium_enabled, args.scrape_containerd,
                                 args.service_test, args.cnp_test, args.ccnp_test, args.ds_test,
                                 args.num_cnps, args.num_ccnps, args.dualstack, args.pods_per_pni,
                                 args.existing_pods, args.cl2_override_file)
    elif args.command == "validate":
        validate_clusterloader2(args.node_count, args.operation_timeout, args.node_label)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.cl2_config_file,
                               args.kubeconfig, args.provider, args.scrape_containerd)
    elif args.command == "collect":
        collect_clusterloader2(args.cpu_per_node, args.node_count, args.pods_per_step, args.pods_per_node, args.max_pods, args.repeats,
                               args.pods_per_pni, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url,
                               args.service_test, args.cnp_test, args.ccnp_test, args.ds_test,
                               args.result_file, args.test_type, args.start_timestamp)


if __name__ == "__main__":
    main()
