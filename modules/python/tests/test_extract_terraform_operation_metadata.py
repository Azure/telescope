import unittest
import os
from unittest.mock import patch, mock_open

from terraform.extract_terraform_operation_metadata import (
  time_to_seconds,
  parse_module_path,
  process_terraform_logs,
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

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=(
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creating...\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [10m0s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... 20m0s elapsed]\n"
        "│ Error: Failed to create/update resource\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creating...\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [15m0s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... 25m30s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creating...\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [5m0s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... 30m45s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creation complete after 30m55s [id=/subscriptions/b8ceb4e5-f05b-4562-a9f5-14acb1f24219/resourceGroups/57202-578c08a2/providers/Microsoft.ContainerService/managedClusters/ccp-provisioning-H4]\n"
    ))
    def test_process_terraform_logs_with_failed_run_and_retries(self, mock_open_file, mock_isfile):
        os.environ["RUN_ID"] = "9988776655"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="perf-eval",
          _scenario_name="test_scenario_name",
        )

        self.assertEqual(len(results), 3)

        # First failed run - last elapsed was 20m0s = 1200s
        self.assertEqual(results[0]["module_name"], "azapi[\"ccp\"]")
        self.assertEqual(results[0]["resource_name"], "aks_cluster")
        self.assertEqual(results[0]["time_taken_seconds"], 1200)
        self.assertEqual(results[0]["result"], {"success": False, "timed_out": False})

        # Second failed run (retry 1) - last elapsed was 25m30s = 1530s
        self.assertEqual(results[1]["module_name"], "azapi[\"ccp\"]")
        self.assertEqual(results[1]["resource_name"], "aks_cluster")
        self.assertEqual(results[1]["time_taken_seconds"], 1530)
        self.assertEqual(results[1]["result"], {"success": False, "timed_out": False})

        # Third failed run (retry 2) - last elapsed was 30m45s = 1845s
        self.assertEqual(results[2]["module_name"], "azapi[\"ccp\"]")
        self.assertEqual(results[2]["resource_name"], "aks_cluster")
        self.assertEqual(results[2]["time_taken_seconds"], 1855)
        self.assertEqual(results[2]["result"], {"success": True, "timed_out": False})

        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=(
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creating...\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [5m0s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [10m0s elapsed]\n"
        "creating/updating Resource: (ResourceId\n"
        "/subscriptions/b8ceb4e5/resourceGroups/58296/providers/Microsoft.ContainerService/managedClusters/ccp-H8\n"
        "│ Error: creating/updating Resource: context deadline exceeded\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creating...\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [5m0s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creation complete after 8m30s [id=/subscriptions/b8ceb4e5/resourceGroups/58296/providers/Microsoft.ContainerService/managedClusters/ccp-H8]\n"
    ))
    def test_process_terraform_logs_with_timeout_and_retry(self, mock_open_file, mock_isfile):
        os.environ["RUN_ID"] = "1234567890"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="perf-eval",
          _scenario_name="test_scenario_name",
        )

        self.assertEqual(len(results), 2)

        # First run timed out
        self.assertEqual(results[0]["module_name"], "azapi[\"ccp\"]")
        self.assertEqual(results[0]["resource_name"], "aks_cluster")
        self.assertEqual(results[0]["time_taken_seconds"], 600)
        self.assertEqual(results[0]["result"], {"success": False, "timed_out": True})

        # Retry succeeded
        self.assertEqual(results[1]["module_name"], "azapi[\"ccp\"]")
        self.assertEqual(results[1]["resource_name"], "aks_cluster")
        self.assertEqual(results[1]["time_taken_seconds"], 510)
        self.assertEqual(results[1]["result"], {"success": True, "timed_out": False})

        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=(
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creating...\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [5m0s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [10m0s elapsed]\n"
        "│ Error: Failed to create/update resource\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creating...\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [5m0s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [10m0s elapsed]\n"
        "│ Error: creating/updating Resource: context deadline exceeded\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Creating...\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [5m0s elapsed]\n"
        "module.azapi[\"ccp\"].azapi_resource.aks_cluster: Still creating... [10m0s elapsed]\n"
        "│ Error: creating/updating Resource: context deadline exceeded\n"
    ))
    def test_process_terraform_logs_with_all_retries_failed(self, mock_open_file, mock_isfile):
        os.environ["RUN_ID"] = "1112223334"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="perf-eval",
          _scenario_name="test_scenario_name",
        )

        self.assertEqual(len(results), 3)

        # First run failed with a non-timeout error
        self.assertEqual(results[0]["run_id"], "1112223334")
        self.assertEqual(results[0]["module_name"], "azapi[\"ccp\"]")
        self.assertEqual(results[0]["resource_name"], "aks_cluster")
        self.assertEqual(results[0]["time_taken_seconds"], 600)
        self.assertEqual(results[0]["result"], {"success": False, "timed_out": False})

        # Second run timed out
        self.assertEqual(results[1]["run_id"], "1112223334")
        self.assertEqual(results[1]["module_name"], "azapi[\"ccp\"]")
        self.assertEqual(results[1]["resource_name"], "aks_cluster")
        self.assertEqual(results[1]["time_taken_seconds"], 600)
        self.assertEqual(results[1]["result"], {"success": False, "timed_out": True})

        # Third run timed out
        self.assertEqual(results[2]["run_id"], "1112223334")
        self.assertEqual(results[2]["module_name"], "azapi[\"ccp\"]")
        self.assertEqual(results[2]["resource_name"], "aks_cluster")
        self.assertEqual(results[2]["time_taken_seconds"], 600)
        self.assertEqual(results[2]["result"], {"success": False, "timed_out": True})

        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=(
        'module.azapi["ccp-provisioning-H2"].azapi_resource.aks_cluster: Destroying... [id=/subscriptions/b8ceb4e5-f05b-4562-a9f5-14acb1f24219/resourceGroups/59393-51f48219/providers/Microsoft.ContainerService/managedClusters/ccp-provisioning-H2]\n'
        'module.azapi["ccp-provisioning-H2"].azapi_resource.aks_cluster: Still destroying... [id=/subscriptions/b8ceb4e5-f05b-4562-a9f5-...ce/managedClusters/ccp-provisioning-H2, 00m10s elapsed]\n'
    ))
    def test_process_terraform_logs_still_destroying_with_id_prefix(self, mock_open_file, mock_isfile):
        """Verify metadata record is created when 'Still destroying' line contains id= prefix before elapsed time."""
        os.environ["RUN_ID"] = "4455667788"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="destroy",
          _scenario_type="ccp",
          _scenario_name="provisioning",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], "4455667788")
        self.assertEqual(results[0]["module_name"], 'azapi["ccp-provisioning-H2"]')
        self.assertEqual(results[0]["submodule_name"], "azapi_resource")
        self.assertEqual(results[0]["resource_name"], "aks_cluster")
        self.assertEqual(results[0]["action"], "destroy")
        self.assertEqual(results[0]["time_taken_seconds"], 10)
        self.assertEqual(results[0]["result"], {"success": False, "timed_out": False})
        mock_open_file.assert_called_once_with('/fake/path/terraform_destroy.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_destroy.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=(
        'module.azapi["ccp-provisioning-H2"].azapi_resource.aks_cluster: Creating... [id=/subscriptions/b8ceb4e5-f05b-4562-a9f5-14acb1f24219/resourceGroups/59393-51f48219/providers/Microsoft.ContainerService/managedClusters/ccp-provisioning-H2]\n'
        'module.azapi["ccp-provisioning-H2"].azapi_resource.aks_cluster: Still creating... [id=/subscriptions/b8ceb4e5-f05b-4562-a9f5-...ce/managedClusters/ccp-provisioning-H2, 10m0s elapsed]\n'
        'module.azapi["ccp-provisioning-H2"].azapi_resource.aks_cluster: Still creating... [id=/subscriptions/b8ceb4e5-f05b-4562-a9f5-...ce/managedClusters/ccp-provisioning-H2, 20m0s elapsed]\n'
        'module.azapi["ccp-provisioning-H2"].azapi_resource.aks_cluster: Creation complete after 25m30s [id=/subscriptions/b8ceb4e5-f05b-4562-a9f5-14acb1f24219/resourceGroups/59393-51f48219/providers/Microsoft.ContainerService/managedClusters/ccp-provisioning-H2]\n'
    ))
    def test_process_terraform_logs_still_creating_with_id_prefix_then_complete(self, mock_open_file, mock_isfile):
        """Verify that 'Still creating' lines with id= prefix are parsed and final completion record is used."""
        os.environ["RUN_ID"] = "5566778899"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="ccp",
          _scenario_name="provisioning",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], "5566778899")
        self.assertEqual(results[0]["module_name"], 'azapi["ccp-provisioning-H2"]')
        self.assertEqual(results[0]["submodule_name"], "azapi_resource")
        self.assertEqual(results[0]["resource_name"], "aks_cluster")
        self.assertEqual(results[0]["action"], "apply")
        self.assertEqual(results[0]["time_taken_seconds"], 1530)
        self.assertEqual(results[0]["result"], {"success": True, "timed_out": False})
        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=(
        'module.azapi["ccp"].azapi_resource.aks_cluster: Destroying... [id=/subscriptions/b8ceb4e5/resourceGroups/59393/providers/Microsoft.ContainerService/managedClusters/ccp-H2]\n'
        '│ Error: deleting Resource: unexpected status 409\n'
    ))
    def test_process_terraform_logs_failure_without_elapsed_line(self, mock_open_file, mock_isfile):
        """Verify a failure record with 0s elapsed is created when there is no 'Still destroying' line."""
        os.environ["RUN_ID"] = "6677889900"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="destroy",
          _scenario_type="ccp",
          _scenario_name="provisioning",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], "6677889900")
        self.assertEqual(results[0]["module_name"], 'azapi["ccp"]')
        self.assertEqual(results[0]["submodule_name"], "azapi_resource")
        self.assertEqual(results[0]["resource_name"], "aks_cluster")
        self.assertEqual(results[0]["action"], "destroy")
        self.assertEqual(results[0]["time_taken_seconds"], 0)
        self.assertEqual(results[0]["result"], {"success": False, "timed_out": False})
        mock_open_file.assert_called_once_with('/fake/path/terraform_destroy.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_destroy.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=(
        'module.azapi["ccp"].azapi_resource.aks_cluster: Creating...\n'
        '│ Error: creating Resource: context deadline exceeded\n'
    ))
    def test_process_terraform_logs_timeout_without_elapsed_line(self, mock_open_file, mock_isfile):
        """Verify a failure record with timed_out=True and 0s elapsed is created when timeout occurs without elapsed lines."""
        os.environ["RUN_ID"] = "7788990011"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="ccp",
          _scenario_name="provisioning",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], "7788990011")
        self.assertEqual(results[0]["module_name"], 'azapi["ccp"]')
        self.assertEqual(results[0]["resource_name"], "aks_cluster")
        self.assertEqual(results[0]["action"], "apply")
        self.assertEqual(results[0]["time_taken_seconds"], 0)
        self.assertEqual(results[0]["result"], {"success": False, "timed_out": True})
        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=(
        'module.azapi["ccp"].azapi_resource.aks_cluster: Creating...\n'
        '│ Error: creating Resource: unexpected status 409\n'
        'module.azapi["ccp"].azapi_resource.aks_cluster: Creating...\n'
        'module.azapi["ccp"].azapi_resource.aks_cluster: Still creating... [5m0s elapsed]\n'
        'module.azapi["ccp"].azapi_resource.aks_cluster: Creation complete after 8m30s [id=/subscriptions/b8ceb4e5/resourceGroups/59393/providers/Microsoft.ContainerService/managedClusters/ccp-H2]\n'
    ))
    def test_process_terraform_logs_retry_after_immediate_failure(self, mock_open_file, mock_isfile):
        """Verify first run records 0s failure when it fails immediately, and retry succeeds normally."""
        os.environ["RUN_ID"] = "8899001122"

        results = process_terraform_logs(
          log_path="/fake/path",
          _command_type="apply",
          _scenario_type="ccp",
          _scenario_name="provisioning",
        )

        self.assertEqual(len(results), 2)

        # First run failed immediately - no elapsed time
        self.assertEqual(results[0]["module_name"], 'azapi["ccp"]')
        self.assertEqual(results[0]["resource_name"], "aks_cluster")
        self.assertEqual(results[0]["time_taken_seconds"], 0)
        self.assertEqual(results[0]["result"], {"success": False, "timed_out": False})

        # Retry succeeded
        self.assertEqual(results[1]["module_name"], 'azapi["ccp"]')
        self.assertEqual(results[1]["resource_name"], "aks_cluster")
        self.assertEqual(results[1]["time_taken_seconds"], 510)
        self.assertEqual(results[1]["result"], {"success": True, "timed_out": False})

        mock_open_file.assert_called_once_with('/fake/path/terraform_apply.log', 'r', encoding='utf-8')
        mock_isfile.assert_called_once_with("/fake/path/terraform_apply.log")

if __name__ == "__main__":
    unittest.main()
