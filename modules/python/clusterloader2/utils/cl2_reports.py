import os
import json
from xml.dom import minidom

from .constants import (
    POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP,
    NETWORK_METRIC_PREFIXES,
    PROM_QUERY_PREFIX,
    RESOURCE_USAGE_SUMMARY_PREFIX,
    NETWORK_POLICY_SOAK_MEASUREMENT_PREFIX,
    JOB_LIFECYCLE_LATENCY_PREFIX,
    SCHEDULING_THROUGHPUT_PROMETHEUS_PREFIX,
    SCHEDULING_THROUGHPUT_PREFIX,
)
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)

def get_measurement(
    file_path,
):
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


def process_cl2_reports(
    cl2_report_dir: str,
    template: dict,
) -> str:
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


def parse_xml_to_json(
    file_path,
    indent=0,
) -> dict:
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


def parse_test_results(cl2_report_dir: str) -> tuple[str, list[any]]:
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")
    
    return status, testsuites
