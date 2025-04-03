from cl2_configurator import CL2Configurator
from utils import parse_xml_to_json
import json

import os
from datetime import datetime, timezone


class KubeletMetrics:
    def __init__(self, node_count, max_pods, cloud_info, run_id, run_url, churn_rate, load_type, status):
        self.node_count = node_count
        self.max_pods = max_pods
        self.cloud_info = cloud_info
        self.run_id = run_id
        self.run_url = run_url
        self.churn_rate = churn_rate
        self.load_type = load_type
        self.status = status

    def set_status(self, status):
        self.status = status

    def create_metric(self, measurement, group, percentile, data) :
        # create a copy of current KubeletMetrics object
        new_metric = KubeletMetrics(
            self.node_count,
            self.max_pods,
            self.cloud_info,
            self.run_id,
            self.run_url,
            self.churn_rate,
            self.load_type,
            self.status
        )

        new_metric.timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        new_metric.measurement = measurement
        new_metric.group = group
        new_metric.percentile = percentile
        new_metric.data = data
        return new_metric

    # return array of KubeletMetrics
    def get_metrics_measurement(self, file_name: str, data):
        measurement, group_name = self.parse_file_format(file_name)
        if not measurement:
            return ""
        print(measurement, group_name)
        metrics_lines = []

        if measurement == "ResourceUsageSummary":
            for percentile, items in data.items():
                for item in items:
                    metrics_lines.append(self.create_metric(measurement, group_name, percentile,item))
            return metrics_lines

        if "dataItems" in data:
            items = data["dataItems"]
            if not items:
                print(f"No data items found in {file_name}")
                print(f"Data:\n{data}")
                return ""

            for item in items:
                metrics_lines.append(self.create_metric(measurement, group_name, "dataItems",item))

            return metrics_lines

        print(f"Unknown measure {measurement} or unexpected data format in {file_name}")


    POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP = {
        "PodStartupLatency_PodStartupLatency_": "PodStartupLatency_PodStartupLatency",
        "StatefulPodStartupLatency_PodStartupLatency_": "StatefulPodStartupLatency_PodStartupLatency",
        "StatelessPodStartupLatency_PodStartupLatency_": "StatelessPodStartupLatency_PodStartupLatency",
    }
    NETWORK_METRIC_PREFIXES = ["APIResponsivenessPrometheus", "InClusterNetworkLatency", "NetworkProgrammingLatency"]
    PROM_QUERY_PREFIX = "GenericPrometheusQuery"
    RESOURCE_USAGE_SUMMARY_PREFIX = "ResourceUsageSummary"

    def parse_file_format(self, file_name: str):
        for file_prefix, measurement in self.POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP.items():
            if file_name.startswith(file_prefix):
                group_name = file_name.split("_")[2]
                return measurement, group_name
        for file_prefix in self.NETWORK_METRIC_PREFIXES:
            if file_name.startswith(file_prefix):
                group_name = file_name.split("_")[1]
                return file_prefix, group_name
        if file_name.startswith(self.PROM_QUERY_PREFIX):
            group_name = file_name.split("_")[1]
            measurement_name = file_name.split("_")[0][len(self.PROM_QUERY_PREFIX)+1:]
            return measurement_name, group_name
        if file_name.startswith(self.RESOURCE_USAGE_SUMMARY_PREFIX):
            group_name = file_name.split("_")[1]
            return self.RESOURCE_USAGE_SUMMARY_PREFIX, group_name
        return None, None


class CL2FileHandler:
    def __init__(self, cl2_config_dir: str, cl2_report_dir: str):
        self.cl2_config_dir = cl2_config_dir
        self.cl2_report_dir = cl2_report_dir
        self.override_file = f'{cl2_config_dir}/overrides.yaml'

        self.parsed_metrics = []

    def export_cl2_override(self, node_count: int, eviction_eval: CL2Configurator):
        print(f"write override file to {self.override_file}")

        with open(self.override_file, 'w', encoding='utf-8') as file:
            node_config = eviction_eval.node_config
            workload_config = eviction_eval.workload_config

            file.write(f"CL2_NODE_COUNT: {node_count}\n")
            file.write(f"CL2_OPERATION_TIMEOUT: {eviction_eval.timeout_seconds}\n")
            file.write(f"CL2_PROVIDER: {eviction_eval.provider}\n")
            file.write(f"CL2_DEPLOYMENT_SIZE: {eviction_eval.pods_per_node}\n")

            file.write(f"CL2_NODE_LABEL: {node_config.node_label}\n")
            file.write(f"CL2_NODE_SELECTOR: {node_config.node_selector}\n")

            file.write(f"CL2_LOAD_TYPE: {workload_config.load_type}\n")
            file.write(f"CL2_RESOURCE_CONSUME_MEMORY_REQUEST_KI: {workload_config.pod_request_resource.memory_ki}Ki\n")
            file.write(f"CL2_RESOURCE_CONSUME_CPU: {workload_config.pod_request_resource.cpu_milli}\n")
            file.write(f"CL2_RESOURCE_CONSUME_MEMORY_CONSUME_MI: {workload_config.load_resource.memory_ki // 1024}\n") # Convert Ki to Mi
            file.write(f"CL2_RESOURCE_CONSUME_DURATION_SEC: {workload_config.load_duration_seconds}\n")

            file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
            file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 30.0\n")
            file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")

        file.close()

    def parse_test_result(self, metrics_template: KubeletMetrics):
        # Placeholder for parsing logic
        details = parse_xml_to_json(os.path.join(self.cl2_report_dir, "junit.xml"), indent = 2)
        json_data = json.loads(details)
        testsuites = json_data["testsuites"]

        if testsuites:
            status = "success" if testsuites[0]["failures"] == 0 else "failure"
            metrics_template.set_status(status)
        else:
            raise Exception(f"No testsuites found in the report! Raw data: {details}")

        total_metrics_lines = []
        for f in os.listdir(self.cl2_report_dir):
            file_path = os.path.join(self.cl2_report_dir, f)
            with open(file_path, 'r', encoding='utf-8') as file:
                data = json.loads(file.read())
                file_name = os.path.basename(file_path)
                metrics_lines = metrics_template.get_metrics_measurement(file_name, data)
                total_metrics_lines.extend(metrics_lines)

        self.parsed_metrics = total_metrics_lines

    def export_metrics_as_json(self, results_file: str):
        total_metrics_lines_formatted = []
        for metrics_line in self.parsed_metrics:
            metrics_line_json = json.dumps(metrics_line)
            total_metrics_lines_formatted.append(metrics_line_json)

        result_content =  "\n".join(total_metrics_lines_formatted)
        os.makedirs(os.path.dirname(self.cl2_report_dir), exist_ok=True)
        with open(results_file, 'w', encoding='utf-8') as file:
            file.write(result_content)

