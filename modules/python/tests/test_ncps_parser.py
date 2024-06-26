import unittest
import json
from ncps.parser import parse_ncps_result

class TestWrkParser(unittest.TestCase):

  def test_parse_ncps_output_file(self):
    file_name = "tests/ncps/result.txt"
    expected_result = {
      "cmd": "./ncps -c 127.0.0.1 -wt 5 -t 25 -r 10",
      "thread_count": 10,
      "version": "1.1",
      "recevied": {
        "value": 0.24,
        "unit": "Gbps"
      },
      "sent": {
        "value": 0.24,
        "unit": "Gbps"
      },
      "connection_times": [
        {
          "N": 100000,
          "T(ms)": 3576,
          "CPS": 27964
        },
        {
          "N": 200000,
          "T(ms)": 7006,
          "CPS": 28546
        },
        {
          "N": 300000,
          "T(ms)": 10364,
          "CPS": 28946
        },
        {
          "N": 400000,
          "T(ms)": 13673,
          "CPS": 29254
        },
        {
          "N": 500000,
          "T(ms)": 17064,
          "CPS": 29301
        },
        {
          "N": 589122,
          "T(ms)": 20004,
          "CPS": 29450
        }
      ],
      "cps": 29450,
      "synrtt": {
        "P25": 13,
        "Median": 13,
        "Mean": 146,
        "P75": 14,
        "P90": 15,
        "P95": 18,
        "P99": 4189,
        "P99.9": 7081,
        "P99.99": 8699
      },
      "rtconnpercentage": 0.0,
      "rtperconn": 0.0
    }

    expected_result = json.dumps(expected_result)
    result = parse_ncps_result(file_name)
    self.assertEqual(result, expected_result)
  
  def test_parse_ncps_output_file_with_retransmit(self):
    file_name = "tests/ncps/result_with_retransmit.txt"
    expected_result = {
      "cmd": "ncps -c 10.2.1.4 -wt 5 -t 60 -r 10",
      "thread_count": 10,
      "version": "1.1",
      "recevied": {
        "value": 0.13,
        "unit": "Gbps"
      },
      "sent": {
        "value": 0.13,
        "unit": "Gbps"
      },
      "connection_times": [
        {
          "N": 100000,
          "T(ms)": 6641,
          "CPS": 15057
        },
        {
          "N": 200000,
          "T(ms)": 12909,
          "CPS": 15493
        },
        {
          "N": 300000,
          "T(ms)": 19100,
          "CPS": 15706
        },
        {
          "N": 400000,
          "T(ms)": 25250,
          "CPS": 15841
        },
        {
          "N": 500000,
          "T(ms)": 31437,
          "CPS": 15904
        },
        {
          "N": 600000,
          "T(ms)": 37692,
          "CPS": 15918
        },
        {
          "N": 700000,
          "T(ms)": 43943,
          "CPS": 15929
        },
        {
          "N": 800000,
          "T(ms)": 50078,
          "CPS": 15975
        },
        {
          "N": 880267,
          "T(ms)": 55007,
          "CPS": 16002
        }
      ],
      "cps": 16002,
      "synrtt": {
        "P25": 794,
        "Median": 1361,
        "Mean": 29229,
        "P75": 4340,
        "P90": 112028,
        "P95": 117808,
        "P99": 211674,
        "P99.9": 244072,
        "P99.99": 1219000
      },
      "rtconnpercentage": 0.2015,
      "rtperconn": 1.0073
    }

    expected_result = json.dumps(expected_result)
    result = parse_ncps_result(file_name)
    self.assertEqual(result, expected_result)

if __name__ == "__main__":
  unittest.main()
