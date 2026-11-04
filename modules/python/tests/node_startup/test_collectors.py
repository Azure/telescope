"""CNI pod, scale-up trigger and node environment collectors: parity with v1 plus v2 additions."""
import unittest
from unittest import mock

from clients.kubernetes_client import KubernetesClient
from node_startup import collectors
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, kubernetes_client, to_model
from tests.node_startup.golden import V1_GOLDEN

NEW_CNI_POD_KEYS = {"cni_pod_scheduled_event_time"}


def cni_client(case):
    return kubernetes_client(KubernetesClient,
                             FakeCoreV1Api(pods=case["pods"], events=case["events"], logs=case["logs"]))


def without_operations(v1_entry):
    """v1 also labelled init container operations by matching log text; v2 doesn't."""
    logs = [{key: value for key, value in log.items() if key != "operations"}
            for log in v1_entry.get("init_container_logs", [])]
    return {**v1_entry, "init_container_logs": logs} if "init_container_logs" in v1_entry else v1_entry


def events_of(event_dicts):
    return [to_model(event, "CoreV1Event") for event in event_dicts]


def cilium_pod_timing(k8s):
    return collectors.daemonset_pod_timing(
        k8s, collectors.find_daemonset_pod(k8s, scenarios.NODE, scenarios.CILIUM_LABEL))


class CniPodTimestampsTest(unittest.TestCase):
    def test_matches_v1(self):
        entry = cilium_pod_timing(cni_client(scenarios.CNI_POD_SCENARIOS["cilium_agent"]))
        v1_keys_only = {key: value for key, value in entry.items() if key not in NEW_CNI_POD_KEYS}
        self.assertEqual(v1_keys_only, without_operations(V1_GOLDEN["cni_pod"]["cilium_agent"]))

    def test_no_pod_on_node(self):
        k8s = cni_client(scenarios.CNI_POD_SCENARIOS["no_pod_on_node"])
        self.assertIsNone(collectors.find_daemonset_pod(k8s, scenarios.NODE, scenarios.CILIUM_LABEL))

    def test_scheduled_event_time(self):
        entry = cilium_pod_timing(cni_client(scenarios.CNI_POD_SCENARIOS["cilium_agent"]))
        self.assertEqual(entry["cni_pod_scheduled_event_time"], "2026-10-02T10:01:41.250000Z")
        self.assertEqual(entry["cni_pod_scheduled"], "2026-10-02T10:01:41Z")

    def test_scheduled_event_time_is_none_without_event_time(self):
        events = events_of([scenarios.event(scenarios.CILIUM_POD, "kube-system", "Scheduled",
                                            first_timestamp=scenarios.at(101))])
        self.assertIsNone(collectors.scheduled_event_time(events))

    def test_pod_events_are_listed_once(self):
        case = scenarios.CNI_POD_SCENARIOS["cilium_agent"]
        k8s = cni_client(case)
        with mock.patch.object(k8s.api, "list_namespaced_event", wraps=k8s.api.list_namespaced_event) as list_events:
            cilium_pod_timing(k8s)
        self.assertEqual(list_events.call_count, 1)

    def test_log_lines_without_a_timestamp_prefix_are_skipped(self):
        self.assertEqual(collectors.split_timestamped_log_line("2026-10-02T10:01:43.100000123Z Installing cilium"),
                         ("2026-10-02T10:01:43.100000123Z", "Installing cilium"))
        self.assertIsNone(collectors.split_timestamped_log_line("not a timestamped line"))


class SupplementaryCniPodsTest(unittest.TestCase):
    def test_same_structure_as_cni_pod_and_none_where_absent(self):
        k8s = cni_client(scenarios.CNI_POD_SCENARIOS["cilium_agent"])
        result = collectors.collect_supplementary_cni_pods(
            k8s, scenarios.NODE, {"agent": scenarios.CILIUM_LABEL, "azure_cns": "k8s-app=azure-cns"})
        self.assertEqual(result["agent"], cilium_pod_timing(k8s))
        self.assertIsNone(result["azure_cns"])


class TriggerLookupTest(unittest.TestCase):
    def test_matches_v1(self):
        for name, event_dicts in scenarios.TRIGGER_SCENARIOS.items():
            with self.subTest(scenario=name):
                events = events_of(event_dicts)
                self.assertEqual(collectors.scale_up_trigger_time(events),
                                 V1_GOLDEN["trigger"][name]["triggered_scale_up"])
                self.assertEqual(collectors.first_failed_scheduling_time(events),
                                 V1_GOLDEN["trigger"][name]["first_scheduling_event"])

    def test_listing_errors_return_no_events(self):
        api = FakeCoreV1Api()
        with mock.patch.object(api, "list_namespaced_event", side_effect=RuntimeError("API server unavailable")):
            self.assertEqual(collectors.list_pod_events(api, scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE), [])


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
