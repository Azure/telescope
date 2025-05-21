import argparse
import json
import time
import random
import sys
import os
from datetime import datetime, timezone
from clients.pod_command import PodRoleCommand
from utils.common import extract_parameter
from utils.retries import execute_with_retries
from utils.constants import CommandConstants
from utils.logger_config import get_logger, setup_logging
from iperf3.parser import parse_tcp_output, parse_udp_output

command_constants = CommandConstants()
setup_logging()
logger = get_logger(__name__)


class Iperf3Pod(PodRoleCommand):
    def __init__(self, client_context, server_context, namespace="default"):
        """
        :param client_context: Cluster config context for client pod.
        :param server_context: Cluster config context for server pod.
        :param namespace: Kubernetes namespace to use. Default is "default".
        """
        super().__init__(
            server_container="iperf3-server",
            client_container="iperf3-client",
            client_label_selector="app=iperf3-client",
            server_label_selector="app=iperf3-server",
            service_name="iperf3-server",
            validate_command=command_constants.IPERF3_VERSION_CMD,
            client_context=client_context,
            server_context=server_context,
            namespace=namespace,
        )

    @staticmethod
    def create_result_file_name(result_dir, protocol, bandwidth, parallel, datapath):
        return f'{result_dir}/iperf3-{protocol}-{bandwidth}-{parallel}-{datapath}.json'

    def run_iperf3(self, iperf3_command, result_file, server_ip_type="pod"):
        """
        Run the iperf3 command on the client pod.

        :param iperf3_command: The iperf3 command to run.
        :param result_file: The file to store the result.
        :param server_ip_type: The type of server IP to use ("pod", "node" or "external").
        :return: The result of the iperf3 command.
        :raises Exception: If there is an error running the iperf3 command.
        """
        server_pod = self.get_pod_by_role(role="server")
        if not server_pod:
            raise RuntimeError(
                "Server pod not found. Ensure the server pod is running and accessible.")
        if server_ip_type == "pod":
            server_ip = server_pod["ip"]
        elif server_ip_type == "node":
            server_ip = server_pod["node_ip"]
        elif server_ip_type == "external":
            server_ip = self.get_service_external_ip()
        else:
            raise ValueError(f"Unsupported server IP type: {server_ip_type}")

        if not server_ip:
            raise RuntimeError(
                f"Server IP not found for server IP type: {server_ip_type}")

        command_cli = f'iperf3 -c {server_ip} {iperf3_command} --json'

        res = self.run_command_for_role(
            role="client", command=command_cli, result_file=result_file)

        if res and "error" in res:
            raise RuntimeError(f"Error running iperf3 command: {res}")

        return res

    def run_netstat(self, role, result_dir, stage_name, index):
        logger.info(
            f"\nRUNNING netstat for {role} in stage {stage_name} with index {index}\n")
        result_file = f"{result_dir}/{role}-netstat-{stage_name}-{index}.json"
        self.run_command_for_role(
            role=role, command=command_constants.NETSTAT_CMD, result_file=result_file)

    def run_iplink(self, role: str, result_dir: str, stage_name: str, index: int):
        logger.info(
            f"\nRUNNING ip-link for {role} in stage {stage_name} with index {index}\n")
        result_file = f"{result_dir}/{role}-ip-link-{stage_name}-{index}.json"
        self.run_command_for_role(
            role=role, command=command_constants.IP_LINK_CMD, result_file=result_file)

    def run_lscpu(self, role, result_dir):
        logger.info(f"\nRUNNING lscpu for {role}\n")
        result_file = f"{result_dir}/{role}-lscpu.json"
        self.run_command_for_role(
            role=role, command=command_constants.LSCPU_CMD, result_file=result_file)

    def run_lspci(self, role, result_dir):
        logger.info(f"\nRUNNING lspci for {role}\n")
        result_file = f"{result_dir}/{role}-lspci.json"
        res = self.run_command_for_role(
            role=role, command=command_constants.LSPCI_CMD, result_file="")
        if not res:
            raise RuntimeError("Error running lspci command. No result found.")
        with open(result_file, 'w', encoding='utf-8') as file:
            json.dump(res.splitlines(), indent=2, fp=file)
            logger.info(f"Saved lspci results to file: {result_file}")

    def run_benchmark(self, index, iperf3_command, result_dir, result_file, server_ip_type="pod"):
        """
        Run the benchmark using iperf3.

        :param index: The index for the benchmark run.
        :param iperf3_command: The iperf3 command to run.
        :param result_dir: The directory to store the results.
        :param result_file: The file to store the result.
        :param server_ip_type: The type of server IP to use ("pod", "node" or "external").
        """
        logger.info(f"\nRUNNING benchmark with index {index}\n")
        self.run_netstat(
            role="client", result_dir=result_dir, stage_name="before-execute", index=index
        )
        self.run_netstat(
            role="server", result_dir=result_dir, stage_name="before-execute", index=index
        )

        self.run_iplink(
            role="client", result_dir=result_dir, stage_name="before-execute", index=index
        )
        self.run_iplink(
            role="server", result_dir=result_dir, stage_name="before-execute", index=index
        )

        self.run_iperf3(
            iperf3_command=iperf3_command, result_file=result_file, server_ip_type=server_ip_type
        )

        self.run_netstat(
            role="client", result_dir=result_dir, stage_name="after-execute", index=index
        )
        self.run_netstat(
            role="server", result_dir=result_dir, stage_name="after-execute", index=index
        )

        self.run_iplink(
            role="client", result_dir=result_dir, stage_name="after-execute", index=index
        )
        self.run_iplink(
            role="server", result_dir=result_dir, stage_name="after-execute", index=index
        )

        self.run_lscpu(role="client", result_dir=result_dir)
        self.run_lscpu(role="server", result_dir=result_dir)

        self.run_lspci(role="client", result_dir=result_dir)
        self.run_lspci(role="server", result_dir=result_dir)

    def collect_iperf3(self, result_dir, result_file, cloud_info, run_url, protocol, bandwidth, parallel, datapath, index="", is_k8s=False):
        iperf3_result_file = self.create_result_file_name(
            result_dir=result_dir,
            protocol=protocol,
            bandwidth=bandwidth,
            parallel=parallel,
            datapath=datapath)
        with open(iperf3_result_file, 'r', encoding='utf-8') as file:
            iperf3_result = file.read()
            file.close()
        if not iperf3_result:
            raise RuntimeError(
                f"Iperf3 result file {iperf3_result_file} is empty or not found!")

        if protocol == "tcp":
            parser_function = parse_tcp_output
        elif protocol == "udp":
            parser_function = parse_udp_output
        else:
            raise ValueError(f"Unsupported protocol: {protocol}")
        parsed_iperf3_result = parser_function(iperf3_result)
        logger.info(f"Parsed iperf3 result:\n{parsed_iperf3_result}")

        os_info = {}
        netstat_info = {}
        ip_link_info = {}
        kubernetes_info = {}
        for role in ["client", "server"]:
            # Collect OS info
            for metric in ["lscpu", "lspci"]:
                file_name = f"{result_dir}/{role}-{metric}.json"
                if os.path.exists(file_name):
                    with open(file_name, 'r', encoding='utf-8') as file:
                        data = json.load(file)
                        os_info[f"{role}_{metric}_info"] = data
                        file.close()
                else:
                    raise RuntimeError(f"File {file_name} not found!")

            # Collect netstat and ip link info
            for stage in ["before-execute", "after-execute"]:
                for metric in ["netstat", "ip-link"]:
                    file_name = f"{result_dir}/{role}-{metric}-{stage}-{index}.json"
                    if os.path.exists(file_name):
                        with open(file_name, 'r', encoding='utf-8') as file:
                            data = json.load(file)
                            if metric == "netstat":
                                netstat_info[f"{role}_{metric}_{stage}_info"] = data
                            elif metric == "ip-link":
                                ip_link_info[f"{role}_{metric}_{stage}_info"] = data
                            file.close()
                    else:
                        raise RuntimeError(f"File {file_name} not found!")

            # Collect kubernetes info
            if is_k8s:
                file_name = f"{result_dir}/{role}_pod_node_info.json"
                if os.path.exists(file_name):
                    with open(file_name, 'r', encoding='utf-8') as file:
                        data = json.load(file)
                        kubernetes_info[f"{role}_pod_node_info"] = data
                        file.close()
                else:
                    raise RuntimeError(f"File {file_name} not found!")

        data = {
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "metric": protocol,
            "target_bandwidth": bandwidth,
            "parallel": parallel,
            "datapath": datapath,
            "unit": "Mbits/sec",
            "result_info": parsed_iperf3_result,
            "os_info": os_info,
            "netstat_info": netstat_info,
            "ip_link_info": ip_link_info,
            "kubernetes_info": kubernetes_info,
            "cloud_info": cloud_info,
            "run_url": run_url,
            "raw_data": iperf3_result,
            "test_engine": "iperf3",
        }
        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        with open(result_file, 'a', encoding='utf-8') as file:
            content = json.dumps(data)
            file.write(f"{content}\n")
            logger.info(f"Final data:\n{json.dumps(data, indent=2)}")
            file.close()


def parse_args(args):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Iperf3 benchmark and validation tool"
    )
    parser.add_argument(
        "action",
        choices=["run_benchmark", "validate",
                 "collect", "collect_pod_node_info", "configure"],
        help="Action to perform"
    )
    parser.add_argument(
        "--index",
        type=int,
        help="Index for the benchmark run"
    )
    parser.add_argument(
        "--protocol",
        choices=["tcp", "udp"],
        help="Protocol to use for iperf3"
    )
    parser.add_argument(
        "--bandwidth",
        type=int,
        help="Bandwidth for iperf3"
    )
    parser.add_argument(
        "--parallel",
        type=int,
        help="Number of parallel streams for iperf3"
    )
    parser.add_argument(
        "--iperf_command",
        help="iperf3 command to run"
    )
    parser.add_argument(
        "--datapath",
        help="Datapath for the benchmark"
    )
    parser.add_argument(
        "--result_dir",
        help="Directory to store the results"
    )
    parser.add_argument(
        "--client_context",
        help="Cluster config context for client pod",
    )
    parser.add_argument(
        "--server_context",
        help="Cluster config context for server pod",
    )
    parser.add_argument(
        "--server_ip_type",
        choices=["pod", "node", "external"],
        help="Select the server ip",
        default="pod"
    )
    parser.add_argument(
        "--cloud_info",
        help="Cloud information for the benchmark"
    )
    parser.add_argument(
        "--run_url",
        help="URL for the benchmark run"
    )
    parser.add_argument(
        "--result_file",
        help="File to store the benchmark result"
    )
    parser.add_argument(
        "--pod_count",
        type=int,
        help="Number of pods to validate"
    )
    parser.add_argument(
        "--label_selector",
        help="Label selector for the pods",
        default=""
    )
    return parser.parse_args(args)


def main():
    """Main function for executing iperf3 commands."""
    args = parse_args(sys.argv[1:])

    iperf3_pod = Iperf3Pod(
        client_context=args.client_context,
        server_context=args.server_context
    )

    if args.action == "run_benchmark":
        logger.info(f"Executing iperf3 command with args: {args}")

        if not all(arg is not None for arg in [
            args.index,
            args.protocol,
            args.bandwidth,
            args.parallel,
            args.iperf_command,
            args.datapath,
            args.result_dir
        ]):
            raise ValueError(
                "Insufficient arguments provided. Expected arguments:\n"
                "  --index, --protocol, --bandwidth, --parallel,\n"
                "  --iperf_command, --datapath, --result_dir\n"
                "Optional arguments:\n"
                "  --client_context, --server_context, --server_ip_type"
            )

        result_file = Iperf3Pod.create_result_file_name(
            args.result_dir, args.protocol, args.bandwidth, args.parallel, args.datapath
        )

        duration = extract_parameter(args.iperf_command, "time")
        backoff_time = int(duration) + 10 if duration else 10

        random_init_delay = random.randint(30, 60)
        logger.info(
            f"Waiting for {random_init_delay} seconds before starting the execution...")
        time.sleep(random_init_delay)

        execute_with_retries(
            iperf3_pod.run_benchmark,
            backoff_time=backoff_time,
            index=args.index,
            result_dir=args.result_dir,
            result_file=result_file,
            iperf3_command=args.iperf_command,
            server_ip_type=args.server_ip_type,
        )

    elif args.action == "validate":
        iperf3_pod.validate()
    elif args.action == "collect":
        iperf3_pod.collect_iperf3(
            result_dir=args.result_dir,
            result_file=args.result_file,
            cloud_info=args.cloud_info,
            run_url=args.run_url,
            protocol=args.protocol,
            bandwidth=args.bandwidth,
            parallel=args.parallel,
            datapath=args.datapath,
            index=args.index,
            is_k8s=True,
        )
    elif args.action == "collect_pod_node_info":
        iperf3_pod.collect(
            result_dir=args.result_dir,
        )
    elif args.action == "configure":
        iperf3_pod.configure(
            pod_count=args.pod_count,
            label_selector=args.label_selector,
        )
    else:
        raise ValueError(f"Unsupported action: {args.action}")


if __name__ == '__main__':
    main()
