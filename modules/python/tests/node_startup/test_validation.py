"""Per-iteration validation rules (plan section 6a)."""
import unittest

from node_startup.validation import cni_readiness_signal, required_milestones, validate_iteration
from tests.node_startup import scenarios

VALID_MEASUREMENT = {
    "node_name": scenarios.NODE,
    "pod_created": scenarios.at(0),
    "node_registered": scenarios.at(100),
    "node_ready": scenarios.at(115),
    "cni_pod_scheduled": scenarios.at(101),
    "cni_container_started": scenarios.at(110),
    "cni_pod_ready": scenarios.at(118),
    "cni_taint_cleared": scenarios.at(119),
    "pod_scheduled": scenarios.at(120),
    "container_started": scenarios.at(123),
    "pod_ready": scenarios.at(124),
}


def iteration(existing_nodes=(), defender=False, **overrides):
    return {
        "measurement": {**VALID_MEASUREMENT, **overrides},
        "environment": {"defender_sensor_present": defender},
        "existing_nodes": set(existing_nodes),
    }


def cilium_problems(result, used_nodes=()):
    return validate_iteration(result, set(used_nodes), scenarios.CILIUM_LABEL, scenarios.CILIUM_TAINT)


class RequiredMilestonesTest(unittest.TestCase):
    def test_managed_cilium(self):
        self.assertEqual(required_milestones(scenarios.CILIUM_LABEL, scenarios.CILIUM_TAINT), [
            "pod_created", "node_registered", "node_ready", "pod_scheduled", "container_started", "pod_ready",
            "cni_pod_scheduled", "cni_container_started", "cni_pod_ready", "cni_taint_cleared",
        ])
        self.assertEqual(cni_readiness_signal(scenarios.CILIUM_LABEL), "cni_pod_ready")

    def test_without_cni_pod(self):
        self.assertEqual(required_milestones(None, None), [
            "pod_created", "node_registered", "node_ready", "pod_scheduled", "container_started", "pod_ready",
            "cni_conflist_placed",
        ])
        self.assertEqual(cni_readiness_signal(None), "cni_conflist_placed")


class ValidateIterationTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(cilium_problems(iteration(existing_nodes=[scenarios.EXISTING_NODE])), [])

    def test_equal_whole_second_timestamps_are_allowed(self):
        self.assertEqual(cilium_problems(iteration(node_ready=scenarios.at(100), pod_created=scenarios.at(100))), [])

    def test_missing_required_milestone(self):
        self.assertEqual(cilium_problems(iteration(cni_taint_cleared=None)), ["missing cni_taint_cleared"])

    def test_server_side_order(self):
        self.assertEqual(cilium_problems(iteration(node_registered=scenarios.at(116))), [
            "node_ready (2026-10-02T10:01:55Z) before node_registered (2026-10-02T10:01:56Z)",
            "cni_pod_scheduled (2026-10-02T10:01:41Z) before node_registered (2026-10-02T10:01:56Z)",
        ])

    def test_watch_observed_milestones_are_not_ordered(self):
        self.assertEqual(cilium_problems(iteration(cni_taint_cleared=scenarios.at(50))), [])

    def test_node_not_fresh(self):
        self.assertEqual(cilium_problems(iteration(existing_nodes=[scenarios.NODE])),
                         [f"node {scenarios.NODE} existed before the scale-up"])
        self.assertEqual(cilium_problems(iteration(), used_nodes=[scenarios.NODE]),
                         [f"node {scenarios.NODE} already used by an earlier iteration"])

    def test_defender_sensor(self):
        self.assertEqual(cilium_problems(iteration(defender=True)), ["defender sensor present"])


if __name__ == "__main__":
    unittest.main()
