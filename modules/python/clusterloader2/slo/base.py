import argparse
import json
import os
from abc import ABC, abstractmethod
from enum import Enum
from xml.dom import minidom

import docker
from clients.docker_client import DockerClient
from utils.constants import MeasurementPrefixConstants
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


class Command(Enum):
    CONFIGURE = "configure"
    VALIDATE = "validate"
    EXECUTE = "execute"
    COLLECT = "collect"


def ignored(func):
    func.is_ignored = True
    return func


class ClusterLoader2Base(ABC):

    class ArgsParser(ABC):
        _parser: argparse.ArgumentParser
        _subparsers: argparse.ArgumentParser

        @property
        def subparser(self):
            return self._subparsers

        def __init__(self, description: str):
            self._parser = argparse.ArgumentParser(description=description)
            self._subparsers = self._parser.add_subparsers(dest="command")

        @abstractmethod
        def add_configure_args(self, parser: argparse.ArgumentParser):
            pass

        @abstractmethod
        def add_validate_args(self, parser: argparse.ArgumentParser):
            pass

        @abstractmethod
        def add_execute_args(self, parser: argparse.ArgumentParser):
            pass

        @abstractmethod
        def add_collect_args(self, parser: argparse.ArgumentParser):
            pass

        def parse(self) -> argparse.Namespace:
            return self._parser.parse_args()

        def print_help(self):
            self._parser.print_help()


    class Runner(ABC):
        @abstractmethod
        def get_cl2_configure(self) -> dict:
            pass

        @abstractmethod
        def validate(self):
            pass

        @abstractmethod
        def execute(self):
            pass

        @abstractmethod
        def collect(self) -> str:
            pass

        def get_measurement(self, file_path):
            file_name = os.path.basename(file_path)
            for file_prefix, measurement in MeasurementPrefixConstants.POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP.items():
                if file_name.startswith(file_prefix):
                    group_name = file_name.split("_")[2]
                    return measurement, group_name
            for file_prefix in MeasurementPrefixConstants.NETWORK_METRIC_PREFIXES:
                if file_name.startswith(file_prefix):
                    group_name = file_name.split("_")[1]
                    return file_prefix, group_name
            if file_name.startswith(MeasurementPrefixConstants.PROM_QUERY_PREFIX):
                group_name = file_name.split("_")[1]
                measurement_name = file_name.split("_")[0][len(MeasurementPrefixConstants.PROM_QUERY_PREFIX)+1:]
                return measurement_name, group_name
            if file_name.startswith(MeasurementPrefixConstants.JOB_LIFECYCLE_LATENCY_PREFIX):
                group_name = file_name.split("_")[1]
                return MeasurementPrefixConstants.JOB_LIFECYCLE_LATENCY_PREFIX, group_name
            if file_name.startswith(MeasurementPrefixConstants.RESOURCE_USAGE_SUMMARY_PREFIX):
                group_name = file_name.split("_")[1]
                return MeasurementPrefixConstants.RESOURCE_USAGE_SUMMARY_PREFIX, group_name
            if file_name.startswith(MeasurementPrefixConstants.NETWORK_POLICY_SOAK_MEASUREMENT_PREFIX):
                group_name = file_name.split("_")[1]
                return MeasurementPrefixConstants.NETWORK_POLICY_SOAK_MEASUREMENT_PREFIX, group_name
            if file_name.startswith(MeasurementPrefixConstants.SCHEDULING_THROUGHPUT_PROMETHEUS_PREFIX):
                group_name = file_name.split("_")[1]
                return MeasurementPrefixConstants.SCHEDULING_THROUGHPUT_PROMETHEUS_PREFIX, group_name
            if file_name.startswith(MeasurementPrefixConstants.SCHEDULING_THROUGHPUT_PREFIX):
                group_name = file_name.split("_")[1]
                return MeasurementPrefixConstants.SCHEDULING_THROUGHPUT_PREFIX, group_name
            return None, None

        def process_cl2_reports(self, cl2_report_dir, template):
            content = ""
            for f in os.listdir(cl2_report_dir):
                file_path = os.path.join(cl2_report_dir, f)
                with open(file_path, "r", encoding="utf-8") as file:
                    logger.info(f"Processing {file_path}")
                    measurement, group_name = self.get_measurement(file_path)
                    if not measurement:
                        continue
                    logger.info(f"Measurement: {measurement}, Group Name: {group_name}")
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

        def run_cl2_command(
            self,
            kubeconfig,
            cl2_image,
            cl2_config_dir,
            cl2_report_dir,
            provider,
            cl2_config_file="config.yaml",
            overrides=False,
            enable_prometheus=False,
            tear_down_prometheus=True,
            enable_exec_service=False,
            scrape_kubelets=False,
            scrape_containerd=False,
            scrape_ksm=False,
            scrape_metrics_server=False
        ):
            docker_client = DockerClient()
            command = f"""--provider={provider} --v=2
        --enable-exec-service={enable_exec_service}
        --enable-prometheus-server={enable_prometheus}
        --prometheus-scrape-kubelets={scrape_kubelets}
        --kubeconfig /root/.kube/config
        --testconfig /root/perf-tests/clusterloader2/config/{cl2_config_file}
        --report-dir /root/perf-tests/clusterloader2/results
        --tear-down-prometheus-server={tear_down_prometheus}
        --prometheus-scrape-kube-state-metrics={scrape_ksm}
        --prometheus-scrape-metrics-server={scrape_metrics_server}"""

            if scrape_containerd:
                command += f" --prometheus-scrape-containerd={scrape_containerd}"

            if overrides:
                command += " --testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml"

            volumes = {
                kubeconfig: {'bind': '/root/.kube/config', 'mode': 'rw'},
                cl2_config_dir: {'bind': '/root/perf-tests/clusterloader2/config', 'mode': 'rw'},
                cl2_report_dir: {
                    'bind': '/root/perf-tests/clusterloader2/results', 'mode': 'rw'}
            }

            if provider == "aws":
                aws_path = os.path.expanduser("~/.aws/credentials")
                volumes[aws_path] = {'bind': '/root/.aws/credentials', 'mode': 'rw'}

            logger.info(
                f"Running clusterloader2 with command: {command} and volumes: {volumes}")
            try:
                container = docker_client.run_container(
                    cl2_image, command, volumes, detach=True)
                for log in container.logs(stream=True):
                    log_line = log.decode('utf-8').rstrip('\n')
                    if log_line:
                        logger.info(log_line)
                result = container.wait()
                exit_code = result['StatusCode']
                if exit_code != 0:
                    logger.error(
                        f"clusterloader2 exited with a non-zero status code {exit_code}. Make sure to check the logs to confirm whether the error is expected!")
            except docker.errors.ContainerError as e:
                logger.error(
                    f"Container exited with a non-zero status code: {e.exit_status}\n{e.stderr.decode('utf-8')}")

        def parse_xml_to_json(self, file_path, indent=0):
            with open(file_path, 'r', encoding='utf-8') as file:
                xml_content = file.read()

            dom = minidom.parseString(xml_content)

            result = {
                "testsuites": []
            }

            # Extract test suites
            testsuites = dom.getElementsByTagName("testsuite")
            for testsuite in testsuites:
                suite_name = testsuite.getAttribute("name")
                suite_tests = int(testsuite.getAttribute("tests"))
                suite_failures = int(testsuite.getAttribute("failures"))
                suite_errors = int(testsuite.getAttribute("errors"))

                suite_result = {
                    "name": suite_name,
                    "tests": suite_tests,
                    "failures": suite_failures,
                    "errors": suite_errors,
                    "testcases": []
                }

                # Extract test cases
                testcases = testsuite.getElementsByTagName("testcase")
                for testcase in testcases:
                    case_name = testcase.getAttribute("name")
                    case_classname = testcase.getAttribute("classname")
                    case_time = testcase.getAttribute("time")

                    case_result = {
                        "name": case_name,
                        "classname": case_classname,
                        "time": case_time,
                        "failure": None
                    }

                    # Check for failure
                    failure = testcase.getElementsByTagName("failure")
                    if failure:
                        failure_message = failure[0].firstChild.nodeValue
                        case_result["failure"] = failure_message

                    suite_result["testcases"].append(case_result)

                result["testsuites"].append(suite_result)

            # Convert the result dictionary to JSON
            json_result = json.dumps(result, indent=indent)
            return json_result


    @property
    @abstractmethod
    def args_parser(self) -> ArgsParser:
        pass

    @property
    @abstractmethod
    def runner(self) -> Runner:
        pass

    def _add_subparser(self, command: str, description: str):
        subparsers = self.args_parser.subparsers

        add_args_method = {
            Command.CONFIGURE.value: self.args_parser.add_configure_args,
            Command.VALIDATE.value: self.args_parser.add_validate_args,
            Command.EXECUTE.value: self.args_parser.add_execute_args,
            Command.COLLECT.value: self.args_parser.add_collect_args,
        }.get(command)

        if not add_args_method:
            return

        is_method_ignored = getattr(add_args_method, "is_ignored", False)

        if not is_method_ignored:
            parser = subparsers.add_parser(command, help=description)
            add_args_method(parser)

    def parse_arguments(self) -> argparse.Namespace:
        self._add_subparser(
            command=Command.CONFIGURE.value,
            description="Override CL2 config file",
        )

        self._add_subparser(
            command=Command.VALIDATE.value,
            description="Validate cluster setup",
        )

        self._add_subparser(
            command=Command.EXECUTE.value,
            description="Execute scale up operation",
        )

        self._add_subparser(
            command=Command.COLLECT.value,
            description="Collect scale up data",
        )

        return self.args_parser.parse()

    def perform(self):
        args = self.parse_arguments()
        args_dict = vars(args)
        command = args_dict.pop("command", None)

        if command == Command.CONFIGURE.value:
            config_dict = self.runner.get_cl2_configure(**args_dict)
            self.write_to_file(
                filename=args_dict["cl2_override_file"],
                content=self.convert_config_to_str(config_dict)
            )
        elif command == Command.VALIDATE.value:
            self.runner.validate(**args_dict)
        elif command == Command.EXECUTE.value:
            self.runner.execute(**args_dict)
        elif command == Command.COLLECT.value:
            status, results = self.parse_test_results(args_dict["cl2_report_dir"])
            result = self.runner.collect(
                test_status=status,
                test_results=results,
                **args_dict
            )
            self.write_to_file(
                filename=args_dict["result_file"],
                content=result,
            )
        else:
            print(f"I can't recognize `{command}`\n")
            self.args_parser.print_help()

    def convert_config_to_str(self, config_dict: dict) -> str:
        return '\n'.join([
            str(k) if v is None else f"{k}: {v}" for k, v in config_dict.items()
        ])

    def write_to_file(
        self,
        filename: str,
        content: str,
    ):
        parent_dir = os.path.dirname(filename)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        with open(filename, "w", encoding="utf-8") as file:
            file.write(content)

        with open(filename, "r", encoding="utf-8") as file:
            if logger:
                logger.info(f"Content of file {filename}:\n{file.read()}")

    def parse_test_results(self, cl2_report_dir: str) -> tuple[str, list[any]]:
        junit_xml_file = os.path.join(cl2_report_dir, "junit.xml")
        details = self.runner.parse_xml_to_json(junit_xml_file, indent=2)
        json_data = json.loads(details)
        testsuites = json_data["testsuites"]

        if testsuites:
            status = "success" if testsuites[0]["failures"] == 0 else "failure"
        else:
            raise Exception(f"No testsuites found in the report! Raw data: {details}")

        return status, testsuites
