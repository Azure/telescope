import unittest
from iperf2.runner import generate_iperf2_command

class TestGenerateIperf2Command(unittest.TestCase):
    def test_tcp_command(self):
        command = generate_iperf2_command("tcp", "192.168.1.1", "5001", 100, 1, 60)
        expected_command = "iperf --enhancedreports --format m --client 192.168.1.1 --port 5001 --bandwidth 100M --parallel 1 --time 60"
        self.assertEqual(command, expected_command)

    def test_udp_command(self):
        command = generate_iperf2_command("udp", "192.168.1.1", "5001", 100, 2, 120)
        expected_command = "iperf --enhancedreports --format m --udp --client 192.168.1.1 --port 5001 --bandwidth 100M --parallel 2 --time 120"
        self.assertEqual(command, expected_command)

if __name__ == "__main__":
    unittest.main()