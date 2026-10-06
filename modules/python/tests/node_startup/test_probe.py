"""Probe pod deploy/wait and node pool waits, with a fake clock."""
import unittest
from unittest import mock

from kubernetes import client

from clients.kubernetes_client import KubernetesClient
from node_startup import probe
from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, kubernetes_client, to_model


class FakeTime:
    """Replaces the `time` module in node_startup.probe: sleep() advances time()."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def pod(phase):
    ready = "True" if phase == "Running" else "False"
    return to_model({
        "metadata": {"name": scenarios.PROBE_POD, "namespace": scenarios.PROBE_NAMESPACE},
        "spec": {"containers": [{"name": "probe"}]},
        "status": {"phase": phase, "conditions": [{"type": "Ready", "status": ready}]},
    }, "V1Pod")


class ProbeApi(FakeCoreV1Api):
    """The probe pod is Pending until `running_at` seconds of fake time."""

    def __init__(self, fake_time, running_at, events=()):
        super().__init__(events=events)
        self.fake_time = fake_time
        self.running_at = running_at

    def read_namespaced_pod(self, name, namespace):
        return pod("Running" if self.fake_time.now >= self.running_at else "Pending")


def event(reason):
    return scenarios.event(scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE, reason, message=reason,
                           first_timestamp=scenarios.at(1))


class WaitForProbePodRunningTest(unittest.TestCase):
    def wait(self, running_at, events=()):
        fake_time = FakeTime()
        with mock.patch("node_startup.probe.time", fake_time):
            return probe.wait_for_probe_pod_running(ProbeApi(fake_time, running_at, events),
                                                    scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE, 1)

    def test_returns_running_pod(self):
        self.assertEqual(self.wait(running_at=30).status.phase, "Running")

    def test_times_out(self):
        with self.assertRaisesRegex(Exception, "did not become Running within 1 minutes"):
            self.wait(running_at=120)

    def test_backoff_extends_deadline(self):
        self.assertEqual(self.wait(running_at=600, events=[event("NotTriggerScaleUp")]).status.phase, "Running")

    def test_scale_up_keeps_five_minutes_after_trigger(self):
        self.assertEqual(self.wait(running_at=299, events=[event("TriggeredScaleUp")]).status.phase, "Running")
        with self.assertRaises(Exception):
            self.wait(running_at=400, events=[event("TriggeredScaleUp")])


def pool_node(name, ready="True"):
    return scenarios.node(name, ready_status=ready)


class PoolApi(FakeCoreV1Api):
    """list_node returns the next snapshot on each call, repeating the last one."""

    def __init__(self, snapshots):
        super().__init__()
        self.snapshots = [[to_model(node, "V1Node") for node in snapshot] for snapshot in snapshots]

    def list_node(self, label_selector=None, **_kwargs):
        return mock.Mock(items=self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0])


class PoolWaitTest(unittest.TestCase):
    def run_wait(self, function, snapshots, **kwargs):
        fake_time = FakeTime()
        k8s = kubernetes_client(KubernetesClient, PoolApi(snapshots))
        with mock.patch("node_startup.probe.time", fake_time):
            return function(k8s, "agentpool", "userpool", **kwargs), fake_time.now

    def test_scaled_to_zero(self):
        result, elapsed = self.run_wait(probe.wait_for_pool_scaled_to_zero,
                                        [[pool_node("a")], [pool_node("a")], []])
        self.assertEqual((result, elapsed), (True, 20))

    def test_not_scaled_to_zero(self):
        result, _ = self.run_wait(probe.wait_for_pool_scaled_to_zero, [[pool_node("a")]])
        self.assertFalse(result)

    def test_settles_after_count_is_stable_and_ready(self):
        snapshots = [[pool_node("a")], [pool_node("a"), pool_node("b", ready="False")],
                     [pool_node("a"), pool_node("b")]]
        result, elapsed = self.run_wait(probe.wait_for_pool_settled, snapshots)
        # Stable from the third poll (t=20s) until 60s later.
        self.assertEqual((result, elapsed), (True, 80))

    def test_never_settles_while_a_node_is_not_ready(self):
        result, _ = self.run_wait(probe.wait_for_pool_settled, [[pool_node("a", ready="False")]])
        self.assertFalse(result)


class DeployProbePodTest(unittest.TestCase):
    def deploy(self, node_label_key, api):
        k8s = kubernetes_client(KubernetesClient, api)
        with mock.patch("node_startup.probe.time", FakeTime()):
            probe.deploy_probe_pod(k8s, "userpool", scenarios.PROBE_NAMESPACE, scenarios.PROBE_POD, node_label_key)
        return api.created_pods[-1][1]

    def test_karpenter_has_no_hostname_affinity(self):
        api = FakeCoreV1Api(nodes=[scenarios.node("a", labels={"karpenter.sh/nodepool": "userpool"})])
        body = self.deploy("karpenter.sh/nodepool", api)
        self.assertIsNone(body.spec.affinity)
        self.assertEqual(body.spec.node_selector, {"karpenter.sh/nodepool": "userpool"})
        self.assertEqual(body.spec.containers[0].image, probe.PROBE_IMAGE)

    def test_existing_pod_is_recreated(self):
        api = FakeCoreV1Api()
        conflict = client.rest.ApiException(status=409)
        with mock.patch.object(api, "create_namespaced_pod", side_effect=[conflict, None]) as create:
            k8s = kubernetes_client(KubernetesClient, api)
            with mock.patch("node_startup.probe.time", FakeTime()):
                probe.deploy_probe_pod(k8s, "userpool", scenarios.PROBE_NAMESPACE, scenarios.PROBE_POD, "agentpool")
        self.assertEqual(create.call_count, 2)
        self.assertEqual(api.deleted_pods, [(scenarios.PROBE_NAMESPACE, scenarios.PROBE_POD)])


if __name__ == "__main__":
    unittest.main()
