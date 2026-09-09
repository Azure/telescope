import json
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

from vmagent_loadtest.runner import (
    _namespace_blocked_only_on_discovery,
    _wait_ns_gone,
)


def _namespace(remaining_content="False", remaining_finalizers="False"):
    return {
        "metadata": {"deletionTimestamp": "2026-08-24T19:02:03Z"},
        "status": {
            "conditions": [
                {"type": "NamespaceDeletionDiscoveryFailure", "status": "True"},
                {"type": "NamespaceContentRemaining", "status": remaining_content},
                {"type": "NamespaceFinalizersRemaining", "status": remaining_finalizers},
            ]
        },
    }


class TestNamespaceCleanup(unittest.TestCase):
    def test_discovery_failure_is_safe_only_after_content_and_finalizers_are_gone(self):
        self.assertTrue(_namespace_blocked_only_on_discovery(_namespace()))
        self.assertFalse(_namespace_blocked_only_on_discovery(_namespace(remaining_content="True")))
        self.assertFalse(_namespace_blocked_only_on_discovery(_namespace(remaining_finalizers="True")))

    @patch("vmagent_loadtest.runner._force_clear_namespace")
    @patch("vmagent_loadtest.runner.kubectl")
    def test_wait_force_clears_empty_namespace_blocked_by_discovery(self, kubectl, force_clear):
        kubectl.side_effect = [
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(returncode=0, stdout=json.dumps(_namespace())),
            SimpleNamespace(returncode=1, stdout=""),
        ]

        _wait_ns_gone("cluster.kubeconfig", "loadtest-ramp", timeout=10)

        force_clear.assert_called_once_with("cluster.kubeconfig", "loadtest-ramp")
        self.assertEqual(
            kubectl.call_args_list,
            [
                call("cluster.kubeconfig", "delete", "ns", "loadtest-ramp",
                     "--wait=false", check=False),
                call("cluster.kubeconfig", "get", "ns", "loadtest-ramp",
                     "-o", "json", check=False),
                call("cluster.kubeconfig", "get", "ns", "loadtest-ramp",
                     "-o", "json", check=False),
            ],
        )

    @patch("vmagent_loadtest.runner.time.sleep")
    @patch("vmagent_loadtest.runner.time.monotonic", side_effect=[0, 0.1, 2])
    @patch("vmagent_loadtest.runner._force_clear_namespace")
    @patch("vmagent_loadtest.runner.kubectl")
    def test_wait_does_not_force_clear_namespace_with_remaining_content(
        self, kubectl, force_clear, monotonic, sleep,
    ):
        kubectl.side_effect = [
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps(_namespace(remaining_content="True")),
            ),
        ]

        _wait_ns_gone("cluster.kubeconfig", "loadtest-ramp", timeout=1)

        force_clear.assert_not_called()
        sleep.assert_called_once_with(5)


if __name__ == "__main__":
    unittest.main()
