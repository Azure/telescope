"""
Collect and process benchmark results.

This module collects JSON result files from a specified directory and processes them
into a consolidated results file. It handles cluster data and operation information
from Kubernetes benchmark runs and formats them for further analysis.
"""

import glob
import json
import os
import sys
from datetime import datetime

# Add the parent directory to sys.path to allow imports from sibling packages
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
from utils.logger_config import get_logger, setup_logging
from utils.common import get_env_vars

# Configure logging
setup_logging()
logger = get_logger(__name__)


def create_result_dir(path):
    """
    Create result directory if it doesn't exist.

    Args:
        path: The directory path to create
    """
    if not os.path.exists(path):
        logger.info("Creating result directory: `%s`", path)
        os.makedirs(path)


def main():
    """Main function to process Cluster Crud benchmark results."""
    result_dir = get_env_vars("RESULT_DIR")
    run_url = get_env_vars("RUN_URL")
    run_id = get_env_vars("RUN_ID")
    region = get_env_vars("REGION")
    logger.info("environment variable REGION: `%s`", region)
    logger.info("environment variable RESULT_DIR: `%s`", result_dir)
    logger.info("environment variable RUN_URL: `%s`", run_url)

    create_result_dir(result_dir)

    for filepath in glob.glob(f"{result_dir}/*.json"):
        logger.info("Processing file: `%s`", filepath)
        with open(filepath, "r", encoding="utf-8") as file:
            content = json.load(file)
        logger.debug("Content: %s", content)

        result = {
            "timestamp": datetime.now().isoformat(),
            "region": region,
            "operation_info": json.dumps(content.get("operation_info")),
            "run_id": run_id,
            "run_url": run_url,
        }
        result_json = json.dumps(result)
        logger.debug("Result: %s", result_json)
        with open(f"{result_dir}/results.json", "a", encoding="utf-8") as file:
            file.write(result_json)
        logger.info("Result written to: `%s/results.json`", result_dir)


if __name__ == "__main__":
    main()
