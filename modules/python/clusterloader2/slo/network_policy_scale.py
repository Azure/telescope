import json
import os

from datetime import datetime, timezone
from clusterloader2.utils import run_cl2_command
from clusterloader2.slo import ClusterLoader2Base, Ignored
from utils import (
    write_to_file, 
    parse_test_results,
    process_cl2_reports
)
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)

class NetworkPolicyScaleArgsParser(ClusterLoader2Base.ArgsParser):
    def __init__(self):
        super().__init__(description="Network Policy Scale Test")
    
    def add_configure_args(self, parser):
        parser_configure = parser.add_parser(
            "configure", 
            help="Configure ClusterLoader2 overrides file"
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
            "--test_duration_secs", type=int, required=True, help="Test duration in seconds"
        )
        parser_configure.add_argument(
            "--provider", type=str, required=True, help="Cloud provider name"
        )
        parser_configure.add_argument(
            "--cl2_override_file",
            type=str,
            required=True,
            help="Path to the overrides of CL2 config file",
        )        

    @Ignored
    def add_validate_args(self, parser):
        pass

    def add_execute_args(self, parser):
        parser_execute = parser.add_parser(
            "execute", 
            help="Execute scale up operation"
        )
        parser_execute.add_argument(
            "--cl2_image", 
            type=str, 
            help="Name of the CL2 image"
        )
        parser_execute.add_argument(
            "--cl2_config_dir", 
            type=str, 
            help="Path to the CL2 config directory"
        )
        parser_execute.add_argument(
            "--cl2_report_dir", 
            type=str, 
            help="Path to the CL2 report directory"
        )
        parser_execute.add_argument(
            "--cl2_config_file", 
            type=str, 
            help="Path to the CL2 config file"
        )
        parser_execute.add_argument(
            "--kubeconfig", 
            type=str, 
            help="Path to the kubeconfig file"
        )
        parser_execute.add_argument(
            "--provider", 
            type=str, 
            help="Cloud provider name"
        )

    def add_collect_args(self, parser):
        parser_collect = parser.add_parser("collect", help="Collect scale up data")
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


class NetworkPolicyScaleRunner(ClusterLoader2Base.Runner):
    def configure(
        self,
        number_of_groups: int,
        clients_per_group: int,
        servers_per_group: int,
        workers_per_client: int,
        test_duration_secs: int,
        provider: str,
        cl2_override_file: str,
    ):
        # Ensure the directory for override_file exists
        override_dir = os.path.dirname(cl2_override_file)
        if not os.path.exists(override_dir):
            os.makedirs(override_dir, exist_ok=True)

        # Build config as dictionary
        config_dict = {
            "# Prometheus server config": None,
            "CL2_PROMETHEUS_TOLERATE_MASTER": "true",
            "CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR": "100.0",
            "CL2_PROMETHEUS_MEMORY_SCALE_FACTOR": "100.0",
            "CL2_PROMETHEUS_CPU_SCALE_FACTOR": "30.0",
            "CL2_PROMETHEUS_NODE_SELECTOR": '"prometheus: \"true\""',
            "CL2_ENABLE_IN_CLUSTER_NETWORK_LATENCY": "false",
            "PROMETHEUS_SCRAPE_KUBE_PROXY": "false",
            "# Test config": None,
            "CL2_DURATION": f"{test_duration_secs}s",
            "CL2_NUMBER_OF_CLIENTS_PER_GROUP": str(clients_per_group),
            "CL2_NUMBER_OF_SERVERS_PER_GROUP": str(servers_per_group),
            "CL2_WORKERS_PER_CLIENT": str(workers_per_client),
            "CL2_NUMBER_OF_GROUPS": str(number_of_groups),
            "CL2_CLIENT_METRICS_GATHERING": "true",
            "# Disable non related tests in measurements.yaml": None,
            # This disables non-related tests
            "CL2_ENABLE_IN_CLUSTER_NETWORK_LATENCY": "false",
        }

        content = '\n'.join([
            f"{k}" if v is None else f"{k}: {v}" for k, v in config_dict.items()
        ])

        write_to_file(
            filename=cl2_override_file,
            content=content,
            logger=logger
        )

    def execute(
        self,
        cl2_image: str,
        cl2_config_dir: str,
        cl2_report_dir: str,
        cl2_config_file: str,
        kubeconfig: str,
        provider: str,
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
            scrape_containerd=False
        )

    def collect(
        self,
        node_count: int,
        pod_count: int,
        cl2_report_dir: str,
        cloud_info: str,
        run_id: str,
        run_url: str,
        result_file: str,
        test_type: str,
    ):
        status, _ = parse_test_results(cl2_report_dir)
        provider = json.loads(cloud_info)["cloud"]

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
        
        content = process_cl2_reports(
            cl2_report_dir,
            template,
            logger=logger
        )

        write_to_file(
            filename=result_file,
            content=content,
            logger=logger
        )


class NetworkPolicyScale(ClusterLoader2Base):
    def __init__(self):
        super().__init__()
        self._args_parser = NetworkPolicyScaleArgsParser()
        self._runner = NetworkPolicyScaleRunner()

    @property
    def args_parser(self):
        return self._args_parser
    
    @property
    def runner(self):
        return self._runner


if __name__ == "__main__":
    NetworkPolicyScale().perform()
