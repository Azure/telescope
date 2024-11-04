import json
import os
import docker

from xml.dom import minidom
from docker_client import DockerClient

POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP = {
    "PodStartupLatency_PodStartupLatency_": "PodStartupLatency_PodStartupLatency",
    "StatefulPodStartupLatency_PodStartupLatency_": "StatefulPodStartupLatency_PodStartupLatency",
    "StatelessPodStartupLatency_PodStartupLatency_": "StatelessPodStartupLatency_PodStartupLatency",
}
API_RESPONSIVENESS_FILE_PREFIX = "APIResponsivenessPrometheus"
PROM_QUERY_PREFIX = "GenericPrometheusQuery"

def run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, cl2_config_file="config.yaml", overrides=False, enable_prometheus=False, enable_exec_service=False):
    docker_client = DockerClient()

    command=f"""--provider={provider} --v=2
--enable-exec-service={enable_exec_service}
--enable-prometheus-server={enable_prometheus}
--kubeconfig /root/.kube/config
--testconfig /root/perf-tests/clusterloader2/config/{cl2_config_file}
--report-dir /root/perf-tests/clusterloader2/results
--tear-down-prometheus-server={enable_prometheus}"""
    if overrides:
        command += f" --testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml"

    volumes = {
        kubeconfig: {'bind': '/root/.kube/config', 'mode': 'rw'},
        cl2_config_dir: {'bind': '/root/perf-tests/clusterloader2/config', 'mode': 'rw'},
        cl2_report_dir: {'bind': '/root/perf-tests/clusterloader2/results', 'mode': 'rw'}
    }

    if provider == "aws":
        aws_path = os.path.expanduser("~/.aws/credentials")
        volumes[aws_path] = {'bind': '/root/.aws/credentials', 'mode': 'rw'}

    print(f"Running clusterloader2 with command: {command} and volumes: {volumes}")
    try:
        container = docker_client.run_container(cl2_image, command, volumes, detach=True)
        for log in container.logs(stream=True):
            print(log.decode('utf-8'), end='')
        container.wait()
    except docker.errors.ContainerError as e:
        print(f"Container exited with a non-zero status code: {e.exit_status}\n{e.stderr.decode('utf-8')}")

def get_measurement(file_path):
    file_name = os.path.basename(file_path)
    for file_prefix, measurement in POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP.items():
        if file_name.startswith(file_prefix):
            group_name = file_name.split("_")[2]
            return measurement, group_name
    if file_name.startswith(API_RESPONSIVENESS_FILE_PREFIX):
        group_name = file_name.split("_")[1]
        return API_RESPONSIVENESS_FILE_PREFIX, group_name
    if file_name.startswith(PROM_QUERY_PREFIX):
        group_name = file_name.split("_")[1]
        measurement_name = file_name.split("_")[0][len(PROM_QUERY_PREFIX)+1:]
        return measurement_name, group_name
    return None, None

def parse_xml_to_json(file_path, indent = 0):
    with open(file_path, 'r') as file:
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
    json_result = json.dumps(result, indent = indent)
    return json_result
