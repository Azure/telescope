"""Node watch that records each new node's lifecycle transitions as they happen (ported from v1).

Times are the pipeline agent's wall clock when the watch event arrived, with
microseconds, not API-server times. v1 stored the same observation truncated to
whole seconds; latency.py truncates when it needs the v1 values.
"""
import time
from datetime import datetime, timezone

from kubernetes import watch

from utils.logger_config import get_logger
from utils.timestamps import format_timestamp, format_timestamp_microseconds

logger = get_logger(__name__)

NOT_READY_TAINT = ("node.kubernetes.io/not-ready", "NoSchedule")
NETWORK_UNAVAILABLE_TAINT = ("node.kubernetes.io/network-unavailable", "NoSchedule")
# Substrings kubelet puts in the Ready condition message until a CNI conflist exists.
CNI_NOT_READY_MESSAGES = ("networkpluginnotready", "cni config uninitialized", "network plugin is not ready")
CSINODE_NOT_READY_MESSAGE = "csinode is not yet initialized"

OBSERVED_KEYS = [
    "node_registered_at",
    "not_ready_taint_observed",
    "not_ready_taint_cleared",
    "network_unavailable_taint_observed",
    "network_unavailable_taint_cleared",
    "cni_taint_observed",
    "cni_taint_cleared",
    "node_ready_at",
    "cni_conflist_placed_at",
    "csinode_ready_at",
]


def new_node_transitions():
    transitions = {key: None for key in OBSERVED_KEYS}
    transitions["events"] = []
    transitions["ready_condition_history"] = []
    return transitions


def utc_now():
    return datetime.now(timezone.utc)


class NodeTransitionRecorder:
    """The transitions of one node. Each is recorded once, the first time the watch sees it."""

    def __init__(self, node_name, cni_blocking_taint):
        self.node_name = node_name
        self.cni_blocking_taint = cni_blocking_taint
        self.transitions = new_node_transitions()

    def observe(self, node, now):
        if self.transitions["node_registered_at"] is None:
            self.record_registration(node, now)
        self.record_taint_transitions(node, now)
        ready_condition = next(
            (condition for condition in (node.status.conditions or []) if condition.type == "Ready"), None)
        if ready_condition is not None:
            self.record_ready_transition(ready_condition, now)
            self.record_initialization_milestones(ready_condition, now)

    def record(self, key, event_name, now, **extra):
        observed_at = format_timestamp_microseconds(now)
        self.transitions[key] = observed_at
        self.transitions["events"].append(
            {"event": event_name, "node": self.node_name, **extra, "observed_at": observed_at})
        logger.info("Watch: %s on '%s'", event_name.replace("_", " "), self.node_name)

    def record_registration(self, node, now):
        self.record("node_registered_at", "node_registered", now,
                    creation_timestamp=format_timestamp(node.metadata.creation_timestamp))

    def record_taint_transitions(self, node, now):
        taints = node.spec.taints or []
        present = {(taint.key, taint.effect) for taint in taints}
        self.record_taint_transition("not_ready_taint", NOT_READY_TAINT in present, now)
        self.record_taint_transition("network_unavailable_taint", NETWORK_UNAVAILABLE_TAINT in present, now)
        if self.cni_blocking_taint:
            # The CNI taint is matched on key only, any effect.
            self.record_taint_transition(
                "cni_taint", any(taint.key == self.cni_blocking_taint for taint in taints), now,
                taint=self.cni_blocking_taint)

    def record_taint_transition(self, name, present, now, **extra):
        observed, cleared = f"{name}_observed", f"{name}_cleared"
        if present:
            if self.transitions[observed] is None:
                self.record(observed, observed, now, **extra)
        elif self.transitions[observed] is not None and self.transitions[cleared] is None:
            self.record(cleared, cleared, now, **extra)

    def record_ready_transition(self, ready_condition, now):
        self.record_ready_condition_change(ready_condition, now)
        if ready_condition.status == "True" and self.transitions["node_ready_at"] is None:
            self.record("node_ready_at", "node_ready", now,
                        last_transition_time=format_timestamp(ready_condition.last_transition_time))

    def record_ready_condition_change(self, ready_condition, now):
        """Append the Ready condition if its status, reason or message differs from the last entry.

        New in v2: shows what kubelet reported while the node was NotReady, so a slow
        node_ready can be attributed (e.g. CNI, CSINode, or a runtime issue).
        """
        history = self.transitions["ready_condition_history"]
        state = {
            "status": ready_condition.status,
            "reason": ready_condition.reason,
            "message": ready_condition.message,
        }
        if history and all(history[-1][key] == value for key, value in state.items()):
            return
        history.append({
            **state,
            "last_transition_time": format_timestamp(ready_condition.last_transition_time),
            "observed_at": format_timestamp_microseconds(now),
        })

    def record_initialization_milestones(self, ready_condition, now):
        """CNI conflist and CSINode are ready once kubelet stops listing them in the Ready message.

        Known v1 limitation, kept for parity: the first event whose message lacks the
        "not ready" text marks the milestone, even if that event arrives late or
        carries an unrelated message.
        """
        if ready_condition.status not in ("True", "False"):
            return
        message = (ready_condition.message or "").lower()
        if (self.transitions["cni_conflist_placed_at"] is None
                and not any(text in message for text in CNI_NOT_READY_MESSAGES)):
            self.record("cni_conflist_placed_at", "cni_conflist_placed", now)
        if self.transitions["csinode_ready_at"] is None and CSINODE_NOT_READY_MESSAGE not in message:
            self.record("csinode_ready_at", "csinode_ready", now)


def watch_node_transitions(api, existing_nodes, node_pool_name, node_label_key, cni_blocking_taint,
                           timeout_seconds, stop_event, recorders):
    """Record the transitions of every new node in the pool until `stop_event` is set or the timeout passes.

    `recorders` (node name -> NodeTransitionRecorder) is filled in as nodes appear, so
    the caller can read it once it stops the watch. The autoscaler can add more than
    one node, so the caller picks the probe pod's node from it. Nodes in
    `existing_nodes` are ignored.
    """
    deadline = time.time() + timeout_seconds
    node_watch = watch.Watch()
    try:
        for event in node_watch.stream(
            api.list_node,
            label_selector=f"{node_label_key}={node_pool_name}",
            timeout_seconds=int(timeout_seconds),
        ):
            if time.time() > deadline:
                break
            if stop_event.is_set():
                logger.info("Watch: stop signal received, terminating")
                break

            node = event["object"]
            node_name = node.metadata.name
            if node_name in existing_nodes:
                continue
            recorder = recorders.get(node_name)
            if recorder is None:
                recorder = recorders[node_name] = NodeTransitionRecorder(node_name, cni_blocking_taint)
            recorder.observe(node, utc_now())
    except Exception as e:
        logger.warning("Node watch ended: %s", e)
    finally:
        node_watch.stop()
