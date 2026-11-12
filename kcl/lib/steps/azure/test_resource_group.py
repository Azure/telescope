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


def delete_failure(name="node-group", timestamp="2026-01-01T00:01:00Z"):
    return {
        "resourceId": group(name=name)["id"],
        "operationName": {"value": "Microsoft.Resources/subscriptions/resourcegroups/delete"},
        "eventTimestamp": timestamp,
        "status": {"value": "Failed"},
        "properties": {"statusMessage": json.dumps({"error": {
            "code": "ResourceGroupDeletionBlocked",
            "message": "Microsoft.Compute/virtualMachineScaleSets/aks-pool could not be deleted",
            "details": [{"code": "OperationNotAllowed", "message": "Rolling Upgrade in progress"}],
        }})},
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
        self.assertTrue(cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group", "group"]))
        self.cli.get_optional.assert_called_once()
        self.cli.run.assert_called_once_with(
            "vmss", "rolling-upgrade", "cancel", "--ids", "vmss-id",
        )

    @patch("resource_group.get_upgrade")
    def test_terminal_or_absent_upgrade_is_not_cancelled(self, get):
        for status in ["Completed", "Cancelled", "Faulted", None]:
            with self.subTest(status=status):
                get.return_value = upgrade(status) if status else None
                self.assertFalse(cleanup.cancel_active_vmss_rolling_upgrades(
                    self.cli, ["group"],
                ))
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
        self.assertTrue(cleanup.cancel_active_vmss_rolling_upgrades(
            self.cli, ["group"],
        ))

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
        self.assertTrue(cleanup.cancel_active_vmss_rolling_upgrades(self.cli, ["group"]))

    def test_no_vmss_or_missing_group(self):
        for value in [[], None]:
            self.cli.get_optional.return_value = value
            self.assertFalse(cleanup.cancel_active_vmss_rolling_upgrades(
                self.cli, ["group"],
            ))
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
                cli, ["cluster"], group(name="node-group"), group(), "2026-01-01T00:00:00Z",
            ), eligible)
        cli.get_optional.return_value = None
        self.assertTrue(cleanup.owners_allow_upgrade_cancellation(
            cli, ["cluster"], group(name="node-group"), group(), "2026-01-01T00:00:00Z",
        ))
        self.assertEqual(cli.get_optional.call_args.args, ("resource", "show", "--ids", "cluster"))

    def test_failed_owner_requires_exact_fresh_blocker_and_deleting_parent(self):
        for state, node_name, parent, events, eligible in [
            ("Failed", "node-group", group(), [delete_failure()], True),
            ("Failed", "other-group", group(), [delete_failure()], False),
            ("Succeeded", "node-group", group(), [delete_failure()], False),
            ("Failed", "node-group", group("Succeeded"), [delete_failure()], False),
            ("Failed", "node-group", group("Failed"), [delete_failure()], False),
            ("Failed", "node-group", None, [delete_failure()], False),
            ("Failed", "node-group", group(), [], False),
            ("Failed", "node-group", group(), [delete_failure("other-group")], False),
            ("Failed", "node-group", group(), [
                delete_failure(timestamp="2025-12-31T23:59:59Z"),
            ], False),
            ("Failed", "node-group", group(), [
                delete_failure(timestamp="2026-01-01T00:00:00Z"),
            ], False),
            ("Failed", "node-group", group(), [
                dict(delete_failure(), properties={"statusMessage": "Unrelated failure"}),
            ], False),
            ("Failed", "node-group", group(), [
                delete_failure(),
                dict(delete_failure(timestamp="2026-01-01T00:02:00Z"), status={"value": "Started"}),
            ], False),
        ]:
            with self.subTest(state=state, node_name=node_name, parent=parent, events=events):
                cli = Mock()
                cli.get_optional.return_value = {"properties": {
                    "provisioningState": state, "nodeResourceGroup": node_name,
                }}
                cli.run.return_value = events
                self.assertEqual(cleanup.owners_allow_upgrade_cancellation(
                    cli, ["cluster"], group("Succeeded", "node-group"), parent,
                    "2026-01-01T00:00:00+00:00",
                ), eligible)

    def test_one_failed_delete_owner_does_not_allow_another_live_owner(self):
        cli = Mock()
        cli.get_optional.side_effect = [
            {"properties": {"provisioningState": "Failed", "nodeResourceGroup": "node-group"}},
            {"properties": {"provisioningState": "Succeeded", "nodeResourceGroup": "node-group"}},
        ]
        cli.run.return_value = [delete_failure()]
        self.assertFalse(cleanup.owners_allow_upgrade_cancellation(
            cli, ["failed-cluster", "live-cluster"], group("Succeeded", "node-group"), group(),
            "2026-01-01T00:00:00Z",
        ))
        cli.run.assert_not_called()

    def test_failed_owner_requires_every_part_of_the_vmss_delete_blocker(self):
        for token in (
            "ResourceGroupDeletionBlocked", "Microsoft.Compute/virtualMachineScaleSets/",
            "OperationNotAllowed", "Rolling Upgrade in progress",
        ):
            with self.subTest(missing=token):
                cli = Mock()
                cli.get_optional.return_value = {"properties": {
                    "provisioningState": "Failed", "nodeResourceGroup": "node-group",
                }}
                failure = delete_failure()
                failure["properties"]["statusMessage"] = (
                    failure["properties"]["statusMessage"].replace(token, "Unrelated")
                )
                cli.run.return_value = [failure]
                self.assertFalse(cleanup.owners_allow_upgrade_cancellation(
                    cli, ["cluster"], group("Succeeded", "node-group"), group(),
                    "2026-01-01T00:00:00Z",
                ))

    def test_only_latest_scoped_delete_event_counts(self):
        cli = Mock()
        failed = delete_failure("group")
        started = dict(failed, eventTimestamp="2026-01-01T00:02:00Z", status={"value": "Started"})
        resource_id = group()["id"]
        since = "2026-01-01T00:00:00Z"
        cli.run.return_value = [failed, started]
        self.assertIsNone(cleanup.latest_delete_failure(cli, resource_id, since))
        cli.run.return_value = [failed]
        self.assertEqual(cleanup.latest_delete_failure(cli, resource_id, since), failed)
        self.assertIn(resource_id, cli.run.call_args.args)


class OrchestrationTests(CleanupTest):
    def setUp(self):
        super().setUp()
        self.cli = Mock()
        self.patches = {}
        for name in (
            "get_group", "discover_node_groups", "submit_delete",
            "cancel_active_vmss_rolling_upgrades", "owners_allow_upgrade_cancellation",
            "latest_delete_failure",
        ):
            patcher = patch(f"resource_group.{name}")
            self.patches[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.patches["discover_node_groups"].return_value = {}
        self.patches["latest_delete_failure"].return_value = None
        self.patches["cancel_active_vmss_rolling_upgrades"].return_value = False
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

    def test_failed_delete_retried_only_after_recovery(self):
        self.patches["get_group"].side_effect = [group(), group("Succeeded"), None]
        self.patches["cancel_active_vmss_rolling_upgrades"].return_value = True
        self.patches["latest_delete_failure"].return_value = {"status": "Failed"}
        self.run_cleanup()
        self.assertEqual(self.patches["submit_delete"].call_count, 2)

    def test_unrelated_failure_is_not_retried(self):
        self.patches["get_group"].return_value = group("Succeeded")
        self.patches["latest_delete_failure"].return_value = {"status": "Failed"}
        with self.assertRaisesRegex(cleanup.CleanupError, "without further recovery"):
            self.run_cleanup()
        self.patches["submit_delete"].assert_called_once()

    def test_recovery_does_not_resubmit_inflight_delete(self):
        self.patches["get_group"].side_effect = [group(), group(), None]
        self.patches["cancel_active_vmss_rolling_upgrades"].return_value = True
        self.run_cleanup()
        self.patches["submit_delete"].assert_called_once()

    def test_failed_event_does_not_resubmit_while_parent_is_still_deleting(self):
        self.patches["get_group"].side_effect = [group(), group(), None]
        self.patches["cancel_active_vmss_rolling_upgrades"].return_value = True
        self.patches["latest_delete_failure"].return_value = {"status": "Failed"}
        self.run_cleanup()
        self.patches["submit_delete"].assert_called_once()

    def test_retries_are_bounded(self):
        self.clock.side_effect = range(100, 1000, 10)
        self.patches["get_group"].return_value = group("Succeeded")
        self.patches["cancel_active_vmss_rolling_upgrades"].return_value = True
        self.patches["latest_delete_failure"].return_value = {"status": "Failed"}
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup()
        self.assertEqual(self.patches["submit_delete"].call_count, 3)

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
                patch("resource_group.datetime", wraps=cleanup.datetime) as date, \
                patch("resource_group.time.sleep"), redirect_stderr(self.output):
            date.now.return_value = date.fromisoformat("2026-01-01T00:00:00+00:00")
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
            [],  # No failed delete in Activity Log.
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
            [
                "monitor", "activity-log", "list", "--resource-id",
                "/subscriptions/sub/resourceGroups/group", "--start-time",
                "2026-01-01T00:00:00+00:00", "--max-events", "100",
            ],
            ["group", "show", "--name", "group"],
            ["group", "show", "--name", "node-group"],
        ])
        self.assertIn("associated node groups deleted", self.output.getvalue())

    def test_failed_aks_delete_recovers_node_upgrades_without_resubmitting_parent(self):
        result, commands = self.run_script(iter([
            group(),
            [{"id": "cluster-id", "nodeResourceGroup": "node-group"}],
            None,
            group(), group("Succeeded", "node-group"),
            {"properties": {"provisioningState": "Failed", "nodeResourceGroup": "node-group"}},
            [delete_failure()],
            [],
            [{"id": "vmss-id", "upgradePolicy": {"mode": "Manual"}}],
            upgrade(), None,
            [],
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
            [
                "monitor", "activity-log", "list", "--resource-id",
                "/subscriptions/sub/resourceGroups/node-group", "--start-time",
                "2026-01-01T00:00:00+00:00", "--max-events", "100",
            ],
            ["vmss", "list", "--resource-group", "group"],
            ["vmss", "list", "--resource-group", "node-group"],
            ["vmss", "rolling-upgrade", "get-latest", "--ids", "vmss-id"],
            ["vmss", "rolling-upgrade", "cancel", "--ids", "vmss-id"],
            [
                "monitor", "activity-log", "list", "--resource-id",
                "/subscriptions/sub/resourceGroups/group", "--start-time",
                "2026-01-01T00:00:00+00:00", "--max-events", "100",
            ],
            ["group", "show", "--name", "group"],
            ["group", "show", "--name", "node-group"],
        ])

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
