import unittest
import json
from sockperf.parser import parse_sockperf_tcp_result

class TestSockperfParser(unittest.TestCase):

  def test_parse_sockperf_output_file(self):
    file_name = "tests/sockperf/result.txt"
    expected_result = {
        "raw": "sockperf: == version #3.7-no.git ==\nsockperf[CLIENT] send on:sockperf: using recvfrom() to block on socket(s)\n\n[ 0] IP = 10.2.1.4        PORT = 20005 # TCP\nsockperf: Warmup stage (sending a few dummy messages)...\nsockperf: Starting test...\nsockperf: Test end (interrupted by timer)\nsockperf: Test ended\nsockperf: [Total Run] RunTime=20.000 sec; Warm up time=400 msec; SentMessages=441774; ReceivedMessages=441773\nsockperf: ========= Printing statistics for Server No: 0\nsockperf: [Valid Duration] RunTime=19.550 sec; SentMessages=431623; ReceivedMessages=431623\nsockperf: ====> avg-rtt=45.237 (std-dev=42.017)\nsockperf: # dropped messages = 0; # duplicated messages = 0; # out-of-order messages = 0\nsockperf: Summary: Round trip is 45.237 usec\nsockperf: Total 431623 observations; each percentile contains 4316.23 observations\nsockperf: ---> <MAX> observation = 5090.021\nsockperf: ---> percentile 99.999 = 4929.629\nsockperf: ---> percentile 99.990 = 1520.337\nsockperf: ---> percentile 99.900 =  112.681\nsockperf: ---> percentile 99.000 =   51.635\nsockperf: ---> percentile 90.000 =   46.574\nsockperf: ---> percentile 75.000 =   45.883\nsockperf: ---> percentile 50.000 =   44.633\nsockperf: ---> percentile 25.000 =   43.792\nsockperf: ---> <MIN> observation =   34.918",
        "rtt": "45.237",
        "rtt_std": "42.017",
        "percentiles":
        [
            {
                "SamplingType": "MAX",
                "Duration": 5090.021
            },
            {
                "SamplingType": "99.900",
                "Duration": 112.681
            },
            {
                "SamplingType": "99.000",
                "Duration": 51.635
            },
            {
                "SamplingType": "90.000",
                "Duration": 46.574
            },
            {
                "SamplingType": "75.000",
                "Duration": 45.883
            },
            {
                "SamplingType": "50.000",
                "Duration": 44.633
            },
            {
                "SamplingType": "25.000",
                "Duration": 43.792
            }
        ]
    }

    expected_result = json.dumps(expected_result)
    result = parse_sockperf_tcp_result(file_name)
    self.maxDiff=None
    self.assertEqual(result, expected_result)

if __name__ == "__main__":
  unittest.main()