"""Offline tests for primary-only, metadata-verified layer downloads."""

import copy
import unittest
from urllib.parse import parse_qs, urlsplit

import download
import pull
import test_pull


REGISTRY_ID = "b" * 32


def primary_bundle(digest=test_pull.DIGEST):
    encoded = digest.removeprefix("sha256:")
    return {
        "image": test_pull.IMAGE,
        "registry_id": REGISTRY_ID,
        "manifest": {"layers": [{"digest": digest, "size": download.LAYER_BYTES}]},
        "location": {
            "PartitionKey": f"{encoded}&{REGISTRY_ID}",
            "RowKey": "dfauemanaged1&primary-container",
            "PrimaryCopy": True, "IsElasticCopy": False, "Status": "Active",
            "StorageAccountName": "dfauemanaged1", "StorageContainerName": "primary-container",
            "RegistryLoginUri": "williamjcusaue1.azurecr-test.io",
        },
        "url": (
            "https://dfauemanaged1.blob.core.windows.net/primary-container/docker/registry"
            f"/v2/blobs/sha256/{encoded[:2]}/{encoded}/data"
            "?sp=r&sr=b&spr=https&se=2026-10-19T05%3A00%3A00Z&sig=PRIMARY-PRIVATE-SAS"
        ),
    }


class TestPrimaryDownloads(unittest.TestCase):
    def setUp(self):
        self.fixture = test_pull.TestCoordinator()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.nodes = self.fixture.nodes[:1]
        self.bundle = primary_bundle()

    def execute(self, **kwargs):
        return self.fixture.execute(
            node_count=1, start_immediately=True, primary_bundle=self.bundle, **kwargs,
        )

    def test_primary_run_pins_five_downloads_without_registry_redirects(self):
        code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(self.fixture.requests, [])
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(report["storage_role"], "primary")
        self.assertEqual(report["storage_account"], "dfauemanaged1")
        self.assertEqual(report["storage_container"], "primary-container")
        self.assertEqual(report["primary_partition_key"], self.bundle["location"]["PartitionKey"])
        self.assertEqual(report["primary_row_key"], self.bundle["location"]["RowKey"])
        self.assertTrue(all(
            entry["storage_account"] == "dfauemanaged1" and entry["storage_role"] == "primary"
            for entry in report["pulls"]
        ))
        self.assertEqual(len({entry["storage_request_id"] for entry in report["pulls"]}), 5)
        self.assertEqual(self.fixture.calls[-1][0][:2], ["delete", "namespace"])
        self.assertNotIn("PRIMARY-PRIVATE-SAS", self.fixture.result_file.read_text())

    def test_primary_run_does_not_require_registry_password(self):
        from unittest.mock import patch
        import os
        with patch.dict(os.environ, {"ACR_PULL_USERNAME": "", "ACR_PULL_PASSWORD": ""}):
            code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 5)
        self.assertEqual(self.fixture.requests, [])

    def test_four_primary_downloads_are_supported(self):
        code, report = self.execute(pull_count=4)
        self.assertEqual(code, 0)
        self.assertEqual(report["successful_pulls"], 4)
        self.assertEqual(report["total_downloaded_bytes"], 4 * download.LAYER_BYTES)

    def test_replica_selector_still_rejects_primary_urls(self):
        with self.assertRaisesRegex(download.DownloadError, "eligible replica"):
            download.storage_account(self.bundle["url"], test_pull.DIGEST)

    def test_primary_identity_rejects_replica_or_expired_rows(self):
        for change in (
            {"PrimaryCopy": False}, {"PrimaryCopy": "true"}, {"IsElasticCopy": True},
            {"IsElasticCopy": "false"}, {"Status": "Expired"}, {"Status": "Unknown"},
            {"PartitionKey": "wrong"}, {"RowKey": "wrong"},
            {"StorageAccountName": ""}, {"StorageContainerName": "bad--container"},
        ):
            with self.subTest(change=change):
                bundle = copy.deepcopy(self.bundle)
                bundle["location"].update(change)
                with self.assertRaises(download.DownloadError):
                    pull.resolve_primary_target(test_pull.IMAGE, bundle)

    def test_primary_requires_matching_pinned_image_registry_and_layer(self):
        for field, value in (
            ("image", "other.azurecr.io/image@" + "sha256:" + "a" * 64),
            ("registry_id", "c" * 32),
            ("registry_id", ""),
            ("manifest", {"layers": []}),
            ("manifest", {"layers": [{"digest": test_pull.DIGEST, "size": 1}]}),
            ("manifest", {"layers": [{"digest": "bad", "size": download.LAYER_BYTES}]}),
        ):
            with self.subTest(field=field, value=value):
                bundle = {**self.bundle, field: value}
                with self.assertRaises(download.DownloadError):
                    pull.resolve_primary_target(test_pull.IMAGE, bundle)
        self.bundle["location"]["RegistryLoginUri"] = "other.azurecr.io"
        with self.assertRaisesRegex(download.DownloadError, "requested registry"):
            pull.resolve_primary_target(test_pull.IMAGE, self.bundle)

    def test_url_cannot_switch_account_container_or_blob(self):
        for before, after in (
            ("dfauemanaged1.blob", "dfauereplica3.blob"),
            ("/primary-container/", "/other-container/"),
            ("/docker/registry/", "/other-prefix/"),
            (test_pull.DIGEST[7:], "a" * 64),
            ("https:", "http:"),
        ):
            with self.subTest(before=before):
                bundle = {**self.bundle, "url": self.bundle["url"].replace(before, after)}
                with self.assertRaises(download.DownloadError):
                    pull.resolve_primary_target(test_pull.IMAGE, bundle)

    def test_sas_must_be_read_only_https_and_blob_scoped(self):
        for before, after in (
            ("sp=r", "sp=rw"), ("sp=r", "sp=w"), ("sp=r", "unused=r"),
            ("sr=b", "sr=c"), ("spr=https", "spr=https,http"),
            ("05%3A00", "02%3A40"),
        ):
            with self.subTest(before=before, after=after):
                bundle = {**self.bundle, "url": self.bundle["url"].replace(before, after)}
                with self.assertRaises(download.DownloadError):
                    pull.resolve_primary_target(test_pull.IMAGE, bundle, start_immediately=True)
        target = pull.resolve_primary_target(test_pull.IMAGE, self.bundle)
        self.assertEqual(parse_qs(urlsplit(target["url"]).query)["sp"], ["r"])

    def test_worker_requires_primary_evidence_even_with_primary_role(self):
        target = pull.resolve_primary_target(test_pull.IMAGE, self.bundle)
        del target["primary_location"]
        with self.assertRaisesRegex(download.DownloadError, "BlobLocation evidence"):
            download.validate_target(target)
        target["storage_role"] = "unknown"
        with self.assertRaisesRegex(download.DownloadError, "storage role"):
            download.validate_target(target)

    def test_invalid_primary_input_never_starts_workers_and_cleans_namespace(self):
        self.bundle["location"]["PrimaryCopy"] = False
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 0)
        self.assertFalse(any(payload and payload["kind"] == "List" for _, payload in self.fixture.calls))
        self.assertEqual(self.fixture.calls[-1][0][:2], ["delete", "namespace"])

    def test_primary_cannot_be_combined_with_warm_traffic(self):
        code, report = self.execute(warm_traffic=True, pull_count=6)
        self.assertEqual(code, 1)
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(report["successful_pulls"], 0)

    def test_partial_primary_failure_preserves_peers_without_retry(self):
        self.fixture.mode = "failure"
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["successful_pulls"], 4)
        self.assertEqual(sum(args[0] == "logs" for args, _ in self.fixture.calls), 5)
        self.assertNotIn("PRIMARY-PRIVATE-SAS", self.fixture.result_file.read_text())

    def test_worker_reporting_replica_role_is_not_accepted_for_primary(self):
        target = pull.resolve_primary_target(test_pull.IMAGE, self.bundle)
        log = {
            "status": "success", "storage_role": "replica",
            "storage_account": target["account"], "blob_digest": target["digest"],
        }
        with self.assertRaisesRegex(download.DownloadError, "does not match"):
            pull.verify_result(log, target)


if __name__ == "__main__":
    unittest.main()
