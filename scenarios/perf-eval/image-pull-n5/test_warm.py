"""Offline SI-03 traffic-shape tests; no storage or Kubernetes requests are made."""

import hashlib
import json
import unittest
from unittest.mock import patch

import download
import pull
import test_pull


FRESH_LAYER_BYTES = 1073834596


class TestWarmTraffic(unittest.TestCase):
    def setUp(self):
        self.fixture = test_pull.TestCoordinator()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.nodes = self.fixture.nodes[:1]
        self.fixture.redirect_accounts = ["dfauereplica3", "dfauereplica10"]
        self.fixture.manifest = json.dumps({
            "schemaVersion": 2, "layers": [{"digest": test_pull.DIGEST, "size": FRESH_LAYER_BYTES}],
        }).encode()
        self.fixture.args.image = (
            "williamjcusaue1.azurecr-test.io/test1gb@sha256:"
            + hashlib.sha256(self.fixture.manifest).hexdigest()
        )

    def execute(self, **kwargs):
        return self.fixture.execute(
            node_count=1, pull_count=6, warm_traffic=True, **kwargs,
        )

    def test_exactly_three_pinned_downloads_per_account_and_shared_window(self):
        code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 0)
        self.assertEqual(report["scenario"], "TC-SI-03")
        self.assertTrue(report["server_validation_required"])
        self.assertEqual(report["expected_pulls"], 6)
        self.assertEqual(report["successful_pulls"], 6)
        self.assertEqual(report["blob_size_bytes"], FRESH_LAYER_BYTES)
        self.assertEqual(report["total_downloaded_bytes"], 6443007576)
        self.assertNotIn("storage_account", report)
        self.assertEqual(report["scale_in_threshold_bytes"], 4294967296)
        self.assertEqual(report["scale_out_threshold_bytes"], 5368709120)
        self.assertEqual(report["storage_accounts"], [
            {"storage_account": name, "expected_pulls": 3, "successful_pulls": 3,
             "downloaded_bytes": 3221503788}
            for name in ("dfauereplica3", "dfauereplica10")
        ])
        self.assertEqual(
            [entry["storage_account"] for entry in report["pulls"]],
            ["dfauereplica3"] * 3 + ["dfauereplica10"] * 3,
        )
        self.assertEqual(len({entry["pod"] for entry in report["pulls"]}), 6)
        self.assertEqual(len({entry["client_request_id"] for entry in report["pulls"]}), 6)
        self.assertEqual(len({entry["storage_request_id"] for entry in report["pulls"]}), 6)
        self.assertEqual({entry["node"] for entry in report["pulls"]}, {"worker-0"})
        self.assertEqual({entry["window_start"] for entry in report["pulls"]}, {report["window_start"]})
        self.assertEqual({entry["window_end"] for entry in report["pulls"]}, {report["window_end"]})
        workload = next(payload for _, payload in self.fixture.calls if payload and payload["kind"] == "List")
        self.assertEqual(
            [pod["spec"]["volumes"][0]["secret"]["secretName"] for pod in workload["items"]],
            ["acr-download-target-1"] * 3 + ["acr-download-target-2"] * 3,
        )
        secrets = [payload for _, payload in self.fixture.calls if payload and payload["kind"] == "Secret"]
        self.assertEqual(len(secrets), 2)
        self.assertEqual(len(self.fixture.requests), 4)
        self.assertTrue(all(
            request.full_url.startswith("https://williamjcusaue1.azurecr-test.io/")
            for request in self.fixture.requests
        ))
        self.assertEqual(self.fixture.calls[-1][0][:2], ["delete", "namespace"])

    def test_duplicate_redirects_are_bounded_selection_not_extra_downloads(self):
        self.fixture.redirect_accounts = ["dfauereplica3", "dfauereplica3", "dfauereplica10"]
        code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 6)
        self.assertEqual(sum("/oauth2/token?" in request.full_url for request in self.fixture.requests), 1)
        self.assertEqual(sum("/manifests/" in request.full_url for request in self.fixture.requests), 1)
        self.assertEqual(sum("/blobs/" in request.full_url for request in self.fixture.requests), 3)

    def test_one_available_account_fails_before_pods_or_storage_gets(self):
        self.fixture.redirect_accounts = ["dfauereplica3"]
        code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 1)
        self.assertIn("two distinct eligible replica accounts", report["errors"][0])
        self.assertEqual(self.fixture.redirect_index, pull.MAX_ACCOUNT_SELECTION_ATTEMPTS)
        self.assertFalse(any(payload and payload["kind"] == "List" for _, payload in self.fixture.calls))
        self.assertEqual(report["successful_pulls"], 0)
        self.assertEqual(report["total_downloaded_bytes"], 0)

    def test_three_gib_scale_in_threshold_is_not_a_valid_aggregation_test_for_new_layer(self):
        code, report = self.execute(
            start_immediately=True, scale_in_threshold_bytes=3 * download.LAYER_BYTES,
        )
        self.assertEqual(code, 1)
        self.assertIn("isolate aggregate warmth", report["errors"][0])
        self.assertEqual(self.fixture.redirect_index, 0)
        self.assertEqual(report["successful_pulls"], 0)
        self.assertFalse(any(payload and payload["kind"] == "List" for _, payload in self.fixture.calls))

    def test_hot_per_account_total_is_rejected_before_any_download(self):
        code, report = self.execute(
            start_immediately=True, scale_out_threshold_bytes=3 * FRESH_LAYER_BYTES,
        )
        self.assertEqual(code, 1)
        self.assertIn("below the scale-out threshold", report["errors"][0])
        self.assertEqual(self.fixture.redirect_index, 0)

    def test_threshold_boundaries_and_invalid_types(self):
        per_account = 3 * FRESH_LAYER_BYTES
        aggregate = 2 * per_account
        pull.validate_warm_traffic(FRESH_LAYER_BYTES, per_account, per_account + 1)
        for scale_in, scale_out in (
            (per_account - 1, aggregate), (aggregate, aggregate),
            (per_account, per_account), (-1, aggregate), (True, aggregate),
            (per_account, 0), (per_account, -1), (per_account, True),
        ):
            with self.subTest(scale_in=scale_in, scale_out=scale_out):
                with self.assertRaises(download.DownloadError):
                    pull.validate_warm_traffic(FRESH_LAYER_BYTES, scale_in, scale_out)

    def test_aligned_mode_publishes_two_secrets_with_one_common_schedule(self):
        self.fixture.resolution_delay = 3
        code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(report["start_mode"], "aligned")
        updates = [payload for args, payload in self.fixture.calls if args[0] == "replace"]
        self.assertEqual(len(updates), 2)
        targets = [json.loads(secret["stringData"]["target.json"]) for secret in updates]
        self.assertEqual(targets[0]["start"], targets[1]["start"])
        self.assertEqual(targets[0]["end"], targets[1]["end"])
        self.assertEqual(targets[0]["start"] % download.WINDOW_SECONDS, 0)

    def test_wrong_account_results_cannot_pass_as_two_account_traffic(self):
        self.fixture.mode = "wrong-account"
        code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 3)
        self.assertEqual(report["storage_accounts"][0]["successful_pulls"], 0)
        self.assertEqual(report["storage_accounts"][1]["successful_pulls"], 3)

    def test_partial_failure_preserves_completed_peers_and_cleans_up(self):
        self.fixture.mode = "failure"
        self.fixture.failed_index = 3
        code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(report["total_downloaded_bytes"], 5 * FRESH_LAYER_BYTES)
        self.assertEqual([account["successful_pulls"] for account in report["storage_accounts"]], [3, 2])
        self.assertEqual(sum(args[0] == "logs" for args, _ in self.fixture.calls), 6)
        self.assertEqual(self.fixture.calls[-1][0][:2], ["delete", "namespace"])

    def test_duplicate_client_ids_are_rejected(self):
        self.fixture.mode = "duplicate-client"
        code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 1)
        self.assertIn("6 distinct client request IDs", report["errors"][0])

    def test_duplicate_storage_ids_are_rejected(self):
        self.fixture.mode = "duplicate-request"
        code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 1)
        self.assertIn("6 distinct Azure Storage request IDs", report["errors"][0])

    def test_cleanup_failure_is_not_reported_as_success(self):
        self.fixture.fail_command = ["delete", "namespace"]
        code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 6)
        self.assertIn("cleanup", report["errors"][0])

    def test_six_worker_collection_budget_is_reserved(self):
        selected = test_pull.target()
        duration = selected["end"] - self.fixture.epoch
        budget = 7 * pull.KUBECTL_TIMEOUT_SECONDS + pull.POLL_SECONDS
        pull.ensure_schedule_fits(selected, duration + budget, pull_count=6)
        with self.assertRaisesRegex(download.DownloadError, "remaining lifetime"):
            pull.ensure_schedule_fits(selected, duration + budget - 1, pull_count=6)

    def test_original_single_account_mode_accepts_the_new_layer_size(self):
        code, report = self.fixture.execute(node_count=1, start_immediately=True)
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(report["total_downloaded_bytes"], 5 * FRESH_LAYER_BYTES)
        self.assertEqual(report["storage_account"], "dfauereplica3")
        self.assertEqual(len(self.fixture.requests), 3)

    def test_second_target_expiry_is_checked_before_workload_creation(self):
        original = self.fixture.http

        def expired_redirect(request, **kwargs):
            try:
                return original(request, **kwargs)
            except test_pull.urllib.error.HTTPError as error:
                if "/blobs/" in request.full_url and self.fixture.redirect_index == 2:
                    error.headers["Location"] = error.headers["Location"].replace("05%3A00", "02%3A40")
                raise

        with patch("urllib.request.OpenerDirector.open", side_effect=expired_redirect):
            code, report = self.execute(start_immediately=True)
        self.assertEqual(code, 1)
        self.assertIn("expires", report["errors"][0])
        self.assertFalse(any(payload and payload["kind"] == "List" for _, payload in self.fixture.calls))


if __name__ == "__main__":
    unittest.main()
