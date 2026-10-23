"""Node watch that records a new node's lifecycle transitions as they happen (ported from v1).

Timestamps here are the pipeline agent's wall clock when the watch event arrived,
not API-server times. Each observation is stored twice from the same instant:
whole-second (v1 format) and `*_precise` (microseconds, new in v2).
"""
import time
from datetime import datetime, timezone

from kubernetes import watch

from node_startup.timestamps import format_precise_timestamp, format_timestamp
from utils.logger_config import get_logger

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


def new_watch_result():
    result = {"events": [], "ready_condition_history": []}
    for key in OBSERVED_KEYS:
        result[key] = None
        result[f"{key}_precise"] = None
    return result


def utc_now():
    return datetime.now(timezone.utc)


def record_ready_condition_change(history, ready_condition, now):
    """Append the Ready condition if its status, reason or message differs from the last entry.

    New in v2: shows what kubelet reported while the node was NotReady, so a slow
    node_ready can be attributed (e.g. CNI, CSINode, or a runtime issue).
    """
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
        "observed_at": format_timestamp(now),
        "observed_at_precise": format_precise_timestamp(now),
    })


def watch_node_transitions(api, existing_nodes, node_pool_name, cni_blocking_taint=None,
                           timeout_minutes=15, stop_event=None, result=None,
                           node_label_key="agentpool", clock=None):
    """Watch the pool for the first node not in `existing_nodes` and record its transitions.

    Writes into `result` as events arrive, so another thread can read partial
    results even if this watch is still blocked on I/O.
    """
    if result is None:
        result = new_watch_result()
    clock = clock or utc_now

    deadline = time.time() + (timeout_minutes * 60)
    new_node_name = None
    saw_not_ready_taint = False
    saw_network_unavailable_taint = False
    saw_cni_taint = False
    node_ready_recorded = False
    cni_conflist_placed = False
    csinode_ready = False

    def record(key, event_name, node_name, now, **extra):
        result[key] = format_timestamp(now)
        result[f"{key}_precise"] = format_precise_timestamp(now)
        result["events"].append({
            "event": event_name,
            "node": node_name,
            **extra,
            "observed_at": format_timestamp(now),
            "observed_at_precise": format_precise_timestamp(now),
        })

    node_watch = watch.Watch()
    try:
        for event in node_watch.stream(
            api.list_node,
            label_selector=f"{node_label_key}={node_pool_name}",
            timeout_seconds=int(timeout_minutes * 60),
        ):
            if time.time() > deadline:
                break
            if stop_event and stop_event.is_set():
                logger.info("Watch: stop signal received, terminating")
                break

            node = event["object"]
            node_name = node.metadata.name
            if node_name in existing_nodes:
                continue

            now = clock()

            if new_node_name is None:
                new_node_name = node_name
                result["node_registered_at"] = format_timestamp(now)
                result["node_registered_at_precise"] = format_precise_timestamp(now)
                result["events"].append({
                    "event": "node_registered",
                    "node": node_name,
                    "observed_at": format_timestamp(now),
                    "observed_at_precise": format_precise_timestamp(now),
                    "creation_timestamp": format_timestamp(node.metadata.creation_timestamp),
                })
                logger.info("Watch: new node '%s' registered", node_name)

            current_taints = {(taint.key, taint.effect) for taint in (node.spec.taints or [])}

            if NOT_READY_TAINT in current_taints:
                if not saw_not_ready_taint:
                    saw_not_ready_taint = True
                    record("not_ready_taint_observed", "not_ready_taint_observed", node_name, now)
                    logger.info("Watch: not-ready taint observed on '%s'", node_name)
            elif saw_not_ready_taint and result["not_ready_taint_cleared"] is None:
                record("not_ready_taint_cleared", "not_ready_taint_cleared", node_name, now)
                logger.info("Watch: not-ready taint cleared on '%s'", node_name)

            if NETWORK_UNAVAILABLE_TAINT in current_taints:
                if not saw_network_unavailable_taint:
                    saw_network_unavailable_taint = True
                    record("network_unavailable_taint_observed", "network_unavailable_taint_observed", node_name, now)
                    logger.info("Watch: network-unavailable taint observed on '%s'", node_name)
            elif saw_network_unavailable_taint and result["network_unavailable_taint_cleared"] is None:
                record("network_unavailable_taint_cleared", "network_unavailable_taint_cleared", node_name, now)
                logger.info("Watch: network-unavailable taint cleared on '%s'", node_name)

            # The CNI taint is matched on key only, any effect.
            if cni_blocking_taint:
                cni_taint_present = any(taint.key == cni_blocking_taint for taint in (node.spec.taints or []))
                if cni_taint_present:
                    if not saw_cni_taint:
                        saw_cni_taint = True
                        record("cni_taint_observed", "cni_taint_observed", node_name, now, taint=cni_blocking_taint)
                        logger.info("Watch: CNI taint '%s' observed on '%s'", cni_blocking_taint, node_name)
                elif saw_cni_taint and result["cni_taint_cleared"] is None:
                    record("cni_taint_cleared", "cni_taint_cleared", node_name, now, taint=cni_blocking_taint)
                    logger.info("Watch: CNI taint '%s' cleared on '%s'", cni_blocking_taint, node_name)

            ready_condition = next(
                (condition for condition in (node.status.conditions or []) if condition.type == "Ready"), None)

            if ready_condition is not None:
                record_ready_condition_change(result["ready_condition_history"], ready_condition, now)

            if not node_ready_recorded and ready_condition is not None and ready_condition.status == "True":
                node_ready_recorded = True
                record("node_ready_at", "node_ready", node_name, now,
                       last_transition_time=format_timestamp(ready_condition.last_transition_time))
                logger.info("Watch: node '%s' is Ready", node_name)

            # Known v1 limitation, kept for parity: the first event whose Ready message
            # lacks the "not ready" text marks the milestone, even if that first event
            # arrives late or carries an unrelated message.
            if not cni_conflist_placed and ready_condition is not None:
                message = (ready_condition.message or "").lower()
                if (not any(text in message for text in CNI_NOT_READY_MESSAGES)
                        and ready_condition.status in ("True", "False")):
                    cni_conflist_placed = True
                    record("cni_conflist_placed_at", "cni_conflist_placed", node_name, now)
                    logger.info("Watch: CNI conflist placed on '%s' (NetworkPluginNotReady cleared)", node_name)

            if not csinode_ready and ready_condition is not None:
                message = (ready_condition.message or "").lower()
                if CSINODE_NOT_READY_MESSAGE not in message and ready_condition.status in ("True", "False"):
                    csinode_ready = True
                    record("csinode_ready_at", "csinode_ready", node_name, now)
                    logger.info("Watch: CSINode registered on '%s'", node_name)

    except Exception as e:
        logger.warning("Node watch ended: %s", e)
    finally:
        node_watch.stop()

    return result
