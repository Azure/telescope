"""Constants and shared configuration for the VMAgent load test."""

import logging
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
MANIFEST_DIR = MODULE_DIR / "manifests"
FAKE_EXPORTER_DIR = MANIFEST_DIR  # fake-exporter manifest lives alongside others

KONN_SERVER_IMAGE = "mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/server:v0.32.1-3"
KONN_AGENT_IMAGE = "mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/agent:v0.32.1-3"
VMAGENT_IMAGE = "mcr.microsoft.com/oss/v2/victoriametrics/vmagent:v1.127.0-1"
VMSINGLE_IMAGE = "victoriametrics/victoria-metrics:v1.117.0"
FAKE_EXPORTER_IMAGE = "cuongcr.azurecr.io/fake-exporter:latest"

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
KUBELET_SA_NAME = "kubelet-scraper"

# Default AKS nodepool name
DEFAULT_NODEPOOL = "nodepool1"

# Max usable pods per node (AKS default max-pods=250, minus ~10 system pods)
PODS_PER_NODE = 240

log = logging.getLogger("loadtest")
