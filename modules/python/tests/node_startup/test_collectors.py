"""CNI pod, scale-up trigger and node environment collectors: parity with v1 plus v2 additions."""
import unittest
from unittest import mock

from clients.kubernetes_client import KubernetesClient
from node_startup import collectors
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, kubernetes_client, to_model
from tests.node_startup.golden import V1_GOLDEN

NEW_CNI_POD_KEYS = {"cni_pod_scheduled_event_precise"}


def empty_events_v1(*_args, **_kwargs):
    return mock.Mock(list_namespaced_event=mock.Mock(return_value=mock.Mock(items=[])))


def cni_client(case):
    return kubernetes_client(KubernetesClient,
                             FakeCoreV1Api(pods=case["pods"], events=case["events"], logs=case["logs"]))


class CniPodTimestampsTest(unittest.TestCase):
    def test_matches_v1(self):
        for name, case in scenarios.CNI_POD_SCENARIOS.items():
            with self.subTest(scenario=name):
                entry = collectors.collect_cni_pod_timestamps(cni_client(case), scenarios.NODE, scenarios.CILIUM_LABEL)
                v1_keys_only = {key: value for key, value in entry.items() if key not in NEW_CNI_POD_KEYS}
                self.assertEqual(v1_keys_only, V1_GOLDEN["cni_pod"][name])

    def test_scheduled_event_precise(self):
        entry = collectors.collect_cni_pod_timestamps(
            cni_client(scenarios.CNI_POD_SCENARIOS["cilium_agent"]), scenarios.NODE, scenarios.CILIUM_LABEL)
        self.assertEqual(entry["cni_pod_scheduled_event_precise"], "2026-10-02T10:01:41.250000Z")
        self.assertEqual(entry["cni_pod_scheduled"], "2026-10-02T10:01:41Z")

    def test_scheduled_event_precise_is_none_without_event_time(self):
        api = FakeCoreV1Api(events=[scenarios.event(scenarios.CILIUM_POD, "kube-system", "Scheduled",
                                                    first_timestamp=scenarios.at(101))])
        self.assertIsNone(collectors.scheduled_event_precise(api, scenarios.CILIUM_POD, "kube-system"))


class SupplementaryCniPodsTest(unittest.TestCase):
    def test_same_structure_as_cni_pod_and_none_where_absent(self):
        k8s = cni_client(scenarios.CNI_POD_SCENARIOS["cilium_agent"])
        result = collectors.collect_supplementary_cni_pods(
            k8s, scenarios.NODE, {"agent": scenarios.CILIUM_LABEL, "azure_cns": "k8s-app=azure-cns"})
        self.assertEqual(result["agent"],
                         collectors.collect_cni_pod_timestamps(k8s, scenarios.NODE, scenarios.CILIUM_LABEL))
        self.assertIsNone(result["azure_cns"])


class TriggerLookupTest(unittest.TestCase):
    def lookup(self, events):
        api = FakeCoreV1Api(events=events)
        with mock.patch("kubernetes.client.EventsV1Api", side_effect=empty_events_v1):
            triggered = collectors.get_triggered_scale_up_timestamp(
                api, scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE, max_retries=1)
        first_scheduling = collectors.get_first_scheduling_event_timestamp(
            api, scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE)
        return triggered, first_scheduling

    def test_whole_seconds_match_v1(self):
        for name, events in scenarios.TRIGGER_SCENARIOS.items():
            with self.subTest(scenario=name):
                triggered, first_scheduling = self.lookup(events)
                self.assertEqual(triggered[0], V1_GOLDEN["trigger"][name]["triggered_scale_up"])
                self.assertEqual(first_scheduling[0], V1_GOLDEN["trigger"][name]["first_scheduling_event"])

    def test_precise_only_from_event_time(self):
        self.assertEqual(self.lookup(scenarios.TRIGGER_SCENARIOS["triggered_scale_up_whole_second"])[0],
                         ("2026-10-02T10:00:05Z", None))
        self.assertEqual(self.lookup(scenarios.TRIGGER_SCENARIOS["triggered_scale_up_with_event_time"])[0],
                         ("2026-10-02T10:00:05Z", "2026-10-02T10:00:05.432100Z"))
        self.assertEqual(self.lookup(scenarios.TRIGGER_SCENARIOS["failed_scheduling_fallback"])[1],
                         ("2026-10-02T10:00:01Z", "2026-10-02T10:00:01.700000Z"))

    def test_events_v1_fallback(self):
        events_v1_event = mock.Mock(reason="TriggeredScaleUp", event_time=scenarios.clock(6, 5),
                                    metadata=mock.Mock(creation_timestamp=scenarios.clock(6)))
        events_v1 = mock.Mock(list_namespaced_event=mock.Mock(return_value=mock.Mock(items=[events_v1_event])))
        with mock.patch("kubernetes.client.EventsV1Api", return_value=events_v1):
            result = collectors.get_triggered_scale_up_timestamp(
                FakeCoreV1Api(), scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE, max_retries=1)
        self.assertEqual(result, ("2026-10-02T10:00:06Z", "2026-10-02T10:00:06.000005Z"))


class NodeEnvironmentTest(unittest.TestCase):
    def environment(self, pod_names):
        labels = {
            "node.kubernetes.io/instance-type": "Standard_D8s_v3",
            "kubernetes.azure.com/os-sku": "Ubuntu",
            "kubernetes.azure.com/node-image-version": "AKSUbuntu-2204gen2containerd-202609.15.0",
            "topology.kubernetes.io/zone": "0",
        }
        node = scenarios.node(scenarios.NODE, labels=labels)
        pods = [{"metadata": {"name": name, "namespace": "kube-system"},
                 "spec": {"nodeName": scenarios.NODE, "containers": [{"name": "main"}]}} for name in pod_names]
        k8s = kubernetes_client(KubernetesClient, FakeCoreV1Api(all_namespace_pods=pods))
        return collectors.collect_node_environment(k8s, to_model(node, "V1Node"))

    def test_without_defender(self):
        self.assertEqual(self.environment(["cilium-x7k2p", "azure-cns-abcde"]), {
            "defender_sensor_present": False,
            "node_instance_type": "Standard_D8s_v3",
            "node_os_sku": "Ubuntu",
            "node_image_version": "AKSUbuntu-2204gen2containerd-202609.15.0",
            "node_zone": "0",
        })

    def test_with_defender(self):
        self.assertTrue(self.environment(["microsoft-defender-collector-ds-q2x8m"])["defender_sensor_present"])


if __name__ == "__main__":
    unittest.main()
