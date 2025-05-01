import re
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
