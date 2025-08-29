import time
from datetime import datetime, timezone
import json

from utils.common import str2bool
from clusterloader2.slo import ClusterLoader2Base
from clients.kubernetes_client import KubernetesClient
from clusterloader2.utils import (
    run_cl2_command, 
    process_cl2_reports,
)
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)

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
    def __init__(self):
        super().__init__(description="SLO Kubernetes resources.")

    def add_configure_args(self, parser_configure):
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

    def add_validate_args(self, parser_validate):
        parser_validate.add_argument("node_count", type=int, help="Number of desired nodes")
        parser_validate.add_argument("operation_timeout", type=int, default=600, help="Operation timeout to wait for nodes to be ready")
        
    def add_execute_args(self, parser_execute):
        parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
        parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
        parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
        parser_execute.add_argument("cl2_config_file", type=str, help="Path to the CL2 config file")
        parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
        parser_execute.add_argument("provider", type=str, help="Cloud provider name")
        parser_execute.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False,
                                    help="Whether to scrape containerd metrics. Must be either True or False")        

    def add_collect_args(self, parser_collect):
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


class SloRunner(ClusterLoader2Base.Runner):
    def configure(
        self,
        cpu_per_node: int,
        node_count: int,
        node_per_step: int,
        max_pods: int,
        repeats: int,
        operation_timeout: str,
        provider: str,
        scrape_containerd: bool,
        service_test: bool,
        cl2_override_file: str,
    ):
        steps = node_count // node_per_step
        throughput, nodes_per_namespace, pods_per_node, cpu_request = self.calculate_config(
            node_count,
            service_test,
            max_pods,
            provider,
            cpu_per_node
        )

        config = {
            f"CL2_NODES": f"{node_count}",
            f"CL2_LOAD_TEST_THROUGHPUT": f"{throughput}",
            f"CL2_NODES_PER_NAMESPACE": f"{nodes_per_namespace}",
            f"CL2_NODES_PER_STEP": f"{node_per_step}",
            f"CL2_PODS_PER_NODE": f"{pods_per_node}",
            f"CL2_DEPLOYMENT_SIZE": f"{pods_per_node}",
            f"CL2_LATENCY_POD_CPU": f"{cpu_request}",
            f"CL2_REPEATS": f"{repeats}",
            f"CL2_STEPS": f"{steps}",
            f"CL2_OPERATION_TIMEOUT": f"{operation_timeout}",
            "CL2_PROMETHEUS_TOLERATE_MASTER": "true",
            "CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR": "100.0",
            "CL2_PROMETHEUS_MEMORY_SCALE_FACTOR": "100.0",
            "CL2_PROMETHEUS_CPU_SCALE_FACTOR": "30.0",
            "CL2_PROMETHEUS_NODE_SELECTOR": "\"prometheus: \\\"true\\\"\"",
            "CL2_POD_STARTUP_LATENCY_THRESHOLD": "3m",
        }

        if scrape_containerd:
            config.update({
                f"CL2_SCRAPE_CONTAINERD": str(scrape_containerd).lower(),
                "CONTAINERD_SCRAPE_INTERVAL": "5m",
            })

        if service_test:
            config.update({ "CL2_SERVICE_TEST": "true" })
        else:
            config.update({ "CL2_SERVICE_TEST": "false" })

        return config
    
    def validate(
        self,
        node_count: int,
        operation_timeout: int,
    ):
        kube_client = KubernetesClient()
        ready_node_count = 0
        timeout = time.time() + (operation_timeout * 60)
        while time.time() < timeout:
            ready_nodes = kube_client.get_ready_nodes()
            ready_node_count = len(ready_nodes)
            logger.info(f"Currently {ready_node_count} nodes are ready.")
            if ready_node_count >= node_count:
                break
            logger.info(f"Waiting for {node_count} nodes to be ready.")
            time.sleep(10)
        if ready_node_count < node_count:
            raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")

    def execute(
        self,
        cl2_image: str,
        cl2_config_dir: str,
        cl2_report_dir: str,
        cl2_config_file: str,
        kubeconfig: str,
        provider: str,
        scrape_containerd: bool,
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

    def collect(
        self,
        cpu_per_node: int,
        node_count: int,
        max_pods: int,
        repeats: int,
        cl2_report_dir: str,
        cloud_info: str,
        run_id: str,
        run_url: str,
        service_test: bool,
        result_file: str,
        test_type: str,
        test_status: str,
        test_results: dict,
    ) -> dict:
        provider = json.loads(cloud_info)["cloud"]

        _, _, pods_per_node, _ = self.calculate_config(
            node_count,
            service_test,
            max_pods,
            provider,
            cpu_per_node,
        )
        pod_count = node_count * pods_per_node

        # TODO: Expose optional parameter to include test details
        template = {
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "cpu_per_node": cpu_per_node,
            "node_count": node_count,
            "pod_count": pod_count,
            "churn_rate": repeats,
            "status": test_status,
            "group": None,
            "measurement": None,
            "result": None,
            # "test_details": details,
            "cloud_info": cloud_info,
            "run_id": run_id,
            "run_url": run_url,
            "test_type": test_type,
        }

        return process_cl2_reports(cl2_report_dir, template)

    def calculate_config(
        self,
        node_count: int,
        service_test: str,
        max_pods: int,
        provider: str,
        cpu_per_node: int,
    ):
        throughput = 100
        nodes_per_namespace = min(node_count, DEFAULT_NODES_PER_NAMESPACE)

        pods_per_node = DEFAULT_PODS_PER_NODE
        if service_test:
            pods_per_node = max_pods

        # Different cloud has different reserved values and number of daemonsets
        # Using the same percentage will lead to incorrect nodes number as the number of nodes grow
        # For AWS, see: 
        #   https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/bootstrap.sh#L290
        # For Azure, see: 
        #   https://learn.microsoft.com/en-us/azure/aks/node-resource-reservations#cpu-reservations
        capacity = CPU_CAPACITY[provider]
        cpu_request = (cpu_per_node * 1000 * capacity) // pods_per_node
        cpu_request = max(cpu_request, CPU_REQUEST_LIMIT_MILLI)

        return throughput, nodes_per_namespace, pods_per_node, cpu_request


class Slo(ClusterLoader2Base):
    def __init__(self):
        super().__init__()
        self._args_parser = SloArgsParser()
        self._runner = SloRunner()

    @property
    def args_parser(self):
        return self._args_parser

    @property
    def runner(self):
        return self._runner


if __name__ == "__main__":  
    Slo().perform()
