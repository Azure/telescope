import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from clients.kubernetes_client import KubernetesClient
from clusterloader2.base import ClusterLoader2Base
from clusterloader2.utils import (
    parse_xml_to_json,
    process_cl2_reports,
    run_cl2_command,
    str2bool,
)
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@dataclass
class JobController(ClusterLoader2Base):
    node_count: int = 0
    operation_timeout: str = ""
    operation_timeout_in_minutes: int = 600
    cl2_override_file: str = ""
    job_count: int = 1000
    job_throughput: int = -1
    node_label: str = ""
    cl2_image: str = ""
    cl2_config_dir: str = ""
    cl2_report_dir: str = ""
    cl2_config_file: str = ""
    kubeconfig: str = ""
    provider: str = ""
    prometheus_enabled: bool = False
    scrape_containerd: bool = False
    cloud_info: str = ""
    run_id: str = ""
    run_url: str = ""
    result_file: str = ""
    test_type: str = "default-config"
    start_timestamp: str = ""

    def configure_clusterloader2(self):
        config = {
            "CL2_NODES": self.node_count,
            "CL2_OPERATION_TIMEOUT": self.operation_timeout,
            "CL2_JOBS": self.job_count,
            "CL2_LOAD_TEST_THROUGHPUT": self.job_throughput,
        }
        self.write_cl2_override_file(logger, self.cl2_override_file, config)

    def validate_clusterloader2(self):
        kube_client = KubernetesClient()
        kube_client.wait_for_nodes_ready(
            self.node_count, self.operation_timeout_in_minutes, self.node_label
        )

    def execute_clusterloader2(self):
        run_cl2_command(
            self.kubeconfig,
            self.cl2_image,
            self.cl2_config_dir,
            self.cl2_report_dir,
            self.provider,
            cl2_config_file=self.cl2_config_file,
            overrides=True,
            enable_prometheus=self.prometheus_enabled,
            scrape_containerd=self.scrape_containerd,
        )

    def collect_clusterloader2(self) -> None:

        details = parse_xml_to_json(
            os.path.join(self.cl2_report_dir, "junit.xml"), indent=2
        )
        json_data = json.loads(details)
        testsuites = json_data["testsuites"]
        provider = json.loads(self.cloud_info)["cloud"]

        if testsuites:
            status = "success" if testsuites[0]["failures"] == 0 else "failure"
        else:
            raise Exception(f"No testsuites found in the report! Raw data: {details}")

        template = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "node_count": self.node_count,
            "status": status,
            "group": None,
            "measurement": None,
            "result": None,
            "cloud_info": self.cloud_info,
            "run_id": self.run_id,
            "run_url": self.run_url,
            "test_type": self.test_type,
            "start_timestamp": self.start_timestamp,
            "job_count": self.job_count,
            "job_throughput": self.job_throughput,
            "provider": provider,
        }

        # Process CL2 report files
        content = process_cl2_reports(self.cl2_report_dir, template)

        # Write results to the result file
        os.makedirs(os.path.dirname(self.result_file), exist_ok=True)
        with open(self.result_file, "w", encoding="utf-8") as file:
            file.write(content)

    @staticmethod
    def add_configure_subparser_arguments(parser):
        parser.add_argument("--node_count", type=int, help="Number of nodes")
        parser.add_argument(
            "--operation_timeout",
            type=str,
            help="Timeout before failing the scale up test",
        )
        parser.add_argument(
            "--cl2_override_file",
            type=str,
            help="Path to the overrides of CL2 config file",
        )
        parser.add_argument(
            "--job_count", type=int, default=1000, help="Number of jobs to run"
        )
        parser.add_argument(
            "--job_throughput", type=int, default=-1, help="Job throughput"
        )

    @staticmethod
    def add_validate_subparser_arguments(parser):
        parser.add_argument("--node_count", type=int, help="Number of desired nodes")
        parser.add_argument(
            "--operation_timeout_in_minutes",
            type=int,
            default=600,
            help="Operation timeout to wait for nodes to be ready",
        )
        parser.add_argument(
            "--node_label",
            type=str,
            default=None,
            help="Node label selectors to filter nodes (e.g., 'kubernetes.io/role=worker')",
        )

    @staticmethod
    def add_execute_subparser_arguments(parser):
        parser.add_argument("--cl2_image", type=str, help="Name of the CL2 image")
        parser.add_argument(
            "--cl2_config_dir", type=str, help="Path to the CL2 config directory"
        )
        parser.add_argument(
            "--cl2_report_dir", type=str, help="Path to the CL2 report directory"
        )
        parser.add_argument(
            "--cl2_config_file", type=str, help="Path to the CL2 config file"
        )
        parser.add_argument(
            "--kubeconfig", type=str, help="Path to the kubeconfig file"
        )
        parser.add_argument("--provider", type=str, help="Cloud provider name")
        parser.add_argument(
            "--prometheus_enabled",
            type=str2bool,
            choices=[True, False],
            default=False,
            help="Whether to enable Prometheus scraping. Must be either True or False",
        )
        parser.add_argument(
            "--scrape_containerd",
            type=str2bool,
            choices=[True, False],
            default=False,
            help="Whether to scrape containerd metrics. Must be either True or False",
        )

    @staticmethod
    def add_collect_subparser_arguments(parser):
        parser.add_argument("--node_count", type=int, help="Number of nodes")
        parser.add_argument(
            "--cl2_report_dir", type=str, help="Path to the CL2 report directory"
        )
        parser.add_argument("--cloud_info", type=str, help="Cloud information")
        parser.add_argument("--run_id", type=str, help="Run ID")
        parser.add_argument("--run_url", type=str, help="Run URL")
        parser.add_argument("--result_file", type=str, help="Path to the result file")
        parser.add_argument(
            "--test_type",
            type=str,
            nargs="?",
            default="default-config",
            help="Description of test type",
        )
        parser.add_argument("--start_timestamp", type=str, help="Test start timestamp")
        parser.add_argument(
            "--job_count", type=int, default=1000, help="Number of jobs to run"
        )
        parser.add_argument(
            "--job_throughput", type=int, default=-1, help="Job throughput"
        )


def main():
    loader_parser = JobController.create_parser(
        description="ClusterLoader2 Job Controller CLI"
    )
    loader_args = loader_parser.parse_args()
    args_dict = vars(loader_args)
    command = args_dict.pop("command")

    # instantiate the loader with parsed arguments
    load_test = JobController(**vars(loader_args))
    # Dispatch to the correct method
    if command == "configure":
        load_test.configure_clusterloader2()
    elif command == "validate":
        load_test.validate_clusterloader2()
    elif command == "execute":
        load_test.execute_clusterloader2()
    elif command == "collect":
        load_test.collect_clusterloader2()
    else:
        loader_parser.print_help()


if __name__ == "__main__":
    main()
