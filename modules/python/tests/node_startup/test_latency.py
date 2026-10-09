"""Parity of the derived metrics with v1 (plan section 9.1)."""
import unittest

from node_startup.latency import PRECISE_LATENCIES, compute_autoscale_latencies, compute_precise_latencies
from tests.node_startup import scenarios
from tests.node_startup.golden import V1_GOLDEN as GOLDEN

DROPPED_ALIASES = {
    "node_ready_after_register_seconds": "node_init_seconds",
    "cilium_init_duration_seconds": "cni_init_seconds",
    "cni_induced_delay_seconds": "cilium_scheduling_block_seconds",
    "pod_init_seconds": "sandbox_setup_seconds",
    "node_to_pod_seconds": "time_to_runnable_seconds",
}


class LatencyParityTest(unittest.TestCase):
    def test_every_scenario_matches_v1_without_aliases(self):
        for name, timestamps in scenarios.LATENCY_SCENARIOS.items():
            with self.subTest(scenario=name):
                expected = {key: value for key, value in GOLDEN["latency"][name].items()
                            if key not in DROPPED_ALIASES}
                self.assertEqual(compute_autoscale_latencies(timestamps), expected)

    def test_dropped_aliases_equal_their_replacements_in_v1(self):
        for name, v1_latencies in GOLDEN["latency"].items():
            for alias, replacement in DROPPED_ALIASES.items():
                with self.subTest(scenario=name, alias=alias):
                    self.assertEqual(v1_latencies[alias], v1_latencies[replacement])

    def test_managed_cilium_headline_values(self):
        latencies = compute_autoscale_latencies(scenarios.MANAGED_CILIUM_TIMESTAMPS)
        self.assertEqual(latencies["time_to_runnable_seconds"], 23.0)
        self.assertEqual(latencies["node_init_seconds"], 15.0)
        self.assertEqual(latencies["cni_init_seconds"], 8.0)
        self.assertEqual(latencies["cilium_scheduling_block_seconds"], 3.0)
        self.assertEqual(latencies["total_e2e_seconds"], 124.0)
        self.assertEqual(latencies["cilium_bootstrap_overall_seconds"], 12.5)
        self.assertEqual(latencies["cilium_version"], "1.19.3")
        for alias in DROPPED_ALIASES:
            self.assertNotIn(alias, latencies)


# Watch observations of the node, in the pipeline agent's clock.
WATCH_OBSERVATIONS = {
    "ready_condition_history": [{"status": "False"}, {"status": "True"}],
    "node_registered_observed_precise": scenarios.at(100, 400000),
    "node_ready_observed_precise": scenarios.at(115, 250000),
    "cni_conflist_placed_precise": scenarios.at(112, 100000),
    "csinode_ready_precise": scenarios.at(105, 999999),
    "not_ready_taint_observed_precise": scenarios.at(100, 400000),
    "not_ready_taint_cleared_precise": scenarios.at(116, 1),
    "cni_taint_observed_precise": scenarios.at(100, 600000),
    "cni_taint_cleared_precise": scenarios.at(114, 800000),
    "network_unavailable_taint_observed_precise": None,
    "network_unavailable_taint_cleared_precise": None,
}


class PreciseLatencyTest(unittest.TestCase):
    def test_values_are_rounded_to_milliseconds(self):
        self.assertEqual(compute_precise_latencies(WATCH_OBSERVATIONS), {
            "node_init_precise_seconds": 14.85,
            "cni_conflist_install_precise_seconds": 11.7,
            "csinode_ready_precise_seconds": 5.6,
            "not_ready_taint_precise_seconds": 15.6,
            "cni_taint_precise_seconds": 14.4,
            "network_unavailable_taint_precise_seconds": None,
            "not_ready_taint_active_precise_seconds": 15.6,
            "cni_taint_active_precise_seconds": 14.2,
            "network_unavailable_taint_active_precise_seconds": None,
            # Signed like its whole-second twin: negative when the CNI taint clears before Ready.
            "node_ready_to_cni_clear_precise_seconds": -0.45,
        })

    def test_all_none_when_the_watch_first_saw_the_node_ready(self):
        for history in ([{"status": "True"}], []):
            with self.subTest(history=history):
                latencies = compute_precise_latencies({**WATCH_OBSERVATIONS, "ready_condition_history": history})
                self.assertEqual(latencies, dict.fromkeys(PRECISE_LATENCIES))

    def test_whole_second_latencies_are_unchanged(self):
        timestamps = {**scenarios.MANAGED_CILIUM_TIMESTAMPS, **WATCH_OBSERVATIONS}
        self.assertEqual(compute_autoscale_latencies(timestamps),
                         compute_autoscale_latencies(scenarios.MANAGED_CILIUM_TIMESTAMPS))


if __name__ == "__main__":
    unittest.main()
