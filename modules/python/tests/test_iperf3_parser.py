import unittest
from iperf3.parser import parse_tcp_output, parse_udp_output

class TestIperf3Parser(unittest.TestCase):
    def test_parse_tcp_output(self):
        stdout = """
{
	"start": {
		"test_start": {
			"num_streams": 1
		}
	},
	"end": {
		"streams": [
			{
				"sender": {
					"socket": 5,
					"start": 0,
					"end": 10.000386,
					"seconds": 10.000386,
					"bytes": 25965363200,
					"bits_per_second": 20771488780.53307,
					"retransmits": 1,
					"max_snd_cwnd": 3339633,
					"max_snd_wnd": 3112448,
					"max_rtt": 117,
					"min_rtt": 46,
					"mean_rtt": 76,
					"sender": true
				},
				"receiver": {
					"socket": 5,
					"start": 0,
					"end": 10.0053,
					"seconds": 10.000386,
					"bytes": 25964707840,
					"bits_per_second": 20760763067.574184,
					"sender": true
				}
			}
		],
		"cpu_utilization_percent": {
			"host_total": 49.681522294439162,
			"host_user": 1.31287197806098,
			"host_system": 48.3686603141087,
			"remote_total": 50.0066564627557,
			"remote_user": 4.0128175887333475,
			"remote_system": 45.993848868711169
		}
	}
}
        """
        expected_result = {
            'throughput': 20771488780.53307,
            'retransmits': 1,
            'max_rtt': 117,
            'min_rtt': 46,
            'mean_rtt': 76,
            'cpu_usage_client': 49.681522294439162,
            'cpu_usage_server': 50.0066564627557,
        }

        self.assertEqual(parse_tcp_output(stdout), expected_result)

    def test_parse_udp_output(self):
        stdout = """
{
	"end":	{
		"sum":	{
			"start":	0,
			"end":	10.000579,
			"seconds":	10.000579,
			"bytes":	1310720,
			"bits_per_second":	1048546.1164356816,
			"jitter_ms":	0.015205598777989252,
			"lost_packets":	0,
			"packets":	40,
			"lost_percent":	0,
			"sender":	true
		},
		"cpu_utilization_percent":	{
			"host_total":	2.16911029122016,
			"host_user":	0.67411861083911218,
			"host_system":	1.4949916803810477,
			"remote_total":	0.021418732011064947,
			"remote_user":	0.0014499141650814273,
			"remote_system":	0.019968817845983519
		}
	}
}
"""
        expected_result = {
            'throughput': 1048546.1164356816,
            'jitter_ms': 0.015205598777989252,
            'lost_packets': 0,
            'total_packets': 40,
            'lost_percent': 0,
            'cpu_usage_client': 2.16911029122016,
            'cpu_usage_server': 0.021418732011064947
        }

        self.assertEqual(parse_udp_output(stdout), expected_result)

if __name__ == "__main__":
    unittest.main()