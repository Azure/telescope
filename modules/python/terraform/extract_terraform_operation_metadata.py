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

def get_job_tags():
    """Read job_tags from the JOB_TAGS environment variable.

    The JOB_TAGS variable is set by the set-job-tags.yml pipeline step as a JSON string
    containing the current matrix entry's key-value pairs.

    Returns:
        str or None: The job tags as a JSON string, or None if not available.
    """
    job_tags_str = os.getenv("JOB_TAGS", "")
    if not job_tags_str or job_tags_str == "{}":
        return None

    try:
        json.loads(job_tags_str)  # validate it's valid JSON
        return job_tags_str
    except json.JSONDecodeError as e:
        print(f"[WARNING] Failed to parse JOB_TAGS: {e}")
        return None

def process_terraform_logs(log_path, _command_type, _scenario_type, _scenario_name):
    log_file = os.path.join(log_path, f"terraform_{_command_type}.log")
    run_id = os.getenv("RUN_ID", "")
    results = []

    if not os.path.isfile(log_file):
        print(f"[WARNING] Log file not found: {log_file}")
        return results

    job_tags = get_job_tags()

    try:
        with open(log_file, "r", encoding='utf-8') as f:
            for line in f:
                match = PATTERN.search(line)
                if match:
                    full_path, time_str = match.groups()
                    seconds = time_to_seconds(time_str)
                    module, submodule, resource = parse_module_path(full_path)

                    result = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "run_id": run_id,
                        "scenario_type": _scenario_type,
                        "scenario_name": _scenario_name,
                        "module_name": module,
                        "submodule_name": submodule,
                        "resource_name": resource,
                        "action": _command_type,
                        "time_taken_seconds": seconds
                    }

                    if job_tags is not None:
                        result["job_tags"] = job_tags

                    results.append(result)
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
