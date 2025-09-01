import json
import os
import argparse

from datetime import datetime, timezone
from clusterloader2.slo import ClusterLoader2Base, Ignored
from clusterloader2.utils import (
    write_to_file, 
    parse_test_results,
    process_cl2_reports,
    CL2Command
)
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)

class NetworkPolicyScaleArgsParser(ClusterLoader2Base.ArgsParser):
    def __init__(self):
        super().__init__(description="Network Policy Scale Test")

    def add_configure_args(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--number_of_groups",
            type=int,
            required=True,
            help="Number of network policy groups to create",
        )
        parser.add_argument(
            "--clients_per_group",
            type=int,
            required=True,
            help="Number of client pods per group",
        )
        parser.add_argument(
            "--servers_per_group",
            type=int,
            required=True,
            help="Number of server pods per group",
        )
        parser.add_argument(
            "--workers_per_client",
            type=int,
            required=True,
            help="Number of workers per client pod",
        )
        parser.add_argument(
            "--test_duration_secs", type=int, required=True, help="Test duration in seconds"
        )
        parser.add_argument(
            "--provider", type=str, required=True, help="Cloud provider name"
        )
        parser.add_argument(
            "--cl2_override_file",
            type=str,
            required=True,
            help="Path to the overrides of CL2 config file",
        )        

    @Ignored
    def add_validate_args(self, parser: argparse.ArgumentParser):
        pass

    def add_execute_args(self, parser):
        parser.add_argument(
            "--cl2_image", 
            type=str, 
            help="Name of the CL2 image"
        )
        parser.add_argument(
            "--cl2_config_dir", 
            type=str, 
            help="Path to the CL2 config directory"
        )
        parser.add_argument(
            "--cl2_report_dir", 
            type=str, 
            help="Path to the CL2 report directory"
        )
        parser.add_argument(
            "--cl2_config_file", 
            type=str, 
            help="Path to the CL2 config file"
        )
        parser.add_argument(
            "--kubeconfig", 
            type=str, 
            help="Path to the kubeconfig file"
        )
        parser.add_argument(
            "--provider", 
            type=str, 
            help="Cloud provider name"
        )

    def add_collect_args(self, parser: argparse.ArgumentParser):
        parser.add_argument("--node_count", type=int, help="Number of nodes")
        parser.add_argument(
            "--pod_count",
            type=int,
            nargs="?",
            default=0,
            help="Maximum number of pods per node",
        )
        parser.add_argument(
            "--cl2_report_dir", type=str, help="Path to the CL2 report directory"
        )
        parser.add_argument("--cloud_info", type=str, help="Cloud information")
        parser.add_argument("--run_id", type=str, help="Run ID")
        parser.add_argument("--run_url", type=str, help="Run URL")
        parser.add_argument(
            "--result_file", type=str, help="Path to the result file"
        )
        parser.add_argument(
            "--test_type",
            type=str,
            nargs="?",
            default="default-config",
            help="Description of test type",
        )


class NetworkPolicyScaleRunner(ClusterLoader2Base.Runner):
    def get_cl2_configure(
        self,
        number_of_groups: int,
        clients_per_group: int,
        servers_per_group: int,
        workers_per_client: int,
        test_duration_secs: int,
        provider: str,
        cl2_override_file: str,
    ) -> dict:
        return {
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

    def get_cl2_parameters(
        self,
        **cli_params
    ) -> CL2Command.Params:
        return CL2Command.Params(
            **cli_params,
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
        test_status: str,
        test_results: dict,
    ) -> str:
        provider = json.loads(cloud_info)["cloud"]

        # TODO: Expose optional parameter to include test details
        template = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "node_count": node_count,
            "pod_count": pod_count,
            "status": test_status,
            "group": None,
            "measurement": None,
            "result": None,
            "cloud_info": provider,
            "run_id": run_id,
            "run_url": run_url,
            "test_type": test_type,
        }
        
        return process_cl2_reports(
            cl2_report_dir,
            template,
        )

    def validate(self):
        pass


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
