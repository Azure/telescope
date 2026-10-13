"""Input scenarios shared by the v2 tests and the v1 golden-output generator.

Kubernetes objects are plain dicts shaped like `kubectl get -o json` output.
"""
from datetime import datetime, timezone

NODE = "aks-userpool-12345678-vmss000003"
EXISTING_NODE = "aks-userpool-12345678-vmss000000"
CILIUM_LABEL = "k8s-app=cilium"
CILIUM_TAINT = "node.cilium.io/agent-not-ready"
PROBE_NAMESPACE = "node-startup-latency"
PROBE_POD = "latency-probe-1"
CILIUM_POD = "cilium-x7k2p"
CILIUM_IMAGE = "mcr.microsoft.com/containernetworking/cilium/cilium:v1.19.3-260520"


def at(second, micro=0):
    """ISO timestamp at 2026-10-02T10:00:00Z + `second` seconds (+ microseconds)."""
    minute, sec = divmod(second, 60)
    base = f"2026-10-02T10:{minute:02d}:{sec:02d}"
    return f"{base}.{micro:06d}Z" if micro else f"{base}Z"


def clock(second, micro=0):
    minute, sec = divmod(second, 60)
    return datetime(2026, 10, 2, 10, minute, sec, micro, tzinfo=timezone.utc)


# --- Derived latencies -------------------------------------------------------

MANAGED_CILIUM_TIMESTAMPS = {
    "pod_created": at(0),
    "triggered_scale_up": at(5),
    "node_registered": at(100),
    "node_ready": at(115),
    "node_network_unavailable_cleared": at(103),
    "cni_conflist_placed": at(112),
    "csinode_ready": at(105),
    "not_ready_taint_observed": at(101),
    "not_ready_taint_cleared": at(116),
    "network_unavailable_taint_observed": None,
    "network_unavailable_taint_cleared": None,
    "cni_taint_observed": at(102),
    "cni_taint_cleared": at(119),
    "cni_container_started": at(110),
    "cni_pod_ready": at(118),
    "cni_pod_scheduled": at(101),
    "cni_containers": [{"name": "cilium-agent", "image": CILIUM_IMAGE, "started_at": at(110), "ready": True}],
    "deep_cilium_metrics": {
        "bootstrap": {"overall": 12.5, "k8sInit": 3.25},
        "endpoint_regen": {"total": 0.5, "policyCalculation": 0},
        "metadata": {"cilium_identity_count": 11, "cilium_bpf_map_pressure": 0.02, "cilium_version": "1.19.3"},
    },
    "pod_scheduled": at(120),
    "container_started": at(123),
    "pod_ready": at(124),
}

LATENCY_SCENARIOS = {
    "managed_cilium": MANAGED_CILIUM_TIMESTAMPS,
    "node_ready_after_cni": {**MANAGED_CILIUM_TIMESTAMPS, "node_ready": at(121), "cni_pod_ready": at(114)},
    "azure_cni_no_cni_pod": {
        "pod_created": at(0), "triggered_scale_up": at(4), "node_registered": at(95), "node_ready": at(108),
        "node_network_unavailable_cleared": None, "cni_conflist_placed": at(104), "csinode_ready": at(99),
        "not_ready_taint_observed": at(96), "not_ready_taint_cleared": at(109),
        "cni_container_started": None, "cni_pod_ready": None, "cni_pod_scheduled": None, "cni_containers": [],
        "deep_cilium_metrics": None,
        "pod_scheduled": at(110), "container_started": at(112), "pod_ready": at(113),
    },
    "kubenet_network_unavailable": {
        "pod_created": at(0), "triggered_scale_up": None, "node_registered": at(90), "node_ready": at(100),
        "node_network_unavailable_cleared": at(118),
        "network_unavailable_taint_observed": at(91), "network_unavailable_taint_cleared": at(119),
        "cni_conflist_placed": at(92), "pod_scheduled": at(120), "container_started": at(121), "pod_ready": at(122),
    },
    "version_from_image_only": {**MANAGED_CILIUM_TIMESTAMPS, "deep_cilium_metrics": None},
    "version_missing_in_metrics": {
        **MANAGED_CILIUM_TIMESTAMPS,
        "deep_cilium_metrics": {"bootstrap": {}, "endpoint_regen": {},
                                "metadata": {"cilium_identity_count": None, "cilium_bpf_map_pressure": None,
                                             "cilium_version": None}},
    },
    "malformed_and_missing": {"pod_created": "not-a-time", "node_registered": at(90), "node_ready": None,
                              "container_started": at(100)},
    "empty": {},
}

# --- Cilium metrics text ------------------------------------------------------

CILIUM_METRICS_TEXT = "\n".join([
    "# HELP cilium_agent_bootstrap_seconds Duration of bootstrap sequence",
    "# TYPE cilium_agent_bootstrap_seconds gauge",
    'cilium_agent_bootstrap_seconds{outcome="success",scope="overall"} 12.5',
    'cilium_agent_bootstrap_seconds{outcome="success",scope="k8sInit"} 3.25',
    'cilium_bootstrap_seconds{scope="restore"} 0.75',
    'cilium_bootstrap_seconds{scope="broken"} not-a-number',
    'cilium_endpoint_regeneration_time_stats_seconds_sum{scope="total"} 4.5',
    'cilium_endpoint_regeneration_time_stats_seconds_count{scope="total"} 9',
    'cilium_endpoint_regeneration_time_stats_seconds_sum{scope="policyCalculation"} 0',
    'cilium_endpoint_regeneration_time_stats_seconds_count{scope="policyCalculation"} 0',
    'cilium_endpoint_regeneration_time_stats_seconds_sum{scope="sumOnly"} 2',
    # v1 takes the first label ending in version="...", here go_version; kept for parity.
    'cilium_version_info{go_version="go1.23",revision="abc",version="1.19.3"} 1',
    'cilium_identity{type="cluster_local"} 7',
    'cilium_identity{type="node_local"} 4',
    'cilium_bpf_map_pressure{map_name="lb4_services"} 0.01',
    'cilium_bpf_map_pressure{map_name="ct4_global"} 0.02',
])

CILIUM_METRICS_SCENARIOS = {
    "per_type_identity_gauges": CILIUM_METRICS_TEXT,
    "legacy_identity_count": CILIUM_METRICS_TEXT + "\ncilium_identity_count 42",
    "empty": "",
}

# --- CNI daemonset pod on the new node ----------------------------------------


def cilium_pod():
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": CILIUM_POD, "namespace": "kube-system", "labels": {"k8s-app": "cilium"}},
        "spec": {
            "nodeName": NODE,
            "initContainers": [{"name": "install-cni-binaries"}, {"name": "mount-cgroup"},
                               {"name": "silent-init"}, {"name": "clean-cilium-state"},
                               {"name": "no-log-access"}],
            "containers": [{"name": "cilium-agent"}],
        },
        "status": {
            "phase": "Running",
            "conditions": [
                {"type": "PodScheduled", "status": "True", "lastTransitionTime": at(101)},
                {"type": "Initialized", "status": "True", "lastTransitionTime": at(109)},
                {"type": "Ready", "status": "True", "lastTransitionTime": at(118)},
            ],
            "initContainerStatuses": [
                {"name": "install-cni-binaries", "image": "cilium-init:1", "imageID": "", "ready": False,
                 "restartCount": 0,
                 "state": {"terminated": {"exitCode": 0, "startedAt": at(103), "finishedAt": at(104)}}},
                {"name": "mount-cgroup", "image": "cilium-init:1", "imageID": "", "ready": False,
                 "restartCount": 1, "state": {"waiting": {"reason": "PodInitializing"}},
                 "lastState": {"terminated": {"exitCode": 0, "startedAt": at(104), "finishedAt": at(106)}}},
                {"name": "silent-init", "image": "cilium-init:1", "imageID": "", "ready": False,
                 "restartCount": 0, "state": {"running": {"startedAt": at(106)}}},
                {"name": "clean-cilium-state", "image": "cilium-init:1", "imageID": "", "ready": False,
                 "restartCount": 0,
                 "state": {"terminated": {"exitCode": 0, "startedAt": at(107), "finishedAt": at(108)}}},
            ],
            "containerStatuses": [
                {"name": "cilium-agent", "image": CILIUM_IMAGE, "imageID": "", "ready": True, "restartCount": 0,
                 "state": {"running": {"startedAt": at(110)}}},
                {"name": "cilium-monitor", "image": CILIUM_IMAGE, "imageID": "", "ready": False,
                 "restartCount": 0, "state": {"waiting": {"reason": "ContainerCreating"}}},
            ],
        },
    }


def event(name, namespace, reason, message="", first_timestamp=None, event_time=None, created=None):
    body = {
        "apiVersion": "v1", "kind": "Event",
        "metadata": {"name": f"{name}.{reason}.{first_timestamp or event_time}", "namespace": namespace,
                     "creationTimestamp": created or first_timestamp or at(0)},
        "involvedObject": {"kind": "Pod", "name": name, "namespace": namespace},
        "reason": reason,
        "message": message,
    }
    if first_timestamp:
        body["firstTimestamp"] = first_timestamp
    if event_time:
        body["eventTime"] = event_time
    return body


CILIUM_POD_EVENTS = [
    event(CILIUM_POD, "kube-system", "Scheduled", "Successfully assigned", event_time=at(101, 250000)),
    event(CILIUM_POD, "kube-system", "Pulling", 'Pulling image "cilium-init:1"', first_timestamp=at(102)),
    event(CILIUM_POD, "kube-system", "Pulled",
          'Successfully pulled image "cilium-init:1" in 1.2s (1.2s including waiting)', first_timestamp=at(103)),
    event(CILIUM_POD, "kube-system", "Pulled",
          f'Container image "{CILIUM_IMAGE}" already present on machine', first_timestamp=at(109)),
    event(CILIUM_POD, "kube-system", "Pulling", "Pulling image without quotes", first_timestamp=at(102)),
    event(CILIUM_POD, "kube-system", "Started", "Started container cilium-agent", first_timestamp=at(110)),
]

CILIUM_POD_LOGS = {
    f"kube-system/{CILIUM_POD}/install-cni-binaries": "\n".join([
        f"{at(103, 100000)[:-1]}123Z Installing cilium-cni binaries to /host/opt/cni/bin",
        "not a timestamped line",
        f"{at(103, 900000)[:-1]}456Z install-plugin done",
    ]),
    f"kube-system/{CILIUM_POD}/mount-cgroup": f"{at(105, 200000)[:-1]}000Z Mounted cgroupv2 filesystem at /run/cilium/cgroupv2",
    f"kube-system/{CILIUM_POD}/silent-init": "",
    f"kube-system/{CILIUM_POD}/clean-cilium-state": "\n".join([
        f"{at(107, 500000)[:-1]}000Z Removing stale cilium state; rm -rf /var/run/cilium/state",
        f"{at(107, 600000)[:-1]}000Z sysctl net.ipv4.conf.all.rp_filter=0",
        f"{at(107, 900000)[:-1]}000Z Mounted bpf on /sys/fs/bpf",
    ]),
}

CNI_POD_SCENARIOS = {
    "cilium_agent": {"pods": [cilium_pod()], "events": CILIUM_POD_EVENTS, "logs": CILIUM_POD_LOGS},
    "no_pod_on_node": {"pods": [], "events": [], "logs": {}},
}

# --- Node watch ---------------------------------------------------------------

CNI_NOT_READY = ("container runtime network not ready: NetworkReady=false reason:NetworkPluginNotReady "
                 "message:Network plugin returns error: cni plugin not initialized")


def node(name, taints=(), ready_status="False", ready_message="", ready_transition=at(100), labels=None):
    return {
        "apiVersion": "v1", "kind": "Node",
        "metadata": {"name": name, "creationTimestamp": at(100),
                     "labels": labels or {"agentpool": "userpool"}},
        "spec": {"taints": [{"key": key, "effect": effect} for key, effect in taints]},
        "status": {"conditions": [
            {"type": "MemoryPressure", "status": "False"},
            {"type": "Ready", "status": ready_status, "message": ready_message,
             "reason": "KubeletReady" if ready_status == "True" else "KubeletNotReady",
             "lastTransitionTime": ready_transition},
        ]},
    }


NOT_READY = ("node.kubernetes.io/not-ready", "NoSchedule")
NOT_READY_EXECUTE = ("node.kubernetes.io/not-ready", "NoExecute")
NETWORK_UNAVAILABLE = ("node.kubernetes.io/network-unavailable", "NoSchedule")
CILIUM_TAINT_ENTRY = (CILIUM_TAINT, "NoExecute")

WATCH_SCENARIOS = {
    "managed_cilium": {
        "cni_blocking_taint": CILIUM_TAINT,
        "nodes": [
            node(EXISTING_NODE, ready_status="True"),
            node(NODE, [NOT_READY, CILIUM_TAINT_ENTRY], ready_message=CNI_NOT_READY),
            node(NODE, [NOT_READY, NOT_READY_EXECUTE, CILIUM_TAINT_ENTRY],
                 ready_message="CSINode is not yet initialized"),
            node(NODE, [NOT_READY, CILIUM_TAINT_ENTRY], ready_message="kubelet is posting ready status"),
            node(NODE, [CILIUM_TAINT_ENTRY], ready_status="True", ready_transition=at(115)),
            node(NODE, [], ready_status="True", ready_transition=at(115)),
            node(NODE, [], ready_status="True", ready_transition=at(115)),
        ],
        "clock": [(100, 400000), (101, 1), (104, 999999), (112, 500000), (115, 250000), (119, 0), (130, 5)],
    },
    "first_event_already_ready": {
        "cni_blocking_taint": CILIUM_TAINT,
        "nodes": [node(NODE, [], ready_status="True", ready_transition=at(108))],
        "clock": [(109, 123456)],
    },
    "kubenet_network_unavailable": {
        "cni_blocking_taint": None,
        "nodes": [
            node(NODE, [NOT_READY, NETWORK_UNAVAILABLE], ready_message=CNI_NOT_READY),
            node(NODE, [NETWORK_UNAVAILABLE], ready_status="True", ready_transition=at(100)),
            node(NODE, [], ready_status="True", ready_transition=at(100)),
        ],
        "clock": [(90, 10), (100, 20), (119, 30)],
    },
}

# --- Scale-up trigger lookup ------------------------------------------------------

TRIGGER_SCENARIOS = {
    "triggered_scale_up_whole_second": [
        event(PROBE_POD, PROBE_NAMESPACE, "FailedScheduling", first_timestamp=at(1)),
        event(PROBE_POD, PROBE_NAMESPACE, "TriggeredScaleUp", first_timestamp=at(5)),
    ],
    "triggered_scale_up_with_event_time": [
        event(PROBE_POD, PROBE_NAMESPACE, "TriggeredScaleUp", event_time=at(5, 432100)),
    ],
    "failed_scheduling_fallback": [
        event(PROBE_POD, PROBE_NAMESPACE, "FailedScheduling", first_timestamp=at(3)),
        event(PROBE_POD, PROBE_NAMESPACE, "FailedScheduling", event_time=at(1, 700000)),
        event(PROBE_POD, PROBE_NAMESPACE, "FailedScheduling", event_time=at(1, 900000)),
        event(PROBE_POD, PROBE_NAMESPACE, "Nominated", first_timestamp=at(0)),
    ],
    "no_events": [],
}
