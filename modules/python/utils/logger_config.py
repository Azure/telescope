import logging


DEFAULT_LOG_LEVEL = logging.WARNING

class AzureDevOpsFormatter(logging.Formatter):
    VSO_FORMATS = {
        'ERROR': '##vso[task.logissue type=error;]',
        'WARNING': '##vso[task.logissue type=warning;]',
        'INFO': '',
        'DEBUG': '##[debug]'
    }

    def format(self, record):
        vso_prefix = self.VSO_FORMATS.get(record.levelname, '')
        # Format the message without the VSO prefix first
        formatted_msg = super().format(record)
        # Then add the VSO prefix at the start
        return f"{vso_prefix}{formatted_msg}"

def setup_logging():
    root_logger = logging.getLogger()
    # Clear any existing handlers
    root_logger.handlers = []

    formatter = AzureDevOpsFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(DEFAULT_LOG_LEVEL)
    root_logger.addHandler(handler)
    root_logger.setLevel(DEFAULT_LOG_LEVEL)
    return root_logger

def get_logger(name):
    return logging.getLogger(name)
