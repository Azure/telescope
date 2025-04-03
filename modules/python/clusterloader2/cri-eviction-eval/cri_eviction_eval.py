
import os
import argparse

from utils import  run_cl2_command
from kubernetes_client import KubernetesClient
from cluster_controller import ClusterController, KubeletConfig
from cl2_configurator import  CL2Configurator
from cl2_file_handler import CL2FileHandler, KubeletMetrics

def override_config_clusterloader2(cluster_controller, file_handler: CL2FileHandler, node_count, max_pods, operation_timeout_seconds, load_type,  provider):
    cluster_controller.validate(node_count)
    node_resource_config = cluster_controller.populate_node_resources()

    # max_pods : int, kubelet_config: KubeletConfig, timeout_seconds:int, provider:str
    eviction_eval = CL2Configurator( max_pods, operation_timeout_seconds, provider)
    eviction_eval.generate_cl2_override(node_resource_config, load_type)
    file_handler.export_cl2_override(node_count, eviction_eval)

def execute_clusterloader2(cluster_controller, file_handler, kubelet_config: KubeletConfig, cl2_image, kubeconfig: str, provider: str):
    print(f"CL2 image: {cl2_image}, kubeconfig: {kubeconfig}, provider: {provider}")
    cluster_controller.reconfigure_kubelet(kubelet_config)
    run_cl2_command(kubeconfig, cl2_image, file_handler.cl2_config_dir, file_handler.cl2_report_dir, provider, overrides=True, enable_prometheus=True,
                    tear_down_prometheus=False, scrape_kubelets=True, scrape_containerd=False)

def collect_clusterloader2(
    cluster_controller: ClusterController,
    file_handler: CL2FileHandler,
    node_count,
    max_pods,
    load_type,
    cloud_info,
    run_id,
    run_url
):
    cluster_controller.verify_measurement()
    print(f"Parsing test result for {node_count} nodes with {max_pods} pods of type {load_type} on {cloud_info}")
    print(f"Run ID: {run_id}, Run URL: {run_url}")
    kubelet_metrics_template = KubeletMetrics(
        node_count= node_count,
        max_pods = max_pods,
        cloud_info = cloud_info,
        churn_rate=1,
        run_id = run_id,
        run_url = run_url,
        load_type = load_type,
        status = "placeholder"
    )
    file_handler.parse_test_result(kubelet_metrics_template)
    file_handler.export_metrics_as_json("results.json")

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

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute resource consume operation")
    parser_execute.add_argument("node_label", type=str, help="Node label selector")
    parser_execute.add_argument("eviction_threshold_mem", type=str, default="100Mi", help="Eviction threshold to evaluate")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
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
    cluster_controller = ClusterController(client, args.node_label)
    file_handler = CL2FileHandler(args.cl2_config_dir, args.cl2_report_dir)

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
        override_config_clusterloader2(cluster_controller, file_handler, args.node_count, args.max_pods, timeout_seconds, args.load_type,  args.provider)

    elif args.command == "execute":
        kubelet_config = KubeletConfig(args.eviction_hard_memory)
        execute_clusterloader2(cluster_controller, file_handler, kubelet_config, args.cl2_image,  args.kubeconfig, args.provider)
    elif args.command == "collect":
            collect_clusterloader2(cluster_controller, file_handler, args.node_count, args.max_pods, args.load_type, args.cloud_info, args.run_id, args.run_url)

if __name__ == "__main__":
    KubeletConfig.set_default_config("100Mi")
    main()
