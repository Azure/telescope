"""One measured iteration: trigger a fresh node, watch it come up, collect all timestamps.

Ported from v1 `collect_autoscale_latency`. The `measurement` dict has every v1
key (minus the dropped alias latencies). Watch-observed times have microseconds;
the v2-only keys are `node_registered_observed`, `node_ready_observed`,
`pod_scheduled_event_time`, `cni_pod_scheduled_event_time`,
`supplementary_cni_pods`, `ready_condition_history` and `sub_second_latencies`.
"""
import threading

from node_startup import collectors, probe
from node_startup.cilium import scrape_cilium_metrics
from node_startup.latency import compute_autoscale_latencies, compute_sub_second_latencies
from node_startup.node_watch import new_node_transitions, watch_node_transitions
from utils.logger_config import get_logger
from utils.timestamps import condition_last_transition_time, format_timestamp

logger = get_logger(__name__)

WATCH_JOIN_TIMEOUT_SECONDS = 15
# Each probe-wait phase can overrun its timeout by one poll interval; the watch must still be running then.
WATCH_TIMEOUT_MARGIN_SECONDS = 60


def probe_node_transitions(recorders, probe_node_name):
    """Transitions of the probe pod's node; other new nodes the autoscaler added are ignored."""
    other_nodes = sorted(set(recorders) - {probe_node_name})
    if other_nodes:
        logger.info("Watch also saw new node(s) %s; only '%s' is measured", other_nodes, probe_node_name)
    recorder = recorders.get(probe_node_name)
    if recorder is None:
        logger.warning("The node watch never saw the probe pod's node '%s'", probe_node_name)
        return new_node_transitions()
    return recorder.transitions


def measure_iteration(k8s, node_pool_name, node_label_key, provisioner, namespace, pod_name,
                      cni_daemonset_label=None, cni_blocking_taint=None, supplementary_cni_pods=None):
    """Run one iteration; raises if the probe pod never runs. Always deletes the probe pod.

    Returns {"measurement", "environment", "existing_nodes"}.
    """
    try:
        if provisioner == probe.Provisioner.NODE_AUTO_PROVISIONING:
            probe.wait_for_pool_scaled_to_zero(k8s, node_label_key, node_pool_name)

        existing_nodes = {node.metadata.name for node in
                          k8s.get_nodes(label_selector=f"{node_label_key}={node_pool_name}")}

        probe.deploy_probe_pod(k8s, node_pool_name, namespace, pod_name, node_label_key, provisioner)
        pod = k8s.api.read_namespaced_pod(name=pod_name, namespace=namespace)
        pod_created = format_timestamp(pod.metadata.creation_timestamp)
        logger.info("Probe pod '%s' created at %s, waiting for autoscaler to scale up...", pod_name, pod_created)

        # The watch runs in the background so a blocked watch can't stall the iteration.
        # It records every new node in `recorders` as it goes; the probe pod's node is
        # only known once it's scheduled.
        stop_event = threading.Event()
        recorders = {}
        watch_thread = threading.Thread(
            target=watch_node_transitions,
            kwargs={
                "api": k8s.api,
                "existing_nodes": existing_nodes,
                "node_pool_name": node_pool_name,
                "node_label_key": node_label_key,
                "cni_blocking_taint": cni_blocking_taint,
                "timeout_seconds": probe.PROBE_WAIT_TIMEOUT_SECONDS + WATCH_TIMEOUT_MARGIN_SECONDS,
                "stop_event": stop_event,
                "recorders": recorders,
            },
            daemon=True,
        )
        watch_thread.start()
        try:
            pod = probe.wait_for_probe_pod_running(k8s.api, pod_name, namespace)
        finally:
            stop_event.set()
            watch_thread.join(timeout=WATCH_JOIN_TIMEOUT_SECONDS)

        new_node_name = pod.spec.node_name
        logger.info("Probe pod scheduled on node '%s'", new_node_name)
        transitions = probe_node_transitions(recorders, new_node_name)
        new_node = k8s.api.read_node(name=new_node_name)

        probe_events = collectors.list_pod_events(k8s.api, pod_name, namespace)
        triggered_scale_up = (collectors.scale_up_trigger_time(probe_events)
                              or collectors.first_failed_scheduling_time(probe_events))

        cni_info = {}
        deep_cilium_metrics = None
        if cni_daemonset_label:
            cni_pod = collectors.find_daemonset_pod(k8s, new_node_name, cni_daemonset_label)
            if cni_pod is None:
                logger.warning("No CNI pod found on node '%s' with label '%s'", new_node_name, cni_daemonset_label)
            else:
                cni_info = collectors.daemonset_pod_timing(k8s, cni_pod)
                logger.info("CNI pod timestamps for node '%s': %s", new_node_name, cni_info)
                deep_cilium_metrics = scrape_cilium_metrics(k8s, cni_pod)

        container_started = None
        if pod.status.container_statuses:
            for status in pod.status.container_statuses:
                if status.state and status.state.running and status.state.running.started_at:
                    container_started = format_timestamp(status.state.running.started_at)
                    break

        measurement = {
            "node_name": new_node_name,
            "pod_name": pod_name,
            "pod_created": pod_created,
            "triggered_scale_up": triggered_scale_up,
            "node_registered": format_timestamp(new_node.metadata.creation_timestamp),
            "node_ready": condition_last_transition_time(new_node.status.conditions, "Ready"),
            "node_network_unavailable_cleared": condition_last_transition_time(
                new_node.status.conditions, "NetworkUnavailable", observed_status="False"),
            "cni_conflist_placed": transitions["cni_conflist_placed_at"],
            "csinode_ready": transitions["csinode_ready_at"],
            "not_ready_taint_observed": transitions["not_ready_taint_observed"],
            "not_ready_taint_cleared": transitions["not_ready_taint_cleared"],
            "network_unavailable_taint_observed": transitions["network_unavailable_taint_observed"],
            "network_unavailable_taint_cleared": transitions["network_unavailable_taint_cleared"],
            "cni_taint_observed": transitions["cni_taint_observed"],
            "cni_taint_cleared": transitions["cni_taint_cleared"],
            "cni_container_started": cni_info.get("cni_container_started"),
            "cni_pod_ready": cni_info.get("cni_pod_ready"),
            "cni_pod_scheduled": cni_info.get("cni_pod_scheduled"),
            "cni_init_containers": cni_info.get("init_containers", []),
            "cni_containers": cni_info.get("containers", []),
            "cni_image_pull_events": cni_info.get("image_pull_events", []),
            "cni_init_container_logs": cni_info.get("init_container_logs", []),
            "deep_cilium_metrics": deep_cilium_metrics,
            "pod_scheduled": condition_last_transition_time(pod.status.conditions, "PodScheduled"),
            "pod_initialized": condition_last_transition_time(pod.status.conditions, "Initialized"),
            "container_started": container_started,
            "containers_ready": condition_last_transition_time(pod.status.conditions, "ContainersReady"),
            "pod_ready": condition_last_transition_time(pod.status.conditions, "Ready"),
            "intermediate_states": transitions["events"],
            # New in v2. node_registered/node_ready are API-server times; these are when the watch saw them.
            "node_registered_observed": transitions["node_registered_at"],
            "node_ready_observed": transitions["node_ready_at"],
            "ready_condition_history": transitions["ready_condition_history"],
            "pod_scheduled_event_time": collectors.scheduled_event_time(probe_events),
            "cni_pod_scheduled_event_time": cni_info.get("cni_pod_scheduled_event_time"),
            "supplementary_cni_pods": collectors.collect_supplementary_cni_pods(
                k8s, new_node_name, supplementary_cni_pods or {}),
        }
        measurement["latencies"] = compute_autoscale_latencies(measurement)
        measurement["sub_second_latencies"] = compute_sub_second_latencies(measurement)
        logger.info("Autoscale latency results: %s", measurement)

        return {
            "measurement": measurement,
            "environment": collectors.collect_node_environment(k8s, new_node),
            "existing_nodes": existing_nodes,
        }
    finally:
        try:
            probe.delete_probe_pod(k8s.api, pod_name, namespace)
        except Exception:
            pass
