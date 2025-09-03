import os

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


def convert_config_to_str(config_dict: dict) -> str:
    return '\n'.join([
        f"{k}" if v is None else f"{k}: {v}" for k, v in config_dict.items()
    ])


def write_to_file(
    filename: str,
    content: str,
):
    parent_dir = os.path.dirname(filename)
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    # os.chmod(os.path.dirname(result_file), 0o755)  # Ensure the directory is writable

    with open(filename, "w", encoding="utf-8") as file:
        file.write(content)
    
    with open(filename, "r", encoding="utf-8") as file:
        if logger:
            logger.info(f"Content of file {filename}:\n{file.read()}")


def read_from_file(
    filename: str,
    encoding: str = "utf-8"
) -> str:
    content = ""
    with open(filename, "r", encoding=encoding) as f:
        content = f.read()
    return content

