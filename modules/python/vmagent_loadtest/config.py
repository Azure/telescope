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
    "FAKE_EXPORTER_IMAGE", "fakexporter.azurecr.io/fake-exporter:v2"
)

# Fake exporter roles: (statefulset_name, app_label, port)
FAKE_EXPORTER_ROLES = [
    ("fake-nodeexp",        "fake-nodeexp",        19100),
    ("fake-cadvisor",       "fake-cadvisor",       19101),
    ("fake-kubelet",        "fake-kubelet",        10250),
    ("fake-kubeproxy",      "fake-kubeproxy",      10249),
    ("fake-cns",            "fake-cns",            10092),
    ("fake-npd",            "fake-npd",            20257),
    ("fake-runtime",        "fake-runtime",        10257),
    ("fake-azurefile",      "fake-azurefile",      29615),
    ("fake-ksm",            "fake-ksm",            8080),
    ("fake-csi-azuredisk",  "fake-csi-azuredisk",  29614),
    ("fake-localdns",       "fake-localdns",       9253),
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
AGENT_MEM_REQUEST_MI = 64       # konnectivity-agent memory request (Mi)
EXPORTER_MEM_REQUEST_MI = 16    # each fake-exporter memory request (Mi)
SYSTEM_CPU_PER_NODE = 200   # kube-system overhead per node
NODE_ALLOCATABLE_CPU = 1900 # Standard_D2_v3 allocatable
NODE_ALLOCATABLE_MEM_MI = 5931  # Standard_D2_v3 allocatable memory (Mi)
SYSTEM_MEM_PER_NODE_MI = 800    # kube-system + kubelet overhead (Mi)

# Tier-bucketed resource sizing for the scrape pipeline. Each bucket gives
# requests/limits for the three components that bottleneck under load:
#   - vmagent         (scrape engine; sharded horizontally via native clustering)
#   - vmagent-proxy   (CONNECT translator; one sidecar per vmagent shard)
#   - konn-server     (per-pod; replica count is scaled separately in runner)
# vmagent/vmagent-proxy values are PER-SHARD. `shards` is the vmagent replica
# count for the tier; sharding splits scrape targets across replicas using
# vmagent native clustering (-promscrape.cluster.*), so each shard holds
# ~total_targets/shards and its memory scales down accordingly.
#
# Memory limits are ~2× the observed/projected per-shard steady RSS. Recorded
# RSS lags sub-second spikes (WAL flush + remote-write backlog), so limits are
# intentionally larger than observed steady-state usage. Observed monolithic
# RSS: tier 150 → 213 MiB, 300 → 285 MiB, 500 → 2126 MiB, 1000 → 3336 MiB.
def _r(cpu_req, mem_req, cpu_lim, mem_lim):
    return {"cpu_req": cpu_req, "mem_req": mem_req,
            "cpu_lim": cpu_lim, "mem_lim": mem_lim}

TIER_RESOURCE_BUCKETS = [
    # (upper_tier, shards, {"vmagent":..., "vmagent_proxy":..., "konn_server":...})
    # vmagent/vmagent_proxy resources are PER-SHARD.
    (200,  1, {"vmagent":       _r("100m", "256Mi", "500m", "512Mi"),
               "vmagent_proxy": _r("100m", "128Mi", "1",    "256Mi"),
               "konn_server":   _r("100m", "128Mi", "500m", "512Mi")}),
    (350,  1, {"vmagent":       _r("250m", "512Mi", "1",    "1Gi"),
               "vmagent_proxy": _r("250m", "256Mi", "2",    "512Mi"),
               "konn_server":   _r("200m", "256Mi", "1",    "1Gi")}),
    (600,  1, {"vmagent":       _r("500m", "1Gi",   "2",    "3Gi"),
               "vmagent_proxy": _r("500m", "256Mi", "4",    "1Gi"),
               "konn_server":   _r("200m", "256Mi", "1",    "1Gi")}),
    (1000, 3, {"vmagent":       _r("500m", "1Gi",   "2",    "3Gi"),
               "vmagent_proxy": _r("500m", "256Mi", "4",    "1Gi"),
               "konn_server":   _r("300m", "512Mi", "1",    "2Gi")}),
    (1500, 3, {"vmagent":       _r("1",    "2Gi",   "3",    "4Gi"),
               "vmagent_proxy": _r("500m", "512Mi", "6",    "1Gi"),
               "konn_server":   _r("500m", "512Mi", "2",    "2Gi")}),
]
# Above the top bucket: shard so each vmagent holds ~TARGETS_PER_SHARD targets.
TARGETS_PER_SHARD = 4000
FAKE_ROLES_COUNT = 11  # keep in sync with len(FAKE_EXPORTER_ROLES)
TIER_RESOURCES_OVER = {
    "vmagent":       _r("1", "2Gi", "4", "4Gi"),
    "vmagent_proxy": _r("1", "512Mi", "6", "2Gi"),
    "konn_server":   _r("500m", "1Gi", "2", "4Gi"),
}


def compute_shard_count(tier: int) -> int:
    """Return the vmagent replica (shard) count for `tier`.

    Sharding splits scrape targets across vmagent replicas via native
    clustering, so each shard runs its own proxy sidecar — removing the
    single-proxy GIL bottleneck that capped throughput at ~5.7k targets.
    """
    for upper, shards, _ in TIER_RESOURCE_BUCKETS:
        if tier <= upper:
            return shards
    import math
    target_count = tier * FAKE_ROLES_COUNT
    return max(1, math.ceil(target_count / TARGETS_PER_SHARD))


def compute_resources_for_tier(tier: int) -> dict:
    """Return PER-SHARD requests/limits sized for `tier`.

    Returns a dict keyed by component name ('vmagent', 'vmagent_proxy',
    'konn_server'), each value a dict with cpu_req/mem_req/cpu_lim/mem_lim.
    vmagent/vmagent_proxy values are per-shard; use compute_shard_count() for
    the replica count.
    """
    for upper, _shards, bucket in TIER_RESOURCE_BUCKETS:
        if tier <= upper:
            return bucket
    return TIER_RESOURCES_OVER

# ---------------- Azure Data Explorer (ADX) export ----------------
# Defaults for vmsingle time-series export. Env vars (ADX_CLUSTER_URI,
# ADX_INGEST_URI, ADX_DATABASE, ADX_AUTH) override these at runtime.
ADX_CLUSTER_URI = "https://vmagent-loadtesting.eastus2.kusto.windows.net"
ADX_INGEST_URI = "https://ingest-vmagent-loadtesting.eastus2.kusto.windows.net"
ADX_DATABASE = "vmagentloadtest"
ADX_AUTH = "az_cli"  # or "msi"

log = logging.getLogger("loadtest")
