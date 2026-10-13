"""One measured iteration: trigger a fresh node, watch it come up, collect all timestamps.

Ported from v1 `collect_autoscale_latency`. The `measurement` dict has every v1
key (minus the dropped alias latencies) plus the new `*_precise`,
`supplementary_cni_pods`, `ready_condition_history` and `precise_latencies` keys.
"""
import threading

from node_startup import collectors, probe
from node_startup.cilium import scrape_cilium_metrics
from node_startup.latency import compute_autoscale_latencies, compute_precise_latencies
from node_startup.node_watch import new_watch_result, watch_node_transitions
from node_startup.timestamps import condition_transition_time, format_timestamp
from utils.logger_config import get_logger

logger = get_logger(__name__)

WATCH_JOIN_TIMEOUT_SECONDS = 15
WATCH_PRECISE_KEYS = {
    "not_ready_taint_observed_precise": "not_ready_taint_observed_precise",
    "not_ready_taint_cleared_precise": "not_ready_taint_cleared_precise",
    "network_unavailable_taint_observed_precise": "network_unavailable_taint_observed_precise",
    "network_unavailable_taint_cleared_precise": "network_unavailable_taint_cleared_precise",
    "cni_taint_observed_precise": "cni_taint_observed_precise",
    "cni_taint_cleared_precise": "cni_taint_cleared_precise",
    "cni_conflist_placed_precise": "cni_conflist_placed_at_precise",
    "csinode_ready_precise": "csinode_ready_at_precise",
    # No whole-second twin: node_registered/node_ready are API-server times, these are when the watch saw them.
    "node_registered_observed_precise": "node_registered_at_precise",
    "node_ready_observed_precise": "node_ready_at_precise",
}


def measure_iteration(k8s, node_pool_name, node_label_key, namespace, pod_name, operation_timeout_in_minutes,
                      cni_daemonset_label=None, cni_blocking_taint=None, supplementary_cni_pods=None,
                      scale_up_retry_interval=6):
    """Run one iteration; raises if the probe pod never runs. Always deletes the probe pod.

    Returns {"measurement", "environment", "existing_nodes"}.
    """
    try:
        if probe.is_karpenter(node_label_key):
            probe.wait_for_pool_scaled_to_zero(k8s, node_label_key, node_pool_name)

        existing_nodes = {node.metadata.name for node in
                          k8s.get_nodes(label_selector=f"{node_label_key}={node_pool_name}")}

        probe.deploy_probe_pod(k8s, node_pool_name, namespace, pod_name, node_label_key)
        pod = k8s.api.read_namespaced_pod(name=pod_name, namespace=namespace)
        pod_created = format_timestamp(pod.metadata.creation_timestamp)
        logger.info("Probe pod '%s' created at %s, waiting for autoscaler to scale up...", pod_name, pod_created)

        # The watch runs in the background so a blocked watch can't stall the iteration;
        # it writes into `intermediate_states` as it goes. It must outlive the probe wait
        # (which can extend its deadline), or late transitions would be missed.
        stop_event = threading.Event()
        intermediate_states = new_watch_result()
        watch_thread = threading.Thread(
            target=watch_node_transitions,
            kwargs={
                "api": k8s.api,
                "existing_nodes": existing_nodes,
                "node_pool_name": node_pool_name,
                "cni_blocking_taint": cni_blocking_taint,
                "timeout_minutes": probe.max_probe_wait_minutes(operation_timeout_in_minutes),
                "stop_event": stop_event,
                "result": intermediate_states,
                "node_label_key": node_label_key,
            },
            daemon=True,
        )
        watch_thread.start()

        pod = probe.wait_for_probe_pod_running(k8s.api, pod_name, namespace, operation_timeout_in_minutes)
        stop_event.set()
        watch_thread.join(timeout=WATCH_JOIN_TIMEOUT_SECONDS)

        triggered_scale_up, triggered_scale_up_precise = collectors.get_triggered_scale_up_timestamp(
            k8s.api, pod_name, namespace, retry_interval=scale_up_retry_interval)
        if triggered_scale_up is None:
            triggered_scale_up, triggered_scale_up_precise = collectors.get_first_scheduling_event_timestamp(
                k8s.api, pod_name, namespace)

        new_node_name = pod.spec.node_name
        logger.info("Probe pod scheduled on node '%s'", new_node_name)
        new_node = k8s.api.read_node(name=new_node_name)

        cni_info = {}
        deep_cilium_metrics = None
        if cni_daemonset_label:
            cni_info = collectors.collect_cni_pod_timestamps(k8s, new_node_name, cni_daemonset_label)
            deep_cilium_metrics = scrape_cilium_metrics(k8s, new_node_name, cni_daemonset_label)

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
            "node_ready": condition_transition_time(new_node.status.conditions, "Ready"),
            "node_network_unavailable_cleared": condition_transition_time(
                new_node.status.conditions, "NetworkUnavailable"),
            "cni_conflist_placed": intermediate_states.get("cni_conflist_placed_at"),
            "csinode_ready": intermediate_states.get("csinode_ready_at"),
            "not_ready_taint_observed": intermediate_states.get("not_ready_taint_observed"),
            "not_ready_taint_cleared": intermediate_states.get("not_ready_taint_cleared"),
            "network_unavailable_taint_observed": intermediate_states.get("network_unavailable_taint_observed"),
            "network_unavailable_taint_cleared": intermediate_states.get("network_unavailable_taint_cleared"),
            "cni_taint_observed": intermediate_states.get("cni_taint_observed"),
            "cni_taint_cleared": intermediate_states.get("cni_taint_cleared"),
            "cni_container_started": cni_info.get("cni_container_started"),
            "cni_pod_ready": cni_info.get("cni_pod_ready"),
            "cni_pod_scheduled": cni_info.get("cni_pod_scheduled"),
            "cni_init_containers": cni_info.get("init_containers", []),
            "cni_containers": cni_info.get("containers", []),
            "cni_image_pull_events": cni_info.get("image_pull_events", []),
            "cni_init_container_logs": cni_info.get("init_container_logs", []),
            "deep_cilium_metrics": deep_cilium_metrics,
            "pod_scheduled": condition_transition_time(pod.status.conditions, "PodScheduled"),
            "pod_initialized": condition_transition_time(pod.status.conditions, "Initialized"),
            "container_started": container_started,
            "containers_ready": condition_transition_time(pod.status.conditions, "ContainersReady"),
            "pod_ready": condition_transition_time(pod.status.conditions, "Ready"),
            "intermediate_states": intermediate_states.get("events", []),
            "ready_condition_history": intermediate_states.get("ready_condition_history", []),
            # New in v2: sub-second companions, only where the source has sub-second data.
            "triggered_scale_up_precise": triggered_scale_up_precise,
            "pod_scheduled_event_precise": collectors.scheduled_event_precise(k8s.api, pod_name, namespace),
            "cni_pod_scheduled_event_precise": cni_info.get("cni_pod_scheduled_event_precise"),
            "supplementary_cni_pods": collectors.collect_supplementary_cni_pods(
                k8s, new_node_name, supplementary_cni_pods or {}),
        }
        for key, watch_key in WATCH_PRECISE_KEYS.items():
            measurement[key] = intermediate_states.get(watch_key)
        measurement["latencies"] = compute_autoscale_latencies(measurement)
        measurement["precise_latencies"] = compute_precise_latencies(measurement)
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
