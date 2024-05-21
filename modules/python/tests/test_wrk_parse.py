import unittest
import json
from wrk.parser import parse_wrk_result

class TestWrkParser(unittest.TestCase):

  def test_parse_wrk_empty_file(self):
    file_name = "tests/wrk/empty.txt"
    with self.assertRaises(SystemExit) as se:
      self.assertEqual(parse_wrk_result(file_name), "No data to process!")
    self.assertEqual(se.exception.code, 1)

  def test_parse_wrk_output_file(self):
    file_name = "tests/wrk/result.txt"
    expected_result = {
      "duration": { "value": 1.0, "unit": "m" },
      "url": "http://localhost",
      "threads": 10,
      "connections": 125,
      "latency_stats": {
        "avg": { "value": 375.32, "unit": "us" },
        "stdev": { "value": 620.53, "unit": "us" },
        "max": { "value": 12.26, "unit": "ms" },
        "within_stdev": { "value": 86.68, "unit": "%"}
      },
      "req_sec_stats": {
        "avg": { "value": 48.23, "unit": "k" },
        "stdev": { "value": 21.85, "unit": "k" },
        "max": { "value": 102.69, "unit": "k" },
        "within_stdev": { "value": 67.24, "unit": "%"}
      },
      "latency_distribution": {
        "50th_percentile": { "value": 116.0, "unit": "us" },
        "75th_percentile": { "value": 211.0, "unit": "us" },
        "90th_percentile": { "value": 1.25, "unit": "ms" },
        "99th_percentile": { "value": 2.93, "unit": "ms" }
      },
      "total_requests": 20014600,
      "total_read": { "value": 7.19, "unit": "GB"},
      "socket_errors": {
        "connect": 120,
        "read": 0,
        "write": 0,
        "timeout": 0
      },
      "requests_per_sec": 333044.61,
      "transfer_per_sec": {"value": 122.58, "unit": "MB"}
    }

    expected_result = json.dumps(expected_result)
    result = parse_wrk_result(file_name)
    self.assertEqual(result, expected_result)

if __name__ == "__main__":
  unittest.main()
