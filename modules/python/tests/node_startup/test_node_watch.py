"""Node watch state machine: parity with v1 and the v2 precise timestamps (plan section 9.4)."""
import threading
import unittest
from datetime import datetime
from unittest import mock

from node_startup.node_watch import new_watch_result, watch_node_transitions
from node_startup.timestamps import PRECISE_FORMAT, WHOLE_SECOND_FORMAT
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, FakeWatch, to_model
from tests.node_startup.golden import V1_GOLDEN


def run_watch(case, stop_event=None):
    nodes = [to_model(node, "V1Node") for node in case["nodes"]]
    instants = iter(scenarios.clock(*instant) for instant in case["clock"])
    with mock.patch("kubernetes.watch.Watch", return_value=FakeWatch(nodes)):
        return watch_node_transitions(
            FakeCoreV1Api(), existing_nodes={scenarios.EXISTING_NODE}, node_pool_name="userpool",
            cni_blocking_taint=case["cni_blocking_taint"], stop_event=stop_event,
            clock=lambda: next(instants))


def v1_fields(result):
    """The watch result without the keys v2 added (`*_precise`, `ready_condition_history`)."""
    stripped = {key: value for key, value in result.items()
                if not key.endswith("_precise") and key != "ready_condition_history"}
    stripped["events"] = [{key: value for key, value in event.items() if key != "observed_at_precise"}
                          for event in result["events"]]
    return stripped


class NodeWatchTest(unittest.TestCase):
    def test_matches_v1(self):
        for name, case in scenarios.WATCH_SCENARIOS.items():
            with self.subTest(scenario=name):
                self.assertEqual(v1_fields(run_watch(case)), V1_GOLDEN["watch"][name])

    def test_precise_values_truncate_to_whole_seconds(self):
        for name, case in scenarios.WATCH_SCENARIOS.items():
            result = run_watch(case)
            for key, value in result.items():
                if key.endswith("_precise") and value is not None:
                    with self.subTest(scenario=name, key=key):
                        whole = result[key[:-len("_precise")]]
                        self.assertEqual(datetime.strptime(value, PRECISE_FORMAT).strftime(WHOLE_SECOND_FORMAT), whole)
            for event in result["events"] + result["ready_condition_history"]:
                with self.subTest(scenario=name, event=event.get("event") or event.get("status")):
                    self.assertEqual(datetime.strptime(event["observed_at_precise"], PRECISE_FORMAT)
                                     .strftime(WHOLE_SECOND_FORMAT), event["observed_at"])

    def test_managed_cilium_precise_values(self):
        result = run_watch(scenarios.WATCH_SCENARIOS["managed_cilium"])
        self.assertEqual(result["cni_taint_cleared_precise"], "2026-10-02T10:01:55.250000Z")
        self.assertEqual(result["cni_conflist_placed_at_precise"], "2026-10-02T10:01:41.000001Z")
        self.assertEqual(result["not_ready_taint_observed_precise"], "2026-10-02T10:01:40.400000Z")
        self.assertIsNone(result["network_unavailable_taint_observed_precise"])

    def test_ready_condition_history_records_only_changes(self):
        result = run_watch(scenarios.WATCH_SCENARIOS["managed_cilium"])
        self.assertEqual(result["ready_condition_history"], [
            {"status": "False", "reason": "KubeletNotReady", "message": scenarios.CNI_NOT_READY,
             "last_transition_time": "2026-10-02T10:01:40Z",
             "observed_at": "2026-10-02T10:01:40Z", "observed_at_precise": "2026-10-02T10:01:40.400000Z"},
            {"status": "False", "reason": "KubeletNotReady", "message": "CSINode is not yet initialized",
             "last_transition_time": "2026-10-02T10:01:40Z",
             "observed_at": "2026-10-02T10:01:41Z", "observed_at_precise": "2026-10-02T10:01:41.000001Z"},
            {"status": "False", "reason": "KubeletNotReady", "message": "kubelet is posting ready status",
             "last_transition_time": "2026-10-02T10:01:40Z",
             "observed_at": "2026-10-02T10:01:44Z", "observed_at_precise": "2026-10-02T10:01:44.999999Z"},
            # The three later Ready=True events are identical, so only the first is kept.
            {"status": "True", "reason": "KubeletReady", "message": "",
             "last_transition_time": "2026-10-02T10:01:55Z",
             "observed_at": "2026-10-02T10:01:52Z", "observed_at_precise": "2026-10-02T10:01:52.500000Z"},
        ])

    def test_stop_event_ends_the_watch_before_any_transition(self):
        stop_event = threading.Event()
        stop_event.set()
        result = run_watch(scenarios.WATCH_SCENARIOS["managed_cilium"], stop_event=stop_event)
        self.assertEqual(result, new_watch_result())

    def test_precise_format(self):
        result = run_watch(scenarios.WATCH_SCENARIOS["first_event_already_ready"])
        self.assertEqual(result["node_ready_at_precise"],
                         scenarios.clock(109, 123456).strftime(PRECISE_FORMAT))


if __name__ == "__main__":
    unittest.main()
