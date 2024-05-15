import unittest
import json
from wrk.parser import parse_wrk_result

class TestJmeterParser(unittest.TestCase):

  def test_parse_wrk_empty_file(self):
    file_name = "tests/wrk/empty.txt"
    with self.assertRaises(SystemExit) as se:
      self.assertEqual(parse_wrk_result(file_name), "No data to process!")
    self.assertEqual(se.exception.code, 1)

  def test_parse_wrk_output_file(self):
    file_name = "tests/wrk/result.txt"
    expected_result = {
      "duration": "10s",
      "url": "http://localhost",
      "threads": 10,
      "connections": 25,
      "latency_stats": {
        "avg": "5.84ms",
        "stdev": "1.55ms",
        "max": "24.01ms",
        "percent_within_stdev": "97.20%"
      },
      "req_sec_stats": {
        "avg": "343.46",
        "stdev": "17.84",
        "max": "383.00",
        "percent_within_stdev": "70.30%"
      },
      "latency_distribution": {
        "50th_percentile": "5.59ms",
        "75th_percentile": "5.69ms",
        "90th_percentile": "5.81ms",
        "99th_percentile": "15.08ms"
      },
      "total_requests": 34221,
      "requests_per_sec": 3418.87,
      "transfer_per_sec": "2.80MB"
    }

    expected_result = json.dumps(expected_result)
    result = parse_wrk_result(file_name)
    self.assertEqual(result, expected_result)

if __name__ == "__main__":
  unittest.main()
