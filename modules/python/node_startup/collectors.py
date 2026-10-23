"""Kubernetes data collectors for one measured iteration (ported from v1, plus v2 additions).

v2 additions, all new keys that don't change any v1 value:
- `cni_pod_scheduled_event_precise`: the scheduler's `Scheduled` event time for a CNI pod.
- The `*_precise` companion returned by the scale-up trigger lookups.
- `collect_node_environment`: Defender sensor presence and the node's shape labels.
"""
import re
import time

from kubernetes import client

from node_startup.timestamps import (
    condition_transition_time,
    format_precise_timestamp,
    format_timestamp,
    parse_log_timestamp,
    parse_timestamp,
)
from utils.logger_config import get_logger

logger = get_logger(__name__)

SCALE_UP_REASONS = {"TriggeredScaleUp", "ScaleUp", "ScaledUpGroup"}
RAW_LOG_LINES_LIMIT = 50

# Known operations inside Cilium init containers (the merged cilium-init-all and the
# pre-merge individual ones), matched against log lines: (regex, operation name).
INIT_CONTAINER_OPERATIONS = [
    (r"install.?plugin|install.?cni|cni.?bin", "install-cni-binaries"),
    (r"cilium.?mount|mount.*cgroup|Mounted cgroupv2", "mount-cgroup"),
    (r"cilium.?sysctlfix|sysctl", "apply-sysctl-overwrites"),
    (r"mount.*bpf|bpf.*fs|bpf on /sys/fs/bpf", "mount-bpf-fs"),
    (r"init.?container\.sh|clean.*state|cilium.*state|rm -rf", "clean-cilium-state"),
    (r"block.?wireserver|iptables.*FORWARD.*168\.63|installRuleIdempotent", "block-wireserver"),
    (r"systemd.?networkd|foreign.?routes", "systemd-networkd-overrides"),
    (r"detach mode|BPF program detached|unpinned from|pinned resources", "iptables-blocker-detach"),
]
KUBELET_LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s(.*)$")

DEFENDER_POD_PREFIX = "microsoft-defender"
NODE_SHAPE_LABELS = {
    "node_instance_type": "node.kubernetes.io/instance-type",
    "node_os_sku": "kubernetes.azure.com/os-sku",
    "node_image_version": "kubernetes.azure.com/node-image-version",
    "node_zone": "topology.kubernetes.io/zone",
}


def pod_events(api, pod_name, namespace):
    return api.list_namespaced_event(
        namespace=namespace,
        field_selector=f"involvedObject.name={pod_name},involvedObject.kind=Pod",
    ).items


def find_daemonset_pod(k8s, node_name, label_selector, namespace):
    pods = k8s.get_pods_by_namespace(
        namespace=namespace,
        label_selector=label_selector,
        field_selector=f"spec.nodeName={node_name}",
    )
    return pods[0] if pods else None


def collect_cni_pod_timestamps(k8s, node_name, cni_daemonset_label, namespace="kube-system"):
    """Timing of the CNI daemonset pod on `node_name`; placeholder values if there's none (as v1)."""
    pod = find_daemonset_pod(k8s, node_name, cni_daemonset_label, namespace)
    if pod is None:
        logger.warning("No CNI pod found on node '%s' with label '%s'", node_name, cni_daemonset_label)
        return {
            "cni_container_started": None,
            "cni_pod_ready": None,
            "cni_pod_scheduled": None,
            "init_containers": [],
            "containers": [],
            "image_pull_events": [],
            "cni_pod_scheduled_event_precise": None,
        }
    entry = daemonset_pod_timing(k8s, pod, namespace)
    logger.info("CNI pod timestamps for node '%s': %s", node_name, entry)
    return entry


def daemonset_pod_timing(k8s, pod, namespace):
    container_started = None
    if pod.status.container_statuses:
        for status in pod.status.container_statuses:
            if status.state and status.state.running and status.state.running.started_at:
                container_started = format_timestamp(status.state.running.started_at)
                break

    return {
        "cni_container_started": container_started,
        "cni_pod_ready": condition_transition_time(pod.status.conditions, "Ready"),
        "cni_pod_scheduled": condition_transition_time(pod.status.conditions, "PodScheduled"),
        "init_containers": collect_init_container_timestamps(pod),
        "containers": collect_container_timestamps(pod),
        "image_pull_events": collect_image_pull_events(k8s.api, pod.metadata.name, namespace),
        "init_container_logs": collect_init_container_logs(k8s.api, pod.metadata.name, namespace),
        "cni_pod_scheduled_event_precise": scheduled_event_precise(k8s.api, pod.metadata.name, namespace),
    }


def collect_supplementary_cni_pods(k8s, node_name, label_selectors, namespace="kube-system"):
    """Timing of extra per-node networking pods (e.g. azure-cns); None where the pod doesn't run.

    Informational only: these values feed no v1 metric and never drop an iteration.
    """
    result = {}
    for name, label_selector in label_selectors.items():
        pod = find_daemonset_pod(k8s, node_name, label_selector, namespace)
        result[name] = daemonset_pod_timing(k8s, pod, namespace) if pod is not None else None
    return result


def collect_init_container_timestamps(pod):
    init_containers = []
    if not pod.status.init_container_statuses:
        return init_containers

    for status in pod.status.init_container_statuses:
        entry = {
            "name": status.name,
            "image": status.image,
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
        }
        terminated = None
        if status.state and status.state.terminated:
            terminated = status.state.terminated
        elif status.last_state and status.last_state.terminated:
            terminated = status.last_state.terminated
        if terminated:
            entry["started_at"] = format_timestamp(terminated.started_at)
            entry["finished_at"] = format_timestamp(terminated.finished_at)
            if terminated.started_at and terminated.finished_at:
                entry["duration_seconds"] = (terminated.finished_at - terminated.started_at).total_seconds()
        init_containers.append(entry)
    return init_containers


def collect_container_timestamps(pod):
    containers = []
    if not pod.status.container_statuses:
        return containers

    for status in pod.status.container_statuses:
        entry = {
            "name": status.name,
            "image": status.image,
            "started_at": None,
            "ready": status.ready,
        }
        if status.state and status.state.running and status.state.running.started_at:
            entry["started_at"] = format_timestamp(status.state.running.started_at)
        containers.append(entry)
    return containers


def collect_image_pull_events(api, pod_name, namespace):
    """Pulling/Pulled event pairs per image, with the pull duration."""
    image_pulls = []
    try:
        pull_map = {}
        for event in pod_events(api, pod_name, namespace):
            if event.reason not in ("Pulling", "Pulled"):
                continue
            image = extract_image_from_event_message(event.message)
            if not image:
                continue
            times = pull_map.setdefault(image, {"pulling_at": None, "pulled_at": None, "message": None})
            ts = event.event_time or event.first_timestamp or event.metadata.creation_timestamp
            if event.reason == "Pulling":
                times["pulling_at"] = format_timestamp(ts)
            else:
                times["pulled_at"] = format_timestamp(ts)
                times["message"] = event.message

        for image, times in pull_map.items():
            entry = {
                "image": image,
                "pulling_at": times["pulling_at"],
                "pulled_at": times["pulled_at"],
                "duration_seconds": None,
                "already_present": times["message"] is not None and "already present on machine" in times["message"],
                "message": times["message"],
            }
            if times["pulling_at"] and times["pulled_at"]:
                try:
                    entry["duration_seconds"] = (
                        parse_timestamp(times["pulled_at"]) - parse_timestamp(times["pulling_at"])
                    ).total_seconds()
                except Exception:
                    pass
            image_pulls.append(entry)
    except Exception as e:
        logger.warning("Failed to collect image pull events for pod '%s': %s", pod_name, e)
    return image_pulls


def extract_image_from_event_message(message):
    """'Pulling image "x"' or 'Successfully pulled image "x" in 3.5s' -> x."""
    if not message:
        return None
    start = message.find('"')
    if start == -1:
        return None
    end = message.find('"', start + 1)
    if end == -1:
        return None
    return message[start + 1:end]


def collect_init_container_logs(api, pod_name, namespace):
    """Per init container: first/last kubelet log timestamps (ns precision) and known operations."""
    results = []
    try:
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        if not pod.spec.init_containers:
            return results

        for init_container in pod.spec.init_containers:
            container_name = init_container.name
            try:
                log_bytes = api.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    container=container_name,
                    timestamps=True,
                    _preload_content=False,
                ).data
                log_text = log_bytes.decode("utf-8", errors="replace") if isinstance(log_bytes, bytes) else str(log_bytes)
            except Exception as e:
                logger.debug("Failed to read logs for init container '%s' in pod '%s': %s",
                             container_name, pod_name, e)
                continue

            if not log_text.strip():
                results.append({
                    "name": container_name,
                    "first_log_ts": None,
                    "last_log_ts": None,
                    "log_duration_seconds": None,
                    "operations": [],
                })
                continue

            first_ts = None
            last_ts = None
            operations = []
            seen_operations = set()
            raw_lines = []
            for line in log_text.strip().splitlines():
                match = KUBELET_LOG_LINE.match(line)
                if not match:
                    continue
                ts_str, content = match.group(1), match.group(2)
                if first_ts is None:
                    first_ts = ts_str
                last_ts = ts_str
                if len(raw_lines) < RAW_LOG_LINES_LIMIT:
                    raw_lines.append({"ts": ts_str, "line": content[:300]})
                for pattern, operation in INIT_CONTAINER_OPERATIONS:
                    if operation not in seen_operations and re.search(pattern, content, re.IGNORECASE):
                        operations.append({"name": operation, "started_at": ts_str, "line": content[:200]})
                        seen_operations.add(operation)
                        break

            log_duration = None
            if first_ts and last_ts:
                try:
                    log_duration = round(
                        (parse_log_timestamp(last_ts) - parse_log_timestamp(first_ts)).total_seconds(), 6)
                except Exception:
                    pass

            results.append({
                "name": container_name,
                "first_log_ts": first_ts,
                "last_log_ts": last_ts,
                "log_duration_seconds": log_duration,
                "operations": operations,
                "raw_lines": raw_lines,
            })
    except Exception as e:
        logger.warning("Failed to collect init container logs for pod '%s': %s", pod_name, e)

    infer_gap_durations(results)
    return results


def infer_gap_durations(init_container_logs):
    """Add `inferred_duration_seconds` to each init container entry.

    With logs: previous container's last log line to this container's last log line.
    Without logs: previous container's last log line to the next container's first log line.
    """
    def parse_or_none(value):
        if not value:
            return None
        try:
            return parse_log_timestamp(value)
        except Exception:
            return None

    for index, entry in enumerate(init_container_logs):
        previous_end = None
        for previous in range(index - 1, -1, -1):
            if init_container_logs[previous].get("last_log_ts"):
                previous_end = parse_or_none(init_container_logs[previous]["last_log_ts"])
                break

        if entry.get("first_log_ts") is None and entry.get("last_log_ts") is None:
            next_start = None
            for following in range(index + 1, len(init_container_logs)):
                if init_container_logs[following].get("first_log_ts"):
                    next_start = parse_or_none(init_container_logs[following]["first_log_ts"])
                    break
            end = next_start
        else:
            end = parse_or_none(entry.get("last_log_ts"))

        if previous_end and end:
            entry["inferred_duration_seconds"] = round((end - previous_end).total_seconds(), 6)
        else:
            entry["inferred_duration_seconds"] = None


def scheduled_event_precise(api, pod_name, namespace):
    """Microsecond time of the scheduler's `Scheduled` event, or None if it only has whole seconds."""
    try:
        times = [event.event_time for event in pod_events(api, pod_name, namespace)
                 if event.reason == "Scheduled" and event.event_time]
    except Exception as e:
        logger.warning("Failed to read Scheduled event for pod '%s': %s", pod_name, e)
        return None
    return format_precise_timestamp(min(times)) if times else None


def find_scale_up_event_time(api, pod_name, namespace):
    """One lookup of the autoscaler's scale-up event: (whole-second, precise), or None if absent."""
    for event in pod_events(api, pod_name, namespace):
        if event.reason in SCALE_UP_REASONS:
            ts = event.event_time or event.first_timestamp or event.metadata.creation_timestamp
            if ts:
                return format_timestamp(ts), format_precise_timestamp(event.event_time)

    # Newer clusters may only publish the event through the events.k8s.io/v1 API.
    try:
        events_v1 = client.EventsV1Api(api.api_client)
        for event in events_v1.list_namespaced_event(
                namespace=namespace,
                field_selector=f"regarding.name={pod_name},regarding.kind=Pod").items:
            if event.reason in SCALE_UP_REASONS:
                ts = event.event_time or event.metadata.creation_timestamp
                if ts:
                    return format_timestamp(ts), format_precise_timestamp(event.event_time)
    except Exception as e:
        logger.debug("EventsV1Api lookup failed (expected on older clusters): %s", e)
    return None


def get_triggered_scale_up_timestamp(api, pod_name, namespace, max_retries=10, retry_interval=6):
    """(whole-second, precise) time of the autoscaler's scale-up event for the pod, or (None, None).

    Retries because the event can appear late (e.g. on BYOCNI clusters).
    """
    for attempt in range(max_retries):
        try:
            found = find_scale_up_event_time(api, pod_name, namespace)
            if found:
                return found
            if attempt < max_retries - 1:
                logger.debug("TriggeredScaleUp event not found (attempt %d/%d), retrying...",
                             attempt + 1, max_retries)
                time.sleep(retry_interval)
        except Exception as e:
            logger.warning("Failed to get TriggeredScaleUp event (attempt %d): %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(retry_interval)

    logger.warning("No TriggeredScaleUp event found for pod '%s' after %d attempts", pod_name, max_retries)
    return None, None


def get_first_scheduling_event_timestamp(api, pod_name, namespace):
    """(whole-second, precise) time of the pod's first FailedScheduling event, or (None, None).

    Fallback for the scale-up trigger when the autoscaler posts no event (e.g. BYOCNI):
    it marks when the scheduler first found the pod unschedulable.
    """
    try:
        earliest_ts = None
        earliest_event = None
        for event in pod_events(api, pod_name, namespace):
            if event.reason != "FailedScheduling":
                continue
            ts = event.event_time or event.first_timestamp or event.metadata.creation_timestamp
            if ts:
                formatted = format_timestamp(ts)
                if earliest_ts is None or formatted < earliest_ts:
                    earliest_ts = formatted
                    earliest_event = event
        if earliest_ts:
            logger.info("Using first FailedScheduling event as T0 fallback: %s", earliest_ts)
            return earliest_ts, format_precise_timestamp(earliest_event.event_time)
        logger.warning("No FailedScheduling event found for pod '%s'", pod_name)
        return None, None
    except Exception as e:
        logger.warning("Failed to get FailedScheduling event: %s", e)
        return None, None


def collect_node_environment(k8s, node):
    """Defender sensor presence and shape labels of the measured node (see plan Q9, Q21)."""
    labels = node.metadata.labels or {}
    pods = k8s.api.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node.metadata.name}").items
    environment = {
        "defender_sensor_present": any(pod.metadata.name.startswith(DEFENDER_POD_PREFIX) for pod in pods),
    }
    for key, label in NODE_SHAPE_LABELS.items():
        environment[key] = labels.get(label)
    return environment
