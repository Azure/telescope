import json
import os
import argparse
import math

from datetime import datetime, timezone
from multiprocessing.spawn import set_executable

from utils import parse_xml_to_json, run_cl2_command, get_measurement
from kubernetes_client import KubernetesClient, client as k8s_client


DAEMONSETS_PER_NODE_MAP = {
    "aws": 2,
    "aks": 6
}

MEMORY_SCALE_FACTOR = 0.95 # 95% of the total allocatable memory to account for error margin

class NodeConfig:
    def __init__(self, node_label, node_count):
        self.node_label = node_label
        self.node_count = node_count
        self.node_selector = f"{self.node_label}=true"


class KubeletConfig:
    def __init__(self, eviction_hard_memory):
        self.eviction_hard_memory = eviction_hard_memory

    default_config = None

    # function needs_override which return True if the config needs to be overridden by comparing the current config with the default
    def needs_override(self):
        if self.default_config.eviction_hard_memory != self.eviction_hard_memory:
            return True
        return False

    # function generate_kubelet_config which returns the command to override the kubelet config
    def generate_kubelet_config(self):
        # rewrite using string template
        kubelet_flag_override = """
          sed -i 's/--eviction-hard=memory\.available<{default_eviction_memory}/--eviction-hard=memory\.available<{desired_eviction_memory}/' "/etc/default/kubelet"
    """
        return kubelet_flag_override.format(default_eviction_memory=self.default_config.eviction_hard_memory, desired_eviction_memory=self.eviction_hard_memory)


    def generate_kubelet_reconfig_daemonset(self, client, node_selector):
        return None

# resourceconfig has memory and cpu
class ResourceConfig:
    def __init__(self, memory, cpu):
        self.memory_ki = memory
        self.cpu_milli = cpu

    def minus(self, other):
        return ResourceConfig(self.memory_ki - other.memory_ki, self.cpu_milli - other.cpu_milli)

    def divide(self, parts):
        return ResourceConfig(self.memory_ki // parts, self.cpu_milli // parts)

    def multiply(self, factor):
        return ResourceConfig(int(self.memory_ki * factor), int(self.cpu_milli * factor))

class WorkloadConfig:
    def __init__(self, node_count, load_type):
        self.node_count = node_count
        self.load_type = load_type


        self.pods_per_node = None
        self.memory_request_ki_pod = None
        self.memory_consume_mi_pod = None
        self.cpu_request_pod = None
        self.resouce_stress_duration = None

    def debug_resource_info(self, node_allocatable_resources: ResourceConfig, system_allocated_resources: ResourceConfig, remaining_resources: ResourceConfig):
        resource_info_template = """
  memory:
    allocatable: {allocatable_memory}Ki
    allocated: {allocated_memory}Ki
    testRunActual: {actual_memory}Ki
  cpu:
    allocatable: {allocatable_cpu}m
    allocated: {allocated_cpu}m
    testRunActual: {actual_cpu}m
    """

    print(resource_info_template.format(
        allocatable_memory=node_allocatable_resources.memory_ki, allocated_memory=system_allocated_resources.memory_ki, actual_memory=remaining_resources.memory_ki,
        allocatable_cpu=node_allocatable_resources.cpu_milli, allocated_cpu=system_allocated_resources.cpu_milli, actual_cpu=remaining_resources.cpu_milli)
    )

    def debug_stress_info(self, resource_per_pod: ResourceConfig, resource_stress: ResourceConfig, resouce_stress_duration):

        stress_pod_info_template = """
    stressPod: 
      load: {load_type}
      timeout: {timeout}
      memory:
        request: {memory_request}Ki
        limit: {memory_limit}Ki
        consume: {memory_consume}Mi
      cpu:
        request: {cpu_request}m
        limit: {cpu_limit}m
        consume: {cpu_consume}m
    """
        print(stress_pod_info_template.format(
            load_type=load_type, timeout=resouce_stress_duration,
            memory_request=resource_per_pod.memory_ki, memory_limit=resource_per_pod.memory_ki, memory_consume=resource_stress.memory_ki))

    def calculate_workload_spec(self, system_allocated_resources: ResoureceConfig, node_allocatable_resources: ResourceConfig, pods_per_node, operation_timeout_seconds):

        remaining_resources = node_allocatable_resources.minus(system_allocated_resources)
        self.debug_resource_info(node_allocatable_resources, system_allocated_resources, remaining_resources)

        # kubelet default watch is 10 seconds, try to get the pod to consume memory in 10 seconds (and spread over pods)
        resouce_stress_duration = 10 * pods_per_node

        # Limit the resource-consume runtime to clusterloader timeout seconds
        if resouce_stress_duration > operation_timeout_seconds:
            resouce_stress_duration = operation_timeout_seconds

        resource_per_pod = remaining_resources.divide(pods_per_node)
        # greedy behave workload consume memory more than requested to trigger OOM
        resource_stress =  remaining_resources.divide(pods_per_node).multiple(1.1)
        self.debug_stress_info(resource_per_pod, resource_stress, resouce_stress_duration)

class EvictionEval:
    def __init__(self, node_config, kubelet_config, workload_config, max_pods, timeout_seconds, provider):
        self.client = KubernetesClient(os.path.expanduser("~/.kube/config"))
        self.node_config = node_config
        self.kubelet_config = kubelet_config
        self.workload_config = workload_config
        self.max_pods = max_pods
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def setup_cl2_env(self):
        nodes = self.client.get_nodes(label_selector=self.node_config.node_selector)
        if len(nodes) == 0:
            raise Exception(f"Invalid node selector: {self.node_config.node_selector}")

        if self.kubelet_config.needs_override():
            self.reconfigure_kubelet()

        system_allocated_resources =self.get_daemonsets_pods_allocated_resources(nodes[0].metadata.name)
        node_allocatable_resources = self.get_node_available_resource(nodes[0])

        # Calculate the number of pods per node
        pods_per_node = self.max_pods - DAEMONSETS_PER_NODE_MAP[self.provider]
        self.workload_config.calculate_workload_spec(system_allocated_resources, node_allocatable_resources, pods_per_node, self.timeout_seconds)

        print(f"Override with Config: \nNode Counts: {self.node_config.node_count} \nNode Label: {self.node_config.node_label} \nTotal pods: {max_pods}")


    def reconfigure_kubelet(self):
        self.client.create_daemonset("kube-system", self.kubelet_config.generate_kubelet_reconfig_daemonset(self.client, self.node_config.node_selector))

    def get_node_available_resource(self, worker_node) -> ResourceConfig:
        node_allocatable_cpu = int(worker_node.status.allocatable["cpu"].replace("m", ""))

        # Bottlerocket OS SKU on EKS has allocatable_memory property in Mi. AKS and Amazon Linux (default SKUs)
        # user Ki. Handling the Mi case here and converting Mi to Ki, if needed.
        #int(nodes[0].status.allocatable["memory"].replace("Ki", ""))
        node_allocatable_memory_str = worker_node.status.allocatable["memory"]
        if "Mi" in node_allocatable_memory_str:
            node_allocatable_memory_ki = int(node_allocatable_memory_str.replace("Mi", "")) * 1024
        elif "Ki" in node_allocatable_memory_str:
            node_allocatable_memory_ki = int(node_allocatable_memory_str.replace("Ki", ""))
        else:
            raise Exception(f"Unexpected format of allocatable memory node property: {node_allocatable_memory_str}")

        return ResourceConfig( node_allocatable_memory_ki, node_allocatable_cpu)

    def get_daemonsets_pods_allocated_resources(self, node_name) -> ResourceConfig:
        pods = self.client.get_pods_by_namespace("kube-system", field_selector=f"spec.nodeName={node_name}")

        cpu_request = 0
        memory_request = 0
        for pod in pods:
            for container in pod.spec.containers:
                print(f"Pod {pod.metadata.name} has container {container.name} with resources {container.resources.requests}")
                cpu_request += int(container.resources.requests.get("cpu", "0m").replace("m", ""))
                memory_request += int(container.resources.requests.get("memory", "0Mi").replace("Mi", ""))

        return ResourceConfig(memory_request * 1024, cpu_request)


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

class CL2Config:
    def __init__(self, node_config, workload_config):
        self.node_config = node_config
        self.workload_config = workload_config

        self.memory_request_ki_pod = memory_request_ki_pod
        self.memory_consume_mi_pod = memory_consume_mi_pod
        self.resouce_stress_duration = resouce_stress_duration
        self.cpu_request_pod = cpu_request_pod

    def write_override_file(self, override_file):
        print(f"write override file to {override_file}")
        with open(override_file, 'w', encoding='utf-8') as file:
            file.write(f"CL2_DEPLOYMENT_SIZE: {self.workload_config.pods_per_node}\n")
            file.write(f"CL2_OPERATION_TIMEOUT: {self.workload_config.operation_timeout}\n")
            file.write(f"CL2_LOAD_TYPE: {self.workload_config.load_type}\n")

            file.write(f"CL2_NODE_COUNT: {self.node_config.node_count}\n")
            file.write(f"CL2_NODE_LABEL: {self.node_config.node_label}\n")
            file.write(f"CL2_NODE_SELECTOR: {self.node_config.node_selector}\n")

            file.write(f"CL2_RESOURCE_CONSUME_MEMORY_REQUEST_KI: {self.memory_request_ki_pod}Ki\n")
            file.write(f"CL2_RESOURCE_CONSUME_MEMORY_CONSUME_MI: {self.memory_consume_mi_pod}\n")

            file.write(f"CL2_RESOURCE_CONSUME_DURATION_SEC: {self.resouce_stress_duration}\n")
            file.write(f"CL2_RESOURCE_CONSUME_CPU: {self.cpu_request_pod}\n")

            file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
            file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")
            file.write(f"CL2_PROVIDER: {self.provider}\n")

        file.close()

def override_config_clusterloader2( node_label, node_count, max_pods, operation_timeout_seconds, load_type, eviction_hard_memory, provider, override_file):
    node_config = NodeConfig(node_label, node_count)
    kubelet_config = KubeletConfig(eviction_hard_memory)
    workload_config = WorkloadConfig(operation_timeout_seconds, load_type)

    eviction_eval = EvictionEval(node_config, kubelet_config, workload_config, max_pods)
    cl2_config = eviction_eval.get_cl2_config(operation_timeout_seconds, load_type,  provider)


def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, kubeconfig, provider):
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
    KubeletConfig.default_config = KubeletConfig("100Mi")

    parser = argparse.ArgumentParser(description="CRI Kubernetes Eviction threshold eval.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for override_config_clusterloader2
    parser_override = subparsers.add_parser("override", help="Override CL2 config file")
    parser_override.add_argument("node_label", type=str, help="Node label selector")
    parser_override.add_argument("node_count", type=int, help="Number of nodes")
    parser_override.add_argument("max_pods", type=int, help="Number of maximum pods per node")
    parser_override.add_argument("operation_timeout", type=str, default="5m", help="Operation timeout")
    parser_override.add_argument("load_type", type=str, choices=["memory", "cpu"],
                                 default="memory", help="Type of load to generate")
    parser_override.add_argument("provider", type=str, help="Cloud provider name")
    # parser_override.add_argument("eviction_threshold_mem", type=str, help="Eviction threshold to evaluate (e.g., memory.available<750Mi)")

    parser_override.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute resource consume operation")
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

    if args.command == "override":
        # validate operation_timeout if value is not null
        if args.operation_timeout:
            if args.operation_timeout.endswith("m"):  # Check if the string ends with 'm' for minutes
                timeout_seconds = int(args.operation_timeout[:-1]) * 60 # Extract the numeric part and convert to integer
            elif args.operation_timeout.endswith("s"):
                timeout_seconds = int(args.operation_timeout[:-1])
            else:
                raise Exception(f"Unexpected format of operation_timeout property, should end with m (min) or s (second): {args.operation_timeout}")
        override_config_clusterloader2(args.node_label, args.node_count, args.max_pods, timeout_seconds, args.load_type, args.provider, args.cl2_override_file)

    elif args.command == "execute":
            execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
            collect_clusterloader2(args.node_label, args.node_count, args.max_pods, args.load_type, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()
