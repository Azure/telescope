"""Integration tests with an executable kubectl double; no cluster or credentials."""

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

import yaml

from collect_cl2_logs import since_timestamp


ROOT = Path(__file__).resolve().parents[1]
MOCK = r"""#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
root = pathlib.Path(os.environ["MOCK_ROOT"])
config = json.loads((root / "scenario.json").read_text())
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as out:
    out.write(json.dumps({"args": args, "time": time.monotonic(), "pid": os.getpid()}) + "\n")
def count(name):
    path = root / name
    value = int(path.read_text()) + 1 if path.exists() else 1
    path.write_text(str(value))
    return value
def hang():
    child = subprocess.Popen(["sleep", "60"])
    with (root / "descendants").open("a") as out:
        out.write(str(child.pid) + "\n")
    time.sleep(60)
if args[:2] == ["create", "namespace"]:
    sys.exit(0)
if args[0] == "apply":
    assert (root / "logs" / "collection-status.json").exists()
    sys.exit(config.get("apply_status", 0))
if args[:2] == ["get", "job"]:
    current = count("job-count")
    if config.get("hang_job"):
        hang()
    if current in config.get("job_errors", []) or config.get("job_error"):
        print("Job read failed", file=sys.stderr)
        sys.exit(1)
    if config.get("malformed_job"):
        print("not JSON")
        sys.exit()
    terminal = current >= config.get("terminal_after", 4)
    print(json.dumps({"metadata": {"name": "cl2"}, "spec": {"completions": config.get("expected_pods", 1)},
                     "status": {"conditions": [
        {"type": config.get("terminal", "Complete"), "status": "True", "reason": "MockResult"}
    ] if terminal else []}}))
elif args[:2] == ["get", "pods"]:
    current = int((root / "job-count").read_text())
    if config.get("pod_error"):
        print("Pod read failed", file=sys.stderr)
        sys.exit(1)
    if config.get("hang_pods"):
        hang()
    items = []
    if current >= config.get("discover_after", 1) and current < config.get("disappear_after", 999):
        for index in range(config.get("drivers", 1)):
            uid = f"uid-{index}"
            if current >= config.get("replace_after", 999):
                uid += "-replacement"
            terminated = current >= config.get("terminate_after", 999)
            state = {"terminated": {"exitCode": 7, "reason": "Error"}} if terminated else {"running": {}}
            items.append({"metadata": {"name": f"cl2-{index}", "uid": uid},
                          "spec": {"containers": [{"name": "cl2"}]},
                          "status": {"phase": "Failed" if terminated else "Running",
                                     "containerStatuses": [{"name": "cl2", "state": state}]}})
    print(json.dumps({"items": items}))
elif args[0] == "logs":
    follow = "--follow" in args
    if config.get("stream_error") or (not follow and config.get("final_error")):
        print("kubelet unavailable", file=sys.stderr)
        sys.exit(1)
    if (follow and config.get("hang_stream")) or (not follow and config.get("hang_final")):
        hang()
    if not config.get("no_timestamp"):
        for index in range(config.get("lines", 1)):
            print("2026-11-12T00:00:05.123456789Z DRIVER-ONLY " + "x" * config.get("line_bytes", 10))
        sys.stdout.flush()
    else:
        print("unparseable driver record", flush=True)
    if follow and not config.get("disconnect"):
        hang()
"""


class LiveCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".cl2-test-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        executable = self.root / "kubectl"
        executable.write_text(MOCK)
        executable.chmod(0o755)
        self.environment = {**os.environ, "MOCK_ROOT": str(self.root),
                            "PATH": f"{self.root}:{os.environ['PATH']}"}

    def start(self, config, *extra):
        (self.root / "scenario.json").write_text(json.dumps(config))
        return subprocess.Popen(
            ["bash", str(ROOT / "scripts/run_cluster_loader_2.sh"),
             "--namespace", "clusterloader2", "--manifest", "unused.yaml",
             "--log-directory", str(self.root / "logs"),
             "--poll-interval", "0.15", "--request-timeout", "0.1",
             "--command-timeout", "0.3", "--job-error-budget", "0.6",
             "--shutdown-grace", "0.5", "--stream-lifetime", "5",
             "--retry-base", "0.03", *extra],
            env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def finish(self, process):
        try:
            output, error = process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            self.fail("collector exceeded outer test deadline")
        self.assertTrue((self.root / "logs/collection-status.json").exists(), output + error)
        status = json.loads((self.root / "logs/collection-status.json").read_text())
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assert_owned_processes_stopped(calls)
        return process.returncode, output, error, status, calls

    def assert_owned_processes_stopped(self, calls):
        pids = [call["pid"] for call in calls]
        descendants = self.root / "descendants"
        if descendants.exists():
            pids += [int(pid) for pid in descendants.read_text().splitlines()]
        for pid in pids:
            path = Path(f"/proc/{pid}/stat")
            if path.exists():
                # Orphan zombies are reaped by init, not by the collector.
                self.assertEqual(path.read_text().split()[2], "Z", f"owned process {pid} still running")

    def run_case(self, config, *extra):
        return self.finish(self.start(config, *extra))

    def test_six_delayed_drivers_keep_healthy_streams_and_separate_stderr(self):
        code, output, error, status, calls = self.run_case({"drivers": 6, "discover_after": 2,
                                                         "terminal_after": 6})
        self.assertEqual(code, 0)
        self.assertEqual(len(status["drivers"]), 6)
        self.assertEqual(len(list((self.root / "logs").glob("cl2-*.log"))), 6)
        self.assertNotIn("DRIVER-ONLY", output + error)
        self.assertEqual([driver["streamAttempts"] for driver in status["drivers"]], [1] * 6)
        self.assertEqual([driver["finalFetch"] for driver in status["drivers"]], ["ok"] * 6)
        for driver in status["drivers"]:
            self.assertIn("DRIVER-ONLY", (self.root / "logs" / driver["file"]).read_text())
        self.assertEqual(sum(call["args"][:2] == ["get", "pods"] for call in calls), 6)
        self.assertTrue(all("-o" not in call["args"] or "json" in call["args"] for call in calls))

    def test_reconnect_uses_persisted_timestamp_overlap(self):
        code, _, error, status, calls = self.run_case({"disconnect": True, "terminal_after": 5})
        streams = [call["args"] for call in calls if "--follow" in call["args"]]
        self.assertEqual(code, 0)
        self.assertGreater(len(streams), 1)
        self.assertIn("--tail=2000", streams[0])
        for command in streams[1:]:
            self.assertEqual(command[command.index("--since-time") + 1], "2026-11-12T00:00:03Z")
            self.assertNotIn("--tail=2000", command)
        self.assertIn("stream interrupted", error)
        self.assertEqual(status["status"], "partial")

    def test_large_outputs_are_streamed_without_blocking_monitor(self):
        code, _, _, status, _ = self.run_case({"lines": 3000, "line_bytes": 1000, "terminal_after": 6})
        self.assertEqual(code, 0)
        self.assertGreater(status["drivers"][0]["bytes"], 3_000_000)
        self.assertEqual(status["drivers"][0]["streamAttempts"], 1)

    def test_uid_replacement_never_mixes_files_and_missing_is_explicit(self):
        code, _, error, status, _ = self.run_case({"replace_after": 3, "terminal_after": 5})
        self.assertEqual(code, 0)
        self.assertEqual([driver["uid"] for driver in status["drivers"]], ["uid-0", "uid-0-replacement"])
        self.assertEqual(len({driver["file"] for driver in status["drivers"]}), 2)
        self.assertTrue(status["drivers"][0]["disappeared"])
        self.assertIn("Pod disappeared", error)

    def test_disappearance_preserves_logs_without_final_refetch(self):
        code, _, _, status, calls = self.run_case({"disappear_after": 3, "terminal_after": 5})
        self.assertEqual(code, 0)
        self.assertEqual(status["drivers"][0]["finalFetch"], "unavailable")
        self.assertFalse(any(call["args"][0] == "logs" and "--follow" not in call["args"] for call in calls))

    def test_terminated_pod_is_fetched_once_with_exit_reason(self):
        code, _, _, status, calls = self.run_case({"terminate_after": 1})
        self.assertEqual(code, 0)
        logs = [call["args"] for call in calls if call["args"][0] == "logs"]
        self.assertEqual(len(logs), 1)
        self.assertNotIn("--follow", logs[0])
        self.assertIn("--limit-bytes=4194304", logs[0])
        self.assertEqual(status["drivers"][0]["state"]["terminated"], {"exitCode": 7, "reason": "Error"})

    def test_success_and_failure_without_pods(self):
        for terminal, expected in (("Complete", 0), ("Failed", 1)):
            with self.subTest(terminal=terminal):
                # Each run gets a fresh artifact directory.
                self.setUp()
                code, _, error, status, _ = self.run_case({"drivers": 0, "terminal": terminal,
                                                          "terminal_after": 1})
                self.assertEqual(code, expected)
                self.assertEqual(status["benchmarkExitCode"], expected)
                self.assertEqual(status["status"], "partial")
                self.assertIn("No driver pods discovered", error)

    def test_apply_failure_has_artifacts_and_preserves_failure(self):
        code, _, _, status, calls = self.run_case({"apply_status": 7})
        self.assertEqual(code, 1)
        self.assertEqual(status["benchmarkExitCode"], 1)
        self.assertFalse(any(call["args"][0] == "get" for call in calls))
        self.assertEqual(json.loads((self.root / "logs/job.json").read_text()), None)
        self.assertTrue((self.root / "logs/pods.json").exists())

    def test_hanging_job_respects_elapsed_failure_budget(self):
        started = time.monotonic()
        code, _, error, _, calls = self.run_case({"hang_job": True, "drivers": 0})
        self.assertEqual(code, 1)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn("budget exhausted", error)
        self.assertEqual(sum(call["args"][:2] == ["get", "job"] for call in calls), 2)

    def test_intermittent_job_errors_reset_continuous_budget(self):
        code, _, _, _, calls = self.run_case({"job_errors": [1, 2, 4, 5], "terminal_after": 7})
        self.assertEqual(code, 0)
        self.assertEqual(sum(call["args"][:2] == ["get", "job"] for call in calls), 7)

    def test_malformed_job_is_not_success(self):
        code, _, error, status, _ = self.run_case({"malformed_job": True, "drivers": 0})
        self.assertEqual(code, 1)
        self.assertIn("Invalid job JSON", error)
        self.assertEqual(status["status"], "partial")

    def test_hanging_six_final_logs_share_one_shutdown_deadline(self):
        started = time.monotonic()
        code, _, error, status, _ = self.run_case({"drivers": 6, "hang_final": True,
                                                "terminal": "Failed", "terminal_after": 2},
                                               "--command-timeout", "3")
        self.assertEqual(code, 1)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(status["benchmarkExitCode"], 1)
        self.assertIn("deadline", error)
        self.assertEqual([driver["finalFetch"] for driver in status["drivers"]], ["partial"] * 6)

    def test_live_lifetime_timeout_is_not_benchmark_failure(self):
        code, _, error, status, _ = self.run_case({"hang_stream": True}, "--stream-lifetime", "0.1")
        self.assertEqual(code, 0)
        self.assertIn("not a driver failure", error)
        self.assertIn("no persisted timestamp", error)
        self.assertEqual(status["status"], "partial")

    def test_no_timestamp_and_collector_errors_are_partial(self):
        code, _, error, status, _ = self.run_case({"no_timestamp": True, "disconnect": True})
        self.assertEqual(code, 0)
        self.assertIn("no persisted timestamp", error)
        self.assertEqual(status["drivers"][0]["finalFetch"], "partial")

    def test_failed_logs_back_off_instead_of_poll_restarting(self):
        code, _, error, status, calls = self.run_case({"stream_error": True, "terminal_after": 8},
                                                    "--retry-base", "0.1")
        streams = [call for call in calls if "--follow" in call["args"]]
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(streams), 3)
        self.assertLess(len(streams), 6)
        self.assertGreaterEqual(streams[2]["time"] - streams[1]["time"], 0.2)
        self.assertIn("kubelet unavailable", error)
        self.assertEqual(status["drivers"][0]["finalFetch"], "partial")

    def test_signals_kill_owned_descendants_and_preserve_signal_exit(self):
        for number in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=number):
                self.setUp()
                process = self.start({"terminal_after": 100, "hang_final": True})
                end = time.monotonic() + 3
                while not (self.root / "descendants").exists() and time.monotonic() < end:
                    time.sleep(0.01)
                self.assertTrue((self.root / "descendants").exists())
                process.send_signal(number)
                code, _, _, status, _ = self.finish(process)
                self.assertEqual(code, 128 + number)
                self.assertEqual(status["benchmarkExitCode"], 128 + number)

    def test_pod_listing_failure_does_not_override_job_failure(self):
        code, _, error, status, _ = self.run_case({"pod_error": True, "terminal": "Failed"})
        self.assertEqual(code, 1)
        self.assertIn("Pod read failed", error)
        self.assertEqual(status["status"], "partial")

    def test_hanging_terminal_pod_query_is_inside_shared_grace(self):
        started = time.monotonic()
        code, _, error, status, _ = self.run_case(
            {"hang_pods": True, "terminal_after": 1}, "--command-timeout", "3")
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - started, 1)
        self.assertIn("deadline", error)
        self.assertFalse(status["podsSnapshotAvailable"])

    def test_signal_during_failed_job_shutdown_does_not_overwrite_failure(self):
        process = self.start({"terminal": "Failed", "terminal_after": 1, "hang_final": True})
        end = time.monotonic() + 3
        while not (self.root / "descendants").exists() and time.monotonic() < end:
            time.sleep(0.01)
        self.assertTrue((self.root / "descendants").exists())
        process.send_signal(signal.SIGTERM)
        code, _, _, status, _ = self.finish(process)
        self.assertEqual(code, 1)
        self.assertEqual(status["benchmarkExitCode"], 1)

    def test_disk_write_error_is_visible_without_changing_benchmark_result(self):
        process = self.start({"discover_after": 3, "terminal_after": 5})
        end = time.monotonic() + 3
        while not (self.root / "logs").exists() and time.monotonic() < end:
            time.sleep(0.01)
        (self.root / "logs/cl2-0--uid-0--cl2.log").symlink_to("/dev/full")
        code, _, error, status, _ = self.finish(process)
        self.assertEqual(code, 0)
        self.assertIn("No space left on device", error)
        self.assertEqual(status["drivers"][0]["finalFetch"], "error")
        self.assertEqual(status["drivers"][0]["lastTimestamp"], None)
        self.assertEqual(status["status"], "partial")

    def test_missing_expected_driver_is_explicit(self):
        code, _, error, status, _ = self.run_case({"expected_pods": 6})
        self.assertEqual(code, 0)
        self.assertIn("fewer pods than Job completions (6)", error)
        self.assertEqual(status["status"], "partial")

    def test_final_byte_cap_enforced_even_if_server_ignores_limit(self):
        code, _, _, status, _ = self.run_case({"terminate_after": 1, "lines": 500},
                                             "--final-bytes", "1024")
        self.assertEqual(code, 0)
        self.assertEqual(status["drivers"][0]["bytes"], 1024)
        self.assertEqual(status["drivers"][0]["finalFetch"], "partial")


class PipelineWiringTests(unittest.TestCase):
    def test_h8_only_artifact_before_cleanup_and_legacy_h2_h4(self):
        pipeline = yaml.safe_load(
            (ROOT / "kcl/ccp_team/hyperscale_apiserver_executing_seats/pipeline.yaml").read_text()
        )
        for stage in pipeline["stages"]:
            steps = stage["jobs"][0]["steps"]
            run = next(index for index, step in enumerate(steps)
                       if step.get("displayName") == "Run cluster loader 2")
            script = steps[run]["inputs"]["inlineScript"]
            if stage["stage"] == "H8":
                self.assertIn("run_cluster_loader_2.sh", script)
                self.assertIn("exec bash", script)
                self.assertIn("--poll-interval 60", script)
                self.assertNotIn("Print cl2 pod logs", str(steps))
                self.assertEqual(steps[run + 1]["task"], "PublishPipelineArtifact@1")
                self.assertEqual(steps[run + 1]["condition"], "always()")
                self.assertEqual(steps[run + 1]["inputs"], {
                    "targetPath": "$(Pipeline.Workspace)/cl2-logs/$(Build.BuildId)/H8/$(System.JobAttempt)",
                    "artifact": "cl2-logs-H8",
                })
            else:
                self.assertNotIn("run_cluster_loader_2.sh", script)
                self.assertIn("sleep 30", script)
                self.assertEqual(steps[run + 1]["displayName"], "Print cl2 pod logs")
            cleanup = steps[run + 2]
            self.assertEqual(cleanup["condition"], "always()")
            self.assertEqual(cleanup["inputs"]["inlineScript"], (
                "set -exo pipefail\n"
                'python3 "$(Build.SourcesDirectory)/kcl/lib/steps/azure/resource_group.py" delete \\\n'
                '  --resource-group "$(RUN_ID)" \\\n'
                '  --subscription "b8ceb4e5-f05b-4562-a9f5-14acb1f24219" \\\n'
                "  --timeout-seconds 2700 \\\n"
                "  --poll-interval-seconds 30\n"
            ))

    def test_timestamp_overlap_rounds_down(self):
        self.assertEqual(since_timestamp("2026-11-12T00:00:05.123456789Z"), "2026-11-12T00:00:03Z")
        self.assertEqual(since_timestamp("2026-11-12T01:00:05+01:00"), "2026-11-12T00:00:03Z")
        with self.assertRaises(ValueError):
            since_timestamp("20261112")


if __name__ == "__main__":
    unittest.main()
