"""Exercise cleanup without Azure credentials or real resource mutations."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import signal
import subprocess
import unittest
from unittest.mock import Mock, patch

import resource_group as cleanup


def upgrade(status="RollingForward", start="2026-01-01T00:00:00Z"):
    return {"runningStatus": {"code": status, "startTime": start}}


def group(state="Deleting", name="group"):
    return {
        "id": f"/subscriptions/sub/resourceGroups/{name}",
        "properties": {"provisioningState": state},
    }


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)


class AzureCliTests(CleanupTest):
    @patch("resource_group.subprocess.Popen")
    @patch("resource_group.os.killpg")
    def test_timeout_terminates_cli_process_group(self, killpg, popen):
        process = popen.return_value
        process.pid = 12345
        process.communicate.side_effect = [subprocess.TimeoutExpired(["az"], 1), ("", "")]
        with self.assertRaises(subprocess.TimeoutExpired):
            cleanup.run_command(["az"], timeout=1)
        killpg.assert_called_once_with(12345, signal.SIGKILL)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(process.communicate.call_count, 2)

    @patch("resource_group.run_command")
    def test_subscription_and_timeout_on_every_request(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '{"name": "group"}', "")
        cli = cleanup.AzureCli("sub", 60)
        self.assertEqual(cli.run("group", "show", "--name", "group"), {"name": "group"})
        self.assertEqual(run.call_args.args[0], [
            "az", "group", "show", "--name", "group",
            "--subscription", "sub", "--only-show-errors", "--output", "json",
        ])
        self.assertGreater(run.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(run.call_args.kwargs["timeout"], 60)

    @patch("resource_group.run_command")
    def test_only_explicit_missing_codes_are_absence(self, run):
        cli = cleanup.AzureCli("sub", 60)
        run.return_value = subprocess.CompletedProcess(
            [], 1, "", "ERROR: (ResourceGroupNotFound) Gone",
        )
        self.assertIsNone(cleanup.get_group(cli, "group"))
        run.return_value = subprocess.CompletedProcess(
            [], 1, "", "ERROR: (AuthorizationFailed) Denied",
        )
        with self.assertRaises(cleanup.AzureCliError):
            cleanup.get_group(cli, "group")
        run.return_value = subprocess.CompletedProcess(
            [], 1, "", "ERROR: (NotFound) Not an explicit resource-group absence",
        )
        with self.assertRaises(cleanup.AzureCliError):
            cleanup.get_group(cli, "group")

    @patch("resource_group.run_command")
    def test_upgrade_not_found_requires_confirmed_vmss_absence(self, run):
        for missing in ("ResourceNotFound", "ResourceGroupNotFound"):
            with self.subTest(missing=missing):
                run.reset_mock()
                run.side_effect = [
                    subprocess.CompletedProcess(
                        [], 1, "", "ERROR: (NotFound) The entity was not found in this Azure location",
                    ),
                    subprocess.CompletedProcess([], 1, "", f"ERROR: ({missing}) Gone"),
                ]
                self.assertIsNone(cleanup.get_upgrade(cleanup.AzureCli("sub", 60), "vmss-id"))
                self.assertEqual(
                    [call.args[0][1:-5] for call in run.call_args_list],
                    [
                        ["vmss", "rolling-upgrade", "get-latest", "--ids", "vmss-id"],
                        ["vmss", "show", "--ids", "vmss-id"],
                    ],
                )

    @patch("resource_group.run_command")
    def test_upgrade_not_found_does_not_hide_existing_vmss_or_failed_verification(self, run):
        for response, code in [
            (subprocess.CompletedProcess([], 0, '{"id": "vmss-id"}', ""), "NotFound"),
            (subprocess.CompletedProcess([], 1, "", "ERROR: (NotFound) Ambiguous"), "NotFound"),
            (subprocess.CompletedProcess([], 1, "", "ERROR: (AuthorizationFailed) Denied"),
             "AuthorizationFailed"),
        ]:
            with self.subTest(response=response):
                run.side_effect = [
                    subprocess.CompletedProcess([], 1, "", "ERROR: (NotFound) Missing"),
                    response,
                ]
                with self.assertRaises(cleanup.AzureCliError) as error:
                    cleanup.get_upgrade(cleanup.AzureCli("sub", 60), "vmss-id")
                self.assertEqual(error.exception.code, code)

    @patch("resource_group.run_command")
    def test_throttling_has_bounded_retries(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 1, "", "ERROR: (TooManyRequests) Slow down",
        )
        cli = cleanup.AzureCli("sub", 60)
        with patch.object(cli, "sleep") as sleep:
            with self.assertRaises(cleanup.AzureCliError):
                cli.run("group", "show", "--name", "group")
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("resource_group.run_command")
    def test_transient_error_then_success(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 1, "", "ERROR: (ServiceUnavailable) Busy"),
            subprocess.CompletedProcess([], 0, "[]", ""),
        ]
        cli = cleanup.AzureCli("sub", 60)
        with patch.object(cli, "sleep"):
            self.assertEqual(cli.run("vmss", "list"), [])

    @patch("resource_group.run_command")
    def test_process_timeout_is_not_retried_as_success(self, run):
        run.side_effect = subprocess.TimeoutExpired(["az"], 1)
        cli = cleanup.AzureCli("sub", 60)
        with self.assertRaisesRegex(cleanup.CleanupError, "timed out"):
            cli.run("group", "delete", "--name", "group")
        run.assert_called_once()

    @patch("resource_group.time.monotonic", side_effect=[0, 11])
    def test_overall_deadline(self, _clock):
        cli = cleanup.AzureCli("sub", 10)
        with self.assertRaisesRegex(cleanup.CleanupError, "deadline"):
            cli.remaining()

    def test_submission_uses_no_wait(self):
        cli = Mock()
        cleanup.submit_delete(cli, "group")
        cli.run.assert_called_once_with(
            "group", "delete", "--name", "group", "--yes", "--no-wait",
        )
        cli.sleep.assert_not_called()

    def test_submission_handles_disappearance_but_not_permission_error(self):
        cli = Mock()
        cli.run.side_effect = cleanup.AzureCliError([], "ERROR: (ResourceGroupNotFound) Gone")
        cleanup.submit_delete(cli, "group")
        cli.run.side_effect = cleanup.AzureCliError([], "ERROR: (AuthorizationFailed) Denied")
        with self.assertRaises(cleanup.AzureCliError):
            cleanup.submit_delete(cli, "group")


class RollingUpgradeTests(CleanupTest):
    def setUp(self):
        super().setUp()
        self.cli = Mock()
        self.cli.get_optional.return_value = [{"id": "vmss-id", "upgradePolicy": {"mode": "Manual"}}]

    @patch("resource_group.get_upgrade")
    def test_active_manual_policy_upgrade_uses_cli_cancellation_waiter(self, get):
        get.return_value = upgrade()
        cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group", "group"])
        self.cli.get_optional.assert_called_once()
        self.cli.run.assert_called_once_with(
            "vmss", "rolling-upgrade", "cancel", "--ids", "vmss-id",
        )

    @patch("resource_group.get_upgrade")
    def test_terminal_or_absent_upgrade_is_not_cancelled(self, get):
        for status in ["Completed", "Cancelled", "Faulted", None]:
            with self.subTest(status=status):
                get.return_value = upgrade(status) if status else None
                cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"])
        self.cli.run.assert_not_called()

    @patch("resource_group.get_upgrade", return_value=upgrade("Unknown"))
    def test_unknown_status_fails_closed(self, _get):
        with self.assertRaisesRegex(cleanup.CleanupError, "Unrecognized"):
            cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"])
        self.cli.run.assert_not_called()

    @patch("resource_group.get_upgrade")
    def test_upgrade_completes_between_inspection_and_cancel(self, get):
        get.side_effect = [upgrade(), upgrade("Completed")]
        self.cli.run.side_effect = cleanup.AzureCliError([], "ERROR: (OperationNotAllowed) Finished")
        cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"])
        self.cli.run.assert_called_once_with(
            "vmss", "rolling-upgrade", "cancel", "--ids", "vmss-id",
        )

    @patch("resource_group.get_upgrade", return_value=upgrade())
    def test_cancel_failure_while_still_active_is_not_ignored(self, _get):
        self.cli.run.side_effect = cleanup.AzureCliError([], "ERROR: (OperationNotAllowed) Busy")
        with self.assertRaises(cleanup.AzureCliError):
            cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"])

    @patch("resource_group.get_upgrade", return_value=upgrade())
    def test_cancellation_timeout_is_surfaced(self, _get):
        self.cli.run.side_effect = cleanup.CleanupError("Azure CLI request timed out")
        with self.assertRaisesRegex(cleanup.CleanupError, "timed out"):
            cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"])

    @patch("resource_group.get_upgrade")
    def test_vmss_disappears_during_cancellation(self, get):
        get.side_effect = [upgrade(), None]
        self.cli.run.side_effect = cleanup.AzureCliError([], "ERROR: (ResourceNotFound) Gone")
        cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"])
        self.cli.run.assert_called_once_with(
            "vmss", "rolling-upgrade", "cancel", "--ids", "vmss-id",
        )

    def test_no_vmss_or_missing_group(self):
        for value in [[], None]:
            self.cli.get_optional.return_value = value
            cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"])
        self.cli.run.assert_not_called()

    @patch("resource_group.get_upgrade", return_value=upgrade())
    def test_cancellation_permission_error_is_not_ignored(self, _get):
        self.cli.run.side_effect = cleanup.AzureCliError([], "ERROR: (AuthorizationFailed) Denied")
        with self.assertRaises(cleanup.AzureCliError):
            cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"])


class DiscoveryTests(CleanupTest):
    def test_uses_actual_node_groups_for_all_clusters(self):
        cli = Mock()
        cli.get_optional.return_value = [
            {"id": "cluster-a", "nodeResourceGroup": "custom-nodes"},
            {"id": "cluster-b", "nodeResourceGroup": "other-nodes"},
        ]
        self.assertEqual(cleanup.discover_node_groups(cli, "group"), {
            "custom-nodes": ["cluster-a"], "other-nodes": ["cluster-b"],
        })
        cli.get_optional.assert_called_once_with(
            "aks", "list", "--resource-group", "group",
            missing_codes={"ResourceGroupNotFound"},
        )

    def test_owner_must_be_deleting_or_absent(self):
        cli = Mock()
        for state, eligible in [("Succeeded", False), ("Failed", False), ("Deleting", True)]:
            cli.get_optional.return_value = {"properties": {"provisioningState": state}}
            self.assertEqual(cleanup.owners_allow_upgrade_cancellation(
                cli, ["cluster"],
            ), eligible)
        cli.get_optional.return_value = None
        self.assertTrue(cleanup.owners_allow_upgrade_cancellation(
            cli, ["cluster"],
        ))
        self.assertEqual(cli.get_optional.call_args.args, ("resource", "show", "--ids", "cluster"))

    def test_all_owners_must_be_deleting_or_absent(self):
        for state, eligible in [("Deleting", True), ("Succeeded", False), ("Failed", False)]:
            with self.subTest(state=state):
                cli = Mock()
                cli.get_optional.side_effect = [
                    None,
                    {"properties": {"provisioningState": "Deleting"}},
                    {"properties": {"provisioningState": state}},
                ]
                self.assertEqual(cleanup.owners_allow_upgrade_cancellation(
                    cli, ["absent-cluster", "deleting-cluster", "other-cluster"],
                ), eligible)
                self.assertEqual(cli.get_optional.call_count, 3)


class OrchestrationTests(CleanupTest):
    def setUp(self):
        super().setUp()
        self.cli = Mock()
        self.patches = {}
        for name in (
            "get_group", "discover_node_groups", "submit_delete",
            "cancel_active_vmss_rolling_upgrades", "owners_allow_upgrade_cancellation",
        ):
            patcher = patch(f"resource_group.{name}")
            self.patches[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.patches["discover_node_groups"].return_value = {}
        self.patches["owners_allow_upgrade_cancellation"].return_value = True
        self.clock = patch("resource_group.time.monotonic", return_value=100).start()
        self.addCleanup(patch.stopall)

    def run_cleanup(self):
        cleanup.delete_resource_group(self.cli, "group", 1)

    def test_already_absent_group_is_success_without_mutation(self):
        self.patches["get_group"].return_value = None
        self.run_cleanup()
        self.patches["submit_delete"].assert_not_called()

    def test_fast_deletion_never_inspects_upgrades(self):
        self.patches["get_group"].side_effect = [group(), None]
        self.run_cleanup()
        self.patches["cancel_active_vmss_rolling_upgrades"].assert_not_called()
        self.patches["submit_delete"].assert_called_once()

    def test_each_poll_inspects_upgrades_without_initial_delay(self):
        self.patches["get_group"].side_effect = [group(), group(), group(), None]
        self.run_cleanup()
        self.assertEqual(self.patches["cancel_active_vmss_rolling_upgrades"].call_count, 2)
        self.assertEqual(self.cli.sleep.call_args_list, [unittest.mock.call(1)] * 2)

    def test_node_group_retained_after_owner_group_disappears(self):
        self.patches["discover_node_groups"].return_value = {"node-group": ["cluster"]}
        self.patches["get_group"].side_effect = [group(), None, group(), None, None]
        self.run_cleanup()
        self.assertEqual(
            self.patches["cancel_active_vmss_rolling_upgrades"].call_args.args[1], ["node-group"],
        )
        self.cli.sleep.assert_called_once()

    def test_live_owner_node_group_excluded_from_cancellation(self):
        self.patches["discover_node_groups"].return_value = {"node-group": ["cluster"]}
        self.patches["get_group"].side_effect = [group(), group(), group(), None, None]
        self.patches["owners_allow_upgrade_cancellation"].return_value = False
        self.run_cleanup()
        self.assertEqual(
            self.patches["cancel_active_vmss_rolling_upgrades"].call_args.args[1], ["group"],
        )

    def test_recovery_does_not_resubmit_inflight_delete(self):
        self.patches["get_group"].side_effect = [group(), group(), None]
        self.run_cleanup()
        self.patches["submit_delete"].assert_called_once()

    def test_timeout_does_not_claim_success(self):
        self.patches["get_group"].return_value = group()
        self.cli.remaining.side_effect = [10, cleanup.CleanupError("deadline exceeded")]
        with self.assertRaisesRegex(cleanup.CleanupError, "deadline"):
            self.run_cleanup()


class CommandLineTests(CleanupTest):
    def run_script(self, responses, timeout="60"):
        arguments = [
            "resource_group.py", "delete", "--resource-group", "group", "--subscription", "sub",
            "--timeout-seconds", timeout, "--poll-interval-seconds", "1",
        ]
        commands = []

        def run(command, timeout):
            commands.append(command[1:-5])
            response = next(responses)
            if isinstance(response, str):
                return subprocess.CompletedProcess(command, 1, "", f"ERROR: ({response}) failed")
            return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

        with patch("resource_group.sys.argv", arguments), \
                patch("resource_group.run_command", side_effect=run), \
                patch("resource_group.time.sleep"), redirect_stderr(self.output):
            result = cleanup.main()
        return result, commands

    def test_single_entrypoint_submits_cancels_and_waits_for_both_groups(self):
        responses = iter([
            group(),
            [{"id": "cluster-id", "nodeResourceGroup": "node-group"}],
            None,  # Async deletion accepted.
            group(), group(),  # Both groups still exist.
            {"properties": {"provisioningState": "Deleting"}},
            [],  # No VMSS in parent RG.
            [{"id": "vmss-id", "upgradePolicy": {"mode": "Manual"}}],
            upgrade(), None,  # CLI waits for cancellation.
            "ResourceGroupNotFound", "ResourceGroupNotFound",
        ])
        result, commands = self.run_script(responses)
        self.assertEqual(result, 0)
        self.assertEqual(commands, [
            ["group", "show", "--name", "group"],
            ["aks", "list", "--resource-group", "group"],
            ["group", "delete", "--name", "group", "--yes", "--no-wait"],
            ["group", "show", "--name", "group"],
            ["group", "show", "--name", "node-group"],
            ["resource", "show", "--ids", "cluster-id"],
            ["vmss", "list", "--resource-group", "group"],
            ["vmss", "list", "--resource-group", "node-group"],
            ["vmss", "rolling-upgrade", "get-latest", "--ids", "vmss-id"],
            ["vmss", "rolling-upgrade", "cancel", "--ids", "vmss-id"],
            ["group", "show", "--name", "group"],
            ["group", "show", "--name", "node-group"],
        ])
        self.assertIn("associated node groups deleted", self.output.getvalue())

    def test_failed_cluster_skips_node_group_until_cluster_disappears(self):
        result, commands = self.run_script(iter([
            group(),
            [{"id": "cluster-id", "nodeResourceGroup": "node-group"}],
            None,
            group(), group("Succeeded", "node-group"),
            {"properties": {"provisioningState": "Failed", "nodeResourceGroup": "node-group"}},
            [],
            None, group("Succeeded", "node-group"),
            "ResourceNotFound",
            [{"id": "vmss-id", "upgradePolicy": {"mode": "Manual"}}],
            upgrade(), None,
            "ResourceGroupNotFound", "ResourceGroupNotFound",
        ]))
        self.assertEqual(result, 0)
        self.assertEqual(commands, [
            ["group", "show", "--name", "group"],
            ["aks", "list", "--resource-group", "group"],
            ["group", "delete", "--name", "group", "--yes", "--no-wait"],
            ["group", "show", "--name", "group"],
            ["group", "show", "--name", "node-group"],
            ["resource", "show", "--ids", "cluster-id"],
            ["vmss", "list", "--resource-group", "group"],
            ["group", "show", "--name", "group"],
            ["group", "show", "--name", "node-group"],
            ["resource", "show", "--ids", "cluster-id"],
            ["vmss", "list", "--resource-group", "node-group"],
            ["vmss", "rolling-upgrade", "get-latest", "--ids", "vmss-id"],
            ["vmss", "rolling-upgrade", "cancel", "--ids", "vmss-id"],
            ["group", "show", "--name", "group"],
            ["group", "show", "--name", "node-group"],
        ])

    def test_stalled_delete_after_cancellation_times_out_without_resubmission(self):
        def responses():
            yield from [
                group(), [], None,
                group("Failed"), [{"id": "vmss-id"}], upgrade(), None,
            ]
            while True:
                yield group("Failed")
                yield []

        with patch("resource_group.time.monotonic", side_effect=range(0, 1000)):
            result, commands = self.run_script(responses(), timeout="20")
        self.assertEqual(result, 1)
        self.assertEqual(commands.count([
            "group", "delete", "--name", "group", "--yes", "--no-wait",
        ]), 1)
        self.assertIn(
            ["vmss", "rolling-upgrade", "cancel", "--ids", "vmss-id"], commands,
        )
        self.assertIn("RESOURCE GROUP CLEANUP FAILED", self.output.getvalue())
        self.assertIn("deadline exceeded", self.output.getvalue())

    def test_permission_error_exits_nonzero(self):
        result, commands = self.run_script(iter(["AuthorizationFailed"]))
        self.assertEqual(result, 1)
        self.assertEqual(commands, [["group", "show", "--name", "group"]])
        self.assertIn("RESOURCE GROUP CLEANUP FAILED", self.output.getvalue())

    @patch("resource_group.time.monotonic", side_effect=[0, 0, 0, 0, 61])
    def test_overall_timeout_exits_nonzero(self, _clock):
        result, commands = self.run_script(iter([group(), [], None]))
        self.assertEqual(result, 1)
        self.assertEqual(commands[-1], [
            "group", "delete", "--name", "group", "--yes", "--no-wait",
        ])
        self.assertIn("deadline exceeded", self.output.getvalue())

    def test_invalid_timeout_is_rejected_before_azure_calls(self):
        with self.assertRaises(SystemExit) as error:
            self.run_script(iter([]), timeout="0")
        self.assertEqual(error.exception.code, 2)

    def test_missing_or_unknown_subcommand_is_rejected_before_azure_calls(self):
        options = [
            "--resource-group", "group", "--subscription", "sub",
            "--timeout-seconds", "60", "--poll-interval-seconds", "1",
        ]
        for arguments in [[], options, ["cancel", *options]]:
            with self.subTest(arguments=arguments), \
                    patch("resource_group.sys.argv", ["resource_group.py", *arguments]), \
                    patch("resource_group.run_command") as run, redirect_stderr(self.output):
                with self.assertRaises(SystemExit) as error:
                    cleanup.main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
