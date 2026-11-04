"""Probe pod lifecycle and node pool waits (ported from v1; `wait_for_pool_settled` is new in v2)."""
import time
from enum import Enum

from kubernetes import client

from node_startup import collectors
from utils.logger_config import get_logger

logger = get_logger(__name__)

PROBE_IMAGE = "mcr.microsoft.com/oss/kubernetes/pause:3.9"
PROBE_APP_LABEL = "latency-probe"

# The probe wait has three phases, each with a fixed timeout. The first covers one
# Cluster Autoscaler backoff period (about 10 minutes) after a failed scale-up.
SCALE_UP_TRIGGER_TIMEOUT_SECONDS = 15 * 60
POD_SCHEDULED_TIMEOUT_SECONDS = 10 * 60
POD_RUNNING_TIMEOUT_SECONDS = 5 * 60
PROBE_WAIT_TIMEOUT_SECONDS = SCALE_UP_TRIGGER_TIMEOUT_SECONDS + POD_SCHEDULED_TIMEOUT_SECONDS + POD_RUNNING_TIMEOUT_SECONDS
POD_POLL_INTERVAL_SECONDS = 2
# Phase 1 lists the pod's events; its timestamp comes from the event itself, so a slower poll loses nothing.
EVENT_POLL_INTERVAL_SECONDS = 10


class Provisioner(str, Enum):
    """How the pool gets new nodes. Recorded in every result; decides how a probe targets a new node."""
    CLUSTER_AUTOSCALER = "cluster-autoscaler"
    NODE_AUTO_PROVISIONING = "node-auto-provisioning"

    def __str__(self):
        return self.value


class ProbeTimeout(Exception):
    pass


def deploy_probe_pod(k8s, node_pool_name, namespace, pod_name, node_label_key, provisioner, image=PROBE_IMAGE):
    """Create a probe pod that can only run on a node of the pool that doesn't exist yet.

    Cluster Autoscaler pools: node affinity excludes every existing node of the pool.
    Node auto-provisioning (Karpenter) pools: no hostname affinity (Karpenter rejects
    it); the caller waits for the pool to be empty instead.
    """
    existing_node_names = [node.metadata.name for node in
                           k8s.get_nodes(label_selector=f"{node_label_key}={node_pool_name}")]
    exclude_existing = provisioner == Provisioner.CLUSTER_AUTOSCALER
    logger.info("Deploying probe pod '%s' with anti-affinity against nodes: %s",
                pod_name, existing_node_names if exclude_existing else [])

    affinity = None
    if existing_node_names and exclude_existing:
        affinity = client.V1Affinity(
            node_affinity=client.V1NodeAffinity(
                required_during_scheduling_ignored_during_execution=client.V1NodeSelector(
                    node_selector_terms=[
                        client.V1NodeSelectorTerm(
                            match_expressions=[
                                client.V1NodeSelectorRequirement(
                                    key="kubernetes.io/hostname",
                                    operator="NotIn",
                                    values=existing_node_names,
                                ),
                                client.V1NodeSelectorRequirement(
                                    key=node_label_key,
                                    operator="In",
                                    values=[node_pool_name],
                                ),
                            ]
                        )
                    ]
                )
            )
        )

    pod_manifest = client.V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=client.V1ObjectMeta(name=pod_name, namespace=namespace, labels={"app": PROBE_APP_LABEL}),
        spec=client.V1PodSpec(
            node_selector={node_label_key: node_pool_name},
            affinity=affinity,
            containers=[
                client.V1Container(
                    name="probe",
                    image=image,
                    resources=client.V1ResourceRequirements(requests={"cpu": "100m", "memory": "64Mi"}),
                )
            ],
        ),
    )

    try:
        k8s.api.create_namespaced_pod(namespace=namespace, body=pod_manifest)
        logger.info("Probe pod '%s' created in namespace '%s'", pod_name, namespace)
    except client.rest.ApiException as e:
        if e.status != 409:
            raise
        logger.info("Probe pod '%s' already exists, recreating", pod_name)
        k8s.api.delete_namespaced_pod(name=pod_name, namespace=namespace)
        time.sleep(2)
        k8s.api.create_namespaced_pod(namespace=namespace, body=pod_manifest)
    return pod_name


def wait_until(failure, timeout_seconds, check, interval_seconds=POD_POLL_INTERVAL_SECONDS):
    """Poll `check` until it returns a truthy value and return that value.

    Raises ProbeTimeout("<failure> within N minutes") after `timeout_seconds`.
    """
    deadline = time.time() + timeout_seconds
    while True:
        result = check()
        if result:
            return result
        if time.time() >= deadline:
            raise ProbeTimeout(f"{failure} within {timeout_seconds // 60} minutes")
        time.sleep(interval_seconds)


def wait_for_scale_up_trigger(api, pod_name, namespace):
    """Phase 1: the autoscaler posts a scale-up event for the pod, or the pod is scheduled without one.

    Node auto-provisioning posts no scale-up event, so for it this phase ends when the pod is scheduled.
    """
    backoff_logged = False

    def triggered():
        nonlocal backoff_logged
        if api.read_namespaced_pod(name=pod_name, namespace=namespace).spec.node_name:
            return True
        for event in collectors.list_pod_events(api, pod_name, namespace):
            if event.reason in collectors.SCALE_UP_REASONS:
                return True
            if event.reason == "NotTriggerScaleUp" and not backoff_logged:
                backoff_logged = True
                logger.warning("Probe pod '%s': autoscaler in backoff (%s)", pod_name, event.message)
        return False

    wait_until(f"Probe pod '{pod_name}': no scale-up was triggered", SCALE_UP_TRIGGER_TIMEOUT_SECONDS, triggered,
               interval_seconds=EVENT_POLL_INTERVAL_SECONDS)
    logger.info("Probe pod '%s': scale-up triggered", pod_name)


def wait_for_probe_pod_running(api, pod_name, namespace):
    """Return the probe pod once it's Running and Ready, waiting through three fixed-timeout phases.

    1. Scale-up triggered (SCALE_UP_TRIGGER_TIMEOUT_SECONDS).
    2. Pod scheduled: the new node registered, became Ready and lost its startup taints
       (POD_SCHEDULED_TIMEOUT_SECONDS).
    3. Pod Running and Ready: sandbox created and container started (POD_RUNNING_TIMEOUT_SECONDS).
    """
    def read_pod():
        return api.read_namespaced_pod(name=pod_name, namespace=namespace)

    def running_and_ready():
        pod = read_pod()
        ready = any(condition.type == "Ready" and condition.status == "True"
                    for condition in (pod.status.conditions or []))
        return pod if pod.status.phase == "Running" and ready else None

    try:
        wait_for_scale_up_trigger(api, pod_name, namespace)
        node_name = wait_until(f"Probe pod '{pod_name}' was not scheduled", POD_SCHEDULED_TIMEOUT_SECONDS,
                               lambda: read_pod().spec.node_name)
        logger.info("Probe pod '%s': scheduled on node '%s'", pod_name, node_name)
        pod = wait_until(f"Probe pod '{pod_name}' did not become Running and Ready", POD_RUNNING_TIMEOUT_SECONDS,
                         running_and_ready)
        logger.info("Probe pod '%s': Running and Ready", pod_name)
        return pod
    except ProbeTimeout:
        log_probe_diagnostics(api, pod_name, namespace)
        raise


def log_probe_diagnostics(api, pod_name, namespace):
    try:
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        logger.warning("Probe pod '%s' final state - phase: %s, node: %s, conditions: %s",
                       pod_name, pod.status.phase, pod.spec.node_name,
                       [(c.type, c.status, c.reason, c.message) for c in (pod.status.conditions or [])])
        for event in collectors.list_pod_events(api, pod_name, namespace):
            logger.warning("Probe pod event: %s - %s: %s",
                           event.reason, event.source.component if event.source else "unknown", event.message)
    except Exception as diag_err:
        logger.warning("Failed to collect probe pod diagnostics: %s", diag_err)


def delete_probe_pod(api, pod_name, namespace):
    try:
        api.delete_namespaced_pod(name=pod_name, namespace=namespace)
        logger.info("Probe pod '%s' deleted", pod_name)
    except client.rest.ApiException as e:
        if e.status != 404:
            raise
        logger.info("Probe pod '%s' not found (already deleted)", pod_name)


def wait_for_pool_scaled_to_zero(k8s, node_label_key, node_pool_name, timeout_seconds=300, poll_interval=10):
    """Wait until a Karpenter pool is empty, so the next probe gets a fresh node."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        nodes = k8s.get_nodes(label_selector=f"{node_label_key}={node_pool_name}")
        if not nodes:
            return True
        logger.info("Waiting for pool '%s=%s' to scale to zero (currently %d node(s))...",
                    node_label_key, node_pool_name, len(nodes))
        time.sleep(poll_interval)
    remaining = k8s.get_nodes(label_selector=f"{node_label_key}={node_pool_name}")
    logger.warning("Pool '%s=%s' still has %d node(s) after %ds; proceeding anyway",
                   node_label_key, node_pool_name, len(remaining), timeout_seconds)
    return False


def is_node_ready(node):
    return any(condition.type == "Ready" and condition.status == "True"
               for condition in (node.status.conditions or []))


def wait_for_pool_settled(k8s, node_label_key, node_pool_name, stable_seconds=60, timeout_seconds=600,
                          poll_interval=10):
    """After a failed iteration, wait until the pool has no scale-up in flight.

    Settled means every node in the pool is Ready and the node count hasn't
    changed for `stable_seconds`. Stops the next probe from landing on a node
    that the failed iteration's scale-up created late.
    """
    deadline = time.time() + timeout_seconds
    last_count = None
    stable_since = None
    while time.time() < deadline:
        nodes = k8s.get_nodes(label_selector=f"{node_label_key}={node_pool_name}")
        all_ready = all(is_node_ready(node) for node in nodes)
        if len(nodes) != last_count or not all_ready:
            stable_since = None
        last_count = len(nodes)
        if all_ready:
            now = time.time()
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_seconds:
                logger.info("Pool '%s=%s' settled at %d node(s)", node_label_key, node_pool_name, len(nodes))
                return True
        time.sleep(poll_interval)
    logger.warning("Pool '%s=%s' didn't settle within %ds; continuing", node_label_key, node_pool_name, timeout_seconds)
    return False
