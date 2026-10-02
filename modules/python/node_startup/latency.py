"""Derived latency metrics, ported from the v1 benchmark.

Metric definitions are identical to v1 `_compute_autoscale_latencies`, except
that the five alias keys v1 kept for old queries are not produced:
node_ready_after_register_seconds (= node_init_seconds),
cilium_init_duration_seconds (= cni_init_seconds),
cni_induced_delay_seconds (= cilium_scheduling_block_seconds),
pod_init_seconds (= sandbox_setup_seconds),
node_to_pod_seconds (= time_to_runnable_seconds).
`compute_precise_latencies` is new in v2 and has no v1 counterpart.
"""
import re

from node_startup.timestamps import parse_timestamp

# Sub-second durations between two node-watch observations. Both ends use the pipeline
# agent's clock, so there's no clock skew. The node's start is the watch's first sighting
# of it (node_registered_observed_precise), not its whole-second creationTimestamp.
PRECISE_LATENCIES = {
    "node_init_precise_seconds": ("node_ready_observed_precise", "node_registered_observed_precise"),
    "cni_conflist_install_precise_seconds": ("cni_conflist_placed_precise", "node_registered_observed_precise"),
    "csinode_ready_precise_seconds": ("csinode_ready_precise", "node_registered_observed_precise"),
    "not_ready_taint_precise_seconds": ("not_ready_taint_cleared_precise", "node_registered_observed_precise"),
    "cni_taint_precise_seconds": ("cni_taint_cleared_precise", "node_registered_observed_precise"),
    "network_unavailable_taint_precise_seconds": (
        "network_unavailable_taint_cleared_precise", "node_registered_observed_precise"),
    "not_ready_taint_active_precise_seconds": ("not_ready_taint_cleared_precise", "not_ready_taint_observed_precise"),
    "cni_taint_active_precise_seconds": ("cni_taint_cleared_precise", "cni_taint_observed_precise"),
    "network_unavailable_taint_active_precise_seconds": (
        "network_unavailable_taint_cleared_precise", "network_unavailable_taint_observed_precise"),
    "node_ready_to_cni_clear_precise_seconds": ("cni_taint_cleared_precise", "node_ready_observed_precise"),
}


def compute_precise_latencies(measurement):
    """Millisecond-resolution counterparts of the whole-second latencies measured by the node watch.

    All values are None if the watch first saw the node already Ready: its first sighting
    was late, so every duration measured from it would be too short.
    """
    history = measurement.get("ready_condition_history") or []
    seen_before_ready = bool(history) and history[0]["status"] != "True"
    latencies = {}
    for name, (end_key, start_key) in PRECISE_LATENCIES.items():
        end, start = measurement.get(end_key), measurement.get(start_key)
        latencies[name] = None
        if seen_before_ready and end and start:
            latencies[name] = round((parse_timestamp(end) - parse_timestamp(start)).total_seconds(), 3)
    return latencies


def compute_autoscale_latencies(timestamps):
    latencies = {}

    def diff_seconds(end_key, start_key):
        end_val = timestamps.get(end_key)
        start_val = timestamps.get(start_key)
        if not end_val or not start_val:
            return None
        try:
            return (parse_timestamp(end_val) - parse_timestamp(start_val)).total_seconds()
        except Exception:
            return None

    # T0-anchored: depend on the IaaS provider, only comparable within one provisioner.
    latencies["autoscaler_reaction_seconds"] = diff_seconds("triggered_scale_up", "pod_created")
    latencies["cloud_provisioning_seconds"] = diff_seconds("node_registered", "triggered_scale_up")
    latencies["node_register_latency_seconds"] = diff_seconds("node_registered", "pod_created")

    # T1-anchored: comparable across provisioners.
    latencies["node_init_seconds"] = diff_seconds("node_ready", "node_registered")
    latencies["cni_conflist_install_seconds"] = diff_seconds("cni_conflist_placed", "node_registered")
    latencies["post_conflist_ready_seconds"] = diff_seconds("node_ready", "cni_conflist_placed")
    latencies["csinode_ready_seconds"] = diff_seconds("csinode_ready", "node_registered")
    latencies["cni_scheduler_latency_seconds"] = diff_seconds("cni_pod_scheduled", "node_registered")

    node_ready_secs = diff_seconds("node_ready", "node_registered")
    cni_ready_secs = diff_seconds("cni_pod_ready", "node_registered")
    if node_ready_secs is not None and cni_ready_secs is not None:
        latencies["total_node_startup_seconds"] = max(node_ready_secs, cni_ready_secs)
    else:
        latencies["total_node_startup_seconds"] = (
            node_ready_secs if node_ready_secs is not None else cni_ready_secs
        )
    # Time until every scheduling gate is clear: Ready, NetworkUnavailable, CNI pod Ready.
    workload_ready_candidates = [
        node_ready_secs,
        diff_seconds("node_network_unavailable_cleared", "node_registered"),
        cni_ready_secs,
    ]
    valid_candidates = [c for c in workload_ready_candidates if c is not None]
    latencies["node_workload_ready_seconds"] = max(valid_candidates) if valid_candidates else None

    # CNI agent lifecycle.
    latencies["cni_init_seconds"] = diff_seconds("cni_pod_ready", "cni_container_started")
    # Time the node sits Ready but unschedulable because of the CNI taint (T4b - T4).
    cni_delay = diff_seconds("cni_pod_ready", "node_ready")
    latencies["cilium_scheduling_block_seconds"] = max(0, cni_delay) if cni_delay is not None else None
    # Time the node waits for Ready after the agent is Ready; ~0 on AKS, so non-zero is a regression signal.
    reverse_cni_delay = diff_seconds("node_ready", "cni_pod_ready")
    latencies["cni_gating_node_ready_seconds"] = (
        max(0, reverse_cni_delay) if reverse_cni_delay is not None else None
    )

    # Taint lifecycle.
    latencies["not_ready_taint_seconds"] = diff_seconds("not_ready_taint_cleared", "node_registered")
    latencies["cni_taint_seconds"] = diff_seconds("cni_taint_cleared", "node_registered")
    latencies["not_ready_taint_active_seconds"] = diff_seconds("not_ready_taint_cleared", "not_ready_taint_observed")
    latencies["cni_taint_active_seconds"] = diff_seconds("cni_taint_cleared", "cni_taint_observed")
    latencies["registration_to_not_ready_taint_seconds"] = diff_seconds("not_ready_taint_observed", "node_registered")
    latencies["registration_to_cni_taint_seconds"] = diff_seconds("cni_taint_observed", "node_registered")
    latencies["node_ready_to_cni_clear_seconds"] = diff_seconds("cni_taint_cleared", "node_ready")
    latencies["network_unavailable_taint_active_seconds"] = diff_seconds(
        "network_unavailable_taint_cleared", "network_unavailable_taint_observed")
    latencies["network_unavailable_taint_seconds"] = diff_seconds(
        "network_unavailable_taint_cleared", "node_registered")

    # Probe pod lifecycle.
    latencies["pod_scheduling_seconds"] = diff_seconds("pod_scheduled", "node_ready")
    latencies["sandbox_setup_seconds"] = diff_seconds("container_started", "pod_scheduled")
    latencies["network_unavailable_seconds"] = diff_seconds("node_network_unavailable_cleared", "node_registered")
    latencies["pod_ready_seconds"] = diff_seconds("pod_ready", "container_started")

    # Headline KPIs.
    latencies["total_e2e_seconds"] = diff_seconds("pod_ready", "pod_created")
    latencies["time_to_runnable_seconds"] = diff_seconds("container_started", "node_registered")

    # Marker positions relative to node registration, used by the phase-breakdown chart.
    latencies["t1c_from_t1_seconds"] = latencies["cni_conflist_install_seconds"]
    latencies["t2_from_t1_seconds"] = diff_seconds("cni_container_started", "node_registered")
    latencies["t3_from_t1_seconds"] = diff_seconds("cni_pod_ready", "node_registered")
    latencies["t4_from_t1_seconds"] = latencies["node_init_seconds"]
    latencies["t4b_from_t1_seconds"] = diff_seconds("cni_taint_cleared", "node_registered")
    latencies["t5_from_t1_seconds"] = latencies["time_to_runnable_seconds"]

    deep = timestamps.get("deep_cilium_metrics")
    if deep and isinstance(deep, dict):
        for scope, value in deep.get("bootstrap", {}).items():
            latencies[f"cilium_bootstrap_{scope}_seconds"] = value
        for scope, value in deep.get("endpoint_regen", {}).items():
            latencies[f"cilium_endpoint_regen_{scope}_seconds"] = value
        metadata = deep.get("metadata", {})
        latencies["cilium_identity_count"] = metadata.get("cilium_identity_count")
        latencies["cilium_bpf_map_pressure"] = metadata.get("cilium_bpf_map_pressure")
        latencies["cilium_version"] = metadata.get("cilium_version")

    # Fallback: take the Cilium version from the agent image tag (e.g. :v1.19.3-260520).
    if not latencies.get("cilium_version"):
        for container in timestamps.get("cni_containers", []):
            image = container.get("image", "")
            if "cilium" in image.lower():
                match = re.search(r':v?(\d+\.\d+\.\d+(?:-\d+)?)', image)
                if match:
                    latencies["cilium_version"] = match.group(1)
                    break

    return latencies
