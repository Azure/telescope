"""Offline regression tests for the five-node Kubernetes pull runner."""

import argparse
import base64
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pull


IMAGE = "williamjcusaue1.azurecr-test.io/test1gb@sha256:" + "a" * 64


class PullTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.args = argparse.Namespace(
            image=IMAGE,
            node_pool="pullpool",
            output=str(Path(self.directory.name) / "results.json"),
            run_id="123-job",
            run_url="https://dev.azure.com/example/results/123",
            pipeline="ACR Kubernetes Five Cold Pulls",
        )
        self.clock = 0
        self.calls = []
        self.pods = []
        self.events = []
        self.mode = "success"
        self.fail_command = None
        self.nodes = [{
            "metadata": {"name": f"worker-{index}"},
            "spec": {},
            "status": {
                "conditions": [{"type": "Ready", "status": "True"}],
                "nodeInfo": {"kubeletVersion": "v1.35.0", "containerRuntimeVersion": "containerd://2.0"},
            },
        } for index in reversed(range(5))]
        patches = [
            patch.dict("os.environ", {
                "ACR_PULL_USERNAME": "pull-user",
                "ACR_PULL_PASSWORD": "secret-not-for-logs",
            }),
            patch("pull.subprocess.run", side_effect=self.fake_subprocess),
            patch("pull.time.monotonic", side_effect=lambda: self.clock),
            patch("pull.time.sleep", side_effect=self.sleep),
            patch("pull.NODE_READY_TIMEOUT_SECONDS", 10),
            patch("pull.PULL_TIMEOUT_SECONDS", 10),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def sleep(self, seconds):
        self.clock += seconds

    def fake_subprocess(self, command, **kwargs):
        self.assertEqual(command[:2], ["kubectl", "--request-timeout=30s"])
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["timeout"], 45)
        arguments = command[2:]
        payload = json.loads(kwargs["input"]) if kwargs["input"] is not None else None
        self.calls.append((arguments, payload))
        if arguments[:len(self.fail_command or [])] == self.fail_command:
            raise subprocess.CalledProcessError(1, command, stderr="Simulated API failure")
        if arguments[:2] == ["get", "nodes"]:
            output = {"items": self.nodes}
        elif arguments[:2] == ["create", "namespace"]:
            output = {}
        elif arguments == ["create", "-f", "-"]:
            if payload["kind"] == "List":
                self.pods = copy.deepcopy(payload["items"])
                for pod in self.pods:
                    pod["metadata"]["uid"] = pod["metadata"]["name"] + "-uid"
                    pod["status"] = {
                        "phase": "Succeeded",
                        "containerStatuses": [{
                            "name": "image-pull",
                            "imageID": IMAGE,
                            "state": {"terminated": {"exitCode": 0}},
                        }],
                    }
                    for reason, timestamp in (
                        ("Pulling", "2026-10-18T00:00:00Z"),
                        ("Pulled", "2026-10-18T00:00:03Z"),
                    ):
                        self.events.append({
                            "involvedObject": {"uid": pod["metadata"]["uid"]},
                            "reason": reason,
                            "message": "Successfully pulled image" if reason == "Pulled" else "Pulling image",
                            "firstTimestamp": timestamp,
                            "count": 1,
                        })
                self.modify_observations()
                if self.mode == "partial-create":
                    raise subprocess.CalledProcessError(1, command, stderr="Partial create failure")
            output = {}
        elif arguments[:2] == ["get", "pods"]:
            output = {"items": self.pods}
        elif arguments[:2] == ["get", "events"]:
            if self.mode == "late-observation":
                self.clock = 11
            output = {"items": self.events}
        elif arguments[:2] == ["delete", "namespace"]:
            output = {}
        else:
            self.fail(f"Unexpected command: {arguments}")
        return subprocess.CompletedProcess(command, 0, json.dumps(output), "")

    def modify_observations(self):
        if self.mode == "cache-hit":
            self.events[1]["message"] = "Container image already present on machine"
        elif self.mode == "retry":
            self.events[0]["count"] = 2
        elif self.mode == "failure-then-success":
            self.events.append({
                "involvedObject": {"uid": self.pods[0]["metadata"]["uid"]},
                "reason": "Failed",
                "message": "Failed to pull image: unauthorized",
            })
        elif self.mode == "backoff":
            self.pods[0]["status"]["containerStatuses"][0]["state"] = {
                "waiting": {"reason": "ImagePullBackOff"}
            }
        elif self.mode == "pending":
            self.events = [event for event in self.events if event["reason"] == "Pulling"]
        elif self.mode == "stale-events":
            for event in self.events:
                event["involvedObject"]["uid"] += "-old"
        elif self.mode == "wrong-node":
            self.pods[0]["spec"]["nodeName"] = "system-node"
        elif self.mode == "wrong-image":
            self.pods[0]["spec"]["containers"][0]["image"] = "other:latest"
        elif self.mode == "missing-timestamp":
            del self.events[1]["firstTimestamp"]
        elif self.mode == "negative-duration":
            self.events[1]["firstTimestamp"] = "2026-10-17T23:59:59Z"

    def execute(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = pull.run_test(self.args)
        report = json.loads(Path(self.args.output).read_text(encoding="utf-8"))
        for output in (stdout.getvalue(), stderr.getvalue(), json.dumps(report)):
            self.assertNotIn("secret-not-for-logs", output)
        if status:
            self.assertIn("IMAGE PULL TEST FAILED", stderr.getvalue())
            self.assertEqual(report["result"]["status"], "failed")
        return status, report

    def test_five_cold_pulls_on_five_distinct_nodes(self):
        status, report = self.execute()
        self.assertEqual(status, 0)
        self.assertEqual(report["run_id"], "123-job")
        self.assertEqual(report["run_url"], self.args.run_url)
        self.assertEqual(report["pipeline"], self.args.pipeline)
        result = report["result"]
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["image"], IMAGE)
        self.assertEqual(result["successful_pull_count"], 5)
        self.assertEqual(result["expected_pull_count"], 5)
        self.assertEqual(result["errors"], [])
        manifests = [payload for _, payload in self.calls if payload and payload["kind"] == "List"]
        self.assertEqual(len(manifests), 1)
        self.assertEqual(len(manifests[0]["items"]), 5)
        for index, pod in enumerate(manifests[0]["items"]):
            self.assertEqual(pod["metadata"]["name"], f"pull-{index + 1}")
            self.assertEqual(pod["spec"]["nodeName"], f"worker-{index}")
            self.assertEqual(pod["spec"]["restartPolicy"], "Never")
            self.assertFalse(pod["spec"]["automountServiceAccountToken"])
            self.assertEqual(pod["spec"]["containers"][0]["image"], IMAGE)
            self.assertEqual(pod["spec"]["containers"][0]["imagePullPolicy"], "Always")
            self.assertEqual(result["pulls"][index]["status"], "succeeded")
            self.assertEqual(result["pulls"][index]["pull_duration_seconds"], 3)
        self.assertEqual(self.calls[-1][0], [
            "delete", "namespace", "acr-five-pulls", "--wait=false"
        ])

    def test_secret_only_goes_through_stdin(self):
        self.execute()
        secret = next(payload for _, payload in self.calls if payload and payload["kind"] == "Secret")
        config = json.loads(base64.b64decode(secret["data"][".dockerconfigjson"]))
        auth = config["auths"]["williamjcusaue1.azurecr-test.io"]["auth"]
        self.assertEqual(base64.b64decode(auth).decode(), "pull-user:secret-not-for-logs")
        for arguments, _ in self.calls:
            self.assertNotIn("secret-not-for-logs", " ".join(arguments))
        self.assertEqual(sorted(path.name for path in Path(self.directory.name).iterdir()), ["results.json"])

    def test_rejects_missing_or_unexpanded_credentials_before_api_calls(self):
        for value in ("", "$(ACR_PULL_PASSWORD)"):
            with self.subTest(value=value), patch.dict("os.environ", {"ACR_PULL_PASSWORD": value}):
                status, report = self.execute()
                self.assertEqual(status, 1)
                self.assertEqual(self.calls, [])
                self.assertIn("secret pipeline", report["result"]["errors"][0])

    def test_requires_digest_instead_of_mutable_tag(self):
        self.args.image = "williamjcusaue1.azurecr-test.io/test1gb:latest"
        status, report = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(self.calls, [])
        self.assertIn("sha256", report["result"]["errors"][0])

    def test_rejects_six_workers(self):
        self.nodes.append(copy.deepcopy(self.nodes[0]))
        status, report = self.execute()
        self.assertEqual(status, 1)
        self.assertIn("found 6", report["result"]["errors"][0])
        self.assertEqual(len(self.calls), 1)

    def test_waits_for_all_five_workers_and_times_out(self):
        self.nodes[0]["status"]["conditions"][0]["status"] = "False"
        status, report = self.execute()
        self.assertEqual(status, 1)
        self.assertIn("Ready worker nodes", report["result"]["errors"][0])
        self.assertTrue(all(arguments[:2] == ["get", "nodes"] for arguments, _ in self.calls))

    def test_observed_pull_errors_are_not_hidden_by_later_success(self):
        for mode in ("cache-hit", "retry", "failure-then-success", "backoff"):
            with self.subTest(mode=mode):
                self.mode = mode
                self.events = []
                status, report = self.execute()
                self.assertEqual(status, 1)
                self.assertEqual(report["result"]["successful_pull_count"], 4)
                self.assertEqual(report["result"]["pulls"][0]["status"], "failed")

    def test_missing_or_stale_events_do_not_count_as_success(self):
        for mode in ("pending", "stale-events"):
            with self.subTest(mode=mode):
                self.clock = 0
                self.events = []
                self.mode = mode
                status, report = self.execute()
                self.assertEqual(status, 1)
                self.assertEqual(report["result"]["successful_pull_count"], 0)
                self.assertIn("Timed out", report["result"]["errors"][0])
                self.assertEqual(len(report["result"]["pulls"]), 5)

    def test_rejects_wrong_placement_or_image(self):
        for mode, expected in (("wrong-node", "assigned worker"), ("wrong-image", "pinned image")):
            with self.subTest(mode=mode):
                self.events = []
                self.mode = mode
                status, report = self.execute()
                self.assertEqual(status, 1)
                self.assertIn(expected, report["result"]["errors"][0])

    def test_invalid_timing_fails_explicitly(self):
        for mode, expected in (("missing-timestamp", "timestamp"), ("negative-duration", "Negative")):
            with self.subTest(mode=mode):
                self.events = []
                self.mode = mode
                status, report = self.execute()
                self.assertEqual(status, 1)
                self.assertIn(expected, report["result"]["errors"][0])

    def test_late_observation_is_not_a_passing_run(self):
        self.mode = "late-observation"
        status, report = self.execute()
        self.assertEqual(status, 1)
        self.assertIn("deadline", report["result"]["errors"][0])

    def test_existing_namespace_is_never_deleted(self):
        self.fail_command = ["create", "namespace"]
        status, report = self.execute()
        self.assertEqual(status, 1)
        self.assertIn("Simulated API failure", report["result"]["errors"])
        self.assertFalse(any(arguments[:2] == ["delete", "namespace"] for arguments, _ in self.calls))

    def test_partial_pod_creation_still_cleans_up(self):
        self.mode = "partial-create"
        status, report = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(len(report["result"]["pulls"]), 5)
        self.assertEqual(self.calls[-1][0][:2], ["delete", "namespace"])

    def test_cleanup_failure_fails_the_run(self):
        self.fail_command = ["delete", "namespace"]
        status, report = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(report["result"]["successful_pull_count"], 5)
        self.assertIn("Namespace cleanup failed", report["result"]["errors"][0])


if __name__ == "__main__":
    unittest.main()
