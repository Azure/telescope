"""Per-iteration validation: only complete, consistent, fresh, customer-like iterations are uploaded."""
from node_startup.timestamps import parse_timestamp

BASE_REQUIRED_MILESTONES = [
    "pod_created",
    "node_registered",
    "node_ready",
    "pod_scheduled",
    "container_started",
    "pod_ready",
]
CNI_POD_MILESTONES = ["cni_pod_scheduled", "cni_container_started", "cni_pod_ready"]

# Only API-server timestamps are ordered here. Watch-observed milestones use the
# agent's clock, so skew could make a correct iteration fail. Equal values are
# allowed because timestamps are truncated to whole seconds.
SERVER_SIDE_ORDER = [
    ["pod_created", "node_registered", "node_ready"],
    ["node_registered", "cni_pod_scheduled", "cni_container_started", "cni_pod_ready"],
    ["pod_scheduled", "container_started", "pod_ready"],
]


def cni_readiness_signal(cni_daemonset_label):
    """Milestone that means "CNI ready for pods": the CNI pod if there is one, else the conflist."""
    return "cni_pod_ready" if cni_daemonset_label else "cni_conflist_placed"


def required_milestones(cni_daemonset_label, cni_blocking_taint):
    required = list(BASE_REQUIRED_MILESTONES)
    if cni_daemonset_label:
        required += CNI_POD_MILESTONES
    if cni_blocking_taint:
        required.append("cni_taint_cleared")
    signal = cni_readiness_signal(cni_daemonset_label)
    if signal not in required:
        required.append(signal)
    return required


def validate_iteration(iteration_result, used_nodes, cni_daemonset_label, cni_blocking_taint):
    """Return the reasons this iteration must be dropped; empty if it's valid."""
    measurement = iteration_result["measurement"]
    problems = []

    for key in required_milestones(cni_daemonset_label, cni_blocking_taint):
        if not measurement.get(key):
            problems.append(f"missing {key}")

    for chain in SERVER_SIDE_ORDER:
        present = [key for key in chain if measurement.get(key)]
        for earlier, later in zip(present, present[1:]):
            if parse_timestamp(measurement[later]) < parse_timestamp(measurement[earlier]):
                problems.append(f"{later} ({measurement[later]}) before {earlier} ({measurement[earlier]})")

    node_name = measurement.get("node_name")
    if node_name in iteration_result["existing_nodes"]:
        problems.append(f"node {node_name} existed before the scale-up")
    if node_name in used_nodes:
        problems.append(f"node {node_name} already used by an earlier iteration")

    if iteration_result["environment"].get("defender_sensor_present"):
        problems.append("defender sensor present")

    return problems
