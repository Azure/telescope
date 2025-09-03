import unittest
from pathlib import Path
from datetime import datetime, timezone

from clusterloader2.utils import parse_test_results, Cl2ReportProcessor


class TestCl2ReportProcessor(unittest.TestCase):

    CURRENT_DIR = Path(__file__).resolve().parent

    def setUp(self):
        cl2_report_dir = self.CURRENT_DIR.parent / "mock_data" / "network-policy-scale" / "report"
        self.cl2_report_dir = cl2_report_dir.absolute()
        self.template = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "node_count": 10,
            "pod_count": 14,
            "status": "success",
            "group": None,
            "measurement": None,
            "result": None,
            "cloud_info": "aks",
            "run_id": "12345",
            "run_url": "https://microsoft.com",
            "test_type": "perf-eval",
        }
        self.processor = Cl2ReportProcessor(self.cl2_report_dir, self.template)

    def test_process(self):
        result = self.processor.process()
        self.assertIsInstance(result, str)

    def test_parse_test_results(self):
        status, testsuites = parse_test_results(self.cl2_report_dir)
        self.assertIn(status, ["success", "failure"])
        self.assertIsInstance(testsuites, list)


if __name__ == "__main__":
    unittest.main()
