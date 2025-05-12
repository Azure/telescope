import unittest
import argparse
import sys
import json
import os
from io import StringIO
from unittest.mock import MagicMock, patch
from iperf3.iperf3_pod import Iperf3Pod, command_constants, main, parse_args


class TestIPerfsPod(unittest.TestCase):
    @patch('kubernetes.config.load_kube_config')
    def setUp(self, _mock_load_kube_config):  # pylint: disable=arguments-differ
        self.namespace = "test-namespace"
        self.iperf3 = Iperf3Pod(
            namespace=self.namespace,
            cluster_cli_context="cli-context",
            cluster_srv_context="srv-context",
        )
        self.iperf3.k8s_client = MagicMock()
        self.client_pod_info = {"name": "client-pod",
                                "ip": "10.0.0.2", "node_ip": "10.0.10.2"}
        self.server_pod_info = {"name": "server-pod",
                                "ip": "10.0.0.1", "node_ip": "10.0.20.1"}
        self.service_external_ip = "1.2.3.4"

    def _assert_run_command(self, command, result_file, pod_name="client-pod", container_name='iperf3-client'):
        self.iperf3.k8s_client.run_pod_exec_command.assert_any_call(
            pod_name=pod_name,
            command=command,
            container_name=container_name,
            dest_path=result_file,
            namespace=self.namespace
        )

    def _assert_run_command_server(self, command, result_file):
        self._assert_run_command(
            command, result_file, pod_name="server-pod", container_name='iperf3-server')

    def test_validate(self):
        self.iperf3.get_pod_by_role = MagicMock(side_effect=[
            self.client_pod_info,
            self.server_pod_info
        ])

        self.iperf3.validate()

        self.iperf3.k8s_client.run_pod_exec_command.assert_any_call(
            pod_name="client-pod",
            command=command_constants.IPERF3_VERSION_CMD,
            container_name='iperf3-client',
            dest_path="",
            namespace=self.namespace
        )
        self.iperf3.k8s_client.run_pod_exec_command.assert_any_call(
            pod_name="server-pod",
            command=command_constants.IPERF3_VERSION_CMD,
            container_name='iperf3-server',
            dest_path="",
            namespace=self.namespace
        )

    def test_run_iperf3(self):
        self.iperf3.get_pod_by_role = MagicMock(side_effect=[
            self.server_pod_info,
            self.client_pod_info
        ])
        protocol = "tcp"
        bandwidth = 1000
        parallel = 1
        datapath = "direct"
        iperf3_properties = "--time 60 --bandwidth 1000M --parallel 1 --interval 0 --port 20003"
        result_file = f"iperf3-{protocol}-{bandwidth}-{parallel}-{datapath}.json"
        expected_command = (
            f"iperf3 -c {self.server_pod_info['ip']} {iperf3_properties} --json"
        )

        self.iperf3.run_iperf3(iperf3_properties, result_file)
        self._assert_run_command(expected_command, result_file)

    def test_run_iperf3_server_node_ip(self):
        self.iperf3.get_pod_by_role = MagicMock(side_effect=[
            self.server_pod_info,
            self.client_pod_info
        ])
        protocol = "tcp"
        bandwidth = 1000
        parallel = 1
        datapath = "direct"
        iperf3_properties = "--time 60 --bandwidth 1000M --parallel 1 --interval 0 --port 20003"
        result_file = f"iperf3-{protocol}-{bandwidth}-{parallel}-{datapath}.json"
        expected_command = (
            f"iperf3 -c {self.server_pod_info['node_ip']} {iperf3_properties} --json"
        )

        self.iperf3.run_iperf3(
            iperf3_command=iperf3_properties, result_file=result_file, server_ip_type="node"
        )
        self._assert_run_command(expected_command, result_file)

    def test_run_iperf3_server_slb(self):
        self.iperf3.get_pod_by_role = MagicMock(side_effect=[
            self.server_pod_info,
            self.client_pod_info
        ])
        protocol = "tcp"
        bandwidth = 1000
        parallel = 1
        datapath = "direct"
        iperf3_properties = "--time 60 --bandwidth 1000M --parallel 1 --interval 0 --port 20003"
        result_file = f"iperf3-{protocol}-{bandwidth}-{parallel}-{datapath}.json"
        expected_command = (
            f"iperf3 -c {self.service_external_ip } {iperf3_properties} --json"
        )

        self.iperf3.get_service_external_ip = MagicMock(
            return_value=self.service_external_ip
        )
        self.iperf3.run_iperf3(
            iperf3_command=iperf3_properties, result_file=result_file, server_ip_type="external"
        )
        self._assert_run_command(expected_command, result_file)

    def test_run_iperf3_error(self):
        self.iperf3.get_pod_by_role = MagicMock(side_effect=[
            self.server_pod_info,
            self.client_pod_info
        ])
        iperf3_properties = "--tcp"
        result_file = "/tmp/iperf3-tcp-direct.json"

        self.iperf3.k8s_client.run_pod_exec_command.return_value = {
            "error": "error"}
        with self.assertRaises(Exception):
            self.iperf3.run_iperf3(iperf3_properties, result_file)

    def test_run_netstat(self):
        self.iperf3.get_pod_by_role = MagicMock(side_effect=[
            self.client_pod_info
        ])

        role = "client"
        stage_name = "before-execute"
        index = 1
        result_dir = "/tmp"
        result_file = f"{result_dir}/{role}-netstat-{stage_name}-{index}.json"

        self.iperf3.run_netstat(role, result_dir, stage_name, index)
        self._assert_run_command(command_constants.NETSTAT_CMD, result_file)

    def test_run_lscpu(self):
        self.iperf3.get_pod_by_role = MagicMock(side_effect=[
            self.client_pod_info
        ])

        role = "client"
        result_dir = "/tmp"
        result_file = f"{result_dir}/{role}-lscpu.json"

        self.iperf3.run_lscpu(role, result_dir)
        self._assert_run_command(command_constants.LSCPU_CMD, result_file)

    @patch("builtins.open", new_callable=MagicMock)
    @patch("json.dump")
    def test_run_lspci(self, mock_json_dump, mock_open_file):
        self.iperf3.get_pod_by_role = MagicMock(side_effect=[
            self.client_pod_info
        ])

        role = "client"
        result_dir = "/tmp"
        result_file = f"{result_dir}/{role}-lspci.json"

        self.iperf3.run_lspci(role, result_dir)
        self._assert_run_command(command_constants.LSPCI_CMD, "")

        mock_open_file.assert_called_with(result_file, 'w', encoding='utf-8')
        mock_json_dump.assert_called()

    @patch("builtins.open", new_callable=MagicMock)
    @patch("json.dump")
    def test_run_benchmark(self, _mock_json_dump, _mock_open):
        self.iperf3.get_pod_by_role = MagicMock(
            side_effect=[
                self.client_pod_info,
                self.server_pod_info,
                self.client_pod_info,
                self.server_pod_info,
                self.server_pod_info,
                self.client_pod_info,
                self.client_pod_info,
                self.server_pod_info,
                self.client_pod_info,
                self.server_pod_info,
                self.client_pod_info,
                self.server_pod_info,
                self.client_pod_info,
                self.server_pod_info,
            ])

        result_dir = "/tmp"
        result_file = "iperf3-tcp-1000-1-direct.json"
        self.iperf3.run_benchmark(
            index=1,
            iperf3_command="--time 60 --bandwidth 1000M --parallel 1 --interval 0 --port 20003",
            result_dir=result_dir,
            result_file=f"{result_dir}/{result_file}"
        )

        self._assert_run_command(
            command_constants.NETSTAT_CMD, f"{result_dir}/client-netstat-before-execute-1.json")
        self._assert_run_command_server(
            command_constants.NETSTAT_CMD, f"{result_dir}/server-netstat-before-execute-1.json")
        self._assert_run_command(
            command_constants.IP_LINK_CMD, f"{result_dir}/client-ip-link-before-execute-1.json")
        self._assert_run_command_server(
            command_constants.IP_LINK_CMD, f"{result_dir}/server-ip-link-before-execute-1.json")
        self._assert_run_command(
            "iperf3 -c 10.0.0.1 --time 60 --bandwidth 1000M --parallel 1 --interval 0 --port 20003 --json",
            f"{result_dir}/{result_file}")
        self._assert_run_command(
            command_constants.NETSTAT_CMD, f"{result_dir}/client-netstat-after-execute-1.json")
        self._assert_run_command_server(
            command_constants.NETSTAT_CMD, f"{result_dir}/server-netstat-after-execute-1.json")
        self._assert_run_command(
            command_constants.IP_LINK_CMD, f"{result_dir}/client-ip-link-after-execute-1.json")
        self._assert_run_command_server(
            command_constants.IP_LINK_CMD, f"{result_dir}/server-ip-link-after-execute-1.json")
        self._assert_run_command(
            command_constants.LSCPU_CMD, f"{result_dir}/client-lscpu.json")
        self._assert_run_command_server(
            command_constants.LSCPU_CMD, f"{result_dir}/server-lscpu.json")

    def test_create_result_file_name(self):
        protocol = "tcp"
        bandwidth = 1000
        parallel = 1
        datapath = "direct"
        result_dir = "/tmp"
        result_file = self.iperf3.create_result_file_name(
            result_dir, protocol, bandwidth, parallel, datapath)
        expected_file_name = f"{result_dir}/iperf3-{protocol}-{bandwidth}-{parallel}-{datapath}.json"
        self.assertEqual(result_file, expected_file_name)

    @patch('iperf3.parser.parse_tcp_output')
    @patch('iperf3.parser.parse_udp_output')
    @patch('os.makedirs')
    @patch('json.dumps')
    @patch('json.load')
    @patch('os.path.exists')
    @patch('builtins.open')
    def test_collect_iperf3_protocol(self, mock_open_file, mock_exists, mock_json_load,
                                     mock_json_dumps, mock_makedirs, mock_parse_udp, mock_parse_tcp):
        # Test cases for different protocols
        test_cases = [
            {
                'protocol': 'tcp',
                'mock_parser': mock_parse_tcp,
                'result': '''
                {
                    "start": {
                        "timestamp": {
                            "timesecs": 1585574400
                        }
                    },
                    "intervals": [{
                        "streams": [{
                            "bits_per_second": 999996999.202924,
                            "retransmits": 121,
                            "rtt": 291,
                            "rttvar": 35
                        }]
                    }],
                    "end": {
                        "streams": [{
                            "sender": {
                                "bits_per_second": 999996988.50411165,
                                "retransmits": 121
                            }
                        }],
                        "cpu_utilization_percent": {
                            "host_total": 20.234409649389292,
                            "remote_total": 9.33333766228252
                        }
                    }
                }
                ''',
                'parsed_result': {
                    "timestamp": "2020-03-30T13:20:00Z",
                    "total_throughput": 999.9969885041116,
                    "retransmits": 121,
                    "p50_rtt": 291.0,
                    "p90_rtt": 291.0,
                    "p99_rtt": 291.0,
                    "max_rtt": 291,
                    "min_rtt": 291,
                    "rtt": 291.0,
                    "rtt_unit": "us",
                    "cpu_usage_client": 20.234409649389292,
                    "cpu_usage_server": 9.33333766228252
                }
            },
            {
                'protocol': 'udp',
                'mock_parser': mock_parse_udp,
                'result': '''
                {
                    "start": {"version": "iperf 3.7", "timestamp": {"timesecs": 1585574400}},
                    "intervals": [{"sum": {"bits_per_second": 952733490.6219, "jitter_ms": 0.5, "lost_packets": 10, "packets": 1000}}],
                    "end": {
                        "sum": {"bits_per_second": 952733490.6219, "jitter_ms": 0.5, "lost_packets": 10, "packets": 1000}
                    }
                }
                ''',
                'parsed_result': {
                    "bw": 952.73,
                    "jitter": 0.5,
                    "lost_percent": 1.0
                }
            }
        ]

        mock_files = {
            "client-lscpu.json": json.dumps(["CPU info"]),
            "server-lscpu.json": json.dumps(["CPU info"]),
            "client-lspci.json": json.dumps(["PCI info"]),
            "server-lspci.json": json.dumps(["PCI info"]),
            "client-netstat-before-execute-1.json": json.dumps({"connections": 10}),
            "server-netstat-before-execute-1.json": json.dumps({"connections": 5}),
            "client-netstat-after-execute-1.json": json.dumps({"connections": 11}),
            "server-netstat-after-execute-1.json": json.dumps({"connections": 6}),
            "client-ip-link-before-execute-1.json": json.dumps({"link": "info"}),
            "server-ip-link-before-execute-1.json": json.dumps({"link": "info"}),
            "client-ip-link-after-execute-1.json": json.dumps({"link": "info"}),
            "server-ip-link-after-execute-1.json": json.dumps({"link": "info"}),
            "client_pod_node_info.json": json.dumps({"pod": "client-pod", "node": "client-node"}),
            "server_pod_node_info.json": json.dumps({"pod": "server-pod", "node": "server-node"})
        }

        for test_case in test_cases:
            with self.subTest(protocol=test_case['protocol']):
                protocol = test_case['protocol']
                bandwidth = 1000
                parallel = 1
                datapath = 'direct'
                index = '1'
                cloud_info = {"provider": "azure", "region": "westus2"}
                run_url = "https://example.com/run"
                result_dir = "/tmp"
                result_file = "/tmp/final_results.json"
                iperf3_result_file = f"{result_dir}/iperf3-{protocol}-{bandwidth}-{parallel}-{datapath}.json"

                # # Configure json.load to return different content based on the file
                def side_effect_load(file_handle):
                    for file_path, content in mock_files.items():
                        if hasattr(file_handle, 'name') and file_handle.name == file_path:
                            return json.loads(content)
                    return {}

                # Set up mocks properly
                mock_exists.return_value = True
                mock_json_load.side_effect = side_effect_load

                # Set up the open mock to use a context manager mock
                mock_file_handle = mock_open_file.return_value.__enter__.return_value
                mock_file_handle.read.return_value = test_case['result']

                test_case['mock_parser'].return_value = test_case['parsed_result']
                mock_json_dumps.return_value = '{}'

                # Call the function under test
                self.iperf3.collect_iperf3(
                    result_dir=result_dir,
                    result_file=result_file,
                    cloud_info=cloud_info,
                    run_url=run_url,
                    protocol=protocol,
                    bandwidth=bandwidth,
                    parallel=parallel,
                    datapath=datapath,
                    index=index,
                    is_k8s=True
                )

                # Verify the open calls
                mock_open_file.assert_any_call(
                    iperf3_result_file, 'r', encoding='utf-8')
                mock_open_file.assert_any_call(
                    result_file, 'a', encoding='utf-8')

                # Verify that write was called with JSON content
                mock_file_handle.write.assert_called()

                # Check that makedirs was called to ensure directory exists
                mock_makedirs.assert_called_with(
                    os.path.dirname(result_file), exist_ok=True)

                # Reset mocks for next iteration
                mock_open_file.reset_mock()
                mock_exists.reset_mock()
                mock_json_load.reset_mock()
                mock_json_dumps.reset_mock()
                mock_makedirs.reset_mock()
                test_case['mock_parser'].reset_mock()

    @patch('builtins.open')
    @patch('os.path.exists')
    def test_collect_iperf3_file_not_found(self, mock_exists, mock_open_file):
        protocol = "tcp"
        bandwidth = 1000
        parallel = 1
        datapath = "direct"
        index = "1"
        cloud_info = {"provider": "azure", "region": "westus2"}
        run_url = "https://example.com/run"
        result_dir = "/tmp"
        result_file = "/tmp/final_results.json"

        mock_exists.return_value = True
        mock_file = mock_open_file.return_value.__enter__.return_value
        mock_file.read.return_value = ""

        # Test when iperf3 result file is empty
        with self.assertRaises(RuntimeError) as _context:
            self.iperf3.collect_iperf3(
                result_dir=result_dir,
                result_file=result_file,
                cloud_info=cloud_info,
                run_url=run_url,
                protocol=protocol,
                bandwidth=bandwidth,
                parallel=parallel,
                datapath=datapath,
                index=index,
                is_k8s=True
            )

    @patch('os.path.exists')
    @patch('builtins.open')
    def test_collect_iperf3_unsupported_protocol(self, mock_open_file, mock_exists):
        protocol = "invalid"
        bandwidth = 1000
        parallel = 1
        datapath = "direct"
        index = "1"
        cloud_info = {"provider": "azure", "region": "westus2"}
        run_url = "https://example.com/run"
        result_dir = "/tmp"
        result_file = "/tmp/final_results.json"

        # Set up mocks
        mock_exists.return_value = True
        mock_file = mock_open_file.return_value.__enter__.return_value
        mock_file.read.return_value = "{}"

        # Test with an invalid protocol
        with self.assertRaises(ValueError) as context:
            self.iperf3.collect_iperf3(
                result_dir=result_dir,
                result_file=result_file,
                cloud_info=cloud_info,
                run_url=run_url,
                protocol=protocol,
                bandwidth=bandwidth,
                parallel=parallel,
                datapath=datapath,
                index=index,
                is_k8s=True
            )
        self.assertIn("Unsupported protocol", str(context.exception))


class TestIperf3PodArguments(unittest.TestCase):
    def setUp(self):
        self.original_sys_argv = sys.argv.copy()

    def tearDown(self):
        sys.argv = self.original_sys_argv.copy()

    @patch('argparse.ArgumentParser.parse_args')
    @patch('iperf3.iperf3_pod.execute_with_retries')
    @patch('iperf3.iperf3_pod.Iperf3Pod')
    @patch('iperf3.iperf3_pod.extract_parameter')
    @patch('random.randint', return_value=42)
    @patch('time.sleep', return_value=None)
    def test_main_run_benchmark(self, _mock_sleep, _mock_randint, mock_extract_parameter, mock_iperf3_pod, mock_execute_with_retries, mock_parse_args):
        mock_parse_args.return_value = argparse.Namespace(
            action='run_benchmark',
            index=1,
            bandwidth=1000,
            protocol='tcp',
            parallel=1,
            iperf_command='--time 60 --bandwidth 1000M --parallel 1 --interval 0 --port 20003',
            datapath='direct',
            result_dir='/tmp',
            cluster_cli_context='cli-context',
            cluster_srv_context='srv-context',
            server_ip_type='pod'
        )
        result_file = '/tmp/iperf3-tcp-1000-1-direct.json'
        mock_extract_parameter.return_value = '60'
        mock_iperf3_pod.create_result_file_name.return_value = result_file

        main()
        mock_execute_with_retries.assert_called_with(
            mock_iperf3_pod.return_value.run_benchmark,
            backoff_time=70,
            index=1,
            result_dir='/tmp',
            result_file=result_file,
            iperf3_command='--time 60 --bandwidth 1000M --parallel 1 --interval 0 --port 20003',
            server_ip_type='pod'
        )

    @patch('argparse.ArgumentParser.parse_args')
    @patch('iperf3.iperf3_pod.Iperf3Pod')
    def test_main_configure(self, mock_iperf3_pod, mock_parse_args):
        mock_parse_args.return_value = argparse.Namespace(
            action='configure',
            pod_count=2,
            label_selector='test=true',
            cluster_cli_context='cli-context',
            cluster_srv_context='srv-context'
        )

        main()

        mock_iperf3_pod.assert_called_once_with(
            cluster_cli_context='cli-context',
            cluster_srv_context='srv-context'
        )
        mock_iperf3_pod.return_value.configure.assert_called_once_with(
            pod_count=2,
            label_selector='test=true'
        )

    @patch('kubernetes.config.load_kube_config')
    @patch('argparse.ArgumentParser.parse_args')
    def test_main_insufficient_args(self, mock_parse_args, _mock_load_kube_config):
        mock_parse_args.return_value = argparse.Namespace(
            action='run_benchmark',
            index=1,
            bandwidth=1000,
            parallel=1,
            protocol='tcp',
            iperf_command=None,  # Missing
            datapath='direct',
            result_dir='/tmp',
            cluster_cli_context='cli-context',
            cluster_srv_context='srv-context'
        )
        with self.assertRaises(ValueError) as context:
            main()
        self.assertIn("Insufficient arguments provided",
                      str(context.exception))

    @patch('kubernetes.config.load_kube_config')
    @patch('argparse.ArgumentParser.parse_args')
    def test_main_invalid_action(self, mock_parse_args, _mock_load_kube_config):
        mock_parse_args.return_value = argparse.Namespace(
            action='invalid_action', cluster_cli_context='cli-context', cluster_srv_context='srv-context'
        )
        with self.assertRaises(ValueError) as context:
            main()
        self.assertIn("Unsupported action", str(context.exception))

    @patch('sys.stderr', new_callable=StringIO)
    def test_main_invalid_protocol(self, mock_stderr):
        args = ["run_benchmark", "--protocol", "invalid_protocol", "--iperf_command",
                "--tcp", "--datapath", "default", "--result_dir", "/tmp"]
        with self.assertRaises(SystemExit):
            parse_args(args)
        self.assertIn("argument --protocol: invalid choice",
                      mock_stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
