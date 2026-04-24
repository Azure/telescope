"""Constants and shared configuration for the fake control plane load test."""

import logging
import os
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
MANIFEST_DIR = MODULE_DIR / "manifests"
FAKE_EXPORTER_DIR = MANIFEST_DIR

KONN_SERVER_IMAGE = "mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/server:v0.32.1-3"
KONN_AGENT_IMAGE = "mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/agent:v0.32.1-3"
VMAGENT_IMAGE = "mcr.microsoft.com/oss/v2/victoriametrics/vmagent:v1.127.0-1"
VMSINGLE_IMAGE = "mcr.microsoft.com/oss/v2/victoriametrics/victoria-metrics:v1.125.1-7"
FAKE_EXPORTER_IMAGE = os.environ.get(
    "FAKE_EXPORTER_IMAGE", "fakexporter.azurecr.io/fake-exporter:latest"
)

# Fake exporter roles: (statefulset_name, app_label, port)
FAKE_EXPORTER_ROLES = [
    ("fake-nodeexp",   "fake-nodeexp",   19100),
    ("fake-cadvisor",  "fake-cadvisor",  19101),
    ("fake-kubelet",   "fake-kubelet",   10250),
    ("fake-kubeproxy", "fake-kubeproxy", 10256),
]
FAKE_EXPORTER_NS = "fake-exporter"

# Real target roles: (job_name, metrics_path, port, scheme)
REAL_TARGET_ROLES = [
    ("real-kubelet",    "/metrics",          10250, "https"),
    ("real-cadvisor",   "/metrics/cadvisor", 10250, "https"),
    ("real-kubeproxy",  "/metrics",          10249, "http"),
    ("real-azure-cns", "/metrics",          10092, "http"),
]

# DaemonSet target roles scraped via node role: (job_name, port)
DAEMONSET_TARGET_ROLES = [
    ("localdns",               9253),
    ("node-problem-detector", 20257),
]

# DaemonSet target roles scraped via pod role: (job_name, namespace)
DAEMONSET_POD_TARGET_ROLES = [
    ("csi-azuredisk-node", "kube-system"),
    ("kube-state-metrics", "kube-system"),
]
KUBELET_SA_NAME = "kubelet-scraper"

# Default AKS nodepool name
DEFAULT_NODEPOOL = "dataplane"

# Max usable pods per node (AKS default max-pods=250, minus ~10 system pods)
PODS_PER_NODE = 240

# CPU requests (millicores) for scaling calculations
AGENT_CPU_REQUEST = 10      # konnectivity-agent
EXPORTER_CPU_REQUEST = 5    # each fake-exporter role
SYSTEM_CPU_PER_NODE = 200   # kube-system overhead per node
NODE_ALLOCATABLE_CPU = 1900 # Standard_D2_v3 allocatable

log = logging.getLogger("loadtest")
