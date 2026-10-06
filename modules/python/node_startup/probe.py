"""Probe pod lifecycle and node pool waits (ported from v1; `wait_for_pool_settled` is new in v2)."""
import time

from kubernetes import client

from utils.logger_config import get_logger

logger = get_logger(__name__)

PROBE_IMAGE = "mcr.microsoft.com/oss/kubernetes/pause:3.9"
PROBE_APP_LABEL = "latency-probe"
SCALE_UP_EVENT_CHECK_INTERVAL_SECONDS = 30
BACKOFF_EXTENSION_MINUTES = 10
MIN_POST_TRIGGER_MINUTES = 5


def is_karpenter(node_label_key):
    return node_label_key.startswith("karpenter")


def max_probe_wait_minutes(operation_timeout_in_minutes):
    """Upper bound of wait_for_probe_pod_running once both deadline extensions have applied."""
    return operation_timeout_in_minutes + BACKOFF_EXTENSION_MINUTES + MIN_POST_TRIGGER_MINUTES


def deploy_probe_pod(k8s, node_pool_name, namespace, pod_name, node_label_key, image=PROBE_IMAGE):
    """Create a probe pod that can only run on a node of the pool that doesn't exist yet.

    Cluster Autoscaler pools: node affinity excludes every existing node of the pool.
    Karpenter pools: no hostname affinity (Karpenter rejects it); the caller waits
    for the pool to be empty instead.
    """
    existing_node_names = [node.metadata.name for node in
                           k8s.get_nodes(label_selector=f"{node_label_key}={node_pool_name}")]
    karpenter = is_karpenter(node_label_key)
    logger.info("Deploying probe pod '%s' with anti-affinity against nodes: %s",
                pod_name, [] if karpenter else existing_node_names)

    affinity = None
    if existing_node_names and not karpenter:
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


def extend_deadline_from_events(api, pod_name, namespace, timeout, backoff_detected,
                                min_post_trigger_minutes, backoff_extension_minutes):
    """Read the pod's autoscaler events once. Returns (timeout, scale_up_triggered, backoff_detected)."""
    events = api.list_namespaced_event(
        namespace=namespace,
        field_selector=f"involvedObject.name={pod_name},involvedObject.kind=Pod",
    )
    for event in events.items:
        if event.reason == "NotTriggerScaleUp" and not backoff_detected:
            backoff_detected = True
            min_deadline = time.time() + (backoff_extension_minutes * 60)
            if min_deadline > timeout:
                logger.warning("Probe pod '%s': autoscaler in backoff (%s), "
                               "extending timeout by %d minutes to allow backoff to clear",
                               pod_name, event.message, int((min_deadline - timeout) / 60) + 1)
                timeout = min_deadline
            else:
                logger.warning("Probe pod '%s': autoscaler in backoff (%s), "
                               "sufficient time remains for backoff to clear", pod_name, event.message)
        if event.reason in ("TriggeredScaleUp", "ScaleUp", "ScaledUpGroup"):
            min_deadline = time.time() + (min_post_trigger_minutes * 60)
            if min_deadline > timeout:
                logger.info("Probe pod '%s': scale-up triggered, extending timeout "
                            "by %d minutes to allow node provisioning",
                            pod_name, int((min_deadline - timeout) / 60) + 1)
                timeout = min_deadline
            return timeout, True, backoff_detected
    return timeout, False, backoff_detected


def wait_for_probe_pod_running(api, pod_name, namespace, operation_timeout_in_minutes,
                               min_post_trigger_minutes=MIN_POST_TRIGGER_MINUTES,
                               backoff_extension_minutes=BACKOFF_EXTENSION_MINUTES):
    """Return the probe pod once it's Running and Ready.

    Extends the deadline so at least `min_post_trigger_minutes` remain after the
    autoscaler's scale-up event, and by `backoff_extension_minutes` the first time
    autoscaler backoff (NotTriggerScaleUp) is seen.
    """
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    logger.info("Waiting for probe pod '%s' to become Running...", pod_name)
    scale_up_triggered = False
    backoff_detected = False
    last_event_check = 0

    while time.time() < timeout:
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        phase = pod.status.phase if pod.status else None

        if phase == "Running" and any(condition.type == "Ready" and condition.status == "True"
                                      for condition in (pod.status.conditions or [])):
            logger.info("Probe pod '%s' is Running and Ready", pod_name)
            return pod

        now = time.time()
        if phase == "Pending" and not scale_up_triggered and (now - last_event_check) >= SCALE_UP_EVENT_CHECK_INTERVAL_SECONDS:
            last_event_check = now
            try:
                timeout, scale_up_triggered, backoff_detected = extend_deadline_from_events(
                    api, pod_name, namespace, timeout, backoff_detected,
                    min_post_trigger_minutes, backoff_extension_minutes)
            except Exception:
                pass  # Event lookup only extends the deadline; never fail the wait on it.

        logger.info("Probe pod '%s' phase: %s, waiting...", pod_name, phase)
        time.sleep(2)

    try:
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        logger.warning("Probe pod '%s' final state - phase: %s, node: %s, conditions: %s",
                       pod_name, pod.status.phase, pod.spec.node_name,
                       [(c.type, c.status, c.reason, c.message) for c in (pod.status.conditions or [])])
        events = api.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name},involvedObject.kind=Pod",
        )
        for event in events.items:
            logger.warning("Probe pod event: %s - %s: %s",
                           event.reason, event.source.component if event.source else "unknown", event.message)
    except Exception as diag_err:
        logger.warning("Failed to collect probe pod diagnostics: %s", diag_err)

    raise Exception(f"Probe pod '{pod_name}' did not become Running within {operation_timeout_in_minutes} minutes")


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
