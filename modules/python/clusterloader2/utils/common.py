import os
from utils.logger_config import setup_logging, get_logger

# Configure logging
setup_logging()
logger = get_logger(__name__)


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