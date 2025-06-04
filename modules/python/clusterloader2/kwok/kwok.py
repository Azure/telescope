import argparse
import json
import os
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from typing import Dict, Any, List

from clients.kubernetes_client import KubernetesClient
from clusterloader2.utils import (
    get_measurement,
    parse_xml_to_json,
    run_cl2_command,
    str2bool,
)
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


class KwokClusterLoaderBase(ABC):
    """Base class for Kwok-based ClusterLoader implementations."""

    def __init__(self):
        self.kube_client = KubernetesClient()

    @abstractmethod
    def get_config_template(self) -> str:
        """Return the path to the config template file."""
        pass

    @abstractmethod
    def configure_clusterloader2(self, **kwargs) -> None:
        """Configure ClusterLoader2 with the given parameters."""
        pass

    @abstractmethod
    def validate_clusterloader2(self, **kwargs) -> None:
        """Validate the cluster setup."""
        pass

    @abstractmethod
    def execute_clusterloader2(self, **kwargs) -> None:
        """Execute ClusterLoader2 tests."""
        pass

    @abstractmethod
    def get_result_template(self, **kwargs) -> Dict[str, Any]:
        """Get the template for test results. To be implemented by subclasses."""
        pass

    @classmethod
    def _add_configure_subparser_arguments(cls, parser_configure: argparse.ArgumentParser) -> None:
        """Add configure-specific arguments. Can be extended by subclasses."""
        parser_configure.add_argument(
            "--cl2_override_file", type=str, help="Path to the overrides of CL2 config file"
        )

    @classmethod
    def _add_validate_subparser_arguments(cls, parser_validate: argparse.ArgumentParser) -> None:
        """Add validate-specific arguments. Can be extended by subclasses."""
        pass

    @classmethod
    def _add_execute_subparser_arguments(cls, parser_execute: argparse.ArgumentParser) -> None:
        """Add execute-specific arguments. Can be extended by subclasses."""
        parser_execute.add_argument("--cl2_image", type=str, help="Name of the CL2 image")
        parser_execute.add_argument(
            "--cl2_config_dir", type=str, help="Path to the CL2 config directory"
        )
        parser_execute.add_argument(
            "--cl2_report_dir", type=str, help="Path to the CL2 report directory"
        )
        parser_execute.add_argument(
            "--cl2_config_file", type=str, help="Path to the CL2 config file"
        )
        parser_execute.add_argument(
            "--kubeconfig", type=str, help="Path to the kubeconfig file"
        )
        parser_execute.add_argument("--provider", type=str, help="Cloud provider name")
        parser_execute.add_argument(
            "--prometheus_enabled",
            type=str2bool,
            choices=[True, False],
            default=False,
            help="Whether to enable Prometheus scraping",
        )
        parser_execute.add_argument(
            "--scrape_containerd",
            type=str2bool,
            choices=[True, False],
            default=False,
            help="Whether to scrape containerd metrics",
        )

    @classmethod
    def _add_collect_subparser_arguments(cls, parser_collect: argparse.ArgumentParser) -> None:
        """Add collect-specific arguments. Can be extended by subclasses."""
        parser_collect.add_argument(
            "--cl2_report_dir", type=str, help="Path to the CL2 report directory"
        )
        parser_collect.add_argument(
            "--result_file", type=str, help="Path to the result file"
        )
        parser_collect.add_argument("--cloud_info", type=str, help="Cloud information")
        parser_collect.add_argument("--run_id", type=str, help="Run ID")
        parser_collect.add_argument("--run_url", type=str, help="Run URL")
        parser_collect.add_argument(
            "--start_timestamp", type=str, help="Test start timestamp"
        )

    @classmethod
    def create_parser(cls) -> argparse.ArgumentParser:
        """Create the argument parser with common arguments. Subclasses can extend the arguments."""
        parser = argparse.ArgumentParser(description="Kubernetes ClusterLoader CLI.")
        subparsers = parser.add_subparsers(dest="command")

        # Sub-command for configure_clusterloader2
        parser_configure = subparsers.add_parser(
            "configure", help="Configure ClusterLoader2"
        )
        cls._add_configure_subparser_arguments(parser_configure)

        # Sub-command for validate_clusterloader2
        parser_validate = subparsers.add_parser("validate", help="Validate cluster setup")
        cls._add_validate_subparser_arguments(parser_validate)

        # Sub-command for execute_clusterloader2
        parser_execute = subparsers.add_parser("execute", help="Execute ClusterLoader2 tests")
        cls._add_execute_subparser_arguments(parser_execute)

        # Sub-command for collect_clusterloader2
        parser_collect = subparsers.add_parser("collect", help="Collect test results")
        cls._add_collect_subparser_arguments(parser_collect)

        return parser

    def process_cl2_reports(self, cl2_report_dir: str, template: Dict[str, Any]) -> str:
        """Process ClusterLoader2 reports."""
        content = ""
        for f in os.listdir(cl2_report_dir):
            file_path = os.path.join(cl2_report_dir, f)
            with open(file_path, "r", encoding="utf-8") as file:
                logger.info(f"Processing {file_path}")
                measurement, group_name = get_measurement(file_path)
                if not measurement:
                    continue
                logger.info(measurement, group_name)
                data = json.loads(file.read())

                if "dataItems" in data:
                    items = data["dataItems"]
                    if not items:
                        logger.info(f"No data items found in {file_path}")
                        logger.info(f"Data:\n{data}")
                        continue
                    for item in items:
                        result = template.copy()
                        result["group"] = group_name
                        result["measurement"] = measurement
                        result["result"] = item
                        content += json.dumps(result) + "\n"
                else:
                    result = template.copy()
                    result["group"] = group_name
                    result["measurement"] = measurement
                    result["result"] = data
                    content += json.dumps(result) + "\n"
        return content

    def collect_clusterloader2(self, cl2_report_dir: str, result_file: str, **kwargs) -> None:
        """Collect ClusterLoader2 test results with customizable template."""
        details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent=2)
        json_data = json.loads(details)
        testsuites = json_data["testsuites"]

        if not testsuites:
            raise Exception(f"No testsuites found in the report! Raw data: {details}")
        
        status = "success" if testsuites[0]["failures"] == 0 else "failure"

        # Get template from subclass implementation
        template = self.get_result_template(status=status, **kwargs)

        # Process CL2 report files
        content = self.process_cl2_reports(cl2_report_dir, template)

        # Write results to the result file
        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        with open(result_file, "w", encoding="utf-8") as file:
            file.write(content)


class JobBenchmark(KwokClusterLoaderBase):
    """Implementation for job scheduling benchmark tests."""

    def get_config_template(self) -> str:
        """Return the path to the job benchmark config template."""
        return os.path.join(os.path.dirname(__file__), "config", "config.yaml")

    @classmethod
    def _add_configure_subparser_arguments(cls, parser_configure: argparse.ArgumentParser) -> None:
        """Add job benchmark specific configure arguments."""
        super()._add_configure_subparser_arguments(parser_configure)
        parser_configure.add_argument("--node_count", type=int, help="Number of nodes")
        parser_configure.add_argument(
            "--operation_timeout", type=str, help="Timeout before failing the scale up test"
        )
        parser_configure.add_argument(
            "--job_count", type=int, default=1000, help="Number of jobs to run"
        )
        parser_configure.add_argument(
            "--job_throughput", type=int, default=-1, help="Job throughput"
        )

    @classmethod
    def _add_validate_subparser_arguments(cls, parser_validate: argparse.ArgumentParser) -> None:
        """Add job benchmark specific validate arguments."""
        super()._add_validate_subparser_arguments(parser_validate)
        parser_validate.add_argument(
            "--node_count", type=int, help="Number of desired nodes"
        )
        parser_validate.add_argument(
            "--operation_timeout_in_minutes",
            type=int,
            default=600,
            help="Operation timeout to wait for nodes to be ready",
        )
        parser_validate.add_argument(
            "--label",
            type=str,
            default="",
            help="Node label selectors to filter nodes (e.g., 'kubernetes.io/role=worker')",
        )

    @classmethod
    def _add_collect_subparser_arguments(cls, parser_collect: argparse.ArgumentParser) -> None:
        """Add job benchmark specific collect arguments."""
        super()._add_collect_subparser_arguments(parser_collect)
        parser_collect.add_argument("--node_count", type=int, help="Number of nodes")
        parser_collect.add_argument(
            "--test_type",
            type=str,
            default="job-scheduling",
            help="Description of test type",
        )
        parser_collect.add_argument(
            "--job_count", type=int, default=1000, help="Number of jobs to run"
        )
        parser_collect.add_argument(
            "--job_throughput", type=int, default=-1, help="Job throughput"
        )

    def configure_clusterloader2(
        self,
        node_count: int,
        operation_timeout: str,
        cl2_override_file: str,
        job_count: int,
        job_throughput: int,
    ) -> None:
        """Configure ClusterLoader2 with job benchmark parameters."""
        with open(cl2_override_file, "w", encoding="utf-8") as file:
            file.write(f"CL2_NODES: {node_count}\n")
            file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
            file.write(f"CL2_JOBS: {job_count}\n")
            file.write(f"CL2_LOAD_TEST_THROUGHPUT: {job_throughput}\n")

        with open(cl2_override_file, "r", encoding="utf-8") as file:
            logger.info(f"Content of file {cl2_override_file}:\n{file.read()}")

    def validate_clusterloader2(
        self,
        node_count: int,
        operation_timeout_in_minutes: int = 10,
        label: str = "",
    ) -> None:
        """Validate the cluster setup for job benchmark."""
        self.kube_client.wait_for_nodes_ready(node_count, operation_timeout_in_minutes, label)

    def execute_clusterloader2(
        self,
        cl2_image: str,
        cl2_config_dir: str,
        cl2_report_dir: str,
        cl2_config_file: str,
        kubeconfig: str,
        prometheus_enabled: bool,
        provider: str,
        scrape_containerd: bool,
    ) -> None:
        """Execute job benchmark tests."""
        run_cl2_command(
            kubeconfig,
            cl2_image,
            cl2_config_dir,
            cl2_report_dir,
            provider,
            cl2_config_file=cl2_config_file,
            overrides=True,
            enable_prometheus=prometheus_enabled,
            scrape_containerd=scrape_containerd,
        )

    def get_result_template(self, **kwargs) -> Dict[str, Any]:
        """Get the template for job benchmark results."""
        status = kwargs.get("status", "unknown")
        return {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "node_count": kwargs.get("node_count", 0),
            "status": status,
            "group": None,  # Will be filled by process_cl2_reports
            "measurement": None,  # Will be filled by process_cl2_reports
            "result": None,  # Will be filled by process_cl2_reports
            "cloud_info": kwargs.get("cloud_info", "{}"),
            "run_id": kwargs.get("run_id", ""),
            "run_url": kwargs.get("run_url", ""),
            "test_type": kwargs.get("test_type", "job-scheduling"),
            "start_timestamp": kwargs.get("start_timestamp", ""),
            "job_count": kwargs.get("job_count", 0),
            "job_throughput": kwargs.get("job_throughput", -1),
            "provider": json.loads(kwargs.get("cloud_info", "{}")). get("cloud", "unknown"),
        }


class BenchmarkRegistry:
    """Registry for available benchmark loaders."""
    _loaders = {
        "job": JobBenchmark,
    }

    @classmethod
    def register(cls, name: str, loader_class: type) -> None:
        """Register a new benchmark loader."""
        cls._loaders[name] = loader_class

    @classmethod
    def get(cls, name: str) -> type:
        """Get a benchmark loader by name."""
        if name not in cls._loaders:
            available = ", ".join(cls._loaders.keys())
            raise ValueError(f"Unknown benchmark type '{name}'. Available types: {available}")
        return cls._loaders[name]


def main():
    # Create a basic parser for the loader type
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument(
        "--loader",
        type=str,
        default="job",
        help="Type of benchmark loader to use (e.g., 'job' for JobBenchmark)",
    )

    # Parse just the loader argument first
    args, remaining_argv = base_parser.parse_known_args()

    # Get the appropriate loader class
    loader_class = BenchmarkRegistry.get(args.loader)

    # Create the full parser with the loader's arguments
    parser = loader_class.create_parser()
    args = parser.parse_args(remaining_argv)
    args_dict = vars(args)

    command = args_dict.pop("command")
    loader = loader_class()

    if command == "configure":
        loader.configure_clusterloader2(**args_dict)
    elif command == "validate":
        loader.validate_clusterloader2(**args_dict)
    elif command == "execute":
        loader.execute_clusterloader2(**args_dict)
    elif command == "collect":
        loader.collect_clusterloader2(**args_dict)
    else:
        raise ValueError(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
