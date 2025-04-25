import time
import traceback
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)

def execute_with_retries(func, max_retries:int=2, backoff_time:int=10, *args, **kwargs):
    retry_count = 0
    while retry_count <= max_retries:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Attempt {retry_count + 1} failed with error: {e}")
            traceback.print_exc()
            if retry_count < max_retries:
                retry_count += 1
                sleep_time = backoff_time * retry_count
                logger.info(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                raise