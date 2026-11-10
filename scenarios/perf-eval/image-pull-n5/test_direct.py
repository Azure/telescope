"""Offline tests for direct-host downloads without Kubernetes."""

import contextlib
import io
import json
import os
import threading
import unittest
from unittest.mock import patch

import direct
import download
import test_primary
import test_pull


class TestDirectDownloads(unittest.TestCase):
    def setUp(self):
        self.fixture = test_pull.TestCoordinator()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.targets = []
        self.lock = threading.Lock()
        self.mode = "success"

    def download(self, target, *, cancel_event):
        with self.lock:
            index = len(self.targets)
            self.targets.append(target)
        if self.mode == "failure" and index == 0:
            raise download.DownloadError("Transfer failed for " + target["url"])
        return {
            "status": "success", "storage_account": target["account"],
            "storage_role": target.get("storage_role", "replica"),
            "blob_digest": target["digest"], "downloaded_bytes": target["size"],
            "started_at": download.utc(target["start"] + 1),
            "finished_at": download.utc(target["start"] + 3), "duration_seconds": 2,
            "window_start": download.utc(target["start"]), "window_end": download.utc(target["end"]),
            "client_request_id": f"client-{index}",
            "storage_request_id": "same" if self.mode == "duplicate" else f"storage-{index}",
            "time_to_headers_seconds": 0.1, "hashing_seconds": 0.2, "cpu_seconds": 0.3,
        }

    def execute(self, **kwargs):
        output = io.StringIO()
        with patch("direct.download.download", side_effect=self.download):
            with contextlib.redirect_stdout(output):
                code = direct.run(self.fixture.args, start_immediately=True, **kwargs)
        report = json.loads(self.fixture.result_file.read_text())
        self.assertNotIn("PRIVATE-SAS", output.getvalue())
        self.assertNotIn("secret-value", output.getvalue())
        self.assertEqual(self.fixture.calls, [], "Direct mode must never invoke kubectl")
        return code, report

    def test_five_full_gets_are_pinned_and_reported_without_pods(self):
        code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(report["execution_backend"], "direct")
        self.assertIsNone(report["namespace"])
        self.assertEqual(report["expected_pulls"], 5)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(len(self.targets), 5)
        self.assertEqual(len({t["url"] for t in self.targets}), 1)
        self.assertTrue(all("worker" in p and "pod" not in p for p in report["pulls"]))
        self.assertEqual(report["total_downloaded_bytes"], 5 * download.LAYER_BYTES)
        self.assertEqual(len({p["storage_request_id"] for p in report["pulls"]}), 5)
        self.assertEqual(report["performance"]["transfer_wall_seconds"], 2)
        self.assertAlmostEqual(report["performance"]["completed_worker_cpu_seconds"], 1.5)
        self.assertEqual(report["performance"]["completed_worker_hashing_seconds"], 1)

    def test_four_gets_preserve_the_requested_count(self):
        code, report = self.execute(pull_count=4)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.targets), 4)
        self.assertEqual(report["successful_pulls"], 4)

    def test_warm_mode_still_requires_exactly_three_gets_per_account(self):
        self.fixture.redirect_accounts = ["dfauereplica3", "dfauereplica10"]
        code, report = self.execute(
            pull_count=6, warm_traffic=True, scale_in_threshold_bytes=3 * download.LAYER_BYTES,
        )
        self.assertEqual(code, 0)
        self.assertEqual([row["successful_pulls"] for row in report["storage_accounts"]], [3, 3])
        self.assertEqual(report["total_downloaded_bytes"], 6 * download.LAYER_BYTES)
        self.assertEqual(len(self.targets), 6)

    def test_primary_mode_preserves_primary_location_and_needs_no_registry_credentials(self):
        with patch.dict(os.environ, {"ACR_PULL_USERNAME": "", "ACR_PULL_PASSWORD": ""}):
            code, report = self.execute(primary_bundle=test_primary.primary_bundle())
        self.assertEqual(code, 0)
        self.assertEqual(self.fixture.requests, [])
        self.assertEqual(report["storage_account"], "dfauemanaged1")
        self.assertEqual(report["storage_role"], "primary")
        self.assertEqual(report["primary_row_key"], "dfauemanaged1&primary-container")

    def test_failure_preserves_verified_peers_and_redacts_sas(self):
        self.mode = "failure"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 4)
        self.assertEqual(len(self.targets), 5)
        self.assertTrue(report["errors"])
        self.assertNotIn("PRIVATE-SAS", self.fixture.result_file.read_text())

    def test_duplicate_request_ids_cannot_report_success(self):
        self.mode = "duplicate"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn("distinct storage_request_id", report["errors"][0])

    def test_invalid_count_fails_without_network_or_workers(self):
        code, report = self.execute(pull_count=3)
        self.assertEqual(code, 1)
        self.assertEqual(self.fixture.requests, [])
        self.assertEqual(self.targets, [])

    def test_invalid_primary_location_fails_before_downloads(self):
        bundle = test_primary.primary_bundle()
        bundle["location"]["PrimaryCopy"] = False
        code, report = self.execute(primary_bundle=bundle)
        self.assertEqual(code, 1)
        self.assertEqual(self.targets, [])

    def test_all_workers_start_concurrently(self):
        barrier = threading.Barrier(5, timeout=5)
        original = self.download

        def concurrent(target, **kwargs):
            barrier.wait()
            return original(target, **kwargs)

        with patch.object(self, "download", side_effect=concurrent):
            code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 5)

    def test_keyboard_interrupt_cancels_and_writes_partial_report(self):
        def interrupted(_futures, **kwargs):
            raise KeyboardInterrupt

        with patch("direct.as_completed", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.execute()
        report = json.loads(self.fixture.result_file.read_text())
        self.assertEqual(report["status"], "failure")
        self.assertIn("interrupted", report["errors"][0])
        self.assertFalse(any(t.name.startswith("blob-download") for t in threading.enumerate()))


if __name__ == "__main__":
    unittest.main()
