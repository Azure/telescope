"""Offline checks for the WSL local launcher."""

import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "linux", "The local launcher runs inside WSL Linux")
class TestLocalLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("local_launcher", Path(__file__).with_name("local.py"))
        cls.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.launcher)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name) / "state"
        patcher = patch.object(self.launcher, "STATE", self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.args = argparse.Namespace(
            registry="registry.azurecr.io", image="image@sha256:" + "a" * 64,
            username="reader", setup_only=False, password_stdin=True, start_immediately=True,
            two_batches=False, pull_count=5,
        )

    def test_dedicated_context_restored_and_parallel_runs_blocked(self):
        with patch.dict(os.environ, {"KUBECONFIG": "/unrelated/config", "KIND_EXPERIMENTAL_PROVIDER": "original"}):
            with self.launcher.local_context():
                self.assertEqual(os.environ["KUBECONFIG"], str(self.state / "kubeconfig"))
                self.assertEqual(os.environ["KIND_EXPERIMENTAL_PROVIDER"], "podman")
                with self.assertRaisesRegex(self.launcher.DownloadError, "already running"):
                    with self.launcher.local_context():
                        self.fail("Parallel local commands must not proceed")
            self.assertEqual(os.environ["KUBECONFIG"], "/unrelated/config")
            self.assertEqual(os.environ["KIND_EXPERIMENTAL_PROVIDER"], "original")

    def test_setup_only_never_requests_credentials_or_runs_downloads(self):
        self.args.setup_only = True
        with patch.object(self.launcher, "prepare_cluster", return_value="local-node"):
            with patch.object(self.launcher, "check_workers") as check:
                with patch.object(self.launcher.pull, "run") as run:
                    self.assertEqual(self.launcher.execute(self.args), 0)
        check.assert_called_once_with("local-node", pull_count=5)
        run.assert_not_called()

    def test_existing_namespace_is_not_deleted_or_reused(self):
        with patch.object(self.launcher, "prepare_cluster", return_value="local-node"):
            with patch.object(self.launcher, "command", return_value="namespace/acr-five-pulls") as command:
                with self.assertRaisesRegex(self.launcher.DownloadError, "already exists"):
                    self.launcher.execute(self.args)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[1], "get")

    def test_repeated_runs_use_unique_reports_and_restore_credentials(self):
        reports = []

        def run(args, **kwargs):
            self.assertEqual(args.image, f"{self.args.registry}/{self.args.image}")
            self.assertEqual(kwargs, {
                "node_count": 1, "region": "local", "registry_resource_group": None,
                "start_immediately": True, "pull_count": 5,
            })
            self.assertEqual(os.environ["ACR_PULL_PASSWORD"], "temporary-password")
            reports.append(args.result_file)
            return 0

        with patch.dict(os.environ, {"ACR_PULL_PASSWORD": "original-password", "ACR_PULL_USERNAME": "original-user"}):
            with patch.object(self.launcher, "prepare_cluster", return_value="local-node"):
                with patch.object(self.launcher, "command", return_value=""):
                    with patch.object(self.launcher.pull, "run", side_effect=run):
                        for _ in range(2):
                            with patch("sys.stdin", io.StringIO("temporary-password\n")):
                                with contextlib.redirect_stdout(io.StringIO()):
                                    self.assertEqual(self.launcher.execute(self.args), 0)
            self.assertEqual(os.environ["ACR_PULL_PASSWORD"], "original-password")
            self.assertEqual(os.environ["ACR_PULL_USERNAME"], "original-user")
        self.assertEqual(len(set(reports)), 2)

    def test_interactive_run_prompts_without_saving_the_password(self):
        self.args.password_stdin = False
        output = io.StringIO()
        with patch.dict(os.environ, {"ACR_PULL_PASSWORD": ""}):
            with patch.object(self.launcher, "prepare_cluster", return_value="local-node"):
                with patch.object(self.launcher, "command", return_value=""):
                    with patch.object(self.launcher.pull, "run", return_value=0):
                        with patch("sys.stdin.isatty", return_value=True):
                            with patch.object(self.launcher.getpass, "getpass", return_value="prompted-password") as prompt:
                                with contextlib.redirect_stdout(output):
                                    self.assertEqual(self.launcher.execute(self.args), 0)
            self.assertEqual(os.environ["ACR_PULL_PASSWORD"], "")
        prompt.assert_called_once()
        self.assertIn(self.args.registry, prompt.call_args.args[0])
        self.assertNotIn("prompted-password", output.getvalue())
        self.assertFalse(any("prompted-password" in path.read_text() for path in self.state.rglob("*") if path.is_file()))

    def test_four_download_dispatch_and_setup_use_requested_count(self):
        self.args.pull_count = 4
        with patch.object(self.launcher, "prepare_cluster", return_value="local-node"):
            with patch.object(self.launcher, "command", return_value=""):
                with patch.object(self.launcher.pull, "run", return_value=0) as run:
                    with patch("sys.stdin", io.StringIO("synthetic-password\n")):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(self.launcher.execute(self.args), 0)
        self.assertEqual(run.call_args.kwargs["pull_count"], 4)
        self.assertEqual(run.call_args.kwargs["node_count"], 1)
        self.assertTrue(run.call_args.kwargs["start_immediately"])
        self.args.setup_only = True
        with patch.object(self.launcher, "prepare_cluster", return_value="local-node"):
            with patch.object(self.launcher, "check_workers") as check:
                self.assertEqual(self.launcher.execute(self.args), 0)
        check.assert_called_once_with("local-node", pull_count=4)

    def test_four_downloads_cannot_change_the_two_batch_workload(self):
        self.args.pull_count = 4
        self.args.two_batches = True
        with patch.object(self.launcher, "prepare_cluster") as prepare:
            with self.assertRaisesRegex(self.launcher.DownloadError, "five downloads per batch"):
                self.launcher.execute(self.args)
        prepare.assert_not_called()

    def test_three_downloads_are_rejected_before_cluster_setup(self):
        self.args.pull_count = 3
        with patch.object(self.launcher, "prepare_cluster") as prepare:
            with self.assertRaisesRegex(self.launcher.DownloadError, "four or five"):
                self.launcher.execute(self.args)
        prepare.assert_not_called()

    def test_local_cli_accepts_four_and_five_but_rejects_three(self):
        for count in (3, 4, 5):
            with self.subTest(count=count):
                arguments = [
                    "local.py", "--registry", self.args.registry, "--image", self.args.image,
                    "--username", self.args.username, "--pull-count", str(count),
                ]
                with patch("sys.argv", arguments), patch.object(self.launcher, "execute", return_value=0) as execute:
                    if count == 3:
                        with contextlib.redirect_stderr(io.StringIO()):
                            with self.assertRaises(SystemExit) as error:
                                self.launcher.main()
                        self.assertEqual(error.exception.code, 2)
                        execute.assert_not_called()
                    else:
                        self.assertEqual(self.launcher.main(), 0)
                        self.assertEqual(execute.call_args.args[0].pull_count, count)

    def test_setup_checks_five_pods_and_cleans_its_namespace(self):
        calls = []

        def command(*arguments, **kwargs):
            calls.append((arguments, kwargs))
            if arguments[:3] == ("kubectl", "get", "pods"):
                return json.dumps({"items": [{"spec": {"nodeName": "node"}} for _ in range(5)]})
            return ""

        with patch.object(self.launcher, "command", side_effect=command):
            with contextlib.redirect_stdout(io.StringIO()):
                self.launcher.check_workers("node")
        workload = next(kwargs["payload"] for _, kwargs in calls if kwargs.get("payload", {}).get("kind") == "List")
        self.assertEqual(len(workload["items"]), 5)
        self.assertTrue(all(pod["spec"]["nodeName"] == "node" for pod in workload["items"]))
        self.assertTrue(all(
            pod["spec"]["serviceAccountName"] == self.launcher.pull.SERVICE_ACCOUNT
            and not pod["spec"]["automountServiceAccountToken"]
            for pod in workload["items"]
        ))
        service_account_index = next(
            index for index, (args, _) in enumerate(calls) if args[:3] == ("kubectl", "create", "serviceaccount")
        )
        pods_index = next(
            index for index, (_, kwargs) in enumerate(calls) if kwargs.get("payload", {}).get("kind") == "List"
        )
        self.assertLess(service_account_index, pods_index)
        self.assertEqual(calls[-1][0][:3], ("kubectl", "delete", "namespace"))
        self.assertTrue(calls[-1][0][3].startswith("acr-five-check-"))

    def test_two_batches_launch_sixty_seconds_apart_before_waiting(self):
        clock = 0
        launches = []
        waits = []
        test = self

        class Process:
            def __init__(self, number):
                self.number = number
                self.returncode = None

            def wait(self, timeout=None):
                test.assertEqual(len(launches), 2, "Both batches must launch before waiting for completion")
                waits.append(self.number)
                self.returncode = 0
                return 0

            def poll(self):
                return self.returncode

        def launch(arguments, **kwargs):
            self.assertEqual(waits, [])
            self.assertEqual(kwargs, {"stdin": subprocess.DEVNULL, "start_new_session": True})
            self.assertNotIn("synthetic-password", arguments)
            launches.append((clock, arguments))
            return Process(len(launches))

        def sleep(seconds):
            nonlocal clock
            clock += seconds

        with patch.dict(os.environ, {"ACR_PULL_PASSWORD": "synthetic-password"}):
            with patch.object(self.launcher.subprocess, "Popen", side_effect=launch):
                with patch.object(self.launcher.time, "monotonic", side_effect=lambda: clock):
                    with patch.object(self.launcher.time, "sleep", side_effect=sleep):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(self.launcher.run_two_batches("registry/image@sha256:" + "a" * 64, "run"), 0)
        self.assertEqual([instant for instant, _ in launches], [0, 60])
        self.assertEqual(waits, [1, 2])
        for index, (_, arguments) in enumerate(launches, 1):
            self.assertIn("--local", arguments)
            self.assertIn("--start-immediately", arguments)
            self.assertEqual(arguments[arguments.index("--namespace") + 1], f"acr-five-pulls-batch-{index}")
            self.assertTrue(arguments[arguments.index("--result-file") + 1].endswith(f"run-batch-{index}.json"))

    def test_either_batch_failure_fails_the_parent(self):
        for exit_codes in ((1, 0), (0, 1)):
            with self.subTest(exit_codes=exit_codes):
                processes = []
                for code in exit_codes:
                    process = unittest.mock.Mock()
                    process.wait.return_value = code
                    process.poll.return_value = code
                    processes.append(process)
                with patch.object(self.launcher.subprocess, "Popen", side_effect=processes):
                    with patch.object(self.launcher.time, "sleep"):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(self.launcher.run_two_batches("image", "run"), 1)
                self.assertTrue(all(process.wait.called for process in processes))

    def test_second_launch_error_interrupts_the_first_batch(self):
        process = unittest.mock.Mock()
        process.pid = 12345
        process.poll.return_value = None
        process.wait.return_value = 130
        with patch.object(self.launcher.subprocess, "Popen", side_effect=[process, OSError("launch failed")]):
            with patch.object(self.launcher.time, "sleep"):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(OSError):
                        self.launcher.run_two_batches("image", "run")
        process.send_signal.assert_called_once_with(self.launcher.signal.SIGINT)
        process.wait.assert_called_once_with(timeout=60)
        process.kill.assert_not_called()

    def test_two_batch_dispatch_reuses_credentials_and_checks_namespaces(self):
        self.args.two_batches = True
        calls = []

        def command(*arguments, **kwargs):
            calls.append(arguments)
            return ""

        def run(image, run_id):
            self.assertEqual(image, f"{self.args.registry}/{self.args.image}")
            self.assertEqual(os.environ["ACR_PULL_PASSWORD"], "synthetic-password")
            self.assertTrue(run_id)
            return 0

        with patch.object(self.launcher, "prepare_cluster", return_value="local-node"):
            with patch.object(self.launcher, "command", side_effect=command):
                with patch.object(self.launcher, "run_two_batches", side_effect=run) as batches:
                    with patch.object(self.launcher.pull, "run") as single:
                        with patch("sys.stdin", io.StringIO("synthetic-password\n")):
                            with contextlib.redirect_stdout(io.StringIO()):
                                self.assertEqual(self.launcher.execute(self.args), 0)
        batches.assert_called_once()
        single.assert_not_called()
        checked = [args[3] for args in calls if args[:3] == ("kubectl", "get", "namespace")]
        self.assertEqual(checked, [
            "acr-five-pulls", "acr-five-pulls-batch-1", "acr-five-pulls-batch-2",
            "acr-five-pulls-batch-1", "acr-five-pulls-batch-2",
        ])

    def test_stopped_kind_node_is_started_before_exporting_kubeconfig(self):
        node = f"{self.launcher.CLUSTER}-control-plane"
        for initial_state in ("created", "configured", "exited", "stopped", "running"):
            with self.subTest(initial_state=initial_state):
                calls = []
                state = initial_state

                def run(arguments, **kwargs):
                    nonlocal state
                    calls.append(arguments)
                    if arguments[:2] == ("podman", "info"):
                        output = "4.9.3"
                    elif arguments == ("kind", "get", "clusters"):
                        output = self.launcher.CLUSTER
                    elif arguments[:3] == ("kind", "get", "nodes"):
                        output = node
                    elif arguments[:2] == ("podman", "inspect"):
                        output = state
                    elif arguments[0] == "systemd-run":
                        self.assertEqual(arguments[-3:], ("podman", "start", node))
                        state = "running"
                        output = node
                    elif arguments[:3] == ("kind", "export", "kubeconfig"):
                        self.assertEqual(state, "running")
                        Path(os.environ["KUBECONFIG"]).touch()
                        output = ""
                    elif arguments == ("kubectl", "config", "current-context"):
                        output = self.launcher.CONTEXT
                    elif "--raw=/readyz" in arguments:
                        output = "ok"
                    elif "--for=condition=Ready" in arguments:
                        output = f"node/{node} condition met"
                    elif arguments[:4] == ("kubectl", "--request-timeout=30s", "get", "nodes"):
                        output = json.dumps({"items": [{
                            "metadata": {"name": node, "labels": {"cri-resource-consume": "true"}},
                            "spec": {},
                        }]})
                    elif arguments[:2] == ("podman", "images") or arguments[:2] == ("podman", "exec"):
                        output = self.launcher.RUNNER_IMAGE
                    else:
                        self.fail(f"Unexpected command: {arguments}")
                    return subprocess.CompletedProcess(arguments, 0, output, "")

                with patch.object(self.launcher.subprocess, "run", side_effect=run):
                    with self.launcher.local_context(), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(self.launcher.prepare_cluster(), node)
                starts = [args for args in calls if args[0] == "systemd-run"]
                self.assertEqual(len(starts), 0 if initial_state == "running" else 1)

    def test_unexpected_nodes_and_paused_state_are_not_modified(self):
        node = f"{self.launcher.CLUSTER}-control-plane"
        for nodes, state in ((["other-node"], "stopped"), ([node], "paused"), ([node], "removing")):
            with self.subTest(nodes=nodes, state=state):
                def run(arguments, **kwargs):
                    if arguments[:3] == ("kind", "get", "nodes"):
                        return subprocess.CompletedProcess(arguments, 0, "\n".join(nodes), "")
                    if arguments[:2] == ("podman", "inspect"):
                        return subprocess.CompletedProcess(arguments, 0, state, "")
                    self.fail(f"Unexpected mutating command: {arguments}")

                with patch.object(self.launcher.subprocess, "run", side_effect=run):
                    with self.assertRaises(self.launcher.DownloadError):
                        self.launcher.ensure_node_running(node)

    def test_node_start_failure_is_not_hidden(self):
        node = f"{self.launcher.CLUSTER}-control-plane"
        failure = subprocess.CalledProcessError(125, ["podman", "start", node], stderr="cannot start")
        responses = [
            subprocess.CompletedProcess([], 0, node, ""),
            subprocess.CompletedProcess([], 0, "exited", ""),
            failure,
        ]
        with patch.object(self.launcher.subprocess, "run", side_effect=responses) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):
                    self.launcher.ensure_node_running(node)
        self.assertEqual(run.call_count, 3)

    def test_node_that_exits_after_start_fails_explicitly(self):
        node = f"{self.launcher.CLUSTER}-control-plane"
        responses = [subprocess.CompletedProcess([], 0, value, "") for value in (node, "exited", node, "exited")]
        with patch.object(self.launcher.subprocess, "run", side_effect=responses):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(self.launcher.DownloadError, "did not stay running"):
                    self.launcher.ensure_node_running(node)

    def test_api_startup_retries_then_becomes_ready(self):
        responses = [
            subprocess.CalledProcessError(1, ["kubectl"], stderr="connection refused"),
            subprocess.CompletedProcess([], 0, "ok\n", ""),
        ]
        output = io.StringIO()
        with patch.object(self.launcher.subprocess, "run", side_effect=responses) as run:
            with patch.object(self.launcher.time, "sleep") as sleep:
                with contextlib.redirect_stdout(output):
                    self.launcher.wait_for_api()
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(5)
        self.assertIn("connection refused", output.getvalue())

    def test_api_readiness_has_a_bounded_timeout(self):
        error = subprocess.CalledProcessError(1, ["kubectl"], stderr="connection refused")
        with patch.object(self.launcher.subprocess, "run", side_effect=error):
            with patch.object(self.launcher.time, "monotonic", side_effect=[0, 0, 180]):
                with patch.object(self.launcher.time, "sleep"):
                    with contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaisesRegex(self.launcher.DownloadError, "180s.*connection refused"):
                            self.launcher.wait_for_api()


if __name__ == "__main__":
    unittest.main()
