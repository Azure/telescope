import os
import json
import glob
import sys
from datetime import datetime
from pathlib import Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)


def get_env_vars(name: str):
    var = os.environ.get(name, None)
    if var is None:
        raise RuntimeError(f"Environment variable `{name}` not set")
    return var


def create_result_dir(path):
    if not os.path.exists(path):
        logger.info(f"Creating result directory: `{path}`")
        os.makedirs(path)


def main():
    RESULT_DIR = get_env_vars("RESULT_DIR")
    RUN_URL = get_env_vars("RUN_URL")
    RUN_ID = get_env_vars("RUN_ID")
    REGION = get_env_vars("REGION")
    logger.info(f"environment variable REGION: `{REGION}`")
    logger.info(f"environment variable RESULT_DIR: `{RESULT_DIR}`")
    logger.info(f"environment variable RUN_URL: `{RUN_URL}`")

    create_result_dir(RESULT_DIR)

    for filepath in glob.glob(f"{RESULT_DIR}/*.json"):
        filename = Path(filepath).name
        logger.info(f"Processing file: `{filepath}`")
        content = json.load(open(filepath, "r"))
        logger.debug(f"Content: {content}")
        result = {
            "timestamp": datetime.now().isoformat(),
            "region": REGION,
            "cluster_info": json.dumps(content.get("cluster_data")),
            "operation_info": json.dumps(content.get("operation_info")),
            "run_id": RUN_ID,
            "run_url": RUN_URL,
        }
        result_json = json.dumps(result)
        logger.debug(f"Result: {result_json}")
        with open(f"{RESULT_DIR}/results.json", "a") as f:
            f.write(result_json)
        logger.info(f"Result written to: `{RESULT_DIR}/results.json`")


if __name__ == "__main__":
    main()
