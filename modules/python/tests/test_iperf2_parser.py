import unittest
from iperf2.parser import parse_tcp_output, parse_udp_output

class TestIperf2Parser(unittest.TestCase):
    def test_parse_tcp_output(self):
        stdout = """
------------------------------------------------------------
Client connecting to 172.206.206.58, TCP port 20001 with pid 193667
Write buffer size: 0.12 MByte
TCP window size: 2.81 MByte (default)
------------------------------------------------------------
[  3] local 10.2.1.4 port 46710 connected with 172.206.206.58 port 20001 (ct=2.15 ms)
[ ID] Interval            Transfer    Bandwidth       Write/Err  Rtry     Cwnd/RTT        NetPwr
[  3] 0.0000-10.0086 sec  2269 MBytes  1902 Mbits/sec  18151/0          0       -1K/2167 us  109692.59
        """
        expected_result = {
            "total_throughput": 1902.0,
            "buffer_size": 0.12,
            "tcp_window_size": 2.81,
            "write_packet_count": 18151,
            "err_packet_count": 0,
            "retry_packet_count": 0,
            "congestion_window": -1.0,
            "rtt": 2167.0,
            "rtt_unit": 'us',
            "netpwr": 109692.59,
        }

        self.assertEqual(parse_tcp_output(stdout), expected_result)

    def test_parse_udp_output(self):
        stdout = """
------------------------------------------------------------
Client connecting to 172.206.206.58, UDP port 20002 with pid 193726
Sending 1470 byte datagrams, IPG target: 11215.21 us (kalman adjust)
UDP buffer size: 0.20 MByte (default)
------------------------------------------------------------
[  3] local 10.2.1.4 port 37322 connected with 172.206.206.58 port 20002
[ ID] Interval            Transfer     Bandwidth      Write/Err  PPS
[  3] 0.0000-10.0041 sec  1.25 MBytes  1.05 Mbits/sec  892/0       89 pps
[  3] Sent 892 datagrams
[  3] Server Report:
[  3]  0.0-10.0 sec  1.25 MBytes  1.05 Mbits/sec   0.251 ms    0/  892 (0%)
        """
        expected_result = {
            "total_throughput": 1.05,
            "buffer_size": 0.20,
            "datagram_size_bytes": 1470,
            "write_packet_count": 892,
            "err_packet_count": 0,
            "pps": 89,
            "ipg_target": 11215.21,
            "ipg_target_unit": "us",
            "jitter": 0.251,
            "jitter_unit": "ms",
            "lost_datagrams": 0,
            "total_datagrams": 892,
            "out_of_order_datagrams": 0,
        }

        self.assertEqual(parse_udp_output(stdout), expected_result)

if __name__ == "__main__":
    unittest.main()