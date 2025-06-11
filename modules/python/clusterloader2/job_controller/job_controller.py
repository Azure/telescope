import argparse
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from clients.kubernetes_client import KubernetesClient
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
class JobControllerBase(ABC):
    @abstractmethod
    def configure_clusterloader2(self):
        pass

    @abstractmethod
    def validate_clusterloader2(self):
        pass

    @abstractmethod
    def execute_clusterloader2(self):
        pass

    @abstractmethod
    def collect_clusterloader2(self):
        pass

    @staticmethod
    @abstractmethod
    def add_validate_subparser_arguments(parser: argparse.ArgumentParser):
        pass

    @staticmethod
    @abstractmethod
    def add_execute_subparser_arguments(parser: argparse.ArgumentParser):
        pass

    @staticmethod
    @abstractmethod
    def add_collect_subparser_arguments(parser: argparse.ArgumentParser):
        pass

    @staticmethod
    @abstractmethod
    def add_configure_subparser_arguments(parser: argparse.ArgumentParser):
        pass

    @classmethod
    def create_parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="ClusterLoader2 Job Controller")
        subparsers = parser.add_subparsers(dest="command")

        # Sub-command for configure_clusterloader2
        parser_configure = subparsers.add_parser(
            "configure", help="Configure ClusterLoader2"
        )
        cls.add_configure_subparser_arguments(parser_configure)

        # Sub-command for validate_clusterloader2
        parser_validate = subparsers.add_parser(
            "validate", help="Validate cluster setup"
        )
        cls.add_validate_subparser_arguments(parser_validate)

        # Sub-command for execute_clusterloader2
        parser_execute = subparsers.add_parser(
            "execute", help="Execute ClusterLoader2 tests"
        )
        cls.add_execute_subparser_arguments(parser_execute)

        # Sub-command for collect_clusterloader2
        parser_collect = subparsers.add_parser("collect", help="Collect test results")
        cls.add_collect_subparser_arguments(parser_collect)

        return parser

    def write_cl2_override_file(self, cl2_override_file, config):
        with open(cl2_override_file, "w", encoding="utf-8") as file:
            file.writelines(f"{k}: {v}\n" for k, v in config.items())

        with open(cl2_override_file, "r", encoding="utf-8") as file:
            logger.info(f"Content of file {cl2_override_file}:\n{file.read()}")


@dataclass
class JobSchedulingBenchmark(JobControllerBase):
    node_count: int = 0
    operation_timeout: str = ""
    operation_timeout_in_minutes: int = 600
    cl2_override_file: str = ""
    job_count: int = 1000
    job_throughput: int = -1
    label: str = ""
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
        self.write_cl2_override_file(self.cl2_override_file, config)

    def validate_clusterloader2(self):
        kube_client = KubernetesClient()
        kube_client.wait_for_nodes_ready(
            self.node_count, self.operation_timeout_in_minutes, self.label
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

        # Initialize the template
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
            "--label",
            type=str,
            default="",
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


@dataclass
class BenchmarkRegistry:
    loaders = {
        "job_scheduling": JobSchedulingBenchmark,
    }


def main():
    # The first positional argument is the loader name
    parser = argparse.ArgumentParser(description="ClusterLoader2 Job Controller")
    parser.add_argument(
        "loader",
        type=str,
        choices=BenchmarkRegistry.loaders.keys(),
        help="Type of benchmark loader to use",
    )
    # Parse only the loader argument and leave the rest
    args, remaining_argv = parser.parse_known_args()
    loader_name = args.loader

    benchmark_registry = BenchmarkRegistry()

    # Get the loader class
    loader_class = benchmark_registry.loaders[loader_name]
    loader_parser = loader_class.create_parser()
    loader_args = loader_parser.parse_args(remaining_argv)
    args_dict = vars(loader_args)
    command = args_dict.pop("command")

    # instantiate the loader with parsed arguments
    benchmark = loader_class(**vars(loader_args))
    # Dispatch to the correct method
    if command == "configure":
        benchmark.configure_clusterloader2()
    elif command == "validate":
        benchmark.validate_clusterloader2()
    elif command == "execute":
        benchmark.execute_clusterloader2()
    elif command == "collect":
        benchmark.collect_clusterloader2()
    else:
        loader_parser.print_help()


if __name__ == "__main__":
    main()
