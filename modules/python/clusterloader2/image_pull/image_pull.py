"""Image Pull performance test using ClusterLoader2."""

import argparse
import json
import os
from datetime import datetime, timezone

from clusterloader2.utils import parse_xml_to_json, run_cl2_command, get_measurement
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def write_overrides(cl2_config_dir: str, provider: str):
    """Write CL2 override file with Prometheus configuration."""
    override_file = os.path.join(cl2_config_dir, "overrides.yaml")
    with open(override_file, "w", encoding="utf-8") as file:
        file.write(f"CL2_PROVIDER: {provider}\n")
        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")
    logger.info(f"Wrote overrides file: {override_file}")


def execute_clusterloader2(
    cl2_image: str,
    cl2_config_dir: str,
    cl2_report_dir: str,
    kubeconfig: str,
    provider: str
):
    """Execute ClusterLoader2 image-pull test."""
    logger.info(f"Starting image-pull test with CL2 image: {cl2_image}")
    logger.info(f"Config dir: {cl2_config_dir}, Report dir: {cl2_report_dir}")

    # Write overrides file with Prometheus configuration
    write_overrides(cl2_config_dir, provider)

    run_cl2_command(
        kubeconfig=kubeconfig,
        cl2_image=cl2_image,
        cl2_config_dir=cl2_config_dir,
        cl2_report_dir=cl2_report_dir,
        provider=provider,
        cl2_config_file="image-pull.yaml",
        overrides=True,
        enable_prometheus=True,
        scrape_kubelets=True,
        scrape_containerd=True,
        tear_down_prometheus=False
    )

    logger.info(f"Test completed. Results in: {cl2_report_dir}")


def collect_clusterloader2(
    cl2_report_dir: str,
    cloud_info: str,
    run_id: str,
    run_url: str,
    result_file: str,
    deployment_count: int = 10,
    replicas: int = 1
):
    """Collect and format image-pull test results for Kusto ingestion."""
    logger.info(f"Collecting results from: {cl2_report_dir}")

    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent=2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise ValueError(f"No testsuites found in the report! Raw data: {details}")

    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "deployment_count": deployment_count,
        "replicas": replicas,
        "total_pods": deployment_count * replicas,
        "status": status,
        "group": None,
        "measurement": None,
        "percentile": None,
        "data": None,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url
    }

    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        if not file_path.endswith('.json'):
            continue

        with open(file_path, 'r', encoding='utf-8') as file:
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue

            logger.info(f"Processing measurement: {measurement}, group: {group_name}")
            data = json.loads(file.read())

            if "dataItems" in data:
                items = data["dataItems"]
                if not items:
                    logger.info(f"No data items found in {file_path}")
                    continue
                for item in items:
                    template["measurement"] = measurement
                    template["group"] = group_name
                    template["percentile"] = "dataItems"
                    template["data"] = item
                    content += json.dumps(template) + "\n"

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w', encoding='utf-8') as file:
        file.write(content)

    logger.info(f"Results written to: {result_file}")


def main():
    """CLI entry point with subcommands."""
    parser = argparse.ArgumentParser(description="Image Pull performance test")
    subparsers = parser.add_subparsers(dest="command")

    # Execute subcommand
    parser_execute = subparsers.add_parser("execute", help="Execute image-pull test")
    parser_execute.add_argument("--cl2_image", type=str, required=True,
                                help="CL2 Docker image")
    parser_execute.add_argument("--cl2_config_dir", type=str, required=True,
                                help="Path to CL2 config directory")
    parser_execute.add_argument("--cl2_report_dir", type=str, required=True,
                                help="Path to CL2 report directory")
    parser_execute.add_argument("--kubeconfig", type=str,
                                default=os.path.expanduser("~/.kube/config"),
                                help="Path to kubeconfig file")
    parser_execute.add_argument("--provider", type=str, required=True,
                                help="Cloud provider (aks, eks, gke)")

    # Collect subcommand
    parser_collect = subparsers.add_parser("collect", help="Collect test results")
    parser_collect.add_argument("--cl2_report_dir", type=str, required=True,
                                help="Path to CL2 report directory")
    parser_collect.add_argument("--cloud_info", type=str, required=True,
                                help="Cloud information JSON")
    parser_collect.add_argument("--run_id", type=str, required=True,
                                help="Pipeline run ID")
    parser_collect.add_argument("--run_url", type=str, required=True,
                                help="Pipeline run URL")
    parser_collect.add_argument("--result_file", type=str, required=True,
                                help="Path to output result file")
    parser_collect.add_argument("--deployment_count", type=int, default=10,
                                help="Number of deployments")
    parser_collect.add_argument("--replicas", type=int, default=1,
                                help="Replicas per deployment")

    args = parser.parse_args()

    if args.command == "execute":
        execute_clusterloader2(
            cl2_image=args.cl2_image,
            cl2_config_dir=args.cl2_config_dir,
            cl2_report_dir=args.cl2_report_dir,
            kubeconfig=args.kubeconfig,
            provider=args.provider
        )
    elif args.command == "collect":
        collect_clusterloader2(
            cl2_report_dir=args.cl2_report_dir,
            cloud_info=args.cloud_info,
            run_id=args.run_id,
            run_url=args.run_url,
            result_file=args.result_file,
            deployment_count=args.deployment_count,
            replicas=args.replicas
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
