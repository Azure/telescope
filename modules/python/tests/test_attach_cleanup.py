"""Exercise the Azure attach step without contacting Kubernetes."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


class TestAttachCleanup(unittest.TestCase):
    def run_step(self, status, namespace="test-12345", cleanup_status=0,
                 terminate=False, progress="complete"):
        root = Path(__file__).resolve().parents[3]
        step = yaml.safe_load(
            (root / "steps/engine/attach/execute-azure.yml").read_text(encoding="utf-8")
        )["steps"][0]["script"]
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "namespace"
            mocks = """
mktemp() { printf '%s\\n' "$MOCK_MARKER"; }
timeout() {
    printf '%s' "$MOCK_NAMESPACE" > "$CSI_NAMESPACE_FILE"
    if [[ "$MOCK_TERMINATE" == "true" ]]; then
        kill -TERM "$$"
    fi
    return "$MOCK_STATUS"
}
kubectl() {
    if [[ "$1" == "delete" ]]; then
        printf 'KUBECTL:%s\\n' "$*"
        return "$MOCK_CLEANUP_STATUS"
    fi
    printf 'QUERY:%s\\n' "$*" >&2
    if [[ "$MOCK_PROGRESS" == "query-error" && "$1 $2" == "get volumeattachments" ]]; then
        return 1
    fi
    if [[ "$1 $2" == "get pv" &&
          ( "$MOCK_ROUND" -eq 0 || "$MOCK_PROGRESS" == "stuck-pv" ) ]]; then
        printf '%s\\n' '{"items":[{"metadata":{"name":"test-pv"},"spec":{"claimRef":{"namespace":"test-12345"}}}]}'
    elif [[ "$1 $2" == "get statefulsets,pods,pvc" &&
            "$MOCK_ROUND" -eq 0 && "$MOCK_PROGRESS" == "delayed" ]]; then
        printf '%s\\n' '{"items":[{"kind":"Pod","metadata":{"name":"statefulset-local-0"}}]}'
    elif [[ "$1 $2" == "get volumeattachments" &&
            ( "$MOCK_PROGRESS" == "stuck-attachment" ||
              ( "$MOCK_PROGRESS" == "delayed" && "$MOCK_ROUND" -eq 0 ) ) ]]; then
        printf '%s\\n' '{"items":[{"metadata":{"name":"test-attachment"},"spec":{"source":{"persistentVolumeName":"test-pv"}}}]}'
    elif [[ "$1 $2" == "get volumeattachments" ]]; then
        printf '%s\\n' '{"items":[{"metadata":{"name":"other-attachment"},"spec":{"source":{"persistentVolumeName":"other-pv"}}}]}'
    else
        printf '%s\\n' '{"items":[]}'
    fi
}
MOCK_ROUND=0
sleep() {
    printf 'POLL_WAIT\\n'
    MOCK_ROUND=$((MOCK_ROUND + 1))
    if [[ "$MOCK_PROGRESS" == stuck-* ]]; then
        SECONDS=$((SECONDS + 901))
    fi
}
"""
            result = subprocess.run(
                ["bash"], input=mocks + step, text=True, capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "MOCK_MARKER": str(marker),
                    "MOCK_NAMESPACE": namespace,
                    "MOCK_STATUS": str(status),
                    "MOCK_CLEANUP_STATUS": str(cleanup_status),
                    "MOCK_TERMINATE": str(terminate).lower(),
                    "MOCK_PROGRESS": progress,
                    "EXECUTION_TIMEOUT_MINUTES": "60",
                    "PYTHON_SCRIPT_FILE": "mock.py",
                    "DISK_NUMBER": "200",
                    "STORAGE_CLASS": "default",
                    "WAIT_TIME": "300",
                    "RESULT_DIR": directory,
                },
            )
            self.assertFalse(marker.exists())
            return result

    def test_failure_and_timeout_delete_only_test_workload(self):
        for status in (1, 124, 137):
            with self.subTest(status=status):
                result = self.run_step(status)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn(
                    "KUBECTL:delete statefulset statefulset-local --namespace test-12345",
                    result.stdout,
                )
                self.assertIn("KUBECTL:delete pvc --all --namespace test-12345", result.stdout)

    def test_success_does_not_repeat_cleanup(self):
        result = self.run_step(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("KUBECTL:", result.stdout)

    def test_missing_or_invalid_namespace_cannot_delete_other_workloads(self):
        for namespace in ("", "default"):
            with self.subTest(namespace=namespace):
                result = self.run_step(1, namespace=namespace)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn("KUBECTL:", result.stdout)

    def test_cleanup_errors_are_reported_and_original_failure_is_preserved(self):
        result = self.run_step(124, cleanup_status=1)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("Failed to delete StatefulSet", result.stdout)
        self.assertIn("Failed to delete PVCs", result.stdout)

    def test_termination_requests_cleanup(self):
        result = self.run_step(0, terminate=True)
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertIn("KUBECTL:delete statefulset", result.stdout)
        self.assertIn("KUBECTL:delete pvc", result.stdout)

    def test_waits_for_pods_volumes_and_attachments(self):
        result = self.run_step(124, progress="delayed")
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("--cascade=foreground", result.stdout)
        self.assertIn("Remaining PVs: [\"test-pv\"]", result.stdout)
        self.assertIn('VolumeAttachments: ["test-attachment"]', result.stdout)
        self.assertLess(
            result.stdout.index("POLL_WAIT"),
            result.stdout.index("have been removed."),
        )
        self.assertNotIn("exceeded 15 minutes", result.stdout)

    def test_stuck_volumes_or_attachments_hit_cleanup_deadline(self):
        for progress in ("stuck-pv", "stuck-attachment"):
            with self.subTest(progress=progress):
                result = self.run_step(124, progress=progress)
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertIn("exceeded 15 minutes", result.stdout)
                self.assertNotIn("have been removed.", result.stdout)

    def test_query_error_is_not_reported_as_successful_deletion(self):
        result = self.run_step(124, progress="query-error")
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("Failed to query workload deletion progress", result.stdout)
        self.assertNotIn("have been removed.", result.stdout)
