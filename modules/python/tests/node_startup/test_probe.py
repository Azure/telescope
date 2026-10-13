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


NEVER = float("inf")


class ProbeApi(FakeCoreV1Api):
    """A probe pod that, in fake time, gets a scale-up event, is scheduled and then runs."""

    def __init__(self, fake_time, triggered_at=NEVER, scheduled_at=NEVER, running_at=NEVER, backoff=False):
        super().__init__()
        self.fake_time = fake_time
        self.triggered_at, self.scheduled_at, self.running_at = triggered_at, scheduled_at, running_at
        self.backoff = backoff

    def read_namespaced_pod(self, name, namespace):
        now = self.fake_time.now
        running = now >= self.running_at
        return to_model({
            "metadata": {"name": name, "namespace": namespace},
            "spec": {"nodeName": scenarios.NODE if now >= self.scheduled_at else None,
                     "containers": [{"name": "probe"}]},
            "status": {"phase": "Running" if running else "Pending",
                       "conditions": [{"type": "Ready", "status": "True" if running else "False"}]},
        }, "V1Pod")

    def list_namespaced_event(self, namespace, field_selector=None):
        reasons = (["NotTriggerScaleUp"] if self.backoff else []) + (
            ["TriggeredScaleUp"] if self.fake_time.now >= self.triggered_at else [])
        return mock.Mock(items=[to_model(event(reason), "CoreV1Event") for reason in reasons])


def event(reason):
    return scenarios.event(scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE, reason, message=reason,
                           first_timestamp=scenarios.at(1))


class WaitForProbePodRunningTest(unittest.TestCase):
    def wait(self, **timeline):
        fake_time = FakeTime()
        with mock.patch("node_startup.probe.time", fake_time):
            pod = probe.wait_for_probe_pod_running(ProbeApi(fake_time, **timeline),
                                                   scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE)
        return pod, fake_time.now

    def assert_times_out(self, message, **timeline):
        with self.assertRaisesRegex(probe.ProbeTimeout, message):
            self.wait(**timeline)

    def test_returns_running_pod_after_the_three_phases(self):
        pod, elapsed = self.wait(triggered_at=60, scheduled_at=120, running_at=150)
        self.assertEqual(pod.status.phase, "Running")
        self.assertEqual(elapsed, 150)

    def test_each_phase_has_a_fixed_timeout(self):
        self.assert_times_out("no scale-up was triggered within 15 minutes")
        self.assert_times_out("was not scheduled within 10 minutes", triggered_at=60)
        self.assert_times_out("did not become Running and Ready within 5 minutes", triggered_at=60, scheduled_at=120)

    def test_phase_timeouts_add_up_to_the_watch_timeout(self):
        # Every phase uses its full budget and succeeds on its last poll.
        _, elapsed = self.wait(triggered_at=900, scheduled_at=1500, running_at=1800)
        self.assertEqual(elapsed, probe.PROBE_WAIT_TIMEOUT_SECONDS)

    def test_backoff_does_not_extend_the_deadline(self):
        self.assertEqual(self.wait(backoff=True, triggered_at=890, scheduled_at=900, running_at=910)[0].status.phase,
                         "Running")
        self.assert_times_out("no scale-up was triggered", backoff=True, triggered_at=910)

    def test_scheduled_without_a_scale_up_event(self):
        # e.g. node auto-provisioning, which posts no TriggeredScaleUp event.
        pod, elapsed = self.wait(scheduled_at=100, running_at=110)
        self.assertEqual((pod.status.phase, elapsed), ("Running", 110))


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
    def deploy(self, node_label_key, provisioner, api):
        k8s = kubernetes_client(KubernetesClient, api)
        with mock.patch("node_startup.probe.time", FakeTime()):
            probe.deploy_probe_pod(k8s, "userpool", scenarios.PROBE_NAMESPACE, scenarios.PROBE_POD, node_label_key,
                                   provisioner)
        return api.created_pods[-1][1]

    def test_cluster_autoscaler_excludes_existing_nodes(self):
        api = FakeCoreV1Api(nodes=[scenarios.node(scenarios.EXISTING_NODE)])
        body = self.deploy("agentpool", probe.Provisioner.CLUSTER_AUTOSCALER, api)
        expressions = body.spec.affinity.node_affinity.required_during_scheduling_ignored_during_execution \
            .node_selector_terms[0].match_expressions
        self.assertEqual(expressions[0].values, [scenarios.EXISTING_NODE])

    def test_node_auto_provisioning_has_no_hostname_affinity(self):
        api = FakeCoreV1Api(nodes=[scenarios.node("a", labels={"karpenter.sh/nodepool": "userpool"})])
        body = self.deploy("karpenter.sh/nodepool", probe.Provisioner.NODE_AUTO_PROVISIONING, api)
        self.assertIsNone(body.spec.affinity)
        self.assertEqual(body.spec.node_selector, {"karpenter.sh/nodepool": "userpool"})
        self.assertEqual(body.spec.containers[0].image, probe.PROBE_IMAGE)

    def test_existing_pod_is_recreated(self):
        api = FakeCoreV1Api()
        conflict = client.rest.ApiException(status=409)
        with mock.patch.object(api, "create_namespaced_pod", side_effect=[conflict, None]) as create:
            k8s = kubernetes_client(KubernetesClient, api)
            with mock.patch("node_startup.probe.time", FakeTime()):
                probe.deploy_probe_pod(k8s, "userpool", scenarios.PROBE_NAMESPACE, scenarios.PROBE_POD, "agentpool",
                                       probe.Provisioner.CLUSTER_AUTOSCALER)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(api.deleted_pods, [(scenarios.PROBE_NAMESPACE, scenarios.PROBE_POD)])


if __name__ == "__main__":
    unittest.main()
