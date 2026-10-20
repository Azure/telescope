"""Condition transition times (utils/timestamps.py), as used for node and pod milestones."""
import unittest

from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import to_model
from utils.timestamps import condition_last_transition_time


def conditions(*entries):
    pod = to_model({"metadata": {"name": "p"}, "spec": {"containers": [{"name": "c"}]},
                    "status": {"conditions": [{"type": condition_type, "status": status,
                                               "lastTransitionTime": scenarios.at(second)}
                                              for condition_type, status, second in entries]}}, "V1Pod")
    return pod.status.conditions


class ConditionLastTransitionTimeTest(unittest.TestCase):
    def test_time_when_the_condition_has_the_observed_status(self):
        self.assertEqual(condition_last_transition_time(conditions(("Ready", "True", 15)), "Ready"),
                         "2026-10-02T10:00:15Z")

    def test_none_when_the_condition_has_another_status(self):
        # A Ready=False condition's time is when it became False, not when it became Ready.
        for status in ("False", "Unknown"):
            with self.subTest(status=status):
                self.assertIsNone(condition_last_transition_time(conditions(("Ready", status, 15)), "Ready"))

    def test_observed_status_false(self):
        # NetworkUnavailable clears when it becomes False.
        unavailable = conditions(("NetworkUnavailable", "False", 18), ("Ready", "True", 20))
        self.assertEqual(condition_last_transition_time(unavailable, "NetworkUnavailable", observed_status="False"),
                         "2026-10-02T10:00:18Z")
        self.assertIsNone(condition_last_transition_time(unavailable, "NetworkUnavailable"))

    def test_none_without_the_condition(self):
        self.assertIsNone(condition_last_transition_time(conditions(("Ready", "True", 15)), "PodScheduled"))
        self.assertIsNone(condition_last_transition_time(None, "Ready"))


if __name__ == "__main__":
    unittest.main()
