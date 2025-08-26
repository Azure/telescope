import argparse
from dataclasses import dataclass
from enum import Enum

from utils.common import str2bool
from base import ClusterLoader2Base


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
    def __init__(self, args: argparse.Namespace):
        super.__init__()
        self._args = args

    def configure(self):
        pass
    
    def validate(self):
        pass
    
    def execute(self):
        pass
    
    def collect(self):
        pass    


class Slo(ClusterLoader2Base):
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

    def __init__(self):
        super().__init__()
        self._args_parser = SloArgsParser()
        self._runner = None

    def calculate_config(
        self,
        cpu_per_node, 
        node_count, 
        max_pods, 
        provider, 
        service_test
    ):
        throughput = 100
        nodes_per_namespace = min(node_count, self.DEFAULT_NODES_PER_NAMESPACE)

        pods_per_node = self.DEFAULT_PODS_PER_NODE
        if service_test:
            pods_per_node = max_pods

        # Different cloud has different reserved values and number of daemonsets
        # Using the same percentage will lead to incorrect nodes number as the number of nodes grow
        # For AWS, see: https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/bootstrap.sh#L290
        # For Azure, see: https://learn.microsoft.com/en-us/azure/aks/node-resource-reservations#cpu-reservations
        capacity = self.CPU_CAPACITY[provider]
        cpu_request = (cpu_per_node * 1000 * capacity) // pods_per_node
        cpu_request = max(cpu_request, self.CPU_REQUEST_LIMIT_MILLI)

        return throughput, nodes_per_namespace, pods_per_node, cpu_request

    @property
    def args_parser(self):
        return self._args_parser

    @property
    def runner(self):
        if self._runner is None:
            self._runner = SloRunner(self.parse_arguments())
        return self._runner

    def parse_arguments(self):
        super().parse_arguments()

    def perform(self):
        super().perform()

if __name__ == "__main__":  
    slo = Slo()
    slo.parse_arguments()
    slo.perform()

