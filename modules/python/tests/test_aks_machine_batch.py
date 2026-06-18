#!/usr/bin/env python3
"""Unit tests for AKSMachineClient batch Machine API helpers."""
# pylint: disable=protected-access
import itertools
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from clients.aks_machine_client import AKSMachineClient


class TestAKSMachineBatch(unittest.TestCase):
    """Tests for AKSMachineClient batch helper methods."""

    def setUp(self):
        """Patch Azure SDK seams and construct an AKSMachineClient."""
        self.patchers = (
            mock.patch("clients.aks_client.ContainerServiceClient"),
            mock.patch("clients.aks_client.ManagedIdentityCredential"),
            mock.patch("clients.aks_client.KubernetesClient"),
        )
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        self._tmp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self._tmp_dir.cleanup)
        self.client = AKSMachineClient(
            subscription_id="fake-sub",
            resource_group="fake-rg",
            cluster_name="fake-cluster",
            use_managed_identity=True,
            result_dir=self._tmp_dir.name,
        )

    @staticmethod
    def _request(**overrides):
        """Build the request namespace used by batch helpers."""
        values = {
            "agent_pool_name": "apool",
            "cluster_name": "fake-cluster",
            "resource_group": "fake-rg",
            "vm_size": "Standard_D2_v3",
            "timeout": 60,
            "machine_workers": 2,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_scale_machine_batch_partitions_and_aggregates(self):
        """Names sharded across workers; all successful slices aggregated."""
        names = ["m-1", "m-2", "m-3", "m-4"]
        with mock.patch.object(
            AKSMachineClient,
            "_create_batch_machines",
            side_effect=lambda req, chunk, worker_id: list(chunk),
        ) as mock_create_batch:
            successful = self.client._scale_machine_batch(self._request(), names)
        self.assertEqual(set(successful), set(names))
        self.assertEqual(mock_create_batch.call_count, 2)
        chunk_lengths = [
            len(call.args[1]) for call in mock_create_batch.call_args_list
        ]
        self.assertEqual(sorted(chunk_lengths), [2, 2])

    def test_scale_machine_batch_per_worker_failure_isolated(self):
        """One worker raising does not poison the other worker's success list."""
        names = ["m-1", "m-2", "m-3", "m-4"]
        counter = itertools.count()

        def fake_create(req, chunk, worker_id):  # pylint: disable=unused-argument
            if next(counter) == 0:
                raise RuntimeError("first worker boom")
            return list(chunk)

        with mock.patch.object(
            AKSMachineClient, "_create_batch_machines", side_effect=fake_create
        ):
            successful = self.client._scale_machine_batch(self._request(), names)
        self.assertEqual(len(successful), 2)

    def test_scale_machine_batch_rejects_non_exact_multiple(self):
        """scale_machine_count must be an exact multiple of machine_workers."""
        names = ["m-1", "m-2", "m-3", "m-4"]
        with self.assertRaises(ValueError):
            self.client._scale_machine_batch(self._request(machine_workers=3), names)

    def test_scale_machine_batch_rejects_non_positive_workers(self):
        """machine_workers must be positive."""
        with self.assertRaises(ValueError):
            self.client._scale_machine_batch(
                self._request(machine_workers=0), ["m-1"]
            )

    def test_scale_machine_batch_rejects_calculated_batch_over_limit(self):
        """Fail fast before ARM when calculated per-worker batch size exceeds 50."""
        names = [f"m-{i}" for i in range(1, 1001)]
        with mock.patch.object(
            AKSMachineClient, "_create_batch_machines"
        ) as mock_create_batch:
            with self.assertRaisesRegex(ValueError, "calculated batch size"):
                self.client._scale_machine_batch(
                    self._request(machine_workers=10), names
                )
        mock_create_batch.assert_not_called()

    def test_scale_machine_batch_allows_calculated_batch_at_limit(self):
        """A calculated per-worker batch size of exactly 50 is allowed."""
        names = [f"m-{i}" for i in range(1, 1001)]
        with mock.patch.object(
            AKSMachineClient,
            "_create_batch_machines",
            side_effect=lambda req, chunk, worker_id: list(chunk),
        ) as mock_create_batch:
            successful = self.client._scale_machine_batch(
                self._request(machine_workers=20), names
            )
        self.assertEqual(set(successful), set(names))
        self.assertEqual(mock_create_batch.call_count, 20)
        self.assertTrue(
            all(len(call.args[1]) == 50 for call in mock_create_batch.call_args_list)
        )

    def test_create_batch_machines_empty_chunk_returns_empty(self):
        """Empty chunk -> early return, no HTTP call."""
        with mock.patch.object(
            AKSMachineClient, "_make_batch_request"
        ) as mock_make_batch:
            result = self.client._create_batch_machines(self._request(), [], 0)
        self.assertEqual(result, [])
        mock_make_batch.assert_not_called()

    def test_create_batch_machines_header_shape(self):
        """BatchPutMachine carries vmSkus, batchMachines, and custom features."""
        request = self._request(
            aks_http_custom_features="SomeOtherFeature, DisableSelfContainedVHD"
        )
        with mock.patch.object(
            AKSMachineClient, "_make_batch_request"
        ) as mock_make_batch:
            result = self.client._create_batch_machines(
                request, ["m-1", "m-2", "m-3"], chunk_idx=0
            )
        self.assertEqual(result, ["m-1", "m-2", "m-3"])
        mock_make_batch.assert_called_once()
        kwargs = mock_make_batch.call_args.kwargs
        self.assertEqual(
            kwargs["aks_http_custom_features"],
            "SomeOtherFeature, DisableSelfContainedVHD",
        )
        parsed = json.loads(kwargs["batch_header_value"])
        self.assertIn("vmSkus", parsed)
        self.assertIn("value", parsed["vmSkus"])
        self.assertEqual(len(parsed["vmSkus"]["value"]), 1)
        self.assertEqual(parsed["vmSkus"]["value"][0]["name"], "Standard_D2_v3")
        self.assertEqual(
            parsed["batchMachines"],
            [{"machineName": "m-2"}, {"machineName": "m-3"}],
        )

    def test_create_batch_machines_rejects_oversized_chunk(self):
        """BatchPutMachine rejects more than 50 machines per request client-side."""
        names = [f"m-{i}" for i in range(1, 52)]
        with mock.patch.object(
            AKSMachineClient, "_make_batch_request"
        ) as mock_make_batch:
            with self.assertRaises(ValueError):
                self.client._create_batch_machines(self._request(), names, chunk_idx=0)
        mock_make_batch.assert_not_called()

    def test_make_batch_request_2xx_returns(self):
        """2xx response returns without raising; one HTTP call made."""
        with mock.patch.object(
            self.client._session, "request"
        ) as mock_request:
            mock_request.return_value.status_code = 200
            self.client._make_batch_request(
                "PUT",
                "https://fake/url",
                {"k": "v"},
                timeout=30,
                batch_header_value="{}",
            )
        mock_request.assert_called_once()

    def test_make_batch_request_sends_custom_feature_header(self):
        """BatchPutMachine PUTs include AKSHTTPCustomFeatures when configured."""
        with mock.patch.object(
            self.client._session, "request"
        ) as mock_request:
            mock_request.return_value.status_code = 202
            self.client._make_batch_request(
                "PUT",
                "https://fake/url",
                {"k": "v"},
                timeout=30,
                batch_header_value="{}",
                aks_http_custom_features="SomeOtherFeature, DisableSelfContainedVHD",
            )
        headers = mock_request.call_args.kwargs["headers"]
        self.assertEqual(headers["BatchPutMachine"], "{}")
        self.assertEqual(
            headers["AKSHTTPCustomFeatures"],
            "SomeOtherFeature, DisableSelfContainedVHD",
        )

    def test_make_batch_request_non_2xx_non_429_raises(self):
        """500 -> RuntimeError, no retry."""
        with mock.patch.object(
            self.client._session, "request"
        ) as mock_request:
            mock_request.return_value.status_code = 500
            mock_request.return_value.text = "boom"
            with self.assertRaises(RuntimeError):
                self.client._make_batch_request(
                    "PUT",
                    "https://fake/url",
                    {},
                    timeout=30,
                    batch_header_value="{}",
                )
        self.assertEqual(mock_request.call_count, 1)

    def test_make_batch_request_429_then_success(self):
        """429 then 2xx (201) -> succeeds after 1 retry."""
        responses = [
            mock.MagicMock(status_code=429),
            mock.MagicMock(status_code=201),
        ]
        with mock.patch.object(
            self.client._session, "request", side_effect=responses,
        ) as mock_request, mock.patch(
            "clients.aks_machine_client.time.sleep"
        ):
            self.client._make_batch_request(
                "PUT",
                "https://fake/url",
                {},
                timeout=30,
                batch_header_value="{}",
            )
        self.assertEqual(mock_request.call_count, 2)

    def test_make_batch_request_429_exhausted_raises(self):
        """429 across the full retry budget -> RuntimeError."""
        with mock.patch.object(
            self.client._session, "request"
        ) as mock_request, mock.patch(
            "clients.aks_machine_client.time.sleep"
        ):
            mock_request.return_value.status_code = 429
            mock_request.return_value.text = "rate limited"
            with self.assertRaises(RuntimeError):
                self.client._make_batch_request(
                    "PUT",
                    "https://fake/url",
                    {},
                    timeout=30,
                    batch_header_value="{}",
                )
        self.assertEqual(mock_request.call_count, 5)


if __name__ == "__main__":
    unittest.main()
