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
    job_template_path: str = ""
    job_gpu: int = 0
    dra_enabled: bool = False
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

    def configure_clusterloader2(self):
        config = {
            "CL2_NODES": self.node_count,
            "CL2_OPERATION_TIMEOUT": self.operation_timeout,
            "CL2_JOBS": self.job_count,
            "CL2_LOAD_TEST_THROUGHPUT": self.job_throughput,
            "CL2_JOB_TEMPLATE_PATH": self.job_template_path,
            "CL2_JOB_GPU": self.job_gpu,
            "CL2_ENABLE_RESOURCE_CLAIMS": self.dra_enabled,
        }
        if self.prometheus_enabled:
            config["CL2_PROMETHEUS_TOLERATE_MASTER"] = True
            config["CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR"] = 100.0
            config["CL2_PROMETHEUS_MEMORY_SCALE_FACTOR"] = 100.0
            config["CL2_PROMETHEUS_CPU_SCALE_FACTOR"] = 30.0
            config["CL2_PROMETHEUS_NODE_SELECTOR"] = "\"prometheus: \\\"true\\\"\""
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
            "job_count": self.job_count,
            "job_throughput": self.job_throughput,
            "job_template_path": self.job_template_path,
            "job_gpu": self.job_gpu,
            "dra_enabled": self.dra_enabled,
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
        parser.add_argument(
            "--job_template_path", type=str, default="job_template.yaml", help="Job template path"
        )
        parser.add_argument(
            "--job_gpu", type=int, default=0, help="Number of GPUs per job"
        )
        parser.add_argument(
            "--dra-enabled",
            type=str2bool,
            choices=[True, False],
            default=False,
            help="Whether to enable DRA. Must be either True or False",
        )
        parser.add_argument(
            "--prometheus_enabled",
            type=str2bool,
            choices=[True, False],
            default=False,
            help="Whether to enable Prometheus scraping. Must be either True or False",
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
            default="default-config",
            help="Description of test type",
        )
        parser.add_argument(
            "--job_count", type=int, default=1000, help="Number of jobs to run"
        )
        parser.add_argument(
            "--job_throughput", type=int, default=-1, help="Job throughput"
        )
        parser.add_argument(
            "--job_template_path", type=str, default="job_template.yaml", help="Job template path"
        )
        parser.add_argument(
            "--job_gpu", type=int, default=0, help="Number of GPUs per job"
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
