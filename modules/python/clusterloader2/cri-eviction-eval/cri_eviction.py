import json
import os
import argparse

from datetime import datetime, timezone

from utils import parse_xml_to_json, run_cl2_command, get_measurement
from kubernetes_client import KubernetesClient, client as k8s_client
from data_type import NodeResourceConfigurator
from kubelet_configurator import KubeletConfig
from eviction_eval_configurator import EvictionEval

def verify_measurement(node_label):
    client = KubernetesClient(os.path.expanduser("~/.kube/config"))
    node_selector = f"{node_label}=true"
    nodes = client.get_nodes(label_selector=node_selector)
    user_pool = [node.metadata.name for node in nodes]
    print(f"User pool: {user_pool}")
    # Create an API client
    api_client = k8s_client.ApiClient()
    for node_name in user_pool:
        url = f"/api/v1/nodes/{node_name}/proxy/metrics"
        try:
            response = api_client.call_api(
                resource_path=url,
                method="GET",
                auth_settings=['BearerToken'],
                response_type="str",
                _preload_content=True
            )

            metrics = response[0]  # The first item contains the response data
            filtered_metrics = "\n".join(
                line for line in metrics.splitlines() if line.startswith("kubelet_pod_start") or line.startswith("kubelet_runtime_operations")
            )
            print("##[section]Metrics for node:", node_name)
            print(filtered_metrics)

        except k8s_client.ApiException as e:
            print(f"Error fetching metrics: {e}")


def override_config_clusterloader2(client, node_label, node_count, max_pods, operation_timeout_seconds, load_type,  provider, override_file):
    node_config = NodeResourceConfigurator(node_label, node_count)
    node_config.validate(client)
    node_config.populate_node_resources(client)

    # node_count: int, max_pods : int, kubelet_config: KubeletConfig, timeout_seconds:int, provider:str
    eviction_eval = EvictionEval( max_pods, operation_timeout_seconds, provider)
    eviction_eval.generate_cl2_override(node_config, load_type)
    eviction_eval.export_cl2_override(node_config, override_file)


def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, kubeconfig: str, provider: str):
    print(f"CL2 image: {cl2_image}, config dir: {cl2_config_dir}, report dir: {cl2_report_dir}, kubeconfig: {kubeconfig}, provider: {provider}")
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, overrides=True, enable_prometheus=True,
                    tear_down_prometheus=False, scrape_kubelets=True, scrape_containerd=False)

def collect_clusterloader2(
    node_label,
    node_count,
    max_pods,
    load_type,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file
):
    verify_measurement(node_label)
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "node_count": node_count,
        "max_pods": max_pods,
        "churn_rate": 1,
        "load_type": load_type,
        "status": status,
        "group": None,
        "measurement": None,
        "percentile": None,
        "data": None,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url
    }

    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, 'r', encoding='utf-8') as file:
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(file.read())

            if measurement == "ResourceUsageSummary":
                for percentile, items in data.items():
                    template["measurement"] = measurement
                    template["group"] = group_name
                    template["percentile"] = percentile
                    for item in items:
                        template["data"] = item
                        content += json.dumps(template) + "\n"
            elif "dataItems" in data:
                items = data["dataItems"]
                if not items:
                    print(f"No data items found in {file_path}")
                    print(f"Data:\n{data}")
                    continue
                for item in items:
                    template["measurement"] = measurement
                    template["group"] = group_name
                    template["percentile"] = "dataItems"
                    template["data"] = item
                    content += json.dumps(template) + "\n"

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    # Set default values for the current  KubeletConfig

    parser = argparse.ArgumentParser(description="CRI Kubernetes Eviction threshold eval.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for override_config_clusterloader2
    parser_override = subparsers.add_parser("override", help="Override CL2 config file")
    parser_override.add_argument("node_label", type=str, help="Node label selector")
    parser_override.add_argument("node_count", type=int, help="Number of nodes")
    parser_override.add_argument("max_pods", type=int, help="Number of maximum pods per node")
    parser_override.add_argument("operation_timeout", type=str, default="5m", help="Operation timeout")
    parser_override.add_argument("load_type", type=str, choices=["memory", "cpu"], default="memory", help="Type of load to generate")
    parser_override.add_argument("provider", type=str, help="Cloud provider name")
    parser_override.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute resource consume operation")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("eviction_threshold_mem", type=str, default="100Mi", help="Eviction threshold to evaluate")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect resource consume data")
    parser_collect.add_argument("node_label", type=str, help="Node label selector")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("max_pods", type=int, help="Number of maximum pods per node")
    parser_collect.add_argument("load_type", type=str, choices=["memory", "cpu"],
                                 default="memory", help="Type of load to generate")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()
    client = KubernetesClient(os.path.expanduser("~/.kube/config"))
    if args.command == "override":
        # validate operation_timeout if value is not null
        timeout_seconds = 0
        if args.operation_timeout:
            if args.operation_timeout.endswith("m"):  # Check if the string ends with 'm' for minutes
                timeout_seconds = int(args.operation_timeout[:-1]) * 60 # Extract the numeric part and convert to integer
            elif args.operation_timeout.endswith("s"):
                timeout_seconds = int(args.operation_timeout[:-1])
            else:
                raise Exception(f"Unexpected format of operation_timeout property, should end with m (min) or s (second): {args.operation_timeout}")
        override_config_clusterloader2(client, args.node_label, args.node_count, args.max_pods, timeout_seconds, args.load_type,  args.provider, args.cl2_override_file)

    elif args.command == "execute":
        kubelet_config = KubeletConfig(args.eviction_hard_memory)
        kubelet_config.reconfigure_kubelet(client, args.node_label)

        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
            collect_clusterloader2(args.node_label, args.node_count, args.max_pods, args.load_type, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    KubeletConfig.default_config = KubeletConfig("100Mi")
    main()
