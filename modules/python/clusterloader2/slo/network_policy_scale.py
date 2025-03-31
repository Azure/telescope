import json
import os
import argparse
import time

from datetime import datetime, timezone
from clusterloader2.utils import parse_xml_to_json, get_measurement,run_cl2_command
from clusterloader2.kubernetes_client import KubernetesClient



def configure_clusterloader2(
    number_of_groups,
    clients_per_group,
    servers_per_group,
    workers_per_client,
    netpol_type,
    test_duration_secs,
    cilium_enabled,
    cilium_envoy_enabled,
    override_file,
):
    # Ensure the directory for override_file exists
    override_dir = os.path.dirname(override_file)
    if not os.path.exists(override_dir):
        os.makedirs(override_dir, exist_ok=True)

    with open(override_file, "w", encoding="utf-8") as file:
        # prometheus server config
        file.write("# Prometheus server config\n")
        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
        file.write('CL2_PROMETHEUS_NODE_SELECTOR: "prometheus: \\"true\\""\n')
        file.write("CL2_ENABLE_IN_CLUSTER_NETWORK_LATENCY: false\n")
        file.write("PROMETHEUS_SCRAPE_KUBE_PROXY: false\n")

        if cilium_enabled:
            file.write("# Cilium config\n")
            file.write("CL2_CILIUM_ENABLED: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL: 30s\n")

        if cilium_envoy_enabled:
            file.write("# Cilium Envoy config\n")
            file.write("CL2_CILIUM_ENVOY_ENABLED: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_ENVOY: true\n")

        # test config
        # add "s" at the end of test_duration_secs
        file.write("# Test config\n")
        test_duration = str(test_duration_secs) + "s"
        # Test config
        # add "s" at the end of test_duration_secs
        file.write("# Test config\n")
        test_duration = f"{test_duration_secs}s"
        file.write(f"CL2_DURATION: {test_duration}\n")
        file.write(f"CL2_NUMBER_OF_CLIENTS_PER_GROUP: {clients_per_group}\n")
        file.write(f"CL2_NUMBER_OF_SERVERS_PER_GROUP: {servers_per_group}\n")
        file.write(f"CL2_WORKERS_PER_CLIENT: {workers_per_client}\n")
        file.write(f"CL2_NUMBER_OF_GROUPS: {number_of_groups}\n")
        file.write(f"CL2_NETWORK_POLICY_TYPE: {netpol_type}\n")
        file.write("CL2_CLIENT_METRICS_GATHERING: true\n")

        # Disable non related tests in measurements.yaml
        file.write("# Disable non related tests in measurements.yaml\n")
        file.write("CL2_ENABLE_IN_CLUSTER_NETWORK_LATENCY: false\n")

    with open(override_file, "r", encoding="utf-8") as file:
        print(f"Content of file {override_file}:\n{file.read()}")

    file.close()

def validate_clusterloader2(node_count=2, operation_timeout_in_minutes=10):
    kube_client = KubernetesClient()
    ready_node_count = 0
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    while time.time() < timeout:
        ready_nodes = kube_client.get_ready_nodes()
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.")
        if ready_node_count >= node_count:
            break
        print(f"Waiting for {node_count} nodes to be ready.")
        time.sleep(10)
    if ready_node_count < node_count:
        raise Exception(
            f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!"
        )


def execute_clusterloader2(
    cl2_image, cl2_config_dir, cl2_report_dir, cl2_config_file, kubeconfig, provider, scrape_containerd
):
    run_cl2_command(
        kubeconfig,
        cl2_image,
        cl2_config_dir,
        cl2_report_dir,
        provider,
        cl2_config_file=cl2_config_file,
        overrides=True,
        enable_prometheus=True,
        scrape_containerd=scrape_containerd
    )

def collect_clusterloader2(
    node_count,
    pod_count,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file,
    test_type,
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent=2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]
    provider = json.loads(cloud_info)["cloud"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    # TODO: Expose optional parameter to include test details
    template = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "node_count": node_count,
        "pod_count": pod_count,
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        "cloud_info": provider,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
    }
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

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    # os.chmod(os.path.dirname(result_file), 0o755)  # Ensure the directory is writable
    with open(result_file, "w", encoding="utf-8") as file:
        file.write(content)


def main():
    parser = argparse.ArgumentParser(description="Network Policy Scale Test")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser(
        "configure", help="Configure ClusterLoader2 overrides file"
    )
    parser_configure.add_argument(
        "--number_of_groups",
        type=int,
        required=True,
        help="Number of network policy groups to create",
    )
    parser_configure.add_argument(
        "--clients_per_group",
        type=int,
        required=True,
        help="Number of client pods per group",
    )
    parser_configure.add_argument(
        "--servers_per_group",
        type=int,
        required=True,
        help="Number of server pods per group",
    )
    parser_configure.add_argument(
        "--workers_per_client",
        type=int,
        required=True,
        help="Number of workers per client pod",
    )
    parser_configure.add_argument(
        "--netpol_type",
        type=str,
        required=True,
        choices=["k8s", "cnp", "ccnp"],
        help="Type of network policy",
    )
    parser_configure.add_argument(
        "--test_duration_secs", type=int, required=True, help="Test duration in seconds"
    )
    parser_configure.add_argument(
        "--provider", type=str, required=True, help="Cloud provider name"
    )
    parser_configure.add_argument(
        "--cilium_enabled",
        type=eval,
        choices=[True, False],
        default=False,
        help="Whether cilium is enabled. Must be either True or False",
    )
    parser_configure.add_argument(
        "--cilium_envoy_enabled",
        type=eval,
        choices=[True, False],
        default=False,
        help="Whether cilium envoy is enabled. Must be either True or False",
    )
    parser_configure.add_argument(
        "--cl2_override_file",
        type=str,
        required=True,
        help="Path to the overrides of CL2 config file",
    )

    # Sub-command for validate_clusterloader2
    parser_validate = subparsers.add_parser("validate", help="Validate cluster setup")
    parser_validate.add_argument(
        "--node_count", type=int, help="Number of desired nodes"
    )
    parser_validate.add_argument(
        "--operation_timeout",
        type=int,
        default=600,
        help="Operation timeout to wait for nodes to be ready",
    )

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("--cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument(
        "--cl2_config_dir", type=str, help="Path to the CL2 config directory"
    )
    parser_execute.add_argument(
        "--cl2_report_dir", type=str, help="Path to the CL2 report directory"
    )
    parser_execute.add_argument(
        "--cl2_config_file", type=str, help="Path to the CL2 config file"
    )
    parser_execute.add_argument(
        "--kubeconfig", type=str, help="Path to the kubeconfig file"
    )
    parser_execute.add_argument("--provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("--node_count", type=int, help="Number of nodes")
    parser_collect.add_argument(
        "--pod_count",
        type=int,
        nargs="?",
        default=0,
        help="Maximum number of pods per node",
    )
    parser_collect.add_argument(
        "--cl2_report_dir", type=str, help="Path to the CL2 report directory"
    )
    parser_collect.add_argument("--cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("--run_id", type=str, help="Run ID")
    parser_collect.add_argument("--run_url", type=str, help="Run URL")
    parser_collect.add_argument(
        "--result_file", type=str, help="Path to the result file"
    )
    parser_collect.add_argument(
        "--test_type",
        type=str,
        nargs="?",
        default="default-config",
        help="Description of test type",
    )

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return

    if args.command == "configure":
        configure_clusterloader2(
            args.number_of_groups,
            args.clients_per_group,
            args.servers_per_group,
            args.workers_per_client,
            args.netpol_type,
            args.test_duration_secs,
            args.cilium_enabled,
            args.cilium_envoy_enabled,
            args.cl2_override_file,
        )
    elif args.command == "validate":
        validate_clusterloader2(
            args.node_count,
            args.operation_timeout,
        )
    elif args.command == "execute":
        execute_clusterloader2(
            args.cl2_image,
            args.cl2_config_dir,
            args.cl2_report_dir,
            args.cl2_config_file,
            args.kubeconfig,
            args.provider,
            scrape_containerd=False,  # for network policy scale test, we don't need to scrape containerd for now
        )
    elif args.command == "collect":
        collect_clusterloader2(
            args.node_count,
            args.pod_count,
            args.cl2_report_dir,
            args.cloud_info,
            args.run_id,
            args.run_url,
            args.result_file,
            args.test_type,
        )


if __name__ == "__main__":
    main()
