"""One full iteration against a fake cluster: key parity with v1 and values end to end."""
import unittest
from unittest import mock

from clients.kubernetes_client import KubernetesClient
from node_startup import probe
from node_startup.iteration import measure_iteration
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, FakeWatch, kubernetes_client, to_model

# Keys of v1 `collect_autoscale_latency` output; main.py adds v1's iteration/total_iterations.
V1_MEASUREMENT_KEYS = {
    "node_name", "pod_name", "pod_created", "triggered_scale_up", "node_registered", "node_ready",
    "node_network_unavailable_cleared", "cni_conflist_placed", "csinode_ready", "not_ready_taint_observed",
    "not_ready_taint_cleared", "network_unavailable_taint_observed", "network_unavailable_taint_cleared",
    "cni_taint_observed", "cni_taint_cleared", "cni_container_started", "cni_pod_ready", "cni_pod_scheduled",
    "cni_init_containers", "cni_containers", "cni_image_pull_events", "cni_init_container_logs",
    "deep_cilium_metrics", "pod_scheduled", "pod_initialized", "container_started", "containers_ready",
    "pod_ready", "intermediate_states", "latencies",
}
NEW_MEASUREMENT_KEYS = {
    "triggered_scale_up_precise", "pod_scheduled_event_precise", "cni_pod_scheduled_event_precise",
    "not_ready_taint_observed_precise", "not_ready_taint_cleared_precise",
    "network_unavailable_taint_observed_precise", "network_unavailable_taint_cleared_precise",
    "cni_taint_observed_precise", "cni_taint_cleared_precise", "cni_conflist_placed_precise",
    "csinode_ready_precise", "supplementary_cni_pods", "ready_condition_history",
    "node_registered_observed_precise", "node_ready_observed_precise", "precise_latencies",
}


def probe_pod(phase="Running"):
    ready = "True" if phase == "Running" else "False"
    return {
        "metadata": {"name": scenarios.PROBE_POD, "namespace": scenarios.PROBE_NAMESPACE,
                     "creationTimestamp": scenarios.at(0)},
        "spec": {"nodeName": scenarios.NODE if phase == "Running" else None, "containers": [{"name": "probe"}]},
        "status": {
            "phase": phase,
            "conditions": [
                {"type": "PodScheduled", "status": ready, "lastTransitionTime": scenarios.at(120)},
                {"type": "Initialized", "status": ready, "lastTransitionTime": scenarios.at(120)},
                {"type": "ContainersReady", "status": ready, "lastTransitionTime": scenarios.at(124)},
                {"type": "Ready", "status": ready, "lastTransitionTime": scenarios.at(124)},
            ],
            "containerStatuses": [{"name": "probe", "image": "pause:3.9", "imageID": "", "ready": True,
                                   "restartCount": 0, "state": {"running": {"startedAt": scenarios.at(123)}}}]
            if phase == "Running" else [],
        },
    }


def fake_cluster(phase="Running"):
    case = scenarios.CNI_POD_SCENARIOS["cilium_agent"]
    probe_events = [
        scenarios.event(scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE, "TriggeredScaleUp",
                        first_timestamp=scenarios.at(5)),
        scenarios.event(scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE, "Scheduled",
                        event_time=scenarios.at(120, 300000)),
    ]
    api = FakeCoreV1Api(
        pods=[probe_pod(phase)] + case["pods"],
        events=probe_events + case["events"],
        logs=case["logs"],
        nodes=[scenarios.node(scenarios.EXISTING_NODE, ready_status="True")],
        readable_nodes=[scenarios.node(scenarios.NODE, ready_status="True", ready_transition=scenarios.at(115))],
        metrics_text=scenarios.CILIUM_METRICS_TEXT,
    )
    return kubernetes_client(KubernetesClient, api), api


def run_iteration(k8s, operation_timeout_in_minutes=10, wait_for_watch=True, fake_watch=None):
    watch_case = scenarios.WATCH_SCENARIOS["managed_cilium"]
    fake_watch = fake_watch or FakeWatch([to_model(node, "V1Node") for node in watch_case["nodes"]])
    instants = iter(scenarios.clock(*instant) for instant in watch_case["clock"])
    wait_for_probe_pod_running = probe.wait_for_probe_pod_running

    # In a real run the probe takes minutes, so the watch sees every transition first.
    # Here the pod is already running, so wait for the watch before stopping it.
    def wait_after_watch(*args, **kwargs):
        if wait_for_watch:
            fake_watch.exhausted.wait(timeout=5)
        return wait_for_probe_pod_running(*args, **kwargs)

    with mock.patch("kubernetes.watch.Watch", return_value=fake_watch), \
            mock.patch("node_startup.probe.wait_for_probe_pod_running", side_effect=wait_after_watch), \
            mock.patch("node_startup.node_watch.utc_now", side_effect=lambda: next(instants)), \
            mock.patch.object(KubernetesClient, "run_pod_exec_command", return_value="DISCOVERY_FAILED"):
        return measure_iteration(
            k8s, node_pool_name="userpool", node_label_key="agentpool", namespace=scenarios.PROBE_NAMESPACE,
            pod_name=scenarios.PROBE_POD, operation_timeout_in_minutes=operation_timeout_in_minutes,
            cni_daemonset_label=scenarios.CILIUM_LABEL, cni_blocking_taint=scenarios.CILIUM_TAINT,
            supplementary_cni_pods={"azure_cns": "k8s-app=azure-cns"}, scale_up_retry_interval=0)


class MeasureIterationTest(unittest.TestCase):
    def test_measurement_keys_are_v1_keys_plus_documented_new_keys(self):
        result = run_iteration(fake_cluster()[0])
        self.assertEqual(set(result["measurement"]), V1_MEASUREMENT_KEYS | NEW_MEASUREMENT_KEYS)

    def test_values(self):
        k8s, api = fake_cluster()
        result = run_iteration(k8s)
        measurement = result["measurement"]
        expected = {
            "node_name": scenarios.NODE,
            "pod_created": "2026-10-02T10:00:00Z",
            "triggered_scale_up": "2026-10-02T10:00:05Z",
            "triggered_scale_up_precise": None,
            "node_registered": "2026-10-02T10:01:40Z",
            "node_ready": "2026-10-02T10:01:55Z",
            "cni_pod_scheduled": "2026-10-02T10:01:41Z",
            "cni_pod_scheduled_event_precise": "2026-10-02T10:01:41.250000Z",
            "cni_container_started": "2026-10-02T10:01:50Z",
            "cni_pod_ready": "2026-10-02T10:01:58Z",
            "cni_taint_cleared": "2026-10-02T10:01:55Z",
            "cni_taint_cleared_precise": "2026-10-02T10:01:55.250000Z",
            "cni_conflist_placed": "2026-10-02T10:01:41Z",
            "cni_conflist_placed_precise": "2026-10-02T10:01:41.000001Z",
            "pod_scheduled": "2026-10-02T10:02:00Z",
            "pod_scheduled_event_precise": "2026-10-02T10:02:00.300000Z",
            "container_started": "2026-10-02T10:02:03Z",
            "pod_ready": "2026-10-02T10:02:04Z",
            "supplementary_cni_pods": {"azure_cns": None},
        }
        self.assertEqual({key: measurement[key] for key in expected}, expected)
        self.assertEqual([(entry["status"], entry["message"]) for entry in measurement["ready_condition_history"]], [
            ("False", scenarios.CNI_NOT_READY),
            ("False", "CSINode is not yet initialized"),
            ("False", "kubelet is posting ready status"),
            ("True", ""),
        ])
        # Watch clock: first sighting 10:01:40.4, Ready 10:01:52.5, CNI taint cleared 10:01:55.25.
        self.assertEqual(measurement["node_registered_observed_precise"], "2026-10-02T10:01:40.400000Z")
        self.assertEqual(measurement["node_ready_observed_precise"], "2026-10-02T10:01:52.500000Z")
        precise = measurement["precise_latencies"]
        self.assertEqual(precise["node_init_precise_seconds"], 12.1)
        self.assertEqual(precise["cni_taint_precise_seconds"], 14.85)
        self.assertEqual(precise["node_ready_to_cni_clear_precise_seconds"], 2.75)
        self.assertEqual(measurement["latencies"]["time_to_runnable_seconds"], 23.0)
        self.assertEqual(measurement["latencies"]["cilium_bootstrap_overall_seconds"], 12.5)
        self.assertEqual(result["existing_nodes"], {scenarios.EXISTING_NODE})
        self.assertFalse(result["environment"]["defender_sensor_present"])

        created_namespace, created_pod = api.created_pods[0]
        self.assertEqual(created_namespace, scenarios.PROBE_NAMESPACE)
        affinity = created_pod.spec.affinity.node_affinity.required_during_scheduling_ignored_during_execution
        self.assertEqual(affinity.node_selector_terms[0].match_expressions[0].values, [scenarios.EXISTING_NODE])
        self.assertEqual(api.deleted_pods, [(scenarios.PROBE_NAMESPACE, scenarios.PROBE_POD)])

    def test_watch_outlives_the_extended_probe_wait(self):
        nodes = [to_model(node, "V1Node") for node in scenarios.WATCH_SCENARIOS["managed_cilium"]["nodes"]]
        fake_watch = FakeWatch(nodes)
        run_iteration(fake_cluster()[0], operation_timeout_in_minutes=10, fake_watch=fake_watch)
        # 10 min step timeout + 10 min backoff extension + 5 min after the scale-up event.
        self.assertEqual(fake_watch.stream_kwargs["timeout_seconds"], 25 * 60)

    def test_probe_pod_deleted_when_it_never_runs(self):
        k8s, api = fake_cluster(phase="Pending")
        with self.assertRaisesRegex(Exception, "did not become Running"):
            run_iteration(k8s, operation_timeout_in_minutes=0, wait_for_watch=False)
        self.assertEqual(api.deleted_pods, [(scenarios.PROBE_NAMESPACE, scenarios.PROBE_POD)])


if __name__ == "__main__":
    unittest.main()
