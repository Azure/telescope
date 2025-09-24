import argparse
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch, mock_open
import docker

# Import the class under test
from clusterloader2.large_cluster.base import ClusterLoader2Base


class ConcreteClusterLoader2Base(ClusterLoader2Base):
    """Concrete implementation for testing abstract methods"""

    def add_configure_args(self, parser: argparse.ArgumentParser):
        parser.add_argument("--cl2_override_file", type=str, required=True)

    def add_validate_args(self, parser: argparse.ArgumentParser):
        parser.add_argument("--kubeconfig", type=str, required=True)

    def add_execute_args(self, parser: argparse.ArgumentParser):
        parser.add_argument("--kubeconfig", type=str, required=True)
        parser.add_argument("--cl2_image", type=str, required=True)
        parser.add_argument("--cl2_config_dir", type=str, required=True)
        parser.add_argument("--cl2_report_dir", type=str, required=True)
        parser.add_argument("--provider", type=str, required=True)

    def add_collect_args(self, parser: argparse.ArgumentParser):
        parser.add_argument("--cl2_report_dir", type=str, required=True)
        parser.add_argument("--result_file", type=str, required=True)

    def configure(self, **kwargs) -> dict:
        return {"test_config": "value"}

    def validate(self, **kwargs):
        return True

    def collect(self, **kwargs) -> str:
        return "test_result"


class TestClusterLoader2Base(unittest.TestCase):
    """Comprehensive test cases for ClusterLoader2Base class"""

    def setUp(self):
        self.instance = ConcreteClusterLoader2Base("test")
        self.template = {"test": "template"}

    # Initialization Tests
    def test_init_valid_string_description(self):
        """Test initialization with valid string description"""
        description = "Test ClusterLoader2"
        instance = ConcreteClusterLoader2Base(description)

        self.assertIsInstance(instance.parser, argparse.ArgumentParser)
        self.assertEqual(instance.parser.description, description)

    def test_init_empty_string_description(self):
        """Test initialization with empty string description"""
        description = ""
        instance = ConcreteClusterLoader2Base(description)

        self.assertIsInstance(instance.parser, argparse.ArgumentParser)
        self.assertEqual(instance.parser.description, description)

    def test_init_long_description(self):
        """Test initialization with long description"""
        description = "A" * 250  # 250 character string
        instance = ConcreteClusterLoader2Base(description)

        self.assertIsInstance(instance.parser, argparse.ArgumentParser)
        self.assertEqual(instance.parser.description, description)

    def test_init_unicode_description(self):
        """Test initialization with unicode description"""
        description = "测试 ClusterLoader2"
        instance = ConcreteClusterLoader2Base(description)

        self.assertIsInstance(instance.parser, argparse.ArgumentParser)
        self.assertEqual(instance.parser.description, description)

    # Abstract Methods Tests
    def test_abstract_methods_must_be_implemented(self):
        """Test that abstract methods must be implemented by subclasses"""
        with self.assertRaises(TypeError):
            # This should fail because ClusterLoader2Base is abstract
            ClusterLoader2Base("test")  # pylint: disable=abstract-class-instantiated

    def test_add_configure_args_called(self):
        """Test that add_configure_args is called correctly"""
        parser = argparse.ArgumentParser()
        self.instance.add_configure_args(parser)

        # Test by actually parsing arguments - this verifies the argument exists and works
        try:
            args = parser.parse_args(['--cl2_override_file', 'test.yaml'])
            self.assertEqual(args.cl2_override_file, 'test.yaml')
        except SystemExit:
            self.fail("Required argument cl2_override_file was not added properly")

    def test_add_validate_args_called(self):
        """Test that add_validate_args is called correctly"""
        parser = argparse.ArgumentParser()
        self.instance.add_validate_args(parser)

        try:
            args = parser.parse_args(['--kubeconfig', 'test.config'])
            self.assertEqual(args.kubeconfig, 'test.config')
        except SystemExit:
            self.fail("Required argument kubeconfig was not added properly")

    def test_add_execute_args_called(self):
        """Test that add_execute_args is called correctly"""
        parser = argparse.ArgumentParser()
        self.instance.add_execute_args(parser)

        test_args = [
            '--kubeconfig', 'test.config',
            '--cl2_image', 'test-image',
            '--cl2_config_dir', 'test-config',
            '--cl2_report_dir', 'test-reports',
            '--provider', 'aws'
        ]

        try:
            args = parser.parse_args(test_args)
            self.assertEqual(args.kubeconfig, 'test.config')
            self.assertEqual(args.cl2_image, 'test-image')
            self.assertEqual(args.cl2_config_dir, 'test-config')
            self.assertEqual(args.cl2_report_dir, 'test-reports')
            self.assertEqual(args.provider, 'aws')
        except SystemExit:
            self.fail("Required execute arguments were not added properly")

    def test_add_collect_args_called(self):
        """Test that add_collect_args is called correctly"""
        parser = argparse.ArgumentParser()
        self.instance.add_collect_args(parser)

        test_args = ['--cl2_report_dir', 'test-reports', '--result_file', 'result.json']

        try:
            args = parser.parse_args(test_args)
            self.assertEqual(args.cl2_report_dir, 'test-reports')
            self.assertEqual(args.result_file, 'result.json')
        except SystemExit:
            self.fail("Required collect arguments were not added properly")

    # Get Measurement Tests
    def test_get_measurement_test_cases(self):
        """Test get_measurement with various file patterns"""
        test_cases = [
            # Pod Startup Latency Files
            ("PodStartupLatency_PodStartupLatency_testgroup_data.json",
             "PodStartupLatency_PodStartupLatency", "testgroup"),
            ("StatefulPodStartupLatency_PodStartupLatency_testgroup_data.json",
             "StatefulPodStartupLatency_PodStartupLatency", "testgroup"),
            ("StatelessPodStartupLatency_PodStartupLatency_testgroup_data.json",
             "StatelessPodStartupLatency_PodStartupLatency", "testgroup"),

            # Network Metric Files
            ("APIResponsivenessPrometheus_testgroup_data.json",
             "APIResponsivenessPrometheus", "testgroup"),
            ("InClusterNetworkLatency_testgroup_data.json",
             "InClusterNetworkLatency", "testgroup"),
            ("NetworkProgrammingLatency_testgroup_data.json",
             "NetworkProgrammingLatency", "testgroup"),

            # Prometheus Query Files
            ("GenericPrometheusQuery_testgroup_metricname_data.json",
             "metricname", "testgroup"),

            # Job Lifecycle Files
            ("JobLifecycleLatency_testgroup_data.json",
             "JobLifecycleLatency", "testgroup"),

            # Resource Usage Files
            ("ResourceUsageSummary_testgroup_data.json",
             "ResourceUsageSummary", "testgroup"),

            # Network Policy Files
            ("NetworkPolicySoakMeasurement_testgroup_data.json",
             "NetworkPolicySoakMeasurement", "testgroup"),

            # Scheduling Throughput Files
            ("SchedulingThroughputPrometheus_testgroup_data.json",
             "SchedulingThroughputPrometheus", "testgroup"),
            ("SchedulingThroughput_testgroup_data.json",
             "SchedulingThroughput", "testgroup"),

            # Edge Cases
            ("UnknownPattern_testgroup_data.json", None, None),
            ("", None, None),
            ("NoUnderscores.json", None, None),
            ("PodStartup_testgroup.json", None, None),
            ("podstartupLatency_PodStartupLatency_testgroup.json", None, None),

            # Malformed Files
            ("PodStartupLatency_PodStartupLatency_.json",
             "PodStartupLatency_PodStartupLatency", ""),
            ("APIResponsivenessPrometheus_.json",
             "APIResponsivenessPrometheus", ""),
            ("FileWithoutExtension", None, None),

            # Multiple Groups
            ("PodStartupLatency_PodStartupLatency_group1_group2_data.json",
             "PodStartupLatency_PodStartupLatency", "group1"),

            # Real-world Examples
            ("PodStartupLatency_PodStartupLatency_default_20230923.json",
             "PodStartupLatency_PodStartupLatency", "default"),
            ("InClusterNetworkLatency_production_1695456789.json",
             "InClusterNetworkLatency", "production"),
            ("GenericPrometheusQuery Cilium Envoy HTTP Metrics_netpol-scale-test_2025-03-04T05:35:56Z.json",
             "Cilium Envoy HTTP Metrics", "netpol-scale-test"),
        ]

        for file_path, expected_measurement, expected_group in test_cases:
            with self.subTest(file_path=file_path):
                measurement, group = self.instance.get_measurement(file_path)
                self.assertEqual(measurement, expected_measurement,
                               f"Failed for file: {file_path}")
                self.assertEqual(group, expected_group,
                               f"Failed for file: {file_path}")

    # Process CL2 Reports Tests
    @patch('os.listdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_process_cl2_reports_with_data_items(self, mock_file, mock_listdir):
        """Test processing reports with dataItems"""
        mock_listdir.return_value = ['ResourceUsageSummary_testgroup_data.json']
        mock_file.return_value.read.return_value = json.dumps({
            "version": "v1",
            "dataItems": [
                {
                    "data": {
                        "Envoy Downstream Connections Rate": 0.027266895378350486,
                        "Envoy Downstream Connections Total": 17.150877192982456,
                        "Envoy Http Requests Rate": 18.920213092349318,
                        "Envoy Http Requests Total": 11900.81403508772,
                        "Envoy Upstream Connections Rate": 0.03317435082140964,
                        "Envoy Upstream Connections Total": 20.866666666666664
                    },
                    "unit": "count"
                }
            ]
        })

        result_str = self.instance.process_cl2_reports("/root/workspace/results", self.template)
        result = json.loads(result_str)

        # Assert basic structure
        self.assertIn("test", result)
        self.assertIn("group", result)
        self.assertIn("measurement", result)
        self.assertIn("result", result)

        # Assert template data is preserved
        self.assertEqual(result["test"], "template")

        # Assert extracted metadata
        self.assertEqual(result["group"], "testgroup")
        self.assertEqual(result["measurement"], "ResourceUsageSummary")

        # Assert result data structure
        self.assertIn("data", result["result"])
        self.assertIn("unit", result["result"])
        self.assertEqual(result["result"]["unit"], "count")

        # Assert specific metric values
        expected_data = {
            "Envoy Downstream Connections Rate": 0.027266895378350486,
            "Envoy Downstream Connections Total": 17.150877192982456,
            "Envoy Http Requests Rate": 18.920213092349318,
            "Envoy Http Requests Total": 11900.81403508772,
            "Envoy Upstream Connections Rate": 0.03317435082140964,
            "Envoy Upstream Connections Total": 20.866666666666664
        }
        self.assertEqual(result["result"]["data"], expected_data)

        # Assert result is single line output
        self.assertEqual(len(result_str.strip().split('\n')), 1)

    @patch('os.listdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_process_cl2_reports_without_data_items(self, mock_file, mock_listdir):
        """Test processing reports without dataItems"""
        mock_listdir.return_value = ['ResourceUsageSummary_testgroup_data.json']
        mock_file.return_value.read.return_value = json.dumps({"version": "v1"})
        str_result = self.instance.process_cl2_reports("/test/dir", self.template)
        result = json.loads(str_result)
        self.assertIn("group", str_result)
        self.assertIn("measurement", str_result)
        self.assertEqual("testgroup", result["group"])
        self.assertEqual("ResourceUsageSummary", result["measurement"])
        self.assertEqual(len(str_result.strip().split('\n')), 1)  # One result

    @patch('os.listdir')
    def test_process_cl2_reports_empty_directory(self, mock_listdir):
        """Test processing empty directory"""
        mock_listdir.return_value = []

        result = self.instance.process_cl2_reports("/test/empty", self.template)

        self.assertEqual(result, "")

    @patch('os.listdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_process_cl2_reports_unknown_files(self, mock_file, mock_listdir):
        """Test processing directory with unknown file patterns"""
        mock_listdir.return_value = ['unknown_file.json']
        mock_file.return_value.read.return_value = json.dumps({"result": "test"})

        with patch.object(self.instance, 'get_measurement', return_value=(None, None)):
            result = self.instance.process_cl2_reports("/test/dir", self.template)

        self.assertEqual(result, "")

    @patch('os.listdir')
    def test_process_cl2_reports_nonexistent_directory(self, mock_listdir):
        """Test processing non-existent directory"""
        mock_listdir.side_effect = OSError("Directory not found")

        with self.assertRaises(OSError):
            self.instance.process_cl2_reports("/invalid/path", self.template)

    @patch('os.listdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_process_cl2_reports_invalid_json(self, mock_file, mock_listdir):
        """Test processing files with invalid JSON"""
        mock_listdir.return_value = ['test_file.json']
        mock_file.return_value.read.return_value = "invalid json"

        with patch.object(self.instance, 'get_measurement', return_value=("test_metric", "test_group")):
            with self.assertRaises(json.JSONDecodeError):
                self.instance.process_cl2_reports("/test/dir", self.template)

    # Execute Tests
    @patch('clusterloader2.large_cluster.base.DockerClient')
    def test_execute_aws_basic(self, mock_docker_client_class):
        """Test basic AWS execution"""
        mock_docker_client = Mock()
        mock_container = Mock()
        mock_container.logs.return_value = [b'test log']
        mock_container.wait.return_value = {'StatusCode': 0}
        mock_docker_client.run_container.return_value = mock_container
        mock_docker_client_class.return_value = mock_docker_client

        self.instance.execute(
            kubeconfig="/test/kubeconfig",
            cl2_image="test-image",
            cl2_config_dir="/test/config",
            cl2_report_dir="/test/reports",
            provider="aws"
        )

        # Verify DockerClient was instantiated
        mock_docker_client_class.assert_called_once()

        # Verify run_container was called once
        mock_docker_client.run_container.assert_called_once()

        # Get the call arguments
        args, kwargs = mock_docker_client.run_container.call_args

        # Verify image parameter
        self.assertEqual(args[0], "test-image")

        # Verify command contains required parameters
        command = args[1]
        self.assertIn("--provider=aws", command)
        self.assertIn("--kubeconfig /root/.kube/config", command)
        self.assertIn("--testconfig /root/perf-tests/clusterloader2/config/config.yaml", command)
        self.assertIn("--report-dir /root/perf-tests/clusterloader2/results", command)
        self.assertIn("--v=2", command)

        # Verify default boolean parameters
        self.assertIn("--enable-exec-service=False", command)
        self.assertIn("--enable-prometheus-server=False", command)
        self.assertIn("--prometheus-scrape-kubelets=False", command)
        self.assertIn("--tear-down-prometheus-server=True", command)
        self.assertIn("--prometheus-scrape-kube-state-metrics=False", command)
        self.assertIn("--prometheus-scrape-metrics-server=False", command)

        # Verify volumes are mounted correctly
        self.assertIn('volumes', kwargs)
        volumes = kwargs['volumes']
        expected_volumes = {
            '/test/kubeconfig': {'bind': '/root/.kube/config', 'mode': 'rw'},
            '/test/config': {'bind': '/root/perf-tests/clusterloader2/config', 'mode': 'rw'},
            '/test/reports': {'bind': '/root/perf-tests/clusterloader2/results', 'mode': 'rw'},
        }

        # Check AWS credentials volume is added for AWS provider
        aws_path = os.path.expanduser("~/.aws/credentials")
        expected_volumes[aws_path] = {'bind': '/root/.aws/credentials', 'mode': 'rw'}

        self.assertEqual(volumes, expected_volumes)

        # Verify detach parameter
        self.assertIn('detach', kwargs)
        self.assertTrue(kwargs['detach'])

        # Verify container logs were retrieved with streaming
        mock_container.logs.assert_called_once_with(stream=True)

        # Verify container wait was called
        mock_container.wait.assert_called_once()

        # Verify optional parameters are not present (since not specified)
        self.assertNotIn("--testoverrides", command)
        self.assertNotIn("--prometheus-scrape-containerd", command)

    @patch('clusterloader2.large_cluster.base.DockerClient')
    def test_execute_azure_with_prometheus(self, mock_docker_client_class):
        """Test Azure execution with prometheus enabled"""
        mock_docker_client = Mock()
        mock_container = Mock()
        mock_container.logs.return_value = [b'test log']
        mock_container.wait.return_value = {'StatusCode': 0}
        mock_docker_client.run_container.return_value = mock_container
        mock_docker_client_class.return_value = mock_docker_client

        self.instance.execute(
            kubeconfig="/test/kubeconfig",
            cl2_image="test-image",
            cl2_config_dir="/test/config",
            cl2_report_dir="/test/reports",
            provider="azure",
            enable_prometheus=True
        )

        args, _ = mock_docker_client.run_container.call_args
        self.assertIn("--enable-prometheus-server=True", args[1])

    @patch('clusterloader2.large_cluster.base.DockerClient')
    def test_execute_with_overrides(self, mock_docker_client_class):
        """Test execution with overrides enabled"""
        mock_docker_client = Mock()
        mock_container = Mock()
        mock_container.logs.return_value = [b'test log']
        mock_container.wait.return_value = {'StatusCode': 0}
        mock_docker_client.run_container.return_value = mock_container
        mock_docker_client_class.return_value = mock_docker_client

        self.instance.execute(
            kubeconfig="/test/kubeconfig",
            cl2_image="test-image",
            cl2_config_dir="/test/config",
            cl2_report_dir="/test/reports",
            provider="aws",
            overrides=True
        )

        args, _ = mock_docker_client.run_container.call_args
        self.assertIn("--testoverrides=", args[1])

    @patch('clusterloader2.large_cluster.base.DockerClient')
    def test_execute_full_monitoring(self, mock_docker_client_class):
        """Test execution with all monitoring options enabled"""
        mock_docker_client = Mock()
        mock_container = Mock()
        mock_container.logs.return_value = [b'test log']
        mock_container.wait.return_value = {'StatusCode': 0}
        mock_docker_client.run_container.return_value = mock_container
        mock_docker_client_class.return_value = mock_docker_client

        self.instance.execute(
            kubeconfig="/test/kubeconfig",
            cl2_image="test-image",
            cl2_config_dir="/test/config",
            cl2_report_dir="/test/reports",
            provider="azure",
            enable_prometheus=True,
            overrides=True,
            scrape_kubelets=True,
            scrape_containerd=True,
            scrape_ksm=True,
            scrape_metrics_server=True
        )

        args, _ = mock_docker_client.run_container.call_args
        command = args[1]
        self.assertIn("--enable-prometheus-server=True", command)
        self.assertIn("--prometheus-scrape-kubelets=True", command)
        self.assertIn("--prometheus-scrape-containerd=True", command)
        self.assertIn("--prometheus-scrape-kube-state-metrics=True", command)
        self.assertIn("--prometheus-scrape-metrics-server=True", command)

    @patch('clusterloader2.large_cluster.base.DockerClient')
    def test_execute_container_failure(self, mock_logger, mock_docker_client_class):
        """Test execution with container failure"""
        mock_docker_client = Mock()
        mock_docker_client.run_container.side_effect = docker.errors.ContainerError(
            container="test", exit_status=1, command="test", image="test", stderr=b"error"
        )
        mock_docker_client_class.return_value = mock_docker_client

        # Should not raise exception, but log error
        self.instance.execute(
            kubeconfig="/test/kubeconfig",
            cl2_image="test-image",
            cl2_config_dir="/test/config",
            cl2_report_dir="/test/reports",
            provider="aws"
        )

        # Verify that the error was logged
        mock_logger.error.assert_called_once()
        error_call_args = mock_logger.error.call_args[0][0]
        self.assertIn("Container exited with a non-zero status code: 1", error_call_args)
        self.assertIn("error", error_call_args)

    # Parse XML to JSON Tests
    def test_parse_xml_to_json_valid_xml(self):
        """Test parsing valid XML with testsuites"""
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
        <testsuites>
            <testsuite name="TestSuite1" tests="2" failures="0" errors="0">
                <testcase name="Test1" classname="Class1" time="1.5"/>
                <testcase name="Test2" classname="Class2" time="2.0"/>
            </testsuite>
        </testsuites>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(xml_content)
            f.flush()

            try:
                result = self.instance.parse_xml_to_json(f.name, indent=0)
                json_data = json.loads(result)

                self.assertIn("testsuites", json_data)
                self.assertEqual(len(json_data["testsuites"]), 1)
                self.assertEqual(json_data["testsuites"][0]["name"], "TestSuite1")
                self.assertEqual(len(json_data["testsuites"][0]["testcases"]), 2)
            finally:
                os.unlink(f.name)

    def test_parse_xml_to_json_with_indentation(self):
        """Test parsing XML with indentation"""
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
        <testsuites>
            <testsuite name="TestSuite1" tests="1" failures="0" errors="0">
                <testcase name="Test1" classname="Class1" time="1.5"/>
            </testsuite>
        </testsuites>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(xml_content)
            f.flush()

            try:
                result = self.instance.parse_xml_to_json(f.name, indent=2)
                # Check that result contains indentation
                self.assertIn('  ', result)
                
                # Verify the parsed content is correct
                json_data = json.loads(result)
                self.assertIn("testsuites", json_data)
                self.assertEqual(len(json_data["testsuites"]), 1)
                
                # Verify test suite data
                testsuite = json_data["testsuites"][0]
                self.assertEqual(testsuite["name"], "TestSuite1")
                self.assertEqual(testsuite["tests"], 1)
                self.assertEqual(testsuite["failures"], 0)
                self.assertEqual(testsuite["errors"], 0)
                
                # Verify test case data
                self.assertEqual(len(testsuite["testcases"]), 1)
                testcase = testsuite["testcases"][0]
                self.assertEqual(testcase["name"], "Test1")
                self.assertEqual(testcase["classname"], "Class1")
                self.assertEqual(testcase["time"], "1.5")
                self.assertIsNone(testcase["failure"])
            finally:
                os.unlink(f.name)

    def test_parse_xml_to_json_with_failures(self):
        """Test parsing XML with test failures"""
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
        <testsuites>
            <testsuite name="TestSuite1" tests="1" failures="1" errors="0">
                <testcase name="FailedTest" classname="Class1" time="1.5">
                    <failure>Test failed: assertion error</failure>
                </testcase>
            </testsuite>
        </testsuites>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(xml_content)
            f.flush()

            try:
                result = self.instance.parse_xml_to_json(f.name, indent=0)
                json_data = json.loads(result)

                testcase = json_data["testsuites"][0]["testcases"][0]
                self.assertEqual(testcase["failure"], "Test failed: assertion error")
            finally:
                os.unlink(f.name)

    def test_parse_xml_to_json_empty_testsuites(self):
        """Test parsing XML with empty testsuites"""
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
        <testsuites>
            <testsuite name="EmptyTestSuite" tests="0" failures="0" errors="0">
            </testsuite>
        </testsuites>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(xml_content)
            f.flush()

            try:
                result = self.instance.parse_xml_to_json(f.name, indent=0)
                json_data = json.loads(result)

                self.assertEqual(len(json_data["testsuites"][0]["testcases"]), 0)
            finally:
                os.unlink(f.name)

    def test_parse_xml_to_json_malformed_xml(self):
        """Test parsing malformed XML"""
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
        <testsuites>
            <testsuite name="TestSuite1" tests="1" failures="0" errors="0">
                <testcase name="Test1" classname="Class1" time="1.5"
            </testsuite>
        </testsuites>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(xml_content)
            f.flush()

            try:
                with self.assertRaises(Exception):
                    self.instance.parse_xml_to_json(f.name, indent=0)
            finally:
                os.unlink(f.name)

    def test_parse_xml_to_json_nonexistent_file(self):
        """Test parsing non-existent file"""
        with self.assertRaises(FileNotFoundError):
            self.instance.parse_xml_to_json("/invalid/path.xml", indent=0)

    # Add Subparser Tests
    def test_add_subparser_configure_command(self):
        """Test adding configure subparser"""
        self.instance._add_subparser("configure", "Configure test")

        # Parse with configure command to verify it was added
        with patch('sys.argv', ['prog', 'configure', '--cl2_override_file', 'test.yaml']):
            args = self.instance.parser.parse_args(['configure', '--cl2_override_file', 'test.yaml'])
            self.assertEqual(args.command, "configure")

    def test_add_subparser_validate_command(self):
        """Test adding validate subparser"""

        self.instance._add_subparser("validate", "Validate test")

        with patch('sys.argv', ['prog', 'validate', '--kubeconfig', 'test.config']):
            args = self.instance.parser.parse_args(['validate', '--kubeconfig', 'test.config'])
            self.assertEqual(args.command, "validate")

    def test_add_subparser_execute_command(self):
        """Test adding execute subparser"""
        self.instance._add_subparser("execute", "Execute test")

        test_args = ['execute', '--kubeconfig', 'test.config', '--cl2_image', 'image',
                    '--cl2_config_dir', 'config', '--cl2_report_dir', 'reports',
                    '--provider', 'aws']
        args = self.instance.parser.parse_args(test_args)
        self.assertEqual(args.command, "execute")

    def test_add_subparser_collect_command(self):
        """Test adding collect subparser"""
        self.instance._add_subparser("collect", "Collect test")

        test_args = ['collect', '--cl2_report_dir', 'reports', '--result_file', 'result.json']
        args = self.instance.parser.parse_args(test_args)
        self.assertEqual(args.command, "collect")

    # Parse Arguments Tests
    def test_parse_arguments_configure_command(self):
        """Test parsing configure command arguments"""
        test_args = ['configure', '--cl2_override_file', 'override.yaml']

        with patch('sys.argv', ['prog'] + test_args):
            with patch.object(self.instance.parser, 'parse_args', return_value=argparse.Namespace(
                command='configure', cl2_override_file='override.yaml'
            )) as mock_parse:
                result = self.instance.parse_arguments()

                self.assertEqual(result.command, 'configure')
                self.assertEqual(result.cl2_override_file, 'override.yaml')

    def test_parse_arguments_validate_command(self):
        """Test parsing validate command arguments"""
        test_args = ['validate', '--kubeconfig', 'test.config']

        with patch.object(self.instance.parser, 'parse_args', return_value=argparse.Namespace(
            command='validate', kubeconfig='test.config'
        )) as mock_parse:
            result = self.instance.parse_arguments()

            self.assertEqual(result.command, 'validate')
            self.assertEqual(result.kubeconfig, 'test.config')

    def test_parse_arguments_execute_command(self):
        """Test parsing execute command arguments"""
        with patch.object(self.instance.parser, 'parse_args', return_value=argparse.Namespace(
            command='execute', kubeconfig='test.config', cl2_image='image',
            cl2_config_dir='config', cl2_report_dir='reports', provider='aws'
        )) as mock_parse:
            result = self.instance.parse_arguments()

            self.assertEqual(result.command, 'execute')
            self.assertEqual(result.provider, 'aws')

    def test_parse_arguments_collect_command(self):
        """Test parsing collect command arguments"""
        with patch.object(self.instance.parser, 'parse_args', return_value=argparse.Namespace(
            command='collect', cl2_report_dir='reports', result_file='result.json'
        )) as mock_parse:
            result = self.instance.parse_arguments()

            self.assertEqual(result.command, 'collect')
            self.assertEqual(result.result_file, 'result.json')

    # Main Method Tests
    @patch.object(ConcreteClusterLoader2Base, 'parse_arguments')
    @patch.object(ConcreteClusterLoader2Base, 'configure')
    @patch.object(ConcreteClusterLoader2Base, 'write_to_file')
    @patch.object(ConcreteClusterLoader2Base, 'convert_config_to_str')
    def test_main_configure_command(self, mock_convert, mock_write, mock_configure, mock_parse):
        """Test main method with configure command"""
        mock_parse.return_value = argparse.Namespace(
            command='configure', cl2_override_file='override.yaml'
        )
        mock_configure.return_value = {'key1': 'value1'}
        mock_convert.return_value = 'key1: value1'

        self.instance.main()

        mock_configure.assert_called_once_with(cl2_override_file='override.yaml')
        mock_write.assert_called_once_with(filename='override.yaml', content='key1: value1')

    @patch.object(ConcreteClusterLoader2Base, 'parse_arguments')
    @patch.object(ConcreteClusterLoader2Base, 'validate')
    def test_main_validate_command(self, mock_validate, mock_parse):
        """Test main method with validate command"""
        mock_parse.return_value = argparse.Namespace(
            command='validate', kubeconfig='test.config'
        )

        self.instance.main()

        mock_validate.assert_called_once_with(kubeconfig='test.config')

    @patch.object(ConcreteClusterLoader2Base, 'parse_arguments')
    @patch.object(ConcreteClusterLoader2Base, 'execute')
    def test_main_execute_command(self, mock_execute, mock_parse):
        """Test main method with execute command"""
        mock_parse.return_value = argparse.Namespace(
            command='execute', kubeconfig='test.config', cl2_image='image'
        )

        self.instance.main()

        mock_execute.assert_called_once_with(kubeconfig='test.config', cl2_image='image')

    @patch.object(ConcreteClusterLoader2Base, 'parse_arguments')
    @patch.object(ConcreteClusterLoader2Base, 'parse_test_results')
    @patch.object(ConcreteClusterLoader2Base, 'collect')
    @patch.object(ConcreteClusterLoader2Base, 'write_to_file')
    def test_main_collect_command(self, mock_write, mock_collect, mock_parse_results, mock_parse):
        """Test main method with collect command"""
        mock_parse.return_value = argparse.Namespace(
            command='collect', cl2_report_dir='reports', result_file='result.json'
        )
        mock_parse_results.return_value = ('success', [{'name': 'test'}])
        mock_collect.return_value = 'test result'

        self.instance.main()

        mock_parse_results.assert_called_once_with('reports')
        mock_collect.assert_called_once()
        mock_write.assert_called_once_with(filename='result.json', content='test result')

    @patch.object(ConcreteClusterLoader2Base, 'parse_arguments')
    @patch('builtins.print')
    def test_main_unknown_command(self, mock_print, mock_parse):
        """Test main method with unknown command"""
        mock_parse.return_value = argparse.Namespace(command='unknown')

        self.instance.main()

        mock_print.assert_called_once()
        self.assertIn("I can't recognize", mock_print.call_args[0][0])

    @patch.object(ConcreteClusterLoader2Base, 'parse_arguments')
    @patch('builtins.print')
    def test_main_no_command(self, mock_print, mock_parse):
        """Test main method with no command"""
        mock_parse.return_value = argparse.Namespace(command=None)

        self.instance.main()

        mock_print.assert_called_once()

    # Convert Config to String Tests
    def test_convert_config_to_str_dict_with_values(self):
        """Test converting dict with values"""
        config_dict = {"key1": "value1", "key2": "value2"}
        result = self.instance.convert_config_to_str(config_dict)

        self.assertIn("key1: value1", result)
        self.assertIn("key2: value2", result)
        self.assertEqual(len(result.split('\n')), 2)

    def test_convert_config_to_str_dict_with_none_values(self):
        """Test converting dict with None values"""
        config_dict = {"key1": None, "key2": "value2"}
        result = self.instance.convert_config_to_str(config_dict)

        lines = result.split('\n')
        self.assertIn("key1", lines)
        self.assertIn("key2: value2", lines)

    def test_convert_config_to_str_empty_dict(self):
        """Test converting empty dict"""
        config_dict = {}
        result = self.instance.convert_config_to_str(config_dict)

        self.assertEqual(result, "")

    def test_convert_config_to_str_mixed_types(self):
        """Test converting dict with mixed types"""
        config_dict = {"str": "text", "int": 42, "bool": True}
        result = self.instance.convert_config_to_str(config_dict)

        self.assertIn("str: text", result)
        self.assertIn("int: 42", result)
        self.assertIn("bool: True", result)

    # Write to File Tests
    def test_write_to_file_valid_path(self):
        """Test writing to valid file path"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "test.txt")
            content = "test content"

            self.instance.write_to_file(file_path, content)

            with open(file_path, 'r', encoding='utf-8') as f:
                self.assertEqual(f.read(), content)

    def test_write_to_file_nested_path(self):
        """Test writing to nested path (creates directories)"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "subdir", "test.txt")
            content = "test content"

            self.instance.write_to_file(file_path, content)

            self.assertTrue(os.path.exists(file_path))
            with open(file_path, 'r', encoding='utf-8') as f:
                self.assertEqual(f.read(), content)

    def test_write_to_file_existing_file(self):
        """Test overwriting existing file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("old content")
            f.flush()

            try:
                new_content = "new content"
                self.instance.write_to_file(f.name, new_content)

                with open(f.name, 'r', encoding='utf-8') as file:
                    self.assertEqual(file.read(), new_content)
            finally:
                os.unlink(f.name)

    def test_write_to_file_empty_content(self):
        """Test writing empty content"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "empty.txt")

            self.instance.write_to_file(file_path, "")

            with open(file_path, 'r', encoding='utf-8') as f:
                self.assertEqual(f.read(), "")

    # Parse Test Results Tests
    @patch.object(ConcreteClusterLoader2Base, 'parse_xml_to_json')
    def test_parse_test_results_success(self, mock_parse_xml):
        """Test parsing successful test results"""
        mock_parse_xml.return_value = json.dumps({
            "testsuites": [{"failures": 0, "name": "TestSuite1"}]
        })

        status, results = self.instance.parse_test_results("/test/reports")

        self.assertEqual(status, "success")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "TestSuite1")

    @patch.object(ConcreteClusterLoader2Base, 'parse_xml_to_json')
    def test_parse_test_results_failure(self, mock_parse_xml):
        """Test parsing failed test results"""
        mock_parse_xml.return_value = json.dumps({
            "testsuites": [{"failures": 1, "name": "TestSuite1"}]
        })

        status, results = self.instance.parse_test_results("/test/reports")

        self.assertEqual(status, "failure")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["failures"], 1)

    @patch.object(ConcreteClusterLoader2Base, 'parse_xml_to_json')
    def test_parse_test_results_empty_testsuites(self, mock_parse_xml):
        """Test parsing results with empty testsuites"""
        mock_parse_xml.return_value = json.dumps({"testsuites": []})

        with self.assertRaises(Exception) as context:
            self.instance.parse_test_results("/test/reports")

        self.assertIn("No testsuites found", str(context.exception))

    @patch.object(ConcreteClusterLoader2Base, 'parse_xml_to_json')
    def test_parse_test_results_missing_junit_xml(self, mock_parse_xml):
        """Test parsing when junit.xml is missing"""
        mock_parse_xml.side_effect = FileNotFoundError("junit.xml not found")

        with self.assertRaises(FileNotFoundError):
            self.instance.parse_test_results("/test/reports")

    @patch.object(ConcreteClusterLoader2Base, 'parse_xml_to_json')
    def test_parse_test_results_invalid_xml(self, mock_parse_xml):
        """Test parsing invalid XML"""
        mock_parse_xml.side_effect = Exception("XML parsing failed")

        with self.assertRaises(Exception):
            self.instance.parse_test_results("/test/reports")


if __name__ == '__main__':
    unittest.main()
