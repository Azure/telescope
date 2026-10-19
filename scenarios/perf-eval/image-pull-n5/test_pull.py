"""Offline tests for Kubernetes-hosted five-copy image downloads."""

import argparse
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pull


IMAGE = "williamjcusaue1.azurecr-test.io/test1gb@sha256:" + "a" * 64
RUNNER = "quay.io/skopeo/stable:v1.20.0"


class TestFiveDownloads(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.result_file = Path(temporary.name) / "results.json"
        self.args = argparse.Namespace(
            image=IMAGE, runner_image=RUNNER, result_file=str(self.result_file),
            run_id="test-5", run_url="https://example/run/test-5",
        )
        self.calls = []
        self.clock = 0
        self.mode = "success"
        self.fail_command = None
        self.pods = []
        self.nodes = [{
            "metadata": {"name": f"worker-{index}"},
            "spec": {},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        } for index in range(5)]
        for patcher in (
            patch.dict(os.environ, {"ACR_PULL_USERNAME": "williamjcusaue1", "ACR_PULL_PASSWORD": "secret-value"}),
            patch("pull.subprocess.run", side_effect=self.command),
            patch("pull.time.monotonic", side_effect=lambda: self.clock),
            patch("pull.time.sleep", side_effect=self.sleep),
            patch("pull.TIMEOUT_SECONDS", 10),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def sleep(self, seconds):
        self.clock += seconds

    def command(self, command, **kwargs):
        self.assertEqual(command[:2], ["kubectl", "--request-timeout=30s"])
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["timeout"], 45)
        arguments = command[2:]
        payload = json.loads(kwargs["input"]) if kwargs["input"] else None
        self.calls.append((arguments, payload))
        if self.fail_command and arguments[:len(self.fail_command)] == self.fail_command:
            raise subprocess.CalledProcessError(1, command, stderr="Sensitive diagnostic must not be published")
        if arguments[:2] == ["get", "nodes"]:
            output = {"items": self.nodes}
        elif arguments[:2] == ["create", "namespace"]:
            output = {}
        elif arguments == ["create", "-f", "-"]:
            output = {}
            if payload["kind"] == "List":
                self.pods = payload["items"]
                for pod in self.pods:
                    pod["status"] = {
                        "phase": "Succeeded",
                        "containerStatuses": [{
                            "name": "pull", "restartCount": 0,
                            "state": {"terminated": {"exitCode": 0}},
                        }],
                    }
                if self.mode == "pending":
                    self.pods[0]["status"]["phase"] = "Pending"
                elif self.mode == "failure":
                    self.pods[0]["status"]["phase"] = "Failed"
                elif self.mode == "wrong-node":
                    self.pods[0]["spec"]["nodeName"] = "system-node"
                elif self.mode == "restart":
                    self.pods[0]["status"]["containerStatuses"][0]["restartCount"] = 1
                elif self.mode == "runner-image-failure":
                    self.pods[0]["status"] = {
                        "phase": "Pending",
                        "containerStatuses": [{"name": "pull", "state": {"waiting": {"reason": "ImagePullBackOff"}}}],
                    }
                elif self.mode == "partial-create":
                    raise subprocess.CalledProcessError(1, command)
        elif arguments[:2] == ["get", "pods"]:
            output = {"items": self.pods}
        elif arguments[0] == "logs":
            output = {
                "started_at": "2026-10-19T00:00:00Z",
                "finished_at": "2026-10-19T00:00:03Z",
                "duration_seconds": 3,
                "downloaded_bytes": pull.LAYER_BYTES + 1024,
            }
            if self.mode == "short-download":
                output["downloaded_bytes"] = pull.LAYER_BYTES - 1
            elif self.mode == "negative-duration":
                output["duration_seconds"] = -1
            elif self.mode == "late":
                self.clock = 11
            elif self.mode == "bad-json":
                return subprocess.CompletedProcess(command, 0, "invalid-json", "")
        elif arguments[:2] == ["delete", "namespace"]:
            output = {}
        else:
            self.fail(f"Unexpected command: {arguments}")
        return subprocess.CompletedProcess(command, 0, json.dumps(output), "")

    def execute(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = pull.run(self.args)
        report = json.loads(self.result_file.read_text(encoding="utf-8"))
        text = stdout.getvalue() + stderr.getvalue() + self.result_file.read_text()
        self.assertNotIn("secret-value", text)
        self.assertNotIn("Sensitive diagnostic", text)
        if code:
            self.assertEqual(report["status"], "failure")
            self.assertIn("IMAGE DOWNLOAD FAILED:", stderr.getvalue())
        return code, report

    def test_five_unique_worker_pods_and_success_results(self):
        code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["image"], IMAGE)
        self.assertEqual(report["run_id"], "test-5")
        workload = next(payload for _, payload in self.calls if payload and payload["kind"] == "List")
        self.assertEqual(len(workload["items"]), 5)
        for index, pod in enumerate(workload["items"]):
            self.assertEqual(pod["metadata"]["name"], f"pull-{index+1}")
            self.assertEqual(pod["spec"]["nodeName"], f"worker-{index}")
            self.assertEqual(pod["spec"]["restartPolicy"], "Never")
            self.assertEqual(pod["spec"]["containers"][0]["image"], RUNNER)
            self.assertEqual(pod["spec"]["containers"][0]["env"], [{"name": "TARGET_IMAGE", "value": IMAGE}])
            self.assertEqual(pod["spec"]["volumes"][1], {"name": "download", "emptyDir": {"sizeLimit": "2Gi"}})
            self.assertEqual(report["pulls"][index]["duration_seconds"], 3)
        self.assertEqual(self.calls[-1][0], ["delete", "namespace", "acr-five-pulls", "--wait=false"])
        self.assertEqual(sum(arguments[0] == "logs" for arguments, _ in self.calls), 5)

    def test_credentials_only_go_to_secret_stdin(self):
        self.execute()
        secret = next(payload for _, payload in self.calls if payload and payload["kind"] == "Secret")
        config = json.loads(base64.b64decode(secret["data"][".dockerconfigjson"]))
        auth = config["auths"]["williamjcusaue1.azurecr-test.io"]["auth"]
        self.assertEqual(base64.b64decode(auth).decode(), "williamjcusaue1:secret-value")
        for arguments, _ in self.calls:
            self.assertNotIn("secret-value", " ".join(arguments))

    def test_missing_or_unexpanded_password_fails_before_api_calls(self):
        for value in ("", "$(ACR_PULL_PASSWORD)"):
            with self.subTest(value=value), patch.dict(os.environ, {"ACR_PULL_PASSWORD": value}):
                code, _ = self.execute()
                self.assertEqual(code, 1)
                self.assertEqual(self.calls, [])

    def test_mutable_tag_rejected(self):
        self.args.image = "williamjcusaue1.azurecr-test.io/test1gb:latest"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn("immutable", report["errors"][0])
        self.assertEqual(self.calls, [])

    def test_wrong_node_count_or_readiness_rejected(self):
        original = self.nodes
        for count in (4, 6):
            self.nodes = (original + [original[0]])[:count]
            code, _ = self.execute()
            self.assertEqual(code, 1)
        self.nodes = original
        self.nodes[0]["status"]["conditions"][0]["status"] = "False"
        code, _ = self.execute()
        self.assertEqual(code, 1)
        self.assertTrue(all(arguments[:2] == ["get", "nodes"] for arguments, _ in self.calls))

    def test_errors_restarts_wrong_placement_and_invalid_metrics_fail(self):
        for mode in (
            "failure", "wrong-node", "restart", "runner-image-failure",
            "short-download", "negative-duration", "bad-json",
        ):
            with self.subTest(mode=mode):
                self.mode = mode
                code, _ = self.execute()
                self.assertEqual(code, 1)
                self.assertEqual(self.calls[-1][0][:2], ["delete", "namespace"])

    def test_timeout_preserves_completed_pulls_without_duplicate_counting(self):
        self.mode = "pending"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 4)
        self.assertIn("Timed out", report["errors"][0])
        self.assertEqual(sum(arguments[0] == "logs" for arguments, _ in self.calls), 4)

    def test_late_completion_fails(self):
        self.mode = "late"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn("deadline", report["errors"][0])

    def test_existing_namespace_is_not_deleted(self):
        self.fail_command = ["create", "namespace"]
        code, _ = self.execute()
        self.assertEqual(code, 1)
        self.assertFalse(any(arguments[:2] == ["delete", "namespace"] for arguments, _ in self.calls))

    def test_partial_creation_still_cleans_up(self):
        self.mode = "partial-create"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(len(report["pulls"]), 5)
        self.assertEqual(self.calls[-1][0][:2], ["delete", "namespace"])

    def test_cleanup_error_fails_successful_downloads(self):
        self.fail_command = ["delete", "namespace"]
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertIn("Namespace cleanup failed", report["errors"][0])


if __name__ == "__main__":
    unittest.main()
