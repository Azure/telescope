"""Node watch: per-node recording, parity with v1, microsecond observations (plan section 9.4)."""
import threading
import unittest
from datetime import datetime
from unittest import mock

from node_startup.node_watch import new_node_transitions, watch_node_transitions
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, FakeWatch, to_model
from tests.node_startup.golden import V1_GOLDEN
from utils.timestamps import TIMESTAMP_MICROSECONDS_FORMAT, TIMESTAMP_SECONDS_FORMAT


def run_watch(case, stop_event=None):
    """Run the watch over the case's node events; returns {node name: transitions}."""
    nodes = [to_model(node, "V1Node") for node in case["nodes"]]
    instants = iter(scenarios.clock(*instant) for instant in case["clock"])
    recorders = {}
    with mock.patch("kubernetes.watch.Watch", return_value=FakeWatch(nodes)), \
            mock.patch("node_startup.node_watch.utc_now", side_effect=lambda: next(instants)):
        watch_node_transitions(
            FakeCoreV1Api(), existing_nodes={scenarios.EXISTING_NODE}, node_pool_name="userpool",
            node_label_key="agentpool", cni_blocking_taint=case["cni_blocking_taint"], timeout_seconds=900,
            stop_event=stop_event or threading.Event(), recorders=recorders)
    return {name: recorder.transitions for name, recorder in recorders.items()}


def whole_seconds(value):
    """v1 stored each watch observation truncated to whole seconds."""
    return datetime.strptime(value, TIMESTAMP_MICROSECONDS_FORMAT).strftime(TIMESTAMP_SECONDS_FORMAT)


def as_v1(transitions):
    """The transitions as v1 recorded them: observations truncated, without the v2-only history."""
    v1 = {key: whole_seconds(value) if value else value for key, value in transitions.items()
          if key not in ("events", "ready_condition_history")}
    v1["events"] = [{**event, "observed_at": whole_seconds(event["observed_at"])} for event in transitions["events"]]
    return v1


class NodeWatchTest(unittest.TestCase):
    def test_matches_v1_after_truncation(self):
        for name, case in scenarios.WATCH_SCENARIOS.items():
            with self.subTest(scenario=name):
                self.assertEqual(as_v1(run_watch(case)[scenarios.NODE]), V1_GOLDEN["watch"][name])

    def test_observations_have_microseconds(self):
        transitions = run_watch(scenarios.WATCH_SCENARIOS["managed_cilium"])[scenarios.NODE]
        self.assertEqual(transitions["cni_taint_cleared"], "2026-10-02T10:01:55.250000Z")
        self.assertEqual(transitions["cni_conflist_placed_at"], "2026-10-02T10:01:41.000001Z")
        self.assertEqual(transitions["not_ready_taint_observed"], "2026-10-02T10:01:40.400000Z")
        self.assertIsNone(transitions["network_unavailable_taint_observed"])
        # API-server times stay whole seconds.
        self.assertEqual(transitions["events"][0]["creation_timestamp"], "2026-10-02T10:01:40Z")

    def test_each_new_node_is_recorded_separately(self):
        recorded = run_watch(scenarios.TWO_NEW_NODES_WATCH)
        self.assertEqual(set(recorded), {scenarios.NODE, scenarios.OTHER_NEW_NODE})
        # The probe node's transitions are exactly those of the single-node scenario.
        self.assertEqual(recorded[scenarios.NODE], run_watch(scenarios.WATCH_SCENARIOS["managed_cilium"])[scenarios.NODE])
        other = recorded[scenarios.OTHER_NEW_NODE]
        self.assertEqual(other["node_registered_at"], "2026-10-02T10:01:39.000000Z")
        self.assertEqual(other["node_ready_at"], "2026-10-02T10:01:50.000000Z")
        self.assertEqual(other["cni_taint_cleared"], "2026-10-02T10:01:50.000000Z")
        self.assertEqual({event["node"] for event in other["events"]}, {scenarios.OTHER_NEW_NODE})

    def test_ready_condition_history_records_only_changes(self):
        transitions = run_watch(scenarios.WATCH_SCENARIOS["managed_cilium"])[scenarios.NODE]
        self.assertEqual(transitions["ready_condition_history"], [
            {"status": "False", "reason": "KubeletNotReady", "message": scenarios.CNI_NOT_READY,
             "last_transition_time": "2026-10-02T10:01:40Z", "observed_at": "2026-10-02T10:01:40.400000Z"},
            {"status": "False", "reason": "KubeletNotReady", "message": "CSINode is not yet initialized",
             "last_transition_time": "2026-10-02T10:01:40Z", "observed_at": "2026-10-02T10:01:41.000001Z"},
            {"status": "False", "reason": "KubeletNotReady", "message": "kubelet is posting ready status",
             "last_transition_time": "2026-10-02T10:01:40Z", "observed_at": "2026-10-02T10:01:44.999999Z"},
            # The three later Ready=True events are identical, so only the first is kept.
            {"status": "True", "reason": "KubeletReady", "message": "",
             "last_transition_time": "2026-10-02T10:01:55Z", "observed_at": "2026-10-02T10:01:52.500000Z"},
        ])

    def test_stop_event_ends_the_watch_before_any_transition(self):
        stop_event = threading.Event()
        stop_event.set()
        self.assertEqual(run_watch(scenarios.WATCH_SCENARIOS["managed_cilium"], stop_event=stop_event), {})

    def test_new_node_transitions_are_empty(self):
        transitions = new_node_transitions()
        self.assertEqual(transitions["events"], [])
        self.assertIsNone(transitions["node_ready_at"])


if __name__ == "__main__":
    unittest.main()
