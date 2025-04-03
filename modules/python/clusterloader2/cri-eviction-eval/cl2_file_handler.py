from cl2_configurator import CL2Configurator
from utils import parse_xml_to_json
import json

import os
from datetime import datetime, timezone
from typing import List

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

    def to_dict(self):
        return {
            "node_count": self.node_count,
            "max_pods": self.max_pods,
            "cloud_info": self.cloud_info,
            "run_id": self.run_id,
            "run_url": self.run_url,
            "churn_rate": self.churn_rate,
            "load_type": self.load_type,
            "status": self.status,
            "timestamp": self.timestamp,
            "measurement": self.measurement,
            "group": self.group,
            "percentile": self.percentile,
            "data": self.data
        }

    # return array of KubeletMetrics
    def parse_metrics(self, file_name: str, data) -> List:
        measurement, group_name = self.parse_file_format(file_name)
        if not measurement:
            return []
        print(measurement, group_name)
        metrics_lines : List[KubeletMetrics] = []

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
                return []

            for item in items:
                metrics_lines.append(self.create_metric(measurement, group_name, "dataItems",item))

            return metrics_lines

        print(f"Unknown measure {measurement} or unexpected data format in {file_name}")
        return []


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

    def export_cl2_override(self, node_count: int, eviction_eval: CL2Configurator):
        print(f"write override file to {self.override_file}")

        with open(self.override_file, 'w', encoding='utf-8') as file:
            node_config = eviction_eval.node_config
            workload_config = eviction_eval.workload_config

            file.write(f"CL2_NODE_COUNT: {node_count}\n")
            file.write(f"CL2_OPERATION_TIMEOUT: {eviction_eval.timeout_seconds}\n")
            file.write(f"CL2_PROVIDER: {eviction_eval.provider}\n")
            file.write(f"CL2_DEPLOYMENT_SIZE: {eviction_eval.pods_per_node}\n")

            file.write(f"CL2_DEPLOYMENT_LABEL: {node_config.node_label}\n")
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

    def load_junit_result(self):
        junit_json = parse_xml_to_json(os.path.join(self.cl2_report_dir, "junit.xml"), indent = 2)
        test_suites = json.loads(junit_json)["testsuites"]

        if test_suites:
            status = "success" if test_suites[0]["failures"] == 0 else "failure"
            return status
        else:
            raise Exception(f"No testsuites found in the report! Raw data: {junit_json}")

    def parse_test_result(self, metric_template: KubeletMetrics, formatter: str = "json"):

        all_metrics : List[KubeletMetrics] = []
        for f in os.listdir(self.cl2_report_dir):
            if not f.endswith(".json"):
                continue
            file_path = os.path.join(self.cl2_report_dir, f)
            with open(file_path, 'r', encoding='utf-8') as file:
                print("Parsing file: ", file_path)
                metric_data = json.loads(file.read())
                file_name = os.path.basename(file_path)
                metrics_lines = metric_template.parse_metrics(file_name, metric_data)
                all_metrics.extend(metrics_lines)

        # only use json for now
        metrics_formatted = []

        if formatter == "json":
            for metric_line in all_metrics:
                metric_line_json = json.dumps(metric_line.to_dict())
                metrics_formatted.append(metric_line_json)
        else:
            print(f"unsupported format {formatter}")

        return metrics_formatted



