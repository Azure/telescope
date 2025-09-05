import json
from dataclasses import dataclass

from datetime import datetime, timezone
from clients.kubernetes_client import KubernetesClient
from utils.common import str2bool
from base import ClusterLoader2Base


@dataclass(frozen=True)
class Cl2DefaultConfigConstants:
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
        super().__init__(description="SLO Kubernetes Resources")

    def add_configure_args(self, parser):
        parser.add_argument("cpu_per_node", type=int, help="CPU per node")
        parser.add_argument("node_count", type=int, help="Number of nodes")
        parser.add_argument("node_per_step", type=int, help="Number of nodes per scaling step")
        parser.add_argument("max_pods", type=int, nargs='?', default=0, help="Maximum number of pods per node")
        parser.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
        parser.add_argument("operation_timeout", type=str, help="Timeout before failing the scale up test")
        parser.add_argument("provider", type=str, help="Cloud provider name")
        parser.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False,
                            help="Whether to scrape containerd metrics. Must be either True or False")
        parser.add_argument("service_test", type=str2bool, choices=[True, False], default=False,
                            help="Whether service test is running. Must be either True or False")
        parser.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    def add_validate_args(self, parser):
        parser.add_argument("node_count", type=int, help="Number of desired nodes")
        parser.add_argument("operation_timeout", type=int, default=600, help="Operation timeout to wait for nodes to be ready")

    def add_execute_args(self, parser):
        parser.add_argument("cl2_image", type=str, help="Name of the CL2 image")
        parser.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
        parser.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
        parser.add_argument("cl2_config_file", type=str, help="Path to the CL2 config file")
        parser.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
        parser.add_argument("provider", type=str, help="Cloud provider name")
        parser.add_argument("scrape_containerd", type=str2bool, choices=[True, False], default=False,
                            help="Whether to scrape containerd metrics. Must be either True or False")

    def add_collect_args(self, parser):
        parser.add_argument("cpu_per_node", type=int, help="CPU per node")
        parser.add_argument("node_count", type=int, help="Number of nodes")
        parser.add_argument("max_pods", type=int, nargs='?', default=0, help="Maximum number of pods per node")
        parser.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
        parser.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
        parser.add_argument("cloud_info", type=str, help="Cloud information")
        parser.add_argument("run_id", type=str, help="Run ID")
        parser.add_argument("run_url", type=str, help="Run URL")
        parser.add_argument("service_test", type=str2bool, choices=[True, False], default=False,
                            help="Whether service test is running. Must be either True or False")
        parser.add_argument("result_file", type=str, help="Path to the result file")
        parser.add_argument("test_type", type=str, nargs='?', default="default-config",
                            help="Description of test type")


class SloRunner(ClusterLoader2Base.Runner):
    # pylint: disable=unused-argument
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
    ) -> str:
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

        return self.process_cl2_reports(cl2_report_dir, template)

    def execute(
        self,
        **kwargs
    ):
        super.execute(
            **kwargs,
            overrides=True,
            enable_prometheus=True
        )

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
    ) -> dict:
        steps = node_count // node_per_step
        throughput, nodes_per_namespace, pods_per_node, cpu_request = self.calculate_config(
            node_count,
            service_test,
            max_pods,
            provider,
            cpu_per_node
        )

        config = {
            "CL2_NODES": f"{node_count}",
            "CL2_LOAD_TEST_THROUGHPUT": f"{throughput}",
            "CL2_NODES_PER_NAMESPACE": f"{nodes_per_namespace}",
            "CL2_NODES_PER_STEP": f"{node_per_step}",
            "CL2_PODS_PER_NODE": f"{pods_per_node}",
            "CL2_DEPLOYMENT_SIZE": f"{pods_per_node}",
            "CL2_LATENCY_POD_CPU": f"{cpu_request}",
            "CL2_REPEATS": f"{repeats}",
            "CL2_STEPS": f"{steps}",
            "CL2_OPERATION_TIMEOUT": f"{operation_timeout}",
            "CL2_PROMETHEUS_TOLERATE_MASTER": "true",
            "CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR": "100.0",
            "CL2_PROMETHEUS_MEMORY_SCALE_FACTOR": "100.0",
            "CL2_PROMETHEUS_CPU_SCALE_FACTOR": "30.0",
            "CL2_PROMETHEUS_NODE_SELECTOR": "\"prometheus: \\\"true\\\"\"",
            "CL2_POD_STARTUP_LATENCY_THRESHOLD": "3m",
        }

        if scrape_containerd:
            config.update({
                "CL2_SCRAPE_CONTAINERD": str(scrape_containerd).lower(),
                "CONTAINERD_SCRAPE_INTERVAL": "5m",
            })

        if service_test:
            config.update({ "CL2_SERVICE_TEST": "true" })
        else:
            config.update({ "CL2_SERVICE_TEST": "false" })

        return config

    def calculate_config(
        self,
        node_count: int,
        service_test: str,
        max_pods: int,
        provider: str,
        cpu_per_node: int,
    ):
        throughput = 100
        nodes_per_namespace = min(node_count, Cl2DefaultConfigConstants.DEFAULT_NODES_PER_NAMESPACE)

        pods_per_node = Cl2DefaultConfigConstants.DEFAULT_PODS_PER_NODE
        if service_test:
            pods_per_node = max_pods

        # Different cloud has different reserved values and number of daemonsets
        # Using the same percentage will lead to incorrect nodes number as the number of nodes grow
        # For AWS, see:
        #   https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/bootstrap.sh#L290
        # For Azure, see:
        #   https://learn.microsoft.com/en-us/azure/aks/node-resource-reservations#cpu-reservations
        capacity = Cl2DefaultConfigConstants.CPU_CAPACITY[provider]
        cpu_request = (cpu_per_node * 1000 * capacity) // pods_per_node
        cpu_request = max(cpu_request, Cl2DefaultConfigConstants.CPU_REQUEST_LIMIT_MILLI)

        return throughput, nodes_per_namespace, pods_per_node, cpu_request

    def validate(
        self,
        node_count: int,
        operation_timeout: int,
    ):
        kube_client = KubernetesClient()
        kube_client.wait_for_nodes_ready(node_count, operation_timeout)


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


if __name__ == '__main__':
    Slo().perform()
