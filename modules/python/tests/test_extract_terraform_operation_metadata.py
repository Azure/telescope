import unittest
import os
from unittest.mock import patch, mock_open

from terraform.extract_terraform_operation_metadata import (
  time_to_seconds,
  parse_module_path,
  process_terraform_logs,
)

class TestExtractTerraformOperationMetadata(unittest.TestCase):
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
    @patch("builtins.open", new_callable=mock_open, read_data="module.aks[\"cas\"].azurerm_kubernetes_cluster.aks: Creation complete after 2m30s\n")
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
        self.assertEqual(results[0]["time_taken_seconds"], 150)
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
    @patch("builtins.open", new_callable=mock_open, read_data="module.network.subnet: Creation complete after 1m15s\nmodule.storage.bucket: Creation complete after 30s\n")
    def test_process_terraform_logs_with_multiple_log_lines(self, mock_open_file, mock_isfile):
        os.environ["RUN_ID"] = "1122334455"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="perf-eval",
          _scenario_name="test_scenario_name",
        )

        self.assertEqual(len(results), 2)

        self.assertEqual(results[0]["run_id"], "1122334455")
        self.assertEqual(results[0]["module_name"], "network")
        self.assertEqual(results[0]["submodule_name"], "")
        self.assertEqual(results[0]["resource_name"], "subnet")
        self.assertEqual(results[0]["action"], "apply")
        self.assertEqual(results[0]["time_taken_seconds"], 75)
        self.assertEqual(results[1]["scenario_type"], "perf-eval")
        self.assertEqual(results[1]["scenario_name"], "test_scenario_name")

        self.assertEqual(results[1]["run_id"], "1122334455")
        self.assertEqual(results[1]["module_name"], "storage")
        self.assertEqual(results[1]["submodule_name"], "")
        self.assertEqual(results[1]["resource_name"], "bucket")
        self.assertEqual(results[1]["action"], "apply")
        self.assertEqual(results[1]["time_taken_seconds"], 30)
        self.assertEqual(results[1]["scenario_type"], "perf-eval")
        self.assertEqual(results[1]["scenario_name"], "test_scenario_name")
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

if __name__ == "__main__":
    unittest.main()
