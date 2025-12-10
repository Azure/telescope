"""Unit tests for image_pull module."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from clusterloader2.image_pull.image_pull import (
    execute_clusterloader2,
    collect_clusterloader2,
    write_overrides,
    main
)


class TestImagePullFunctions(unittest.TestCase):
    """Test cases for image_pull execute and collect functions."""

    def test_write_overrides(self):
        """Test write_overrides creates correct override file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            write_overrides(tmpdir, "aks")

            override_file = os.path.join(tmpdir, "overrides.yaml")
            self.assertTrue(os.path.exists(override_file))

            with open(override_file, 'r', encoding='utf-8') as f:
                content = f.read()

            self.assertIn("CL2_PROVIDER: aks", content)
            self.assertIn("CL2_PROMETHEUS_TOLERATE_MASTER: true", content)
            self.assertIn("CL2_PROMETHEUS_NODE_SELECTOR", content)

    @patch('clusterloader2.image_pull.image_pull.run_cl2_command')
    @patch('clusterloader2.image_pull.image_pull.write_overrides')
    def test_execute_clusterloader2(self, mock_write_overrides, mock_run_cl2):
        """Test execute_clusterloader2 calls run_cl2_command with correct params."""
        execute_clusterloader2(
            cl2_image="ghcr.io/azure/clusterloader2:v20250311",
            cl2_config_dir="/tmp/config",
            cl2_report_dir="/tmp/report",
            kubeconfig="/tmp/kubeconfig",
            provider="aks"
        )

        mock_write_overrides.assert_called_once_with("/tmp/config", "aks")
        mock_run_cl2.assert_called_once_with(
            kubeconfig="/tmp/kubeconfig",
            cl2_image="ghcr.io/azure/clusterloader2:v20250311",
            cl2_config_dir="/tmp/config",
            cl2_report_dir="/tmp/report",
            provider="aks",
            cl2_config_file="image-pull.yaml",
            overrides=True,
            enable_prometheus=True,
            scrape_kubelets=True,
            scrape_containerd=True,
            tear_down_prometheus=False
        )

    @patch('clusterloader2.image_pull.image_pull.get_measurement')
    @patch('clusterloader2.image_pull.image_pull.parse_xml_to_json')
    def test_collect_clusterloader2_success(self, mock_parse_xml, mock_get_measurement):
        """Test collect_clusterloader2 with successful test results."""
        # Mock junit.xml parsing - success case
        mock_parse_xml.return_value = json.dumps({
            "testsuites": [{"failures": 0, "tests": 1}]
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = os.path.join(tmpdir, "report")
            os.makedirs(report_dir)

            # Create a mock measurement file
            measurement_file = os.path.join(report_dir, "ImagePullLatency_test.json")
            with open(measurement_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "dataItems": [
                        {"labels": {"node": "node1"}, "data": {"P50": 1.5, "P99": 3.0}}
                    ]
                }, f)

            # Create junit.xml (required by parse_xml_to_json)
            junit_file = os.path.join(report_dir, "junit.xml")
            with open(junit_file, 'w', encoding='utf-8') as f:
                f.write("<testsuites><testsuite></testsuite></testsuites>")

            mock_get_measurement.return_value = ("ImagePullLatency", "test")

            result_file = os.path.join(tmpdir, "results", "output.json")

            collect_clusterloader2(
                cl2_report_dir=report_dir,
                cloud_info='{"cloud": "azure", "region": "eastus2"}',
                run_id="12345",
                run_url="https://dev.azure.com/run/12345",
                result_file=result_file,
                deployment_count=10,
                replicas=1
            )

            # Verify result file was created
            self.assertTrue(os.path.exists(result_file))

            # Verify content
            with open(result_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.assertIn("ImagePullLatency", content)
                self.assertIn("success", content)
                self.assertIn("12345", content)

    @patch('clusterloader2.image_pull.image_pull.parse_xml_to_json')
    def test_collect_clusterloader2_failure(self, mock_parse_xml):
        """Test collect_clusterloader2 with failed test results."""
        # Mock junit.xml parsing - failure case
        mock_parse_xml.return_value = json.dumps({
            "testsuites": [{"failures": 1, "tests": 1}]
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = os.path.join(tmpdir, "report")
            os.makedirs(report_dir)

            # Create junit.xml
            junit_file = os.path.join(report_dir, "junit.xml")
            with open(junit_file, 'w', encoding='utf-8') as f:
                f.write("<testsuites><testsuite></testsuite></testsuites>")

            result_file = os.path.join(tmpdir, "results", "output.json")

            collect_clusterloader2(
                cl2_report_dir=report_dir,
                cloud_info='{"cloud": "azure"}',
                run_id="12345",
                run_url="https://dev.azure.com/run/12345",
                result_file=result_file
            )

            # Result file should exist even for failures
            self.assertTrue(os.path.exists(result_file))

    @patch('clusterloader2.image_pull.image_pull.parse_xml_to_json')
    def test_collect_clusterloader2_no_testsuites(self, mock_parse_xml):
        """Test collect_clusterloader2 raises error when no testsuites found."""
        # Mock junit.xml with empty testsuites
        mock_parse_xml.return_value = json.dumps({"testsuites": []})

        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = os.path.join(tmpdir, "report")
            os.makedirs(report_dir)

            junit_file = os.path.join(report_dir, "junit.xml")
            with open(junit_file, 'w', encoding='utf-8') as f:
                f.write("<testsuites></testsuites>")

            result_file = os.path.join(tmpdir, "results", "output.json")

            with self.assertRaises(ValueError) as context:
                collect_clusterloader2(
                    cl2_report_dir=report_dir,
                    cloud_info='{"cloud": "azure"}',
                    run_id="12345",
                    run_url="https://dev.azure.com/run/12345",
                    result_file=result_file
                )

            self.assertIn("No testsuites found", str(context.exception))


class TestImagePullMain(unittest.TestCase):
    """Test cases for CLI main function."""

    @patch('clusterloader2.image_pull.image_pull.execute_clusterloader2')
    def test_main_execute_command(self, mock_execute):
        """Test main function with execute subcommand."""
        test_args = [
            'image_pull.py', 'execute',
            '--cl2_image', 'ghcr.io/azure/clusterloader2:v20250311',
            '--cl2_config_dir', '/tmp/config',
            '--cl2_report_dir', '/tmp/report',
            '--provider', 'aks'
        ]

        with patch('sys.argv', test_args):
            main()

        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args[1]
        self.assertEqual(call_kwargs['cl2_image'], 'ghcr.io/azure/clusterloader2:v20250311')
        self.assertEqual(call_kwargs['provider'], 'aks')

    @patch('clusterloader2.image_pull.image_pull.collect_clusterloader2')
    def test_main_collect_command(self, mock_collect):
        """Test main function with collect subcommand."""
        test_args = [
            'image_pull.py', 'collect',
            '--cl2_report_dir', '/tmp/report',
            '--cloud_info', '{"cloud": "azure"}',
            '--run_id', '12345',
            '--run_url', 'https://dev.azure.com/run/12345',
            '--result_file', '/tmp/result.json',
            '--deployment_count', '10',
            '--replicas', '1'
        ]

        with patch('sys.argv', test_args):
            main()

        mock_collect.assert_called_once()
        call_kwargs = mock_collect.call_args[1]
        self.assertEqual(call_kwargs['deployment_count'], 10)
        self.assertEqual(call_kwargs['replicas'], 1)


if __name__ == '__main__':
    unittest.main()
