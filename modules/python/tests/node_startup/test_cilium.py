"""Cilium metrics: parsing parity with v1 and scrape fallbacks."""
import unittest
from unittest import mock

from clients.kubernetes_client import KubernetesClient
from node_startup.cilium import metric_labels, parse_cilium_metrics, scrape_cilium_metrics
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, kubernetes_client, to_model
from tests.node_startup.golden import V1_GOLDEN

# What a Cilium 1.19 agent exposes. The Go runtime's own version is in a different metric.
CILIUM_VERSION_LINES = "\n".join([
    'go_info{version="go1.24.4"} 1',
    'cilium_version{arch="amd64",revision="5d4a3b2",version="1.19.6"} 1',
])


class ParseCiliumMetricsTest(unittest.TestCase):
    def test_matches_v1_except_the_version(self):
        # v1 read the version from `cilium_version_info`, which Cilium doesn't expose, and took the
        # first label ending in `version`, here `go_version`. v2 reads only `cilium_version{version=...}`.
        for name, text in scenarios.CILIUM_METRICS_SCENARIOS.items():
            with self.subTest(scenario=name):
                expected = V1_GOLDEN["cilium_metrics"][name]
                expected = {**expected, "metadata": {**expected["metadata"], "cilium_version": None}}
                self.assertEqual(parse_cilium_metrics(text), expected)

    def test_values(self):
        parsed = parse_cilium_metrics(scenarios.CILIUM_METRICS_SCENARIOS["legacy_identity_count"])
        self.assertEqual(parsed["bootstrap"], {"overall": 12.5, "k8sInit": 3.25, "restore": 0.75})
        self.assertEqual(parsed["endpoint_regen"], {"total": 0.5, "policyCalculation": 0, "sumOnly": 0})
        self.assertEqual(parsed["metadata"], {"cilium_identity_count": 42, "cilium_bpf_map_pressure": 0.02,
                                              "cilium_version": None})

    def test_version_is_the_agent_build_not_the_go_runtime(self):
        parsed = parse_cilium_metrics(scenarios.CILIUM_METRICS_TEXT + "\n" + CILIUM_VERSION_LINES)
        self.assertEqual(parsed["metadata"]["cilium_version"], "1.19.6")

    def test_metric_labels(self):
        self.assertEqual(metric_labels('cilium_version{arch="amd64",revision="5d4a3b2",version="1.19.6"} 1'),
                         {"arch": "amd64", "revision": "5d4a3b2", "version": "1.19.6"})
        self.assertEqual(metric_labels('m{go_version="go1.23",version="1.19.3"} 1')["version"], "1.19.3")
        self.assertEqual(metric_labels('m{path="a\\"b,c"} 1'), {"path": 'a\\"b,c'})
        self.assertEqual(metric_labels("cilium_identity_count 42"), {})


class ScrapeCiliumMetricsTest(unittest.TestCase):
    def client(self, metrics_text):
        api = FakeCoreV1Api(pods=[scenarios.cilium_pod()], metrics_text=metrics_text)
        return kubernetes_client(KubernetesClient, api)

    def scrape(self, k8s):
        return scrape_cilium_metrics(k8s, to_model(scenarios.cilium_pod(), "V1Pod"))

    def test_api_proxy(self):
        k8s = self.client(scenarios.CILIUM_METRICS_TEXT)
        with mock.patch.object(KubernetesClient, "run_pod_exec_command", return_value="DISCOVERY_FAILED"):
            result = self.scrape(k8s)
        self.assertEqual(result, parse_cilium_metrics(scenarios.CILIUM_METRICS_TEXT))

    def test_exec_fallback_when_proxy_fails(self):
        k8s = self.client(None)
        with mock.patch.object(KubernetesClient, "run_pod_exec_command",
                               side_effect=["DISCOVERY_FAILED", scenarios.CILIUM_METRICS_TEXT]) as exec_command:
            result = self.scrape(k8s)
        self.assertEqual(result, parse_cilium_metrics(scenarios.CILIUM_METRICS_TEXT))
        self.assertIn("http://localhost:9962/metrics", exec_command.call_args_list[1].kwargs["command"])
        self.assertEqual(exec_command.call_args_list[1].kwargs["container_name"], "cilium-agent")

    def test_port_from_runtime_config(self):
        k8s = self.client(None)
        with mock.patch.object(KubernetesClient, "run_pod_exec_command",
                               side_effect=[":9090", scenarios.CILIUM_METRICS_TEXT]) as exec_command:
            self.scrape(k8s)
        self.assertIn("http://localhost:9090/metrics", exec_command.call_args_list[1].kwargs["command"])

    def test_none_when_both_methods_fail(self):
        k8s = self.client(None)
        with mock.patch.object(KubernetesClient, "run_pod_exec_command", side_effect=["DISCOVERY_FAILED", "short"]):
            self.assertIsNone(self.scrape(k8s))


if __name__ == "__main__":
    unittest.main()
