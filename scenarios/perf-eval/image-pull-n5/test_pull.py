"""Offline tests for five fixed-account layer downloads and their coordinator."""

import argparse
import base64
import contextlib
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

import download
import pull


BASE_TIME = 1792377300
DIGEST = "sha256:" + "f" * 64
MANIFEST = json.dumps({"schemaVersion": 2, "layers": [{"digest": DIGEST, "size": download.LAYER_BYTES}]}).encode()
IMAGE = "williamjcusaue1.azurecr-test.io/test1gb@sha256:" + hashlib.sha256(MANIFEST).hexdigest()
RUNNER = "python:3.12.12-slim"


def target(digest=DIGEST):
    encoded = digest.removeprefix("sha256:")
    return {
        "account": "dfauereplica3",
        "digest": digest,
        "size": download.LAYER_BYTES,
        "start": BASE_TIME + 300,
        "end": BASE_TIME + 600,
        "url": (
            "https://dfauereplica3.blob.core.windows.net/registry-copy/docker/registry"
            f"/v2/blobs/sha256/{encoded[:2]}/{encoded}/data"
            "?sp=r&se=2026-10-19T05%3A00%3A00Z&sig=PRIVATE-SAS"
        ),
    }


class Response(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


class TestCoordinator(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.result_file = Path(temporary.name) / "results.json"
        self.args = argparse.Namespace(
            image=IMAGE, runner_image=RUNNER, result_file=str(self.result_file),
            run_id="test-5", run_url="https://example/run/test-5",
        )
        self.calls = []
        self.requests = []
        self.clock = 0
        self.epoch = BASE_TIME
        self.mode = "success"
        self.fail_command = None
        self.pods = []
        self.selected = None
        self.failed_index = 0
        self.ready_after_seconds = 0
        self.resolution_delay = 0
        self.nodes = [{
            "metadata": {"name": f"worker-{index}"},
            "spec": {},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        } for index in range(5)]
        for patcher in (
            patch.dict(os.environ, {"ACR_PULL_USERNAME": "williamjcusaue1", "ACR_PULL_PASSWORD": "secret-value"}),
            patch("pull.subprocess.run", side_effect=self.command),
            patch("urllib.request.OpenerDirector.open", side_effect=self.http),
            patch("time.monotonic", side_effect=lambda: self.clock),
            patch("time.time", side_effect=lambda: self.epoch),
            patch("time.sleep", side_effect=self.sleep),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def sleep(self, seconds):
        self.clock += seconds
        self.epoch += seconds

    def http(self, request, **_kwargs):
        self.requests.append(request)
        if "/oauth2/token?" in request.full_url:
            if self.mode == "unauthorized":
                raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)
            self.assertTrue(request.get_header("Authorization").startswith("Basic "))
            return Response(json.dumps({"access_token": "private-token"}).encode())
        if "/manifests/" in request.full_url:
            return Response(MANIFEST if self.mode != "wrong-manifest" else b"bad-manifest")
        if "/blobs/" in request.full_url:
            self.sleep(self.resolution_delay)
            if self.mode == "proxy":
                return Response()
            url = target()["url"]
            if self.mode == "wrong-redirect":
                url = url.replace("dfauereplica3.blob.core.windows.net", "other.example")
            raise urllib.error.HTTPError(request.full_url, 307, "redirect", {"Location": url}, None)
        self.fail("Coordinator must never download from the SAS endpoint")

    def command(self, command, **kwargs):
        self.assertEqual(command[:2], ["kubectl", "--request-timeout=30s"])
        self.assertTrue(kwargs["check"])
        payload = json.loads(kwargs["input"]) if kwargs["input"] else None
        arguments = command[2:]
        self.calls.append((arguments, payload))
        if self.fail_command and arguments[:len(self.fail_command)] == self.fail_command:
            raise subprocess.CalledProcessError(1, command, stderr="Request rejected; sig=PRIVATE-SAS")
        if arguments[:2] == ["get", "nodes"]:
            output = {"items": self.nodes}
        elif arguments[:2] == ["create", "namespace"]:
            output = {}
        elif arguments[:2] == ["create", "serviceaccount"]:
            self.assertEqual(arguments, ["create", "serviceaccount", pull.SERVICE_ACCOUNT, "-n", pull.NAMESPACE])
            output = {}
        elif arguments == ["create", "-f", "-"]:
            output = {}
            if payload["kind"] == "Secret":
                self.selected = json.loads(payload["stringData"]["target.json"]) or None
            if payload["kind"] == "List":
                self.assertTrue(any(args[:2] == ["create", "serviceaccount"] for args, _ in self.calls))
                self.pods = payload["items"]
                for pod in self.pods:
                    pod["status"] = {
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                        "containerStatuses": [{"name": "pull", "restartCount": 0, "state": {"running": {}}}],
                    }
                if self.mode == "not-ready":
                    self.pods[0]["status"]["conditions"][0]["status"] = "False"
                elif self.mode == "wrong-node":
                    self.pods[0]["spec"]["nodeName"] = "system-node"
                elif self.mode == "restart":
                    self.pods[0]["status"]["containerStatuses"][0]["restartCount"] = 1
                elif self.mode == "partial-create":
                    raise subprocess.CalledProcessError(1, command)
                if self.selected:
                    self.complete_downloads()
        elif arguments == ["replace", "-f", "-"]:
            self.selected = json.loads(payload["stringData"]["target.json"])
            self.complete_downloads()
            output = {}
        elif arguments[:2] == ["get", "pods"]:
            if self.selected is None and self.mode != "not-ready":
                for pod in self.pods:
                    pod["status"]["conditions"][0]["status"] = (
                        "True" if self.clock >= self.ready_after_seconds else "False")
            output = {"items": self.pods}
        elif arguments[0] == "logs":
            pod_name = arguments[3]
            if self.mode == "failure" and pod_name == f"pull-{self.failed_index + 1}":
                output = {"status": "failure", "error": "Storage SAS expires before the download window finishes"}
            else:
                output = {
                    "status": "success",
                    "storage_account": self.selected["account"],
                    "blob_digest": self.selected["digest"],
                    "downloaded_bytes": download.LAYER_BYTES,
                    "started_at": download.utc(self.selected["start"] + 1),
                    "finished_at": download.utc(self.selected["start"] + 3),
                    "duration_seconds": 2,
                    "window_start": download.utc(self.selected["start"]),
                    "window_end": download.utc(self.selected["end"]),
                    "client_request_id": "client-" + pod_name,
                    "storage_request_id": "storage-" + pod_name,
                }
                if self.mode == "wrong-account":
                    output["storage_account"] = "dfauereplica10"
                elif self.mode == "wrong-digest":
                    output["blob_digest"] = "sha256:" + "0" * 64
                elif self.mode == "short-download":
                    output["downloaded_bytes"] -= 1
                elif self.mode == "late":
                    output["finished_at"] = download.utc(self.selected["end"])
                elif self.mode == "duplicate-request":
                    output["storage_request_id"] = "same-request"
                elif self.mode == "bad-json":
                    return subprocess.CompletedProcess(command, 0, "invalid-json", "")
        elif arguments[:2] == ["delete", "namespace"]:
            output = {}
        else:
            self.fail(f"Unexpected command: {arguments}")
        return subprocess.CompletedProcess(command, 0, json.dumps(output), "")

    def complete_downloads(self):
        self.sleep(self.selected["start"] + 3 - self.epoch)
        for pod in self.pods:
            pod["status"]["phase"] = "Succeeded"
            pod["status"]["containerStatuses"][0]["state"] = {"terminated": {"exitCode": 0}}
        if self.mode == "pending":
            self.pods[0]["status"]["phase"] = "Running"
        if self.mode == "failure":
            self.pods[self.failed_index]["status"]["phase"] = "Failed"
            self.pods[self.failed_index]["status"]["containerStatuses"][0]["state"] = {
                "terminated": {"exitCode": 1}}
        if self.mode == "unexpected-pod":
            self.pods.append({**self.pods[0], "metadata": {"name": "unexpected"}})

    def execute(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = pull.run(self.args)
        report = json.loads(self.result_file.read_text(encoding="utf-8"))
        text = stdout.getvalue() + stderr.getvalue() + self.result_file.read_text()
        for secret in ("secret-value", "PRIVATE-SAS", "private-token"):
            self.assertNotIn(secret, text)
        if code:
            self.assertEqual(report["status"], "failure")
            self.assertIn("IMAGE DOWNLOAD FAILED:", stderr.getvalue())
        return code, report

    def test_five_verified_downloads_use_one_secret_target(self):
        code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(report["storage_account"], "dfauereplica3")
        self.assertEqual(report["blob_digest"], DIGEST)
        self.assertEqual(report["window_start"], download.utc(BASE_TIME + 300))
        workload = next(payload for _, payload in self.calls if payload and payload["kind"] == "List")
        self.assertEqual(len(workload["items"]), 5)
        for index, pod in enumerate(workload["items"]):
            self.assertEqual(pod["metadata"]["name"], f"pull-{index+1}")
            self.assertEqual(pod["spec"]["nodeName"], f"worker-{index}")
            self.assertEqual(pod["spec"]["restartPolicy"], "Never")
            self.assertEqual(pod["spec"]["serviceAccountName"], pull.SERVICE_ACCOUNT)
            self.assertFalse(pod["spec"]["automountServiceAccountToken"])
            self.assertEqual(pod["spec"]["containers"][0]["image"], RUNNER)
            self.assertEqual(pod["spec"]["volumes"][0]["secret"]["secretName"], "acr-download-target")
            self.assertEqual(report["pulls"][index]["downloaded_bytes"], 1073741824)
            self.assertEqual(report["pulls"][index]["storage_account"], report["storage_account"])
        secrets = [payload for _, payload in self.calls if payload and payload["kind"] == "Secret"]
        self.assertEqual(len(secrets), 2)
        self.assertEqual(json.loads(secrets[0]["stringData"]["target.json"]), {})
        self.assertEqual(json.loads(secrets[1]["stringData"]["target.json"])["url"], target()["url"])
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(sum("/blobs/" in request.full_url for request in self.requests), 1)
        for arguments, _ in self.calls:
            self.assertNotIn("PRIVATE-SAS", " ".join(arguments))
        self.assertEqual(self.calls[-1][0], ["delete", "namespace", "acr-five-pulls", "--wait=false"])

    def test_missing_password_fails_before_any_network(self):
        with patch.dict(os.environ, {"ACR_PULL_PASSWORD": "$(ACR_PULL_PASSWORD)"}):
            code, _ = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.requests, [])

    def test_mutable_tag_rejected(self):
        self.args.image = "williamjcusaue1.azurecr-test.io/test1gb:latest"
        code, _ = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])

    def test_incorrect_worker_count_fails(self):
        self.nodes.pop()
        code, _ = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 1)

    def test_local_mode_downloads_five_times_on_one_node(self):
        self.nodes = self.nodes[:1]
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = pull.run(self.args, node_count=1, region="local", registry_resource_group=None)
        report = json.loads(self.result_file.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(report["node_count"], 1)
        self.assertEqual(report["region"], "local")
        self.assertIsNone(report["registry_resource_group"])
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(len(report["pulls"]), 5)
        self.assertEqual({entry["node"] for entry in report["pulls"]}, {"worker-0"})
        self.assertEqual(len({entry["pod"] for entry in report["pulls"]}), 5)
        self.assertEqual(len({entry["storage_request_id"] for entry in report["pulls"]}), 5)
        workload = next(payload for _, payload in self.calls if payload and payload["kind"] == "List")
        self.assertEqual(len(workload["items"]), 5)
        self.assertTrue(all(pod["spec"]["nodeName"] == "worker-0" for pod in workload["items"]))
        self.assertNotIn("secret-value", output.getvalue())

    def test_local_mode_rejects_extra_nodes_before_creating_pods(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pull.run(self.args, node_count=1)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 1)

    def test_four_downloads_create_and_verify_exactly_four_pods(self):
        self.nodes = self.nodes[:1]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pull.run(self.args, node_count=1, pull_count=4, start_immediately=True)
        report = json.loads(self.result_file.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(report["expected_pulls"], 4)
        self.assertEqual(report["successful_pulls"], 4)
        self.assertEqual(len(report["pulls"]), 4)
        self.assertEqual(sum(item["downloaded_bytes"] for item in report["pulls"]), 4294967296)
        self.assertEqual(len({item["storage_request_id"] for item in report["pulls"]}), 4)
        workload = next(payload for _, payload in self.calls if payload and payload["kind"] == "List")
        self.assertEqual([pod["metadata"]["name"] for pod in workload["items"]], ["pull-1", "pull-2", "pull-3", "pull-4"])
        self.assertTrue(all(pod["spec"]["nodeName"] == "worker-0" for pod in workload["items"]))
        self.assertFalse(any(args[0] == "replace" for args, _ in self.calls))
        self.assertEqual(sum(args[0] == "logs" for args, _ in self.calls), 4)
        self.assertEqual(self.calls[-1][0][:2], ["delete", "namespace"])

    def test_four_downloads_preserve_partial_results_and_reject_duplicates(self):
        self.nodes = self.nodes[:1]
        for mode, expected_successes in (("failure", 3), ("pending", 3), ("duplicate-request", 4)):
            with self.subTest(mode=mode):
                self.mode = mode
                self.clock = 0
                self.epoch = BASE_TIME
                self.selected = None
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = pull.run(self.args, node_count=1, pull_count=4, start_immediately=True)
                report = json.loads(self.result_file.read_text())
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "failure")
                self.assertEqual(report["expected_pulls"], 4)
                self.assertEqual(report["successful_pulls"], expected_successes)
                self.assertEqual(len(report["pulls"]), 4)

    def test_invalid_download_counts_fail_before_kubernetes_calls(self):
        for count in (0, 3, 6):
            with self.subTest(count=count):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = pull.run(self.args, node_count=1, pull_count=count)
                self.assertEqual(code, 1)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.requests, [])

    def test_immediate_mode_provides_target_before_five_pods_start(self):
        self.nodes = self.nodes[:1]
        self.epoch = BASE_TIME + 121
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pull.run(self.args, node_count=1, start_immediately=True)
        report = json.loads(self.result_file.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(report["start_mode"], "immediate")
        self.assertEqual(self.selected["start"], BASE_TIME + 121)
        self.assertEqual(self.selected["end"], BASE_TIME + 421)
        self.assertEqual(self.clock, 3)
        secret_index = next(index for index, (_, payload) in enumerate(self.calls) if payload and payload["kind"] == "Secret")
        pod_index = next(index for index, (_, payload) in enumerate(self.calls) if payload and payload["kind"] == "List")
        self.assertLess(secret_index, pod_index)
        self.assertEqual(json.loads(self.calls[secret_index][1]["stringData"]["target.json"])["url"], target()["url"])
        self.assertFalse(any(args[0] == "replace" for args, _ in self.calls))
        self.assertEqual(len({entry["storage_request_id"] for entry in report["pulls"]}), 5)

    def test_immediate_mode_retains_partial_results_and_fails(self):
        self.nodes = self.nodes[:1]
        self.mode = "failure"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pull.run(self.args, node_count=1, start_immediately=True)
        report = json.loads(self.result_file.read_text())
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 4)
        self.assertEqual(report["pulls"][0]["status"], "failure")
        self.assertEqual(self.clock, 3)

    def test_immediate_auth_failure_creates_no_workload_pods(self):
        self.mode = "unauthorized"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pull.run(self.args, start_immediately=True)
        self.assertEqual(code, 1)
        self.assertFalse(any(payload and payload["kind"] == "List" for _, payload in self.calls))
        self.assertEqual(self.calls[-1][0][:2], ["delete", "namespace"])

    def test_local_mode_preserves_four_successes_when_one_pod_fails(self):
        self.nodes = self.nodes[:1]
        self.mode = "failure"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pull.run(self.args, node_count=1)
        report = json.loads(self.result_file.read_text())
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 4)
        self.assertEqual(report["pulls"][0]["status"], "failure")
        self.assertEqual(sum(arguments[0] == "logs" for arguments, _ in self.calls), 5)

    def test_no_target_resolution_until_every_worker_is_ready(self):
        self.mode = "not-ready"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(self.requests, [])
        self.assertIn("ready", report["errors"][0])

    def test_no_unsafe_fallback_on_auth_proxy_or_redirect_errors(self):
        for mode in ("unauthorized", "proxy", "wrong-redirect", "wrong-manifest"):
            with self.subTest(mode=mode):
                self.mode = mode
                self.epoch = BASE_TIME
                self.clock = 0
                self.selected = None
                code, _ = self.execute()
                self.assertEqual(code, 1)
                self.assertIsNone(self.selected)

    def test_wrong_account_digest_size_window_and_duplicate_requests_fail(self):
        for mode in ("wrong-account", "wrong-digest", "short-download", "late", "duplicate-request", "bad-json"):
            with self.subTest(mode=mode):
                self.mode = mode
                self.clock = 0
                self.epoch = BASE_TIME
                code, _ = self.execute()
                self.assertEqual(code, 1)

    def test_worker_failures_have_actionable_sanitized_diagnostics(self):
        self.mode = "failure"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn("SAS expires", report["errors"][0])

    def test_failed_worker_preserves_all_successful_terminal_results(self):
        for failed_index in (0, 4):
            with self.subTest(failed_index=failed_index):
                self.mode = "failure"
                self.failed_index = failed_index
                self.clock = 0
                self.epoch = BASE_TIME
                self.selected = None
                self.calls = []
                code, report = self.execute()
                self.assertEqual(code, 1)
                self.assertEqual(report["successful_pulls"], 4)
                self.assertEqual(len(report["pulls"]), 5)
                for index, result in enumerate(report["pulls"]):
                    if index == failed_index:
                        self.assertEqual(result["status"], "failure")
                        self.assertIn("SAS expires", result["error"])
                    else:
                        self.assertEqual(result["status"], "success")
                        self.assertEqual(result["storage_request_id"], f"storage-pull-{index + 1}")
                        self.assertEqual(result["downloaded_bytes"], 1073741824)
                        self.assertEqual(result["started_at"], download.utc(self.selected["start"] + 1))
                self.assertEqual(sum(arguments[0] == "logs" for arguments, _ in self.calls), 5)
                self.assertEqual(self.calls[-1][0][:2], ["delete", "namespace"])

    def test_late_readiness_never_publishes_an_infeasible_target(self):
        self.ready_after_seconds = 900
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIsNone(self.selected)
        self.assertFalse(any(arguments[0] == "replace" for arguments, _ in self.calls))
        self.assertIn("remaining lifetime", report["errors"][0])

    def test_target_resolution_time_is_included_in_feasibility_check(self):
        self.resolution_delay = 900
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIsNone(self.selected)
        self.assertIn("remaining lifetime", report["errors"][0])

    def test_slow_but_feasible_startup_still_succeeds(self):
        self.ready_after_seconds = 420
        code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertLess(self.selected["end"] - BASE_TIME, pull.TIMEOUT_SECONDS)

    def test_schedule_reserves_the_full_window_and_result_collection(self):
        selected = target()
        required = selected["end"] - self.epoch + pull.RESULT_COLLECTION_SECONDS
        pull.ensure_schedule_fits(selected, self.clock + required)
        with self.assertRaisesRegex(download.DownloadError, "remaining lifetime"):
            pull.ensure_schedule_fits(selected, self.clock + required - 0.1)
        with self.assertRaises(download.DownloadError):
            pull.ensure_schedule_fits(selected, selected["start"] - self.epoch + 1)
        self.assertEqual(pull.TIMEOUT_SECONDS, download.WORKER_TIMEOUT_SECONDS)
        for pod in pull.manifests(RUNNER, [f"worker-{i}" for i in range(5)])["items"]:
            self.assertEqual(pod["spec"]["activeDeadlineSeconds"], download.WORKER_TIMEOUT_SECONDS)

    def test_peer_log_errors_do_not_discard_other_terminal_results(self):
        for failure in ("timeout", "invalid-json"):
            with self.subTest(failure=failure):
                self.clock = 0
                self.epoch = BASE_TIME
                self.selected = None
                self.calls = []
                original = self.command

                def fail_first_log(command, **kwargs):
                    arguments = command[2:]
                    if arguments[:4] == ["logs", "-n", pull.NAMESPACE, "pull-1"]:
                        self.calls.append((arguments, None))
                        if failure == "timeout":
                            raise subprocess.TimeoutExpired(command, 45, stderr=b"API connection timeout")
                        return subprocess.CompletedProcess(command, 0, "not JSON: " + target()["url"], "")
                    return original(command, **kwargs)

                with patch("pull.subprocess.run", side_effect=fail_first_log):
                    code, report = self.execute()
                self.assertEqual(code, 1)
                self.assertEqual(report["successful_pulls"], 4)
                self.assertEqual(report["pulls"][0]["status"], "failure")
                self.assertEqual(
                    [entry["storage_request_id"] for entry in report["pulls"][1:]],
                    [f"storage-pull-{i}" for i in range(2, 6)],
                )
                self.assertEqual(sum(arguments[0] == "logs" for arguments, _ in self.calls), 5)

    def test_unexpected_pod_does_not_discard_expected_terminal_results(self):
        self.mode = "unexpected-pod"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertIn("Unexpected workload Pods", report["errors"][0])
        self.assertEqual(sum(arguments[0] == "logs" for arguments, _ in self.calls), 5)

    def test_kubernetes_forbidden_and_timeout_diagnostics_remain_distinct(self):
        command = ["kubectl", "--request-timeout=30s", "get", "nodes", "-o", "json"]
        forbidden = subprocess.CalledProcessError(
            1, command, stderr=(
                'Error from server (Forbidden): nodes is forbidden; cannot list resource "nodes". '
                'https://example.test/api?sig=PRIVATE-SAS password=secret-value Authorization: Bearer private-token'))
        timeout = subprocess.TimeoutExpired(
            command, 45, stderr=b"Unable to connect to the server: i/o timeout")
        for error, expected in ((forbidden, ("Forbidden", "exit 1")), (timeout, ("timed out", "45"))):
            with self.subTest(error=type(error).__name__):
                with patch("pull.subprocess.run", side_effect=error):
                    code, report = self.execute()
                self.assertEqual(code, 1)
                message = report["errors"][0]
                self.assertIn("kubectl get nodes", message)
                for text in expected:
                    self.assertIn(text, message)

    def test_secret_write_errors_redact_plain_and_encoded_secret_data(self):
        original = self.command
        encoded_payloads = []

        def reject_secret_update(command, **kwargs):
            if command[2:3] == ["replace"]:
                value = json.loads(kwargs["input"])["stringData"]["target.json"]
                encoded = base64.b64encode(value.encode()).decode()
                encoded_payloads.append(encoded)
                raise subprocess.CalledProcessError(
                    1, command, stderr=f"Error from server (Forbidden): Secret update denied; data={encoded}; value={value}")
            return original(command, **kwargs)

        with patch("pull.subprocess.run", side_effect=reject_secret_update):
            code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn("kubectl replace -f - [Secret/acr-download-target]", report["errors"][0])
        self.assertIn("Forbidden", report["errors"][0])
        self.assertEqual(len(encoded_payloads), 1)
        self.assertNotIn(encoded_payloads[0], self.result_file.read_text())

    def test_missing_kubectl_has_operation_and_os_error_context(self):
        with patch("pull.subprocess.run", side_effect=FileNotFoundError(2, "No such file or directory", "kubectl")):
            code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn("kubectl get nodes", report["errors"][0])
        self.assertIn("FileNotFoundError", report["errors"][0])
        self.assertIn("No such file", report["errors"][0])

    def test_pending_downloads_are_not_double_counted(self):
        self.mode = "pending"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 4)
        self.assertEqual(sum(arguments[0] == "logs" for arguments, _ in self.calls), 4)

    def test_wrong_node_restart_and_partial_creation_fail(self):
        for mode in ("wrong-node", "restart", "partial-create"):
            with self.subTest(mode=mode):
                self.mode = mode
                self.clock = 0
                code, _ = self.execute()
                self.assertEqual(code, 1)
                self.assertEqual(self.calls[-1][0][:2], ["delete", "namespace"])

    def test_existing_namespace_not_deleted(self):
        self.fail_command = ["create", "namespace"]
        code, _ = self.execute()
        self.assertEqual(code, 1)
        self.assertFalse(any(arguments[:2] == ["delete", "namespace"] for arguments, _ in self.calls))

    def test_service_account_creation_failure_cleans_up_without_downloads(self):
        self.fail_command = ["create", "serviceaccount"]
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(self.requests, [])
        self.assertIn("serviceaccount", report["errors"][0])
        self.assertEqual(self.calls[-1][0][:2], ["delete", "namespace"])

    def test_cleanup_failure_fails_successful_downloads(self):
        self.fail_command = ["delete", "namespace"]
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertIn("cleanup", report["errors"][0])

    def test_window_leaves_time_for_secret_propagation(self):
        for offset in (0, 119, 120, 121, 299):
            with self.subTest(offset=offset):
                self.epoch = BASE_TIME + offset
                selected = pull.resolve_target(IMAGE, "williamjcusaue1", "secret-value")
                self.assertGreaterEqual(selected["start"] - self.epoch, 180)
                self.assertEqual(selected["start"] % 300, 0)
                self.assertEqual(selected["end"] - selected["start"], 300)

    def test_immediate_schedule_never_waits_for_a_boundary(self):
        for offset in (0, 119, 120, 121, 299):
            with self.subTest(offset=offset):
                self.epoch = BASE_TIME + offset
                selected = pull.resolve_target(IMAGE, "williamjcusaue1", "secret-value", start_immediately=True)
                self.assertEqual(selected["start"], self.epoch)
                self.assertEqual(selected["end"], self.epoch + 300)
                self.assertEqual(selected["start_mode"], "immediate")


class StreamingResponse:
    def __init__(self, count, status=200):
        self.remaining = count
        self.status = status
        self.headers = {"Content-Length": str(download.LAYER_BYTES), "x-ms-request-id": "storage-id"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size):
        length = min(self.remaining, size)
        self.remaining -= length
        return b"x" * length


class TestDownloadWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        digest = hashlib.sha256()
        for _ in range(1024):
            digest.update(b"x" * (1024 * 1024))
        cls.digest = "sha256:" + digest.hexdigest()

    def setUp(self):
        self.target = target(self.digest)
        self.epoch = self.target["start"] + 1
        for patcher in (
            patch("time.time", side_effect=lambda: self.epoch),
            patch("time.sleep", side_effect=self.sleep),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def sleep(self, seconds):
        self.epoch += seconds

    def test_streams_and_hashes_exactly_one_gib_with_one_request(self):
        with patch("urllib.request.OpenerDirector.open", return_value=StreamingResponse(download.LAYER_BYTES)) as opened:
            result = download.download(self.target)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["downloaded_bytes"], 1073741824)
        self.assertEqual(result["blob_digest"], self.digest)
        self.assertEqual(result["storage_account"], "dfauereplica3")
        self.assertEqual(result["storage_request_id"], "storage-id")
        opened.assert_called_once()
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, self.target["url"])
        self.assertIsNone(request.get_header("Authorization"))
        self.assertIsNone(request.get_header("Range"))
        self.assertEqual(request.get_header("X-ms-client-request-id"), result["client_request_id"])

    def test_rejects_non_replica_wrong_blob_http_and_other_hosts(self):
        for old, new in (
            ("https://", "http://"),
            ("dfauereplica3.blob.core.windows.net", "dfauereplica3.example.com"),
            ("dfauereplica3", "dfauemanaged"),
            ("/data?", "/other?"),
            ("sig=PRIVATE-SAS", "missing=signature"),
        ):
            with self.subTest(new=new), self.assertRaises(download.DownloadError):
                download.validate_target({**self.target, "url": self.target["url"].replace(old, new)})

    def test_rejects_expired_sas_and_mismatched_account(self):
        for changes in (
            {"url": self.target["url"].replace("05%3A00", "02%3A40")},
            {"account": "dfauereplica10"},
            {"start": self.target["start"] + 1},
            {"size": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(download.DownloadError):
                download.validate_target({**self.target, **changes})

    def test_immediate_worker_downloads_without_sleeping(self):
        self.target.update(start_mode="immediate", start=BASE_TIME + 121, end=BASE_TIME + 421)
        self.epoch = self.target["start"]
        with patch("time.sleep") as sleep:
            with patch("urllib.request.OpenerDirector.open", return_value=StreamingResponse(download.LAYER_BYTES)) as opened:
                result = download.download(self.target)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["downloaded_bytes"], download.LAYER_BYTES)
        opened.assert_called_once()
        sleep.assert_not_called()

    def test_immediate_mode_still_rejects_invalid_deadlines_and_expired_sas(self):
        self.target.update(start_mode="immediate", start=BASE_TIME + 121, end=BASE_TIME + 421)
        for changes in (
            {"start_mode": "unknown"},
            {"end": self.target["end"] + 1},
            {"url": self.target["url"].replace("05%3A00", "02%3A40")},
        ):
            with self.subTest(changes=changes), self.assertRaises(download.DownloadError):
                download.validate_target({**self.target, **changes})
        self.epoch = self.target["end"]
        with patch("urllib.request.OpenerDirector.open") as opened:
            with self.assertRaisesRegex(download.DownloadError, "expired"):
                download.download(self.target)
        opened.assert_not_called()

    def test_no_redirects_are_followed(self):
        self.assertIsNone(download.NoRedirect().redirect_request(None, None, 307, "", {}, "https://other.example"))
        error = urllib.error.HTTPError(self.target["url"], 307, "redirect", {"Location": "https://other.example"}, None)
        with patch("urllib.request.OpenerDirector.open", side_effect=error) as opened:
            with self.assertRaises(urllib.error.HTTPError):
                download.download(self.target)
        self.assertEqual(opened.call_count, 1)
        self.assertNotIn("PRIVATE-SAS", download.error_message(error))

    def test_truncated_body_and_bad_status_fail(self):
        for response in (StreamingResponse(100), StreamingResponse(100, status=206)):
            with patch("urllib.request.OpenerDirector.open", return_value=response):
                with self.assertRaises(download.DownloadError):
                    download.download(self.target)

    def test_download_crossing_window_end_fails(self):
        response = StreamingResponse(100)
        original_read = response.read

        def late_read(size):
            self.epoch = self.target["end"]
            return original_read(size)

        response.read = late_read
        with patch("urllib.request.OpenerDirector.open", return_value=response):
            with self.assertRaisesRegex(download.DownloadError, "exceeded"):
                download.download(self.target)

    def test_missing_length_or_request_id_fails(self):
        for header in ("Content-Length", "x-ms-request-id"):
            with self.subTest(header=header):
                response = StreamingResponse(1)
                del response.headers[header]
                with patch("urllib.request.OpenerDirector.open", return_value=response):
                    with self.assertRaises(download.DownloadError):
                        download.download(self.target)

    def test_wrong_hash_fails_even_with_full_size(self):
        altered = target("sha256:" + "0" * 64)
        with patch("urllib.request.OpenerDirector.open", return_value=StreamingResponse(download.LAYER_BYTES)):
            with self.assertRaisesRegex(download.DownloadError, "SHA-256"):
                download.download(altered)

    def test_waits_for_start_and_refuses_late_start(self):
        self.epoch = self.target["start"] - 2
        with patch("urllib.request.OpenerDirector.open", return_value=StreamingResponse(1)):
            with self.assertRaises(download.DownloadError):
                download.download(self.target)
        self.assertEqual(self.epoch, self.target["start"])
        self.epoch = self.target["end"]
        with patch("urllib.request.OpenerDirector.open") as opened:
            with self.assertRaisesRegex(download.DownloadError, "expired"):
                download.download(self.target)
        opened.assert_not_called()

    def test_worker_failure_output_does_not_expose_sas(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "target.json").write_text(json.dumps(self.target))
            failure = urllib.error.HTTPError(self.target["url"], 403, "forbidden", {}, None)
            output = io.StringIO()
            with patch("urllib.request.OpenerDirector.open", side_effect=failure):
                with contextlib.redirect_stdout(output):
                    code = download.worker(path / "target.json", path / "ready")
            self.assertEqual(code, 1)
            self.assertTrue((path / "ready").exists())
            self.assertIn("403", output.getvalue())
            self.assertNotIn("PRIVATE-SAS", output.getvalue())

    def test_worker_rejects_window_exceeding_its_own_lifetime(self):
        self.epoch = BASE_TIME
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "target.json").write_text(json.dumps(self.target))
            output = io.StringIO()
            with patch("download.WORKER_TIMEOUT_SECONDS", 100):
                with patch("urllib.request.OpenerDirector.open") as opened:
                    with contextlib.redirect_stdout(output):
                        code = download.worker(path / "target.json", path / "ready")
            self.assertEqual(code, 1)
            self.assertIn("remaining worker lifetime", output.getvalue())
            opened.assert_not_called()


class TestDiagnostics(unittest.TestCase):
    def test_urls_passwords_auth_headers_and_signatures_are_redacted(self):
        text = (
            'Forbidden: https://account.blob.core.windows.net/blob?sig=PRIVATE-SAS '
            'Authorization: Bearer TOKEN-VALUE password="PASSWORD-VALUE" '
            "'sig': 'SIGNATURE-VALUE' refresh_token=REFRESH-VALUE"
        )
        sanitized = download.sanitize_diagnostic(text)
        self.assertIn("Forbidden", sanitized)
        for secret in ("PRIVATE-SAS", "TOKEN-VALUE", "PASSWORD-VALUE", "SIGNATURE-VALUE", "REFRESH-VALUE"):
            self.assertNotIn(secret, sanitized)
        self.assertNotIn("https://", sanitized)

    def test_known_credentials_are_redacted_when_not_labelled(self):
        secret = "unlabelled+secret/value"
        encoded = base64.b64encode(secret.encode()).decode()
        text = f"Forbidden {secret} {encoded} " + urllib.parse.quote(secret, safe="")
        self.assertEqual(
            download.sanitize_diagnostic(text, [secret]),
            "Forbidden [redacted] [redacted] [redacted]",
        )

    def test_transport_cause_is_preserved_without_signed_urls(self):
        error = urllib.error.URLError("TLS handshake timed out for " + target()["url"])
        message = download.error_message(error)
        self.assertIn("TLS handshake timed out", message)
        self.assertNotIn("PRIVATE-SAS", message)

    def test_nested_errors_remain_redacted_without_losing_context(self):
        error = download.DownloadError(
            "kubectl logs failed: " + urllib.parse.quote(target()["url"], safe="") + " sig=PRIVATE-SAS")
        message = download.error_message(error)
        self.assertIn("kubectl logs failed", message)
        self.assertNotIn("PRIVATE-SAS", message)
        self.assertNotIn("https", message)
        self.assertEqual(download.sanitize_diagnostic(message), message)


class TestCoordinatorCli(unittest.TestCase):
    def test_batch_cli_selects_its_own_namespace_and_single_node(self):
        argv = [
            "pull.py", "--image", IMAGE, "--runner-image", RUNNER, "--result-file", "result.json",
            "--run-id", "batch-1", "--run-url", "file:///result.json",
            "--namespace", "acr-five-pulls-batch-1", "--local", "--start-immediately",
        ]
        with patch("sys.argv", argv), patch.object(pull, "NAMESPACE", pull.NAMESPACE):
            with patch.object(pull, "run", return_value=0) as run:
                self.assertEqual(pull.main(), 0)
                self.assertEqual(pull.NAMESPACE, "acr-five-pulls-batch-1")
                self.assertEqual(run.call_args.kwargs, {
                    "node_count": 1, "region": "local", "registry_resource_group": None, "start_immediately": True,
                })

    def test_default_cli_preserves_azure_aligned_mode(self):
        argv = [
            "pull.py", "--image", IMAGE, "--runner-image", RUNNER, "--result-file", "result.json",
            "--run-id", "run", "--run-url", "https://example/run",
        ]
        with patch("sys.argv", argv), patch.object(pull, "NAMESPACE", pull.NAMESPACE):
            with patch.object(pull, "run", return_value=0) as run:
                self.assertEqual(pull.main(), 0)
                self.assertEqual(pull.NAMESPACE, "acr-five-pulls")
                self.assertEqual(run.call_args.kwargs, {"start_immediately": False})


class TestNetworkConfiguration(unittest.TestCase):
    def test_aks_references_the_declared_nonoverlapping_subnet(self):
        text = (Path(__file__).parent / "terraform-inputs" / "azure.tfvars").read_text()
        declared_subnet = re.search(r'subnet\s*=\s*\[\s*\{\s*name\s*=\s*"([^"]+)"', text).group(1)
        referenced_subnet = re.search(r'subnet_name\s*=\s*"([^"]+)"', text).group(1)
        self.assertEqual(declared_subnet, "imgpull-subnet-1")
        self.assertEqual(referenced_subnet, declared_subnet)

        def network(field):
            return ipaddress.ip_network(re.search(rf'{field}\s*=\s*"([^"]+)"', text).group(1))

        vnet, subnet, pods, services = [network(field) for field in (
            "vnet_address_space", "address_prefix", "pod_cidr", "service_cidr")]
        self.assertTrue(subnet.subnet_of(vnet))
        self.assertFalse(pods.overlaps(vnet))
        self.assertFalse(services.overlaps(vnet))
        self.assertFalse(pods.overlaps(services))
        dns_ip = re.search(r'dns_service_ip\s*=\s*"([^"]+)"', text).group(1)
        self.assertIn(ipaddress.ip_address(dns_ip), services)


if __name__ == "__main__":
    unittest.main()
