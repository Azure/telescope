import json
import os
import argparse

from datetime import datetime, timezone
from utils import parse_xml_to_json, run_cl2_command

def override_config_clusterloader2(override_file):
    pass

def execute_clusterloader2(cl2_image, cl2_config_dir, cl2_report_dir, kubeconfig, provider):
    run_cl2_command(kubeconfig, cl2_image, cl2_config_dir, cl2_report_dir, provider, overrides=True)

def collect_clusterloader2(
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file,
    tag
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent = 2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    template = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "status": tag, # for now
        "measurement": None,
        "result": None,
        "test_details": details,
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
    }
    print("tag: " + tag)
    content = ""
    for f in os.listdir(cl2_report_dir):
        # validate filename
        if not f.startswith("APIResponsiveness") and not f.startswith("GenericPrometheusQuery") \
            and not f.startswith("PodStartupLatency") and not f.startswith("SchedulingThroughput"):
            continue
        file_path = os.path.join(cl2_report_dir, f)
        print(file_path)
        with open(file_path, 'r') as f:
            measurement = parse_file(file_path)
            data = json.loads(f.read())

            if "dataItems" in data:
                items = data["dataItems"]
                if items is not None:
                    for item in items:
                        result = template.copy()
                        result["measurement"] = measurement
                        result["result"] = item
                        content += json.dumps(result) + "\n"
                        print(result["status"])
            else:
                result = template.copy()
                result["measurement"] = measurement
                result["result"] = data
                content += json.dumps(result) + "\n"

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, 'w') as f:
        f.write(content)

def parse_file(fpath):
    f = os.path.basename(fpath)
    print(f)
    # if f.startswith("GenericPrometheusQuery"):
    #     return f.split("_")[0][23:]
    return f.split("_")[0]

def main():
    parser = argparse.ArgumentParser(description="Cilscale Kubernetes resources.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for override_config_clusterloader2
    parser_override = subparsers.add_parser("override", help="Override CL2 config file")
    parser_override.add_argument("cl2_override_file", type=str, help="Path to the overrides of CL2 config file")

    # Sub-command for execute_clusterloader2
    parser_execute = subparsers.add_parser("execute", help="Execute scale up operation")
    parser_execute.add_argument("cl2_image", type=str, help="Name of the CL2 image")
    parser_execute.add_argument("cl2_config_dir", type=str, help="Path to the CL2 config directory")
    parser_execute.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_execute.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")
    parser_execute.add_argument("provider", type=str, help="Cloud provider name")

    # Sub-command for collect_clusterloader2
    parser_collect = subparsers.add_parser("collect", help="Collect scale up data")
    parser_collect.add_argument("cl2_report_dir", type=str, help="Path to the CL2 report directory")
    parser_collect.add_argument("cloud_info", type=str, help="Cloud information")
    parser_collect.add_argument("run_id", type=str, help="Run ID")
    parser_collect.add_argument("run_url", type=str, help="Run URL")
    parser_collect.add_argument("result_file", type=str, help="Path to the result file")
    parser_collect.add_argument("tag", type=str, help="Test tag")

    args = parser.parse_args()

    if args.command == "override":
        override_config_clusterloader2(args.cl2_override_file)
    elif args.command == "execute":
        execute_clusterloader2(args.cl2_image, args.cl2_config_dir, args.cl2_report_dir, args.kubeconfig, args.provider)
    elif args.command == "collect":
        collect_clusterloader2(args.cl2_report_dir, args.cloud_info, args.run_id, args.run_url, args.result_file, args.tag)

if __name__ == "__main__":
    main()