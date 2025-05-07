import unittest
from iperf3.parser import parse_tcp_output, parse_udp_output

class TestIperf3Parser(unittest.TestCase):
    def test_parse_tcp_output(self):
        stdout = """
{
	"start": {
		"test_start": {
			"num_streams": 2
		},
        "timestamp": {
			"timesecs": 1585574400
        }
	},
	"intervals":	[{
			"streams":	[{
					"socket":	5,
					"start":	58.001105,
					"end":	59.001109,
					"seconds":	1.0000040531158447,
					"bytes":	124911616,
					"bits_per_second":	999288877.766416,
					"retransmits":	0,
					"snd_cwnd":	159372,
					"snd_wnd":	3145728,
					"rtt":	231,
					"rttvar":	158,
					"pmtu":	1500,
					"omitted":	false,
					"sender":	true
				}, {
					"socket":	7,
					"start":	58.001134,
					"end":	59.001145,
					"seconds":	1.0000109672546387,
					"bytes":	124911616,
					"bits_per_second":	999281968.62019432,
					"retransmits":	0,
					"snd_cwnd":	153780,
					"snd_wnd":	3145728,
					"rtt":	193,
					"rttvar":	62,
					"pmtu":	1500,
					"omitted":	false,
					"sender":	true
				}],
			"sum":	{
				"start":	58.001105,
				"end":	59.001109,
				"seconds":	1.0000040531158447,
				"bytes":	249823232,
				"bits_per_second":	1998577755.5328321,
				"retransmits":	0,
				"omitted":	false,
				"sender":	true
			}
		}, {
        	"streams":	[{
					"socket":	5,
					"start":	59.001109,
					"end":	60.001675,
					"seconds":	1.0005660057067871,
					"bytes":	125042688,
					"bits_per_second":	999775625.290579,
					"retransmits":	1,
					"snd_cwnd":	155178,
					"snd_wnd":	3145728,
					"rtt":	330,
					"rttvar":	35,
					"pmtu":	1500,
					"omitted":	false,
					"sender":	true
				}, {
					"socket":	7,
					"start":	59.001145,
					"end":	60.00168,
					"seconds":	1.0005350112915039,
					"bytes":	125042688,
					"bits_per_second":	999806596.18172264,
					"retransmits":	3,
					"snd_cwnd":	156576,
					"snd_wnd":	3145728,
					"rtt":	337,
					"rttvar":	63,
					"pmtu":	1500,
					"omitted":	false,
					"sender":	true
				}],
			"sum":	{
				"start":	59.001109,
				"end":	60.001675,
				"seconds":	1.0005660057067871,
				"bytes":	250085376,
				"bits_per_second":	1999551250.5811577,
				"retransmits":	4,
				"omitted":	false,
				"sender":	true
			}
		}],
	"end":	{
		"streams":	[{
				"sender":	{
					"socket":	5,
					"start":	0,
					"end":	60.001675,
					"seconds":	60.001675,
					"bytes":	7500201984,
					"bits_per_second":	999999014.56084359,
					"retransmits":	743,
					"max_snd_cwnd":	342510,
					"max_snd_wnd":	3145728,
					"max_rtt":	330,
					"min_rtt":	231,
					"mean_rtt":	280.5,
					"sender":	true
				},
				"receiver":	{
					"socket":	5,
					"start":	0,
					"end":	60.001851,
					"seconds":	60.001675,
					"bytes":	7500201984,
					"bits_per_second":	999996081.32089126,
					"sender":	true
				}
			}, {
				"sender":	{
					"socket":	7,
					"start":	0,
					"end":	60.001675,
					"seconds":	60.001675,
					"bytes":	7500201984,
					"bits_per_second":	999999014.56084359,
					"retransmits":	750,
					"max_snd_cwnd":	311754,
					"max_snd_wnd":	3145728,
					"max_rtt":	337,
					"min_rtt":	193,
					"mean_rtt":	265,
					"sender":	true
				},
				"receiver":	{
					"socket":	7,
					"start":	0,
					"end":	60.001851,
					"seconds":	60.001675,
					"bytes":	7500201984,
					"bits_per_second":	999996081.32089126,
					"sender":	true
				}
			}],
		"sum_sent":	{
			"start":	0,
			"end":	60.001675,
			"seconds":	60.001675,
			"bytes":	15000403968,
			"bits_per_second":	1999998029.1216872,
			"retransmits":	1493,
			"sender":	true
		},
		"sum_received":	{
			"start":	0,
			"end":	60.001851,
			"seconds":	60.001851,
			"bytes":	15000403968,
			"bits_per_second":	1999992162.6417825,
			"sender":	true
		},
		"cpu_utilization_percent":	{
			"host_total":	49.681522294439162,
			"host_user":	1.2592420893075011,
			"host_system":	15.553787429500328,
			"remote_total":	50.0066564627557,
			"remote_user":	0.66067939781411145,
			"remote_system":	18.97770821179893
		},
		"sender_tcp_congestion":	"cubic",
		"receiver_tcp_congestion":	"cubic"
	}
}
        """
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

        self.maxDiff = None
        self.assertEqual(parse_tcp_output(stdout), expected_result)

    def test_parse_udp_output(self):
        stdout = """
{
	"start": {
        "timestamp": {
			"timesecs": 1585574400
        }
	},
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