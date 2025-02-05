import json
import os
import argparse
import re
import subprocess

from datetime import datetime, timezone
from utils import parse_xml_to_json, run_cl2_command

def override_config_clusterloader2(cpu_per_node, node_count, pod_count, scale_up_timeout, scale_down_timeout, loop_count, node_label_selector, node_selector, override_file):
    # assuming 85% of the CPU cores can be used by test pods
    cpu_request = (cpu_per_node * 1000 * 0.85) * node_count // pod_count

    print(f"Total number of nodes: {node_count}, total number of pods: {pod_count}")
    print(f"CPU request for each pod: {cpu_request}m")

    # assuming the number of surge nodes is no more than 10
    with open(override_file, 'w') as file:
        file.write(f"CL2_DEPLOYMENT_CPU: {cpu_request}m\n")
        file.write(f"CL2_MIN_NODE_COUNT: {node_count}\n")
        file.write(f"CL2_MAX_NODE_COUNT: {node_count + 10}\n")
        file.write(f"CL2_DESIRED_NODE_COUNT: {desired_node_count}\n")
        file.write(f"CL2_DEPLOYMENT_SIZE: {pod_count}\n")
        file.write(f"CL2_SCALE_UP_TIMEOUT: {scale_up_timeout}\n")
        file.write(f"CL2_SCALE_DOWN_TIMEOUT: {scale_down_timeout}\n")
        file.write(f"CL2_LOOP_COUNT: {loop_count}\n")
        file.write(f"CL2_NODE_LABEL_SELECTOR: {node_label_selector}\n")
        file.write(f"CL2_NODE_SELECTOR: \"{node_selector}\"\n")

    file.close()

def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, kubeconfig, provider):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, overrides=True)

def collect_clusterloader2(
    cpu_per_node,
    node_count,
    pod_count,
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file
):
    index_pattern = re.compile(r'(\d+)$')

    raw_data = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(raw_data)
    testsuites = json_data["testsuites"]
    summary = {}

    if testsuites:
        # Process each loop
        for testcase in testsuites[0]["testcases"]:
            name = testcase["name"]
            index = -1
            match = index_pattern.search(name)
            if match:
                index = match.group()
                if index not in summary:
                    summary[index] = {
                        "up": { "failures": 0 },
                        "down": { "failures": 0 }
                    }
            else:
                continue

            failure = testcase["failure"]
            if "WaitForRunningPodsUp" in name:
                summary[index]["up"]["wait_for_pods_seconds"] = -1 if failure else testcase["time"]
                summary[index]["up"]["failures"] += 1 if failure else 0
            elif "WaitForNodesUp" in name:
                summary[index]["up"]["wait_for_nodes_seconds"] = -1 if failure else testcase["time"]
                summary[index]["up"]["failures"] += 1 if failure else 0
            elif "WaitForRunningPodsDown" in name:
                summary[index]["down"]["wait_for_pods_seconds"] = -1 if failure else testcase["time"]
                summary[index]["down"]["failures"] += 1 if failure else 0
            elif "WaitForNodesDown" in name:
                summary[index]["down"]["wait_for_nodes_seconds"] = -1 if failure else testcase["time"]
                summary[index]["down"]["failures"] += 1 if failure else 0

        content = ""
        for index in summary:
            for key in summary[index]:
                data = {
                    "wait_for_nodes_seconds": summary[index][key]["wait_for_nodes_seconds"],
                    "wait_for_pods_seconds": summary[index][key]["wait_for_pods_seconds"],
                    "autoscale_result": "success" if summary[index][key]["failures"] == 0 else "failure"
                }
                # TODO: Expose optional parameter to include test details
                result = {
                    "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "autoscale_type": key,
                    "cpu_per_node": cpu_per_node,
                    "node_count": node_count,
                    "pod_count": pod_count,
                    "data": data,
                    # "raw_data": raw_data,
                    "cloud_info": cloud_info,
                    "run_id": run_id,
                    "run_url": run_url
                }
                content += json.dumps(result) + "\n"

    else:
        raise Exception(f"No testsuites found in the report! Raw data: {raw_data}")

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w') as f:
        f.write(content)

def main():
    parser = argparse.ArgumentParser(description="Autoscale Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for override_config_clusterloader2
    parser_override = subparsers.add_parser("override", help="Override CL2 config file")
    parser_override.add_argument("cpu_per_node", type=int, help="Name of cpu cores per node")
    parser_override.add_argument("node_count", type=int, help="Number of nodes")
    parser_override.add_argument("pod_count", type=int, help="Number of pods")
    parser_override.add_argument("scale_up_timeout", type=str, help="Timeout before failing the scale up test")
    parser_override.add_argument("scale_down_timeout", type=str, help="Timeout before failing the scale down test")
    parser_override.add_argument("loop_count", type=int, help="Number of times to repeat the test")
    parser_override.add_argument("node_label_selector", type=str, help="Node label selector")
    parser_override.add_argument("node_selector", type=str, help="Node selector for the test pods")
    parser_override.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")
    parser_override.add_argument("warmup_deployment", type=str, help="Warmup deployment to get the cpu request")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("cpu_per_node", type=int, help="Name of cpu cores per node")
    parser_collect.add_argument("node_count", type=int, help="Number of nodes")
    parser_collect.add_argument("pod_count", type=int, help="Number of pods")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    if args.command == "override":
        override_config_clusterloader2(args.cpu_per_node ,args.node_count, args.pod_count, args.scale_up_timeout, args.scale_down_timeout, args.loop_count, args.node_label_selector, args.node_selector, args.cl2_override_file, args.warmup_deployment, args.warmup_deployment)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(args.cpu_per_node, args.node_count, args.pod_count, args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()