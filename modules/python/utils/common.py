import re
import os
import json
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)


def extract_parameter(command: str, parameter_name: str, prefix: str = "--", has_space: bool = True):
    """
    Extracts the value of the given parameter_name from the given command string.

    Returns: value of given parameter_name, or None if not found.
        command (str): The command string containing parameters in the format '--<parameter_name> <value>'.
        parameter_name (str): The name of the parameter to extract.
        prefix (str): The prefix used before the parameter name (default is '--').
        space (bool): Whether there is a space between the parameter name and its value (default is True).

    Returns:
        int: The value of the given parameter_name, or None if not found.
    """
    space = r"\s+" if has_space else ""
    match = re.search(rf"{prefix}{parameter_name}{space}(\d+)", command)
    if match:
        value = int(match.group(1))
        logger.info(f"Parameter '{parameter_name}' value is: '{value}'")
        return value
    return None


def save_info_to_file(info, file_path):
    """
    Save information to a JSON file.
    """
    if not info:
        logger.error(f"No data to save for {file_path}. Skipping file creation.")
        return

    directory = os.path.dirname(file_path)
    if not os.path.exists(directory):
        raise Exception(
            f"Directory does not exist: {directory}. Please ensure it is created before running the script.")

    logger.info(f"Writing data to {file_path}")
    with open(file_path, "w", encoding='utf-8') as f:
        json.dump(info, f, indent=2)

def get_env_vars(name: str):
    """
    Get environment variable value.
    Args:
        name: The name of the environment variable
    Returns:
        The value of the environment variable
    Raises:
        RuntimeError: If the environment variable is not set
    """
    var = os.environ.get(name, None)
    if var is None:
        raise RuntimeError(f"Environment variable `{name}` not set")
    return var
