import argparse
import json
import os
import tempfile
import unittest
from unittest.mock import patch

# Mock kubernetes config before importing
with patch('kubernetes.config.load_kube_config'):
    from clusterloader2.job_controller.job_controller import JobController


# pylint: disable=protected-access
class TestJobControllerBenchmark(unittest.TestCase):
    def test_configure_clusterloader2(self):
        # Create a temporary file for the override file
        fd, tmp_path = tempfile.mkstemp()
        try:
            benchmark = JobController(
                node_count=3,
                operation_timeout="10m",
                cl2_override_file=tmp_path,
                job_count=1000,
                job_throughput=50,
            )
            benchmark.configure_clusterloader2()
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("CL2_NODES: 3", content)
            self.assertIn("CL2_OPERATION_TIMEOUT: 10m", content)
            self.assertIn("CL2_JOBS: 1000", content)
            self.assertIn("CL2_LOAD_TEST_THROUGHPUT: 50", content)
            # Test that job_template_path default is written to config
            self.assertIn("CL2_JOB_TEMPLATE_PATH: base/job_template.yaml", content)
        finally:
            os.close(fd)
            os.remove(tmp_path)

    def test_configure_clusterloader2_with_custom_job_template(self):
        # Create a temporary file for the override file
        fd, tmp_path = tempfile.mkstemp()
        try:
            benchmark = JobController(
                node_count=3,
                operation_timeout="10m",
                cl2_override_file=tmp_path,
                job_count=1000,
                job_throughput=50,
                job_template_path="custom/template.yaml",
            )
            benchmark.configure_clusterloader2()
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Test that custom job_template_path is written to config
            self.assertIn("CL2_JOB_TEMPLATE_PATH: custom/template.yaml", content)
        finally:
            os.close(fd)
            os.remove(tmp_path)

    @patch("clusterloader2.job_controller.job_controller.KubernetesClient")
    def test_validate_clusterloader2(self, mock_kube_client_class):
        mock_kube_client_instance = mock_kube_client_class.return_value
        benchmark = JobController(
            node_count=2,
            operation_timeout_in_minutes=600,
            node_label="role=worker",
            dra_enabled=True,
        )
        benchmark.validate_clusterloader2()
        mock_kube_client_class.assert_called_once()
        mock_kube_client_instance.wait_for_nodes_ready.assert_called_once_with(2, 600, "role=worker")

    @patch("clusterloader2.job_controller.job_controller.run_cl2_command")
    def test_execute_clusterloader2(self, mock_run_cl2_command):
        benchmark = JobController(
            kubeconfig="kubeconfig.yaml",
            cl2_image="cl2-image",
            cl2_config_dir="config_dir",
            cl2_report_dir="report_dir",
            provider="aws",
            prometheus_enabled=True,
            scrape_containerd=True,
        )
        benchmark.execute_clusterloader2()
        mock_run_cl2_command.assert_called_once_with(
            "kubeconfig.yaml",
            "cl2-image",
            "config_dir",
            "report_dir",
            "aws",
            overrides=True,
            enable_prometheus=True,
            scrape_containerd=True,
        )

    @patch("clusterloader2.job_controller.job_controller.parse_xml_to_json")
    @patch("clusterloader2.job_controller.job_controller.process_cl2_reports")
    def test_collect_clusterloader2(
        self, mock_process_cl2_reports, mock_parse_xml_to_json
    ):
        # Setup mock return values
        mock_parse_xml_to_json.return_value = json.dumps(
            {"testsuites": [{"failures": 0}]}
        )
        mock_process_cl2_reports.return_value = "mock_content"

        fd, tmp_path = tempfile.mkstemp()
        try:
            benchmark = JobController(
                cl2_report_dir="report_dir",
                cloud_info=json.dumps({"cloud": "aws"}),
                run_id="run123",
                run_url="http://example.com/run123",
                result_file=tmp_path,
                test_type="unit-test",
                node_count=3,
                job_count=1000,
                job_throughput=50,
            )
            benchmark.collect_clusterloader2()
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, "mock_content")
        finally:
            os.close(fd)
            os.remove(tmp_path)


class TestJobControllerParser(unittest.TestCase):
    def test_create_parser(self):
        parser = JobController.create_parser(description="Job Controller CLI")
        # The parser should have subcommands: configure, validate, execute, collect
        subparsers_action = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        subcommand_names = set(subparsers_action.choices.keys())
        self.assertEqual(
            subcommand_names, {"configure", "validate", "execute", "collect"}
        )

        # Test that configure subparser has expected arguments
        configure_parser = subparsers_action.choices["configure"]
        configure_args = [a.dest for a in configure_parser._actions if a.dest != "help"]
        self.assertIn("node_count", configure_args)
        self.assertIn("operation_timeout", configure_args)
        self.assertIn("cl2_override_file", configure_args)
        self.assertIn("job_count", configure_args)
        self.assertIn("job_throughput", configure_args)
        self.assertIn("job_template_path", configure_args)

        # Test that job_template_path has correct default value
        job_template_path_action = next(
            action for action in configure_parser._actions
            if action.dest == "job_template_path"
        )
        self.assertEqual(job_template_path_action.default, "base/job_template.yaml")

        # Test that validate subparser has expected arguments
        validate_parser = subparsers_action.choices["validate"]
        validate_args = [a.dest for a in validate_parser._actions if a.dest != "help"]
        self.assertIn("node_count", validate_args)
        self.assertIn("operation_timeout_in_minutes", validate_args)
        self.assertIn("node_label", validate_args)
        self.assertIn("dra_enabled", validate_args)

        # Test that execute subparser has expected arguments
        execute_parser = subparsers_action.choices["execute"]
        execute_args = [a.dest for a in execute_parser._actions if a.dest != "help"]
        self.assertIn("cl2_image", execute_args)
        self.assertIn("cl2_config_dir", execute_args)
        self.assertIn("cl2_report_dir", execute_args)
        self.assertIn("kubeconfig", execute_args)
        self.assertIn("provider", execute_args)
        self.assertIn("prometheus_enabled", execute_args)
        self.assertIn("scrape_containerd", execute_args)

        # Test that collect subparser has expected arguments
        collect_parser = subparsers_action.choices["collect"]
        collect_args = [a.dest for a in collect_parser._actions if a.dest != "help"]
        self.assertIn("node_count", collect_args)
        self.assertIn("cl2_report_dir", collect_args)
        self.assertIn("cloud_info", collect_args)
        self.assertIn("run_id", collect_args)
        self.assertIn("run_url", collect_args)
        self.assertIn("result_file", collect_args)
        self.assertIn("test_type", collect_args)
        self.assertIn("job_count", collect_args)
        self.assertIn("job_throughput", collect_args)
        self.assertIn("job_template_path", collect_args)
        self.assertIn("dra_enabled", collect_args)

        # Test that job_template_path has correct default value in collect subparser
        job_template_path_action = next(
            action for action in collect_parser._actions
            if action.dest == "job_template_path"
        )
        self.assertEqual(job_template_path_action.default, "base/job_template.yaml")


if __name__ == "__main__":
    unittest.main()
