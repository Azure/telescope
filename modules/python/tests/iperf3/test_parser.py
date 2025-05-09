import unittest
import os
from iperf3.parser import parse_tcp_output, parse_udp_output


class TestIperf3Parser(unittest.TestCase):
    def setUp(self):
        self.mock_data_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "mock_data", "iperf3"
        )
        self.tcp_output_file = os.path.join(self.mock_data_dir, "tcp.json")
        self.udp_output_file = os.path.join(self.mock_data_dir, "udp.json")

    def test_parse_tcp_output(self):
        with open(self.tcp_output_file, "r", encoding="utf-8") as f:
            stdout = f.read()

        expected_result = {
            'timestamp': '2020-03-30T13:20:00Z',
            'total_throughput': 1999.998029121687,
            'retransmits': 1493,
            'max_rtt': 337,
            'min_rtt': 193,
            'p50_rtt': 280.5,
            'p90_rtt': 321.35,
            'p99_rtt': 332.28499999999997,
            'rtt': 272.75,
            'rtt_unit': 'us',
            'cpu_usage_client': 49.681522294439162,
            'cpu_usage_server': 50.0066564627557,
        }

        self.assertEqual(parse_tcp_output(stdout), expected_result)

    def test_parse_udp_output(self):
        with open(self.udp_output_file, "r", encoding="utf-8") as f:
            stdout = f.read()

        expected_result = {
            'timestamp': '2020-03-30T13:20:00Z',
            'total_throughput': 1.0485461164356815,
            'jitter': 0.015205598777989252,
            'jitter_unit': 'ms',
            'lost_datagrams': 0,
            'total_datagrams': 40,
            'lost_percent': 0,
            'cpu_usage_client': 2.16911029122016,
            'cpu_usage_server': 0.021418732011064947
        }

        self.assertEqual(parse_udp_output(stdout), expected_result)


if __name__ == "__main__":
    unittest.main()
