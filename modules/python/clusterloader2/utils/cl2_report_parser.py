import json
import os

from utils.logger_config import get_logger, setup_logging
from .common import read_from_file, get_measurement
from .xml_to_json_parser import Xml2JsonParser

# Configure logging
setup_logging()
logger = get_logger(__name__)


class Cl2ReportProcessor:
    def __init__(self, cl2_report_dir: str, template: dict):
        self.cl2_report_dir = cl2_report_dir
        self.template = template

    def _make_line(self, measurement, group_name, result_obj):
        result = self.template.copy()
        result["group"] = group_name
        result["measurement"] = measurement
        result["result"] = result_obj
        return json.dumps(result)

    def _process_file(self, path: str):
        logger.info(f"Processing {path}")

        measurement, group_name = get_measurement(path)
        if not measurement:
            return []

        try:
            raw = read_from_file(path)
            data = json.loads(raw)
        except Exception as e:
            logger.info(f"Failed to read/parse {path}: {e}")
            return []

        # If data contains multiple items, emit one line per item
        if isinstance(data, dict) and ("dataItems" in data):
            items = data.get("dataItems", [])
            if not items:
                logger.info(f"No data items found in {path}")
                logger.info(f"Data:\n{data}")
                return []
            return [self._make_line(measurement, group_name, item) for item in items]

        # Single-object result
        return [self._make_line(measurement, group_name, data)]

    def process(self) -> str:
        # Collect file paths (skip non-files)
        file_paths = [os.path.join(self.cl2_report_dir, fname) for fname in os.listdir(self.cl2_report_dir)]
        file_paths = [p for p in file_paths if os.path.isfile(p)]

        # Process all files and flatten results
        lines = [line for path in file_paths for line in self._process_file(path)]
        return "\n".join(lines) + ("\n" if lines else "")


def parse_test_results(cl2_report_dir: str) -> tuple[str, list[any]]:
    junit_xml_file = os.path.join(cl2_report_dir, "junit.xml")
    details = Xml2JsonParser(junit_xml_file, indent=2).parse()
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    return status, testsuites
