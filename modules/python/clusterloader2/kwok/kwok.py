import argparse
import json
import os
from datetime import datetime, timezone

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


def configure_clusterloader2(
    node_count: int,
    operation_timeout: str,
    cl2_override_file: str,
    job_count: int,
    job_throughput: int,
) -> None:

    # Write configurations to the override file
    with open(cl2_override_file, "w", encoding="utf-8") as file:
        file.write(f"CL2_NODES: {node_count}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write(f"CL2_JOBS: {job_count}\n")
        file.write(f"CL2_LOAD_TEST_THROUGHPUT: {job_throughput}\n")

    with open(cl2_override_file, "r", encoding="utf-8") as file:
        logger.info(f"Content of file {cl2_override_file}:\n{file.read()}")


def validate_clusterloader2(
    node_count: int, operation_timeout_in_minutes: int = 10, label: str = ""
) -> None:
    kube_client = KubernetesClient()
    kube_client.wait_for_nodes_ready(node_count, operation_timeout_in_minutes, label)


def execute_clusterloader2(
    cl2_image: str,
    cl2_config_dir: str,
    cl2_report_dir: str,
    cl2_config_file: str,
    kubeconfig: str,
    prometheus_enabled: bool,
    provider: str,
    scrape_containerd: bool,
) -> None:
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


def process_cl2_reports(cl2_report_dir, template):
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


def collect_clusterloader2(
    node_count: int,
    cl2_report_dir: str,
    cloud_info: str,
    run_id: str,
    run_url: str,
    result_file: str,
    test_type: str,
    start_timestamp: str,
    job_count: int,
    job_throughput: int,
) -> None:

    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent=2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]
    provider = json.loads(cloud_info)["cloud"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    # Initialize the template
    template = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "node_count": node_count,
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
        "start_timestamp": start_timestamp,
        "job_count": job_count,
        "job_throughput": job_throughput,
        "provider": provider,
    }

    # Process CL2 report files
    content = process_cl2_reports(cl2_report_dir, template)

    # Write results to the result file
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as file:
        file.write(content)


def main():
    parser = argparse.ArgumentParser(description="CLI Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser(
        "configure", help="Override CL2 config file"
    )
    parser_configure.add_argument("--node_count", type=int, help="Number of nodes")
    parser_configure.add_argument(
        "--operation_timeout", type=str, help="Timeout before failing the scale up test"
    )
    parser_configure.add_argument(
        "--cl2_override_file", type=str, help="Path to the overrides of CL2 config file"
    )
    parser_configure.add_argument(
        "--job_count", type=int, default=1000, help="Number of jobs to run"
    )
    parser_configure.add_argument(
        "--job_throughput", type=int, default=-1, help="Job throughput"
    )

    # Sub-command for validate_clusterloader2
    parser_validate = subparsers.add_parser("validate", help="Validate cluster setup")
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

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
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
        help="Whether to enable Prometheus scraping. Must be either True or False",
    )
    parser_execute.add_argument(
        "--scrape_containerd",
        type=str2bool,
        choices=[True, False],
        default=False,
        help="Whether to scrape containerd metrics. Must be either True or False",
    )

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale-up data")
    parser_collect.add_argument("--node_count", type=int, help="Number of nodes")
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
    parser_collect.add_argument(
        "--start_timestamp", type=str, help="Test start timestamp"
    )
    parser_collect.add_argument(
        "--job_count", type=int, default=1000, help="Number of jobs to run"
    )
    parser_collect.add_argument(
        "--job_throughput", type=int, default=-1, help="Job throughput"
    )

    args = parser.parse_args()
    args_dict = vars(args)

    command = args_dict.pop("command")

    if command == "configure":
        configure_clusterloader2(**args_dict)
    elif command == "validate":
        validate_clusterloader2(**args_dict)
    elif command == "execute":
        execute_clusterloader2(**args_dict)
    elif command == "collect":
        collect_clusterloader2(**args_dict)
    else:
        raise ValueError(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
