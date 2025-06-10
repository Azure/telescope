import json
import os
import argparse

from datetime import datetime, timezone
from clusterloader2.utils import parse_xml_to_json, run_cl2_command, get_measurement, str2bool

def configure_clusterloader2(
    no_of_namespaces,
    no_of_pods,
    no_of_replicas_per_deployment,
    repeats,
    operation_timeout,
    cilium_enabled,
    override_file):

    print(f"no_of_namespaces {no_of_namespaces} ")
    with open(override_file, 'w', encoding='utf-8') as file:
        file.write(f"CL2_NO_OF_NAMESPACES: {no_of_namespaces}\n")
        file.write(f"CL2_NO_OF_PODS: {no_of_pods}\n")
        file.write(f"CL2_NO_OF_REPLICAS_PER_DEPLOYMENT: {no_of_replicas_per_deployment}\n")
        file.write(f"CL2_REPEATS: {repeats}\n")
        file.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")
        file.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        file.write("CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_MEMORY_SCALE_FACTOR: 100.0\n")
        file.write("CL2_PROMETHEUS_CPU_SCALE_FACTOR: 30.0\n")
        file.write("CL2_PROMETHEUS_NODE_SELECTOR: \"prometheus: \\\"true\\\"\"\n")
        file.write("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m\n")

        if cilium_enabled:
            file.write("CL2_CILIUM_METRICS_ENABLED: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
            file.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT_INTERVAL: 30s\n")

    with open(override_file, 'r', encoding='utf-8') as file:
        print(f"Content of file {override_file}:\n{file.read()}")

    file.close()

def execute_clusterloader2(
    cl2_image,
    cl2_config_dir,
    cl2_report_dir,
    cl2_config_file,
    kubeconfig,
    provider,
):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider,
                    cl2_config_file=cl2_config_file, overrides=True, enable_prometheus=True)

def collect_clusterloader2(
    no_of_namespaces,
    no_of_pods,
    no_of_replicas_per_deployment,
    repeats,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file,
    test_type,
    start_timestamp,
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    # TODO: Expose optional parameter to include test details
    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "no_of_namespaces": no_of_namespaces,
        "no_of_pods": no_of_pods,
        "no_of_replicas_per_deployment": no_of_replicas_per_deployment,
        "churn_rate": repeats,
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
        "start_timestamp": start_timestamp,
    }
    content = ""
    for f in os.listdir(cl2_report_dir):
        file_path = os.path.join(cl2_report_dir, f)
        with open(file_path, 'r', encoding='utf-8') as file:
            print(f"Processing {file_path}")
            measurement, group_name = get_measurement(file_path)
            if not measurement:
                continue
            print(measurement, group_name)
            data = json.loads(file.read())

            if "dataItems" in data:
                items = data["dataItems"]
                if not items:
                    print(f"No data items found in {file_path}")
                    print(f"Data:\n{data}")
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

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    parser = argparse.ArgumentParser(description="SLO Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for configure_clusterloader2
    parser_configure = subparsers.add_parser("configure", help="Override CL2 config file")
    parser_configure.add_argument("no_of_namespaces", type=int, help="Number of namespaces to create")
    parser_configure.add_argument("no_of_pods", type=int, help="Maximum total number of pods")
    parser_configure.add_argument("no_of_replicas_per_deployment", type=int, nargs='?', default=20, help="Number of replicas per deployment")
    parser_configure.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_configure.add_argument("operation_timeout", type=str, help="Timeout before failing the scale up test")
    parser_configure.add_argument("provider", type=str, help="Cloud provider name")
    parser_configure.add_argument("cilium_enabled", type=str2bool, choices=[True, False], default=False,
                                  help="Whether cilium is enabled. Must be either True or False")
    parser_configure.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("cl2_config_file", type=str, help="Path to the CL2 config file")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("no_of_namespaces", type=int, nargs='?', default=1, help="Number of namespaces to create")
    parser_collect.add_argument("no_of_pods", type=int, nargs='?', default=0, help="Maximum total number of pods")
    parser_collect.add_argument("no_of_replicas_per_deployment", type=int, nargs='?', default=20, help="Number of replicas per deployment")
    parser_collect.add_argument("repeats", type=int, help="Number of times to repeat the deployment churn")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")

    parser_collect.add_argument("result_file", type=str, help="Path to the result file")
    parser_collect.add_argument("test_type", type=str, nargs='?', default="default-config",
                                help="Description of test type")
    parser_collect.add_argument("start_timestamp", type=str, help="Test start timestamp")

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(args.no_of_namespaces, args.no_of_pods, args.no_of_replicas_per_deployment,
                                 args.repeats, args.operation_timeout,
                                 args.cilium_enabled, args.cl2_override_file)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.cl2_config_file,
                               args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(args.no_of_namespaces, args.no_of_pods, args.no_of_replicas_per_deployment,
                               args.repeats, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url,
                               args.result_file, args.test_type, args.start_timestamp)

if __name__ == "__main__":
    main()
