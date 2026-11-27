"""Regression tests for fresh legacy Job submissions on repeated runs."""

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from kubernetes.client.rest import ApiException

from clients.kubernetes_client import KubernetesClient
from crud.azure.node_pool_crud import NodePoolCRUD


class TestLegacyJobReruns(unittest.TestCase):
    """Keep cleanup outside readiness timing and fail closed on cleanup errors."""

    def setUp(self):
        self.result_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.result_dir)
        self.node_pool_crud = NodePoolCRUD.__new__(NodePoolCRUD)
        self.node_pool_crud.aks_client = mock.Mock()
        self.node_pool_crud.result_dir = str(self.result_dir)
        self.node_pool_crud.step_timeout = 600

    def _legacy_client(self):
        client = mock.Mock()
        self.node_pool_crud.aks_client.k8s_client = client
        client.create_template.side_effect = lambda *args: KubernetesClient.create_template(
            client, *args,
        )
        client.batch.read_namespaced_job.side_effect = ApiException(status=404)
        client.api.list_namespaced_pod.return_value.items = []
        client.get_pods_by_namespace.side_effect = lambda *args, **kwargs: (
            client.api.list_namespaced_pod(
                namespace=args[0], label_selector=kwargs["label_selector"],
            ).items if "label_selector" in kwargs
            else client.get_pods_by_namespace.return_value
        )
        return client

    def _read_operation_info(self):
        files = list(self.result_dir.iterdir())
        self.assertEqual(len(files), 1)
        operation = json.loads(files[0].read_text(encoding="utf-8"))["operation_info"]
        files[0].unlink()
        return operation

    def test_legacy_job_reruns_wait_for_old_controller_and_pods(self):
        client = self._legacy_client()
        state = SimpleNamespace(exists=True, reads=0, pod_reads=0, elapsed=0, runs=0)
        old_pod = SimpleNamespace(metadata=SimpleNamespace(name="pi-test-pool-old"))

        def delete(**_kwargs):
            state.reads = 0
            state.pod_reads = 0

        def read(**_kwargs):
            state.reads += 1
            if state.reads == 1:
                return SimpleNamespace()
            state.exists = False
            raise ApiException(status=404)

        def pods(*_args, **kwargs):
            if "label_selector" in kwargs:
                state.pod_reads += 1
                return [old_pod] if state.pod_reads == 1 else []
            self.assertTrue(state.exists)
            return [SimpleNamespace(metadata=SimpleNamespace(
                name=f"pi-test-pool-run-{state.runs}",
            ))]

        def create(**kwargs):
            self.assertFalse(state.exists, "The previous Job must be gone before create")
            self.assertEqual(state.pod_reads, 2, "Old pods must be gone before create")
            self.assertEqual(kwargs["body"]["metadata"]["name"], "pi-test-pool")
            state.exists = True
            state.runs += 1

        def apply(**kwargs):
            KubernetesClient._apply_single_manifest(  # pylint: disable=protected-access
                client, kwargs["manifest_dict"], kwargs["namespace"],
            )

        def sleep(seconds):
            state.elapsed += seconds

        client.batch.delete_namespaced_job.side_effect = delete
        client.batch.read_namespaced_job.side_effect = read
        client.batch.create_namespaced_job.side_effect = create
        client.apply_manifest_from_file.side_effect = apply
        client.get_pods_by_namespace.side_effect = pods
        start = datetime(2026, 11, 6, tzinfo=timezone.utc)
        with (
            mock.patch("crud.azure.node_pool_crud.time.sleep", side_effect=sleep),
            mock.patch("crud.azure.node_pool_crud.time.monotonic",
                       side_effect=lambda: state.elapsed),
            mock.patch("crud.azure.node_pool_crud.datetime") as clock,
        ):
            clock.now.side_effect = lambda *_args: start + timedelta(seconds=state.elapsed)
            for _ in range(2):
                self.assertTrue(self.node_pool_crud.create_job(
                    "test-pool", workload_profile="legacy-shell",
                ))
                metadata = self._read_operation_info()["metadata"]
                self.assertEqual(metadata["workload_readiness_time"], 1)
        self.assertEqual(state.runs, 2)
        self.assertEqual(client.batch.create_namespaced_job.call_count, 2)
        client._update_single_manifest.assert_not_called()  # pylint: disable=protected-access
        self.assertEqual(
            metadata["workload_start_timestamp"], (start + timedelta(seconds=5)).isoformat(),
        )

    @mock.patch("crud.azure.node_pool_crud.time.sleep")
    def test_legacy_job_cleanup_accepts_missing_job(self, sleeper):
        client = self._legacy_client()
        client.batch.delete_namespaced_job.side_effect = ApiException(status=404)
        client.get_pods_by_namespace.return_value = [
            SimpleNamespace(metadata=SimpleNamespace(name="pi-test-pool-new")),
        ]
        self.assertTrue(self.node_pool_crud.create_job(
            "test-pool", workload_profile="legacy-shell",
        ))
        client.get_pods_by_namespace.assert_any_call(
            "default", label_selector="job-name=pi-test-pool",
        )
        client.apply_manifest_from_file.assert_called_once()
        sleeper.assert_called_once_with(1)

    @mock.patch("crud.azure.node_pool_crud.time.sleep")
    def test_legacy_job_cleanup_errors_stop_submission(self, sleeper):
        for stage, error in (
            ("delete", ApiException(status=403)),
            ("delete", RuntimeError("delete failed")),
            ("read", ApiException(status=403)),
            ("pods", ApiException(status=500)),
        ):
            with self.subTest(stage=stage, error=error):
                client = self._legacy_client()
                if stage == "delete":
                    client.batch.delete_namespaced_job.side_effect = error
                elif stage == "read":
                    client.batch.read_namespaced_job.side_effect = error
                else:
                    client.api.list_namespaced_pod.side_effect = error
                self.assertFalse(self.node_pool_crud.create_job(
                    "test-pool", workload_profile="legacy-shell",
                ))
                client.apply_manifest_from_file.assert_not_called()
                operation = self._read_operation_info()
                self.assertFalse(operation["success"])
                self.assertIn(str(error), operation["error_message"])
        sleeper.assert_not_called()

    def test_legacy_job_cleanup_timeout_stops_submission(self):
        for remaining in ("job", "pods"):
            with self.subTest(remaining=remaining):
                client = self._legacy_client()
                if remaining == "job":
                    client.batch.read_namespaced_job.side_effect = None
                else:
                    client.api.list_namespaced_pod.return_value.items = [mock.Mock()]
                self.node_pool_crud.step_timeout = 2
                with (
                    mock.patch("crud.azure.node_pool_crud.time.monotonic",
                               side_effect=[0, 0, 1, 2]),
                    mock.patch("crud.azure.node_pool_crud.time.sleep") as sleeper,
                ):
                    self.assertFalse(self.node_pool_crud.create_job(
                        "test-pool", workload_profile="legacy-shell",
                    ))
                client.apply_manifest_from_file.assert_not_called()
                self.assertEqual(sleeper.call_args_list, [mock.call(1)] * 2)
                operation = self._read_operation_info()
                self.assertFalse(operation["success"])
                self.assertIn("cleanup", operation["error_message"])
                self.assertNotIn("workload_readiness_time", operation["metadata"])
