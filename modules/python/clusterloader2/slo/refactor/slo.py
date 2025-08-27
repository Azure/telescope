import argparse
import time
from datetime import datetime, timezone

from utils.common import str2bool
from modules.python.clusterloader2.slo.refactor.ClusterLoader2Base import ClusterLoader2Base
from clients.kubernetes_client import KubernetesClient
from clusterloader2.utils import (
    run_cl2_command, 
    process_cl2_reports,
    parse_test_results,
    write_to_file
)


DEFAULT_PODS_PER_NODE = 40

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


class SloArgsParser(ClusterLoader2Base.ArgsParser):
    _parser: argparse.ArgumentParser
    _subparsers: argparse.ArgumentParser

    def __init__(self):
        super().__init__()
        self._parser = argparse.ArgumentParser(description="SLO Kubernetes resources.")
        self._subparsers = self._parser.add_subparsers(dest="command")

    def add_configure_args(self):
        # Sub-command for configure_clusterloader2
        parser_configure = self._subparsers.add_parser("configure", help="Override CL2 config file")
        parser_configure.add_argument("cpu_per_node", type=int, help="CPU per node")
        parser_configure.add_argument("node_count", type=int, help="Number of nodes")
        parser_configure.add_argument("node_per_step", type=int, help="Number of nodes per scaling step")
        parser_configure.add_argument("max_pods", type=int, nargs='?', default=0, help="Maximum number of pods per node")
        parser_configure.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
        parser_configure.add_argument("operation_timeout", type=str, help="Timeout before failing the scale up test")
        parser_configure.add_argument("provider", type=str, help="Cloud provider name")
        parser_configure.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False,
                                        help="Whether to scrape containerd metrics. Must be either True or False")
        parser_configure.add_argument("service_test", type=str2bool, choices=[True, False], default=False,
                                        help="Whether service test is running. Must be either True or False")
        parser_configure.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    def add_validate_args(self):
        parser_validate = self._subparsers.add_parser("validate", help="Validate cluster setup")
        parser_validate.add_argument("node_count", type=int, help="Number of desired nodes")
        parser_validate.add_argument("operation_timeout", type=int, default=600, help="Operation timeout to wait for nodes to be ready")
        
    def add_execute_args(self):
        parser_execute = self._subparsers.add_parser("execute", help="Execute scale up operation")
        parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
        parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
        parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
        parser_execute.add_argument("cl2_config_file", type=str, help="Path to the CL2 config file")
        parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
        parser_execute.add_argument("provider", type=str, help="Cloud provider name")
        parser_execute.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False,
                                    help="Whether to scrape containerd metrics. Must be either True or False")        

    def add_collect_args(self):
        parser_collect = self._subparsers.add_parser("collect", help="Collect scale up data")
        parser_collect.add_argument("cpu_per_node", type=int, help="CPU per node")
        parser_collect.add_argument("node_count", type=int, help="Number of nodes")
        parser_collect.add_argument("max_pods", type=int, nargs='?', default=0, help="Maximum number of pods per node")
        parser_collect.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
        parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
        parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
        parser_collect.add_argument("run_id", type=str, help="Run ID")
        parser_collect.add_argument("run_url", type=str, help="Run URL")
        parser_collect.add_argument("service_test", type=str2bool, choices=[True, False], default=False,
                                    help="Whether service test is running. Must be either True or False")
        parser_collect.add_argument("result_file", type=str, help="Path to the result file")
        parser_collect.add_argument("test_type", type=str, nargs='?', default="default-config",
                                    help="Description of test type")
        
    def parse(self) -> argparse.Namespace:
        return self._parser.parse_args()

    def print_help(self):
        self._parser.print_help()


class SloRunner(ClusterLoader2Base.Runner):
    _args: argparse.Namespace

    def __init__(self, args: argparse.Namespace):
        super.__init__()
        self._args = args

    def configure(self):
        steps = self._args.node_count // self._args.node_per_step
        throughput, nodes_per_namespace, pods_per_node, cpu_request = self.calculate_config()

        config = {
            f"CL2_NODES": f"{self._args.node_count}",
            f"CL2_LOAD_TEST_THROUGHPUT": f"{throughput}",
            f"CL2_NODES_PER_NAMESPACE": f"{nodes_per_namespace}",
            f"CL2_NODES_PER_STEP": f"{self._args.node_per_step}",
            f"CL2_PODS_PER_NODE": f"{pods_per_node}",
            f"CL2_DEPLOYMENT_SIZE": f"{pods_per_node}",
            f"CL2_LATENCY_POD_CPU": f"{cpu_request}",
            f"CL2_REPEATS": f"{self._args.repeats}",
            f"CL2_STEPS": f"{steps}",
            f"CL2_OPERATION_TIMEOUT": f"{self._args.operation_timeout}",
            "CL2_PROMETHEUS_TOLERATE_MASTER": "true",
            "CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR": "100.0",
            "CL2_PROMETHEUS_MEMORY_SCALE_FACTOR": "100.0",
            "CL2_PROMETHEUS_CPU_SCALE_FACTOR": "30.0",
            "CL2_PROMETHEUS_NODE_SELECTOR": "\"prometheus: \\\"true\\\"\"",
            "CL2_POD_STARTUP_LATENCY_THRESHOLD": "3m",
        }

        if self._args.scrape_containerd:
            config.update({
                f"CL2_SCRAPE_CONTAINERD": str(self._args.scrape_containerd).lower(),
                "CONTAINERD_SCRAPE_INTERVAL": "5m",
            })

        if self._args.service_test:
            config.update({ "CL2_SERVICE_TEST:" "true" })
        else:
            config.update({ "CL2_SERVICE_TEST:" "false" })

        write_to_file(
            logger=None,
            filename=self._args.override_file,
            content="\n".join([f"{k}: {v}" for k, v in config.items()])
        )
    
    def validate(self):
        node_count = self._args.node_count
        operation_timeout = getattr(self._args, 'operation_timeout', 10)
        
        kube_client = KubernetesClient()
        ready_node_count = 0
        timeout = time.time() + (operation_timeout * 60)
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

    def execute(self):
        overrides=True
        enable_prometheus=True
        
        run_cl2_command(
            self._args.kubeconfig, 
            self._args.cl2_image, 
            self._args.cl2_config_dir, 
            self._args.cl2_report_dir, 
            self._args.provider,
            cl2_config_file=self._args.cl2_config_file, 
            overrides=overrides, 
            enable_prometheus=enable_prometheus,
            scrape_containerd=self._args.scrape_containerd
        )

    def collect(self):
        status, _ = parse_test_results(self._args.cl2_report_dir)

        _, _, pods_per_node, _ = self.calculate_config()
        pod_count = self._args.node_count * pods_per_node

        # TODO: Expose optional parameter to include test details
        template = {
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "cpu_per_node": self._args.cpu_per_node,
            "node_count": self._args.node_count,
            "pod_count": pod_count,
            "churn_rate": self._args.repeats,
            "status": status,
            "group": None,
            "measurement": None,
            "result": None,
            # "test_details": details,
            "cloud_info": self._args.cloud_info,
            "run_id": self._args.run_id,
            "run_url": self._args.run_url,
            "test_type": self._args.test_type,
        }

        content = process_cl2_reports(self._args.cl2_report_dir, template)

        write_to_file(
            filename=self._args.result_file,
            content=content
        )

    def calculate_config(self):
        throughput = 100
        nodes_per_namespace = min(self._args.node_count, DEFAULT_NODES_PER_NAMESPACE)

        pods_per_node = DEFAULT_PODS_PER_NODE
        if self._args.service_test:
            pods_per_node = self._args.max_pods

        # Different cloud has different reserved values and number of daemonsets
        # Using the same percentage will lead to incorrect nodes number as the number of nodes grow
        # For AWS, see: 
        #   https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/bootstrap.sh#L290
        # For Azure, see: 
        #   https://learn.microsoft.com/en-us/azure/aks/node-resource-reservations#cpu-reservations
        capacity = CPU_CAPACITY[self._args.provider]
        cpu_request = (self._args.cpu_per_node * 1000 * capacity) // pods_per_node
        cpu_request = max(cpu_request, CPU_REQUEST_LIMIT_MILLI)

        return throughput, nodes_per_namespace, pods_per_node, cpu_request


class Slo(ClusterLoader2Base):
    def __init__(self):
        super().__init__()
        self._args_parser = SloArgsParser()
        self._runner = None

    @property
    def args_parser(self):
        return self._args_parser

    @property
    def runner(self):
        if self._runner is None:
            self._runner = SloRunner(self.parse_arguments())
        return self._runner


if __name__ == "__main__":  
    slo = Slo()
    slo.parse_arguments()
    slo.perform()
