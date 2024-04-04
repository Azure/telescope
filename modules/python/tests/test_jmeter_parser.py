import unittest
import json
from jmeter.parser import parse_jmeter_output

class TestJmeterParser(unittest.TestCase):
  def test_parse_jmeter_empty_file(self):
    file_name = "tests/jmeter/empty.csv"
    self.assertEqual(parse_jmeter_output(file_name), "Empty file!")

  def test_parse_jmeter_output_no_error(self):
    file_name = "tests/jmeter/result_no_error.csv"
    expected_result = {
      "# Samples": 4,
      "Average": 2.0,
      "Median": 1.0,
      "90% Line": 3.8,
      "95% Line": 4.4,
      "99% Line": 4.88,
      "Min": 1,
      "Max": 5,
      "Std. Dev.": 2.0,
      "Error %": 0.0,
      "Throughput": 30.77,
      "Received KB/sec": 26.46,
      "Errors": [],
    }

    expected_result = json.dumps(expected_result)
    result = parse_jmeter_output(file_name)
    self.assertEqual(result, expected_result)

  def test_parse_jmeter_output_with_error(self):
    file_name = "tests/jmeter/result_with_error.csv"
    expected_result = {
      "# Samples": 6,
      "Average": 108.0,
      "Median": 3.0,
      "90% Line": 320.0,
      "95% Line": 373.5,
      "99% Line": 416.3,
      "Min": 1,
      "Max": 427,
      "Std. Dev.": 177.62,
      "Error %": 33.33333333333333,
      "Throughput": 26.09,
      "Received KB/sec": 22.43,
      "Errors": [
        {
          "responseCode": 502,
          "responseMessage": "Bad Gateway"
        }
      ],
    }

    expected_result = json.dumps(expected_result)
    result = parse_jmeter_output(file_name)
    self.assertEqual(result, expected_result)

if __name__ == "__main__":
  unittest.main()
