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
    ("fake-cns",       "fake-cns",       10092),
    ("fake-npd",       "fake-npd",       20257),
    ("fake-runtime",   "fake-runtime",   10257),
    ("fake-azurefile", "fake-azurefile", 29615),
]
FAKE_EXPORTER_NS = "fake-exporter"

# Real target roles: (job_name, metrics_path, port, scheme)
REAL_TARGET_ROLES = [
    ("real-kubelet",    "/metrics",          10250, "https"),
    ("real-cadvisor",   "/metrics/cadvisor", 10250, "https"),
    ("real-kubeproxy",  "/metrics",          10249, "http"),
    ("real-azure-cns", "/metrics",          10092, "http"),
    ("node-exporter",  "/metrics",          19100, "http"),
    ("node-runtime",   "/v1/metrics",       10257, "http"),
]

# DaemonSet target roles scraped via node role: (job_name, port)
# NOTE: only roles whose underlying daemonsets are actually deployed in the
# target cluster contribute to min_targets. localdns/NPD are typically not
# present on stock AKS, so they are excluded from the expectation. The scrape
# config still defines those jobs (harmless if absent).
DAEMONSET_TARGET_ROLES = [
]

# DaemonSet target roles scraped via pod role (1 per node): (job_name, namespace)
# csi-azuredisk-node pods exist but their relabel filter (port name "metrics")
# does not match in stock AKS, so only csi-azurefile-node contributes.
DAEMONSET_POD_TARGET_ROLES = [
    ("csi-azurefile-node", "kube-system"),
]

# Singleton targets scraped via pod role (1 total): (job_name, namespace)
# kube-state-metrics is not deployed by default on AKS — exclude from expected.
SINGLETON_POD_TARGET_ROLES = [
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

# ---------------- Azure Data Explorer (ADX) export ----------------
# Defaults for vmsingle time-series export. Env vars (ADX_CLUSTER_URI,
# ADX_INGEST_URI, ADX_DATABASE, ADX_AUTH) override these at runtime.
ADX_CLUSTER_URI = "https://vmagent-loadtesting.eastus2.kusto.windows.net"
ADX_INGEST_URI = "https://ingest-vmagent-loadtesting.eastus2.kusto.windows.net"
ADX_DATABASE = "vmagentloadtest"
ADX_AUTH = "az_cli"  # or "msi"

log = logging.getLogger("loadtest")
