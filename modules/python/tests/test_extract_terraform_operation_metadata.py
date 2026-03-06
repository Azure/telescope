import unittest
import os
import json
from unittest.mock import patch, mock_open

from terraform.extract_terraform_operation_metadata import (
  time_to_seconds,
  parse_module_path,
  process_terraform_logs,
  get_job_tags,
)

class TestExtractTerraformOperationMetadata(unittest.TestCase):
    def test_time_to_seconds_with_hours_minutes_and_seconds(self):
        self.assertEqual(time_to_seconds("1h2m30s"), 3750)

    def test_time_to_seconds_with_hours_and_seconds(self):
        self.assertEqual(time_to_seconds("1h30s"), 3630)

    def test_time_to_seconds_with_minutes_and_seconds(self):
        self.assertEqual(time_to_seconds("2m30s"), 150)

    def test_time_to_seconds_with_seconds_only(self):
        self.assertEqual(time_to_seconds("45s"), 45)

    def test_time_to_seconds_with_invalid_format(self):
        self.assertEqual(time_to_seconds("invalid"), 0)

    def test_parse_module_path_with_submodule(self):
        module, submodule, resource = parse_module_path("module.aks[\"cas\"].azurerm_kubernetes_cluster.aks")
        self.assertEqual(module, "aks[\"cas\"]")
        self.assertEqual(submodule, "azurerm_kubernetes_cluster")
        self.assertEqual(resource, "aks")

    def test_parse_module_path_without_submodule(self):
        module, submodule, resource = parse_module_path("module.main.resource")
        self.assertEqual(module, "main")
        self.assertEqual(submodule, "")
        self.assertEqual(resource, "resource")

    def test_parse_module_path_with_only_module(self):
        module, submodule, resource = parse_module_path("module.main")
        self.assertEqual(module, "main")
        self.assertEqual(submodule, "")
        self.assertEqual(resource, "")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="module.aks[\"cas\"].azurerm_kubernetes_cluster.aks: Creation complete after 1h2m30s\n")
    def test_process_terraform_logs_with_valid_log_line(self, mock_open_file, mock_isfile):
        os.environ["RUN_ID"] = "123456789"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="test_scenario_type",
          _scenario_name="test_scenario_name",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], "123456789")
        self.assertEqual(results[0]["module_name"], "aks[\"cas\"]")
        self.assertEqual(results[0]["submodule_name"], "azurerm_kubernetes_cluster")
        self.assertEqual(results[0]["resource_name"], "aks")
        self.assertEqual(results[0]["action"], "apply")
        self.assertEqual(results[0]["time_taken_seconds"], 3750)
        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="module.main.resource: Destruction complete after 45s\n")
    def test_process_terraform_logs_with_destruction_log_line(self, mock_open_file, mock_isfile):
        os.environ["RUN_ID"] = "987654321"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="destroy",
          _scenario_type="test_scenario_type",
          _scenario_name="test_scenario_name",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], "987654321")
        self.assertEqual(results[0]["module_name"], "main")
        self.assertEqual(results[0]["submodule_name"], "")
        self.assertEqual(results[0]["resource_name"], "resource")
        self.assertEqual(results[0]["action"], "destroy")
        self.assertEqual(results[0]["time_taken_seconds"], 45)
        mock_open_file.assert_called_once_with('/fake/path/terraform_destroy.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_destroy.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="module.network.vnet: Creation complete after 1h5m15s\nmodule.network.subnet: Creation complete after 1m15s\nmodule.storage.bucket: Creation complete after 30s\n")
    def test_process_terraform_logs_with_multiple_log_lines(self, mock_open_file, mock_isfile):
        os.environ["RUN_ID"] = "1122334455"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="perf-eval",
          _scenario_name="test_scenario_name",
        )

        self.assertEqual(len(results), 3)

        self.assertEqual(results[0]["run_id"], "1122334455")
        self.assertEqual(results[0]["module_name"], "network")
        self.assertEqual(results[0]["submodule_name"], "")
        self.assertEqual(results[0]["resource_name"], "vnet")
        self.assertEqual(results[0]["action"], "apply")
        self.assertEqual(results[0]["time_taken_seconds"], 3915)
        self.assertEqual(results[0]["scenario_type"], "perf-eval")
        self.assertEqual(results[0]["scenario_name"], "test_scenario_name")

        self.assertEqual(results[1]["run_id"], "1122334455")
        self.assertEqual(results[1]["module_name"], "network")
        self.assertEqual(results[1]["submodule_name"], "")
        self.assertEqual(results[1]["resource_name"], "subnet")
        self.assertEqual(results[1]["action"], "apply")
        self.assertEqual(results[1]["time_taken_seconds"], 75)
        self.assertEqual(results[1]["scenario_type"], "perf-eval")
        self.assertEqual(results[1]["scenario_name"], "test_scenario_name")

        self.assertEqual(results[2]["run_id"], "1122334455")
        self.assertEqual(results[2]["module_name"], "storage")
        self.assertEqual(results[2]["submodule_name"], "")
        self.assertEqual(results[2]["resource_name"], "bucket")
        self.assertEqual(results[2]["action"], "apply")
        self.assertEqual(results[2]["time_taken_seconds"], 30)
        self.assertEqual(results[2]["scenario_type"], "perf-eval")
        self.assertEqual(results[2]["scenario_name"], "test_scenario_name")
        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="module.invalid.log.line: Invalid complete after 10m\n")
    def test_process_terraform_logs_with_invalid_logs_format(self, mock_open_file, mock_isfile):
        os.environ["RUN_ID"] = "5566778899"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="test_scenario_type",
          _scenario_name="test_scenario_name",
        )

        self.assertEqual(len(results), 0)
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")
        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')

    @patch("os.path.isfile", return_value=False)
    def test_process_terraform_logs_with_missing_file(self, mock_isfile):
        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="test_scenario_type",
          _scenario_name="test_scenario_name",
        )
        self.assertEqual(results, [])
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="invalid log line\n")
    def test_process_terraform_logs_with_invalid_log_line(self, mock_open_file, mock_isfile):
        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="test_scenario_type",
          _scenario_name="test_scenario_name",
        )
        self.assertEqual(results, [])
        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    # --- get_job_tags tests ---

    @patch.dict(os.environ, {
        "JOB_TAGS": '{"node_count": 10, "max_pods": 30, "kubernetes_version": "1.31"}'
    }, clear=False)
    def test_get_job_tags_with_valid_json(self):
        job_tags = get_job_tags()
        self.assertIsNotNone(job_tags)
        parsed = json.loads(job_tags)
        self.assertEqual(parsed["node_count"], 10)
        self.assertEqual(parsed["max_pods"], 30)
        self.assertEqual(parsed["kubernetes_version"], "1.31")

    @patch.dict(os.environ, {
        "JOB_TAGS": "invalid json"
    }, clear=False)
    def test_get_job_tags_with_invalid_json(self):
        job_tags = get_job_tags()
        self.assertIsNone(job_tags)

    @patch.dict(os.environ, {
        "JOB_TAGS": "{}"
    }, clear=False)
    def test_get_job_tags_with_empty_object(self):
        job_tags = get_job_tags()
        self.assertIsNone(job_tags)

    @patch.dict(os.environ, {
        "JOB_TAGS": ""
    }, clear=False)
    def test_get_job_tags_with_empty_string(self):
        job_tags = get_job_tags()
        self.assertIsNone(job_tags)

    def test_get_job_tags_with_no_env_var(self):
        saved = os.environ.pop("JOB_TAGS", None)
        try:
            job_tags = get_job_tags()
            self.assertIsNone(job_tags)
        finally:
            if saved is not None:
                os.environ["JOB_TAGS"] = saved

    # --- process_terraform_logs with job_tags integration tests ---

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="module.aks.cluster: Creation complete after 1m30s\n")
    @patch.dict(os.environ, {
        "RUN_ID": "test-run-123",
        "JOB_TAGS": '{"node_count": 10, "max_pods": 30}'
    }, clear=False)
    def test_process_terraform_logs_with_job_tags(self, mock_open_file, mock_isfile):
        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="perf-eval",
          _scenario_name="cri-resource-consume",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], "test-run-123")
        self.assertEqual(results[0]["module_name"], "aks")
        self.assertEqual(results[0]["resource_name"], "cluster")
        self.assertEqual(results[0]["action"], "apply")
        self.assertEqual(results[0]["time_taken_seconds"], 90)
        self.assertIn("job_tags", results[0])
        parsed_tags = json.loads(results[0]["job_tags"])
        self.assertEqual(parsed_tags["node_count"], 10)
        self.assertEqual(parsed_tags["max_pods"], 30)

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="module.aks.cluster: Creation complete after 1m30s\n")
    def test_process_terraform_logs_without_job_tags(self, mock_open_file, mock_isfile):
        saved = os.environ.pop("JOB_TAGS", None)
        try:
            os.environ["RUN_ID"] = "test-run-456"
            results = process_terraform_logs(
              log_path="/fake/path",
              _command_type="apply",
              _scenario_type="perf-eval",
              _scenario_name="test-scenario",
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["run_id"], "test-run-456")
            self.assertNotIn("job_tags", results[0])
        finally:
            if saved is not None:
                os.environ["JOB_TAGS"] = saved

if __name__ == "__main__":
    unittest.main()
