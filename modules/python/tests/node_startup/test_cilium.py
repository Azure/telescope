"""Cilium metrics: parsing parity with v1 and scrape fallbacks."""
import unittest
from unittest import mock

from clients.kubernetes_client import KubernetesClient
from node_startup.cilium import parse_cilium_metrics, scrape_cilium_metrics
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, kubernetes_client
from tests.node_startup.golden import V1_GOLDEN


class ParseCiliumMetricsTest(unittest.TestCase):
    def test_matches_v1(self):
        for name, text in scenarios.CILIUM_METRICS_SCENARIOS.items():
            with self.subTest(scenario=name):
                self.assertEqual(parse_cilium_metrics(text), V1_GOLDEN["cilium_metrics"][name])

    def test_values(self):
        parsed = parse_cilium_metrics(scenarios.CILIUM_METRICS_SCENARIOS["legacy_identity_count"])
        self.assertEqual(parsed["bootstrap"], {"overall": 12.5, "k8sInit": 3.25, "restore": 0.75})
        self.assertEqual(parsed["endpoint_regen"], {"total": 0.5, "policyCalculation": 0, "sumOnly": 0})
        self.assertEqual(parsed["metadata"], {"cilium_identity_count": 42, "cilium_bpf_map_pressure": 0.02,
                                              "cilium_version": "go1.23"})


class ScrapeCiliumMetricsTest(unittest.TestCase):
    def client(self, metrics_text):
        api = FakeCoreV1Api(pods=[scenarios.cilium_pod()], metrics_text=metrics_text)
        return kubernetes_client(KubernetesClient, api)

    def test_api_proxy(self):
        k8s = self.client(scenarios.CILIUM_METRICS_TEXT)
        with mock.patch.object(KubernetesClient, "run_pod_exec_command", return_value="DISCOVERY_FAILED"):
            result = scrape_cilium_metrics(k8s, scenarios.NODE, scenarios.CILIUM_LABEL)
        self.assertEqual(result, parse_cilium_metrics(scenarios.CILIUM_METRICS_TEXT))

    def test_exec_fallback_when_proxy_fails(self):
        k8s = self.client(None)
        with mock.patch.object(KubernetesClient, "run_pod_exec_command",
                               side_effect=["DISCOVERY_FAILED", scenarios.CILIUM_METRICS_TEXT]) as exec_command:
            result = scrape_cilium_metrics(k8s, scenarios.NODE, scenarios.CILIUM_LABEL)
        self.assertEqual(result, parse_cilium_metrics(scenarios.CILIUM_METRICS_TEXT))
        self.assertIn("http://localhost:9962/metrics", exec_command.call_args_list[1].kwargs["command"])
        self.assertEqual(exec_command.call_args_list[1].kwargs["container_name"], "cilium-agent")

    def test_port_from_runtime_config(self):
        k8s = self.client(None)
        with mock.patch.object(KubernetesClient, "run_pod_exec_command",
                               side_effect=[":9090", scenarios.CILIUM_METRICS_TEXT]) as exec_command:
            scrape_cilium_metrics(k8s, scenarios.NODE, scenarios.CILIUM_LABEL)
        self.assertIn("http://localhost:9090/metrics", exec_command.call_args_list[1].kwargs["command"])

    def test_none_without_agent_pod(self):
        k8s = kubernetes_client(KubernetesClient, FakeCoreV1Api())
        self.assertIsNone(scrape_cilium_metrics(k8s, scenarios.NODE, scenarios.CILIUM_LABEL))

    def test_none_when_both_methods_fail(self):
        k8s = self.client(None)
        with mock.patch.object(KubernetesClient, "run_pod_exec_command", side_effect=["DISCOVERY_FAILED", "short"]):
            self.assertIsNone(scrape_cilium_metrics(k8s, scenarios.NODE, scenarios.CILIUM_LABEL))


if __name__ == "__main__":
    unittest.main()
