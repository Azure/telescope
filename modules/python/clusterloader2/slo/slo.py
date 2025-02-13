import json
import os
import argparse
import time

from datetime import datetime, timezone
from utils import parse_xml_to_json, run_cl2_command, get_measurement
from kubernetes_client import KubernetesClient

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

<<<<<<< HEAD
def calculate_config(cpu_per_node, node_per_step, pods_per_node, provider):
=======
def calculate_config(cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test):
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf
    throughput = 100
    nodes_per_namespace = min(node_per_step, DEFAULT_NODES_PER_NAMESPACE)

    if cnp_test or ccnp_test:
        pods_per_node = max_pods
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
    max_pods,
    pods_per_node,
    repeats,
    operation_timeout,
    no_of_namespaces,
    total_network_policies,
    provider,
    cilium_enabled,
    service_test,
<<<<<<< HEAD
    network_test,
    override_file):

    steps = node_count // node_per_step
    throughput, nodes_per_namespace, cpu_request = calculate_config(cpu_per_node, node_per_step, pods_per_node, provider)
=======
    cnp_test, 
    ccnp_test,
    num_cnps,
    num_ccnps,
    dualstack,
    override_file):

    steps = node_count // node_per_step
    throughput, nodes_per_namespace, pods_per_node, cpu_request = calculate_config(cpu_per_node, node_per_step, max_pods, provider, service_test, cnp_test, ccnp_test)
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf

    with open(override_file, 'w') as file:
        file.write(f"CL2_LOAD_TEST_THROUGHPUT: {throughput}\n")
        #file.write(f"CL2_NODES_PER_NAMESPACE: {nodes_per_namespace}\n"): TEMP
        file.write(f"CL2_NODES_PER_STEP: {node_per_step}\n")
        file.write(f"CL2_NODES: {node_count}\n")
        file.write(f"CL2_PODS_PER_NODE: {pods_per_node}\n")
        file.write(f"CL2_DEPLOYMENT_SIZE: {pods_per_node}\n")
        file.write(f"CL2_LATENCY_POD_CPU: {cpu_request}\n")
        file.write(f"CL2_REPEATS: {repeats}\n")
        file.write(f"CL2_STEPS: {steps}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write(f"CL2_NO_OF_NAMESPACES: {no_of_namespaces}\n")
        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")
        file.write("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m\n")

        if cilium_enabled:
            file.write("CL2_CILIUM_METRICS_ENABLED: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL: 30s\n")

        if service_test:
            file.write("CL2_SERVICE_TEST: true\n")
        else:
            file.write("CL2_SERVICE_TEST: false\n")

<<<<<<< HEAD
        if network_test:
            file.write("CL2_NETWORK_TEST: true\n")
            file.write("CL2_ENABLE_NETWORK_POLICY_ENFORCEMENT_LATENCY_TEST: true\n")
            file.write("CL2_ENABLE_VIOLATIONS_FOR_API_CALL_PROMETHEUS_SIMPLE: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_KUBE_PROXY: true\n")
            file.write("CL2_NETWORK_PROGRAMMING_LATENCY_THRESHOLD: 30s\n")
            file.write("CL2_ENABLE_VIOLATIONS_FOR_NETWORK_PROGRAMMING_LATENCIES: false\n")
            file.write("CL2_NETWORK_LATENCY_THRESHOLD: 0s\n")
            file.write("CL2_PROBE_MEASUREMENTS_PING_SLEEP_DURATION: 1s\n")
            file.write("CL2_ENABLE_IN_CLUSTER_NETWORK_LATENCY: true\n")
            file.write("CL2_PROBE_MEASUREMENTS_CHECK_PROBES_READY_TIMEOUT: 15m\n")
            file.write("CL2_NETWORK_POLICY_ENFORCEMENT_LATENCY_BASELINE: false\n")
            file.write("CL2_NET_POLICY_ENFORCEMENT_LATENCY_TARGET_LABEL_KEY: net-pol-test\n")
            file.write("CL2_NET_POLICY_ENFORCEMENT_LATENCY_TARGET_LABEL_VALUE: enforcement-latency\n")
            #file.write("CL2_NET_POLICY_ENFORCEMENT_LATENCY_NODE_LABEL_KEY: test\n")
            file.write("CL2_NET_POLICY_ENFORCEMENT_LATENCY_NODE_LABEL_VALUE: net-policy-client\n")
            file.write("CL2_NET_POLICY_ENFORCEMENT_LATENCY_MAX_TARGET_PODS_PER_NS: 100\n")
            file.write(f"CL2_NET_POLICY_ENFORCEMENT_LOAD_COUNT: {total_network_policies}\n")
            file.write("CL2_NET_POLICY_ENFORCEMENT_LOAD_QPS: 10\n")
            file.write("CL2_POLICY_ENFORCEMENT_LOAD_TARGET_NAME: small-deployment\n")
=======
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
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf

    with open(override_file, 'r') as file:
        print(f"Content of file {override_file}:\n{file.read()}")

    file.close()

def validate_clusterloader2(node_count, operation_timeout_in_minutes=10):
    kube_client = KubernetesClient()
    ready_node_count = 0
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    while time.time() < timeout:
        ready_nodes = kube_client.get_ready_nodes()
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.")
        if ready_node_count == node_count:
            break
        print(f"Waiting for {node_count} nodes to be ready.")
        time.sleep(10)
    if ready_node_count != node_count:
        raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")

def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, cl2_config_file, kubeconfig, provider):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, cl2_config_file=cl2_config_file, overrides=True, enable_prometheus=True)

def collect_clusterloader2(
    cpu_per_node,
    node_count,
    max_pods,
    pods_per_node,
    repeats,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    service_test,
<<<<<<< HEAD
    network_test,
=======
    cnp_test, 
    ccnp_test,
    num_cnps,
    num_ccnps,
    dualstack,
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf
    result_file,
    start_timestamp,
    test_type="default_config",
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]
    provider = json.loads(cloud_info)["cloud"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

<<<<<<< HEAD
=======
    _, _, pods_per_node, _ = calculate_config(cpu_per_node, node_count, max_pods, provider, service_test, cnp_test, ccnp_test)
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf
    pod_count = node_count * pods_per_node

    # TODO: Expose optional parameter to include test details
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
        "start_timestamp": start_timestamp,
        "test_type": test_type,
    }
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, 'r') as f:
            print(f"Processing {file_path}")
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(f.read())

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
    with open(result_file, 'w') as f:
        f.write(content)

def main():
    parser = argparse.ArgumentParser(description="SLO Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("cpu_per_node", type=int, help="CPU per node")
    parser_configure.add_argument("node_count", type=int, help="Number of nodes")
    parser_configure.add_argument("node_per_step", type=int, help="Number of nodes per scaling step")
<<<<<<< HEAD
    parser_configure.add_argument("max_pods", type=int, help="Maximum number of pods per node")
    parser_configure.add_argument("pods_per_node", type=int, help="Number of pods per node")
=======
    parser_configure.add_argument("max_pods", type=int, nargs='?', default=0, help="Maximum number of pods per node")
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf
    parser_configure.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_configure.add_argument("operation_timeout", type=str, help="Timeout before failing the scale up test")
    parser_configure.add_argument("no_of_namespaces", type=int, default=1, help="Number of namespaces to create")
    parser_configure.add_argument("total_network_policies", type=int, default=0, help="Total number of network policies to create")
    parser_configure.add_argument("provider", type=str, help="Cloud provider name")
    parser_configure.add_argument("cilium_enabled", type=eval, choices=[True, False], default=False,
                                  help="Whether cilium is enabled. Must be either True or False")
    parser_configure.add_argument("service_test", type=eval, choices=[True, False], default=False,
                                  help="Whether service test is running. Must be either True or False")
<<<<<<< HEAD
    parser_configure.add_argument("network_test", type=eval, choices=[True, False], default=False,
                                  help="Whether network test is running. Must be either True or False")
=======
    parser_configure.add_argument("cnp_test", type=eval, choices=[True, False], nargs='?', default=False,
                                  help="Whether cnp test is running. Must be either True or False")
    parser_configure.add_argument("ccnp_test", type=eval, choices=[True, False], nargs='?', default=False,
                                  help="Whether ccnp test is running. Must be either True or False")
    parser_configure.add_argument("num_cnps", type=int, nargs='?', default=0, help="Number of cnps")
    parser_configure.add_argument("num_ccnps", type=int, nargs='?', default=0, help="Number of ccnps")
    parser_configure.add_argument("dualstack", type=eval, choices=[True, False], nargs='?', default=False,
                                  help="Whether cluster is dualstack. Must be either True or False")
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf
    parser_configure.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for validate_clusterloader2
    parser_validate = subparsers.add_parser("validate", help="Validate cluster setup")
    parser_validate.add_argument("node_count", type=int, help="Number of desired nodes")
    parser_validate.add_argument("operation_timeout", type=int, default=600, help="Operation timeout to wait for nodes to be ready")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("cl2_config_file", type=str, help="Path to the CL2 config file")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("cpu_per_node", type=int, help="CPU per node")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
<<<<<<< HEAD
    parser_collect.add_argument("max_pods", type=int, help="Maximum number of pods per node")
    parser_collect.add_argument("pods_per_node", type=int, help="Number of pods per node")
=======
    parser_collect.add_argument("max_pods", type=int, nargs='?', default=0, help="Maximum number of pods per node")
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf
    parser_collect.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("service_test", type=eval, choices=[True, False], default=False,
                                  help="Whether service test is running. Must be either True or False")
<<<<<<< HEAD
    parser_collect.add_argument("network_test", type=eval, choices=[True, False], default=False,
                                  help="Whether network test is running. Must be either True or False")
=======
    parser_collect.add_argument("cnp_test", type=eval, choices=[True, False], nargs='?', default=False,
                                  help="Whether cnp test is running. Must be either True or False")
    parser_collect.add_argument("ccnp_test", type=eval, choices=[True, False], nargs='?', default=False,
                                  help="Whether ccnp test is running. Must be either True or False")
    parser_collect.add_argument("num_cnps", type=int, nargs='?', default=0, help="Number of cnps")
    parser_collect.add_argument("num_ccnps", type=int, nargs='?', default=0, help="Number of ccnps")
    parser_collect.add_argument("dualstack", type=eval, choices=[True, False], nargs='?', default=False,
                                  help="Whether cluster is dualstack. Must be either True or False")
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")
    parser_collect.add_argument("start_timestamp", type=str, help="Test start timestamp")
    parser_collect.add_argument("test_type", type=str, nargs='?', default="default-config",
                                help="Description of test type")

    args = parser.parse_args()
    
    if args.command == "configure":
        configure_clusterloader2(args.cpu_per_node, args.node_count, args.node_per_step, args.max_pods,
<<<<<<< HEAD
                                 args.pods_per_node, args.repeats, args.operation_timeout, args.no_of_namespaces,
                                 args.total_network_policies, args.provider,
                                 args.cilium_enabled, args.service_test, args.network_test, args.cl2_override_file)
=======
                                 args.repeats, args.operation_timeout, args.provider, args.cilium_enabled,
                                 args.service_test, args.cnp_test, args.ccnp_test, args.num_cnps, args.num_ccnps, args.dualstack, args.cl2_override_file)
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf
    elif args.command == "validate":
        validate_clusterloader2(args.node_count, args.operation_timeout)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.cl2_config_file,
                               args.kubeconfig, args.provider)
    elif args.command == "collect":
<<<<<<< HEAD
        collect_clusterloader2(args.cpu_per_node, args.node_count, args.max_pods, args.pods_per_node,
                               args.repeats, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url,
                               args.service_test, args.network_test, args.result_file, args.start_timestamp, args.test_type)
=======
        collect_clusterloader2(args.cpu_per_node, args.node_count, args.max_pods, args.repeats,
                               args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url,
                               args.service_test, args.cnp_test, args.ccnp_test, args.num_cnps, args.num_ccnps, args.dualstack, args.result_file, args.test_type)
>>>>>>> 918ad2bc4af344106fa0309cb6d7c5db4f2aa2bf

if __name__ == "__main__":
    main()
