import re
import json
import sys
import os
import datetime

# Regex to extract: full module path and time
PATTERN = re.compile(r"(module\.[^:]+): (?:Creation|Destruction) complete after (\d+h\d+m\d+s|\d+h\d+s|\d+m\d+s|\d+s)")

def time_to_seconds(time_str):
    try:
        time_parts = re.findall(r'(\d+)([hms])', time_str)
        time_in_seconds = 0
        for value, unit in time_parts:
            if unit == 'h':
                time_in_seconds += int(value) * 3600
            elif unit == 'm':
                time_in_seconds += int(value) * 60
            elif unit == 's':
                time_in_seconds += int(value)
        return time_in_seconds
    except (ValueError, AttributeError) as e:
        print(f"Failed to convert time '{time_str}' to seconds: {e}")
        return 0

def parse_module_path(full_path):
    path = full_path.replace("module.", "")
    parts = path.split(".")

    module_name = parts[0] if parts else ""
    resource_name = parts[-1] if len(parts) > 1 else ""
    submodule_path = ".".join(parts[1:-1]) if len(parts) > 2 else ""

    return module_name, submodule_path, resource_name

def process_terraform_logs(log_path, _command_type, _scenario_type, _scenario_name):
    log_file = os.path.join(log_path, f"terraform_{_command_type}.log")
    run_id = os.getenv("RUN_ID", "")
    results = []

    if not os.path.isfile(log_file):
        print(f"[WARNING] Log file not found: {log_file}")
        return results

    try:
        with open(log_file, "r", encoding='utf-8') as f:
            for line in f:
                match = PATTERN.search(line)
                if match:
                    full_path, time_str = match.groups()
                    seconds = time_to_seconds(time_str)
                    module, submodule, resource = parse_module_path(full_path)

                    results.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "run_id": run_id,
                        "scenario_type": _scenario_type,
                        "scenario_name": _scenario_name,
                        "module_name": module,
                        "submodule_name": submodule,
                        "resource_name": resource,
                        "action": _command_type,
                        "time_taken_seconds": seconds
                    })
    except Exception as e:
        print(f"[ERROR] Failed to process log file '{log_file}': {e}")

    return results

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python3 extract_terraform_operation_time.py <log_directory> <result_output_file>")
        sys.exit(1)

    log_dir = sys.argv[1]
    result_file = sys.argv[2]
    scenario_type = sys.argv[3]
    scenario_name = sys.argv[4]

    try:
        apply_result = process_terraform_logs(log_dir, "apply", scenario_type, scenario_name)
        destroy_result = process_terraform_logs(log_dir, "destroy", scenario_type, scenario_name)
        merged_result = apply_result + destroy_result

        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        with open(result_file, 'w', encoding='utf-8') as file:
            for result in merged_result:
                print(json.dumps(result) + "\n")
                file.write(json.dumps(result) + "\n")

    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)
