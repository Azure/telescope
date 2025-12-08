from xml.dom import minidom
import json
import os
import docker
from clients.docker_client import DockerClient
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP = {
    "PodStartupLatency_PodStartupLatency_": "PodStartupLatency_PodStartupLatency",
    "StatefulPodStartupLatency_PodStartupLatency_": "StatefulPodStartupLatency_PodStartupLatency",
    "StatelessPodStartupLatency_PodStartupLatency_": "StatelessPodStartupLatency_PodStartupLatency",
}
NETWORK_METRIC_PREFIXES = ["APIResponsivenessPrometheus",
                           "InClusterNetworkLatency", "NetworkProgrammingLatency"]
PROM_QUERY_PREFIX = "GenericPrometheusQuery"
RESOURCE_USAGE_SUMMARY_PREFIX = "ResourceUsageSummary"
NETWORK_POLICY_SOAK_MEASUREMENT_PREFIX = "NetworkPolicySoakMeasurement"
JOB_LIFECYCLE_LATENCY_PREFIX = "JobLifecycleLatency"
SCHEDULING_THROUGHPUT_PROMETHEUS_PREFIX = "SchedulingThroughputPrometheus"
SCHEDULING_THROUGHPUT_PREFIX = "SchedulingThroughput"


def run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, cl2_config_file="config.yaml", overrides=False, enable_prometheus=False, tear_down_prometheus=True,
                    enable_exec_service=False, scrape_kubelets=False,
                    scrape_containerd=False, scrape_ksm=False, scrape_metrics_server=False, extra_flags=""):
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

    if extra_flags:
        command += f" {extra_flags}"

    volumes = {
        kubeconfig: {'bind': '/root/.kube/config', 'mode': 'rw'},
        cl2_config_dir: {'bind': '/root/perf-tests/clusterloader2/config', 'mode': 'rw'},
        cl2_report_dir: {
            'bind': '/root/perf-tests/clusterloader2/results', 'mode': 'rw'}
    }

    if provider == "aws":
        aws_path = os.path.expanduser("~/.aws/credentials")
        volumes[aws_path] = {'bind': '/root/.aws/credentials', 'mode': 'rw'}

    if provider == "aks":
        azure_path = os.path.expanduser("~/.azure")
        volumes[azure_path] = {'bind': '/root/.azure', 'mode': 'rw'}

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


def get_measurement(file_path):
    file_name = os.path.basename(file_path)
    for file_prefix, measurement in POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP.items():
        if file_name.startswith(file_prefix):
            group_name = file_name.split("_")[2]
            return measurement, group_name
    for file_prefix in NETWORK_METRIC_PREFIXES:
        if file_name.startswith(file_prefix):
            group_name = file_name.split("_")[1]
            return file_prefix, group_name
    if file_name.startswith(PROM_QUERY_PREFIX):
        group_name = file_name.split("_")[1]
        measurement_name = file_name.split("_")[0][len(PROM_QUERY_PREFIX)+1:]
        return measurement_name, group_name
    if file_name.startswith(JOB_LIFECYCLE_LATENCY_PREFIX):
        group_name = file_name.split("_")[1]
        return JOB_LIFECYCLE_LATENCY_PREFIX, group_name
    if file_name.startswith(RESOURCE_USAGE_SUMMARY_PREFIX):
        group_name = file_name.split("_")[1]
        return RESOURCE_USAGE_SUMMARY_PREFIX, group_name
    if file_name.startswith(NETWORK_POLICY_SOAK_MEASUREMENT_PREFIX):
        group_name = file_name.split("_")[1]
        return NETWORK_POLICY_SOAK_MEASUREMENT_PREFIX, group_name
    if file_name.startswith(SCHEDULING_THROUGHPUT_PROMETHEUS_PREFIX):
        group_name = file_name.split("_")[1]
        return SCHEDULING_THROUGHPUT_PROMETHEUS_PREFIX, group_name
    if file_name.startswith(SCHEDULING_THROUGHPUT_PREFIX):
        group_name = file_name.split("_")[1]
        return SCHEDULING_THROUGHPUT_PREFIX, group_name
    return None, None

def process_cl2_reports(cl2_report_dir, template):
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, "r", encoding="utf-8") as file:
            logger.info(f"Processing {file_path}")
            measurement, group_name = get_measurement(file_path)
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


def parse_xml_to_json(file_path, indent=0):
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
