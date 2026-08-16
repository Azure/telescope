"""Constants and shared configuration for the fake control plane load test."""

import logging
import os
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
MANIFEST_DIR = MODULE_DIR / "manifests"
FAKE_EXPORTER_DIR = MANIFEST_DIR

KONN_SERVER_IMAGE = "mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/server:v0.32.1-11"
KONN_AGENT_IMAGE = "mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/agent:v0.32.1-11"
VMAGENT_IMAGE = "mcr.microsoft.com/oss/v2/victoriametrics/vmagent:v1.127.0-1"
# Real Go vmagent-proxy (prometheus-extensions) — matches prod's adx-vmagent kustomization.
VMAGENT_PROXY_IMAGE = "mcr.microsoft.com/aks/hcp/vmagent-proxy:1.522.0-master.260728-f125952f"
# Real, unmodified Prometheus -- used only as the per-node aggregator prototype
# (vmagent itself is push-only and can't expose a combined pull/federate
# endpoint; Prometheus's real /federate is the equivalent capability).
NODE_AGGREGATOR_IMAGE = "mcr.microsoft.com/oss/v2/prometheus/prometheus:v2.55.1-5"
VMSINGLE_IMAGE = "mcr.microsoft.com/oss/v2/victoriametrics/victoria-metrics:v1.125.1-7"
# -remoteWrite.rateLimit / -remoteWrite.flushInterval — both merged to prod
# 2026-07-28, fixed here rather than CLI-configurable (see wiki
# VMAgent-Konnectivity-Complete-Scale-Analysis.md). maxBlockSize remains
# configurable in main.py — still pending validation.
VMAGENT_RATE_LIMIT = 2097152
VMAGENT_FLUSH_INTERVAL = "1s"
FAKE_EXPORTER_IMAGE = os.environ.get(
    "FAKE_EXPORTER_IMAGE", "fakexporter.azurecr.io/fake-exporter:v2"
)

# Fixed tier-block nodepools (see azure.tfvars): tier selection is a
# scrape-config regex change, not a node scale. Cumulative by tier.
TIER_BLOCK_NODE_LABEL_KEY = "loadtest.io/tier-block"
TIER_BLOCK_REGEX = {
    500: "a",
    1000: "a|b",
    1500: "a|b|c",
    2000: "a|b|c|d",
}

# Dedicated, tainted konn-agent nodepool (see azure.tfvars) so several
# agent image/config variants can share it.
AGENT_NODE_LABEL_KEY = "loadtest.io/role"
AGENT_NODE_LABEL_VALUE = "konn-agent"
AGENT_TAINT_KEY = "dedicated"
AGENT_TAINT_VALUE = "konn-agent"
AGENT_TAINT_EFFECT = "NoSchedule"


def tier_block_regex(tier: int) -> str:
    """Cumulative tier-block regex; falls back to all blocks for unknown tiers."""
    return TIER_BLOCK_REGEX.get(tier, "a|b|c|d")


def tier_block_label_selector(tier: int) -> str:
    """kubectl label selector for the nodes in scope for `tier` (excludes dpagentpool)."""
    blocks = ",".join(tier_block_regex(tier).split("|"))
    return f"{TIER_BLOCK_NODE_LABEL_KEY} in ({blocks})"

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

# Terraform-provisioned system pool on the DP cluster (see
# scenarios/perf-eval/vmagent-loadtest/terraform-inputs/azure.tfvars). The
# "dataplane" pool itself is NOT terraform-managed -- it's created/deleted
# directly via az cli (see scaling.py) so it can be freely deleted+recreated
# between tiers/combos without terraform state drift or the slow
# graceful-drain path a terraform-managed scale-down would go through. This
# system pool's spec is used as the template when (re)creating "dataplane"
# from scratch.
DP_SYSTEM_NODEPOOL = "nodepool1"

# AKS hard cap: a single nodepool cannot exceed 1000 nodes. To reach larger
# tiers (2000, 5000, ...) the dataplane is fanned out across multiple nodepools
# named <base>, <base>2, <base>3, ... each holding up to this many nodes.
MAX_NODES_PER_POOL = 1000

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
# vmagent/vmagent_proxy requests+limits are pinned to prod's exact static
# values (aks-operator/config/channels/packages/adx-vmagent/default/
# statefulset.yaml) instead of scaling per tier -- matches real fleet sizing,
# and keeps deploy_vmagent()'s pod template identical across tier transitions
# so the StatefulSet only adds shards (non-disruptive) instead of also
# triggering a rolling restart of already-running shards on every tier step.
def _r(cpu_req, mem_req, cpu_lim, mem_lim):
    return {"cpu_req": cpu_req, "mem_req": mem_req,
            "cpu_lim": cpu_lim, "mem_lim": mem_lim}

VMAGENT_PROD_RESOURCES = _r("200m", "500Mi", "1500m", "2500Mi")
VMAGENT_PROXY_PROD_RESOURCES = _r("50m", "150Mi", "400m", "800Mi")

TIER_RESOURCE_BUCKETS = [
    # (upper_tier, shards, {"vmagent":..., "vmagent_proxy":..., "konn_server":...})
    # konn_server floors match prod's real Control Plane Scaling Profile (CPSP)
    # minimums -- H2 (cpuReq=1, memLimit=2Gi) below, H4/H8 (cpuReq=2,
    # memLimit=4Gi) at tier>=1000 -- so even the smallest load-test tier isn't
    # under-provisioned relative to the smallest real control plane (see
    # aks-rp/ccp/konnectivity-server-synth/helmvalues/control_plane_scaling_profile.go).
    (200,  1, {"vmagent":       VMAGENT_PROD_RESOURCES,
               "vmagent_proxy": VMAGENT_PROXY_PROD_RESOURCES,
               "konn_server":   _r("1",    "1Gi",   "2",    "2Gi")}),
    (350,  1, {"vmagent":       VMAGENT_PROD_RESOURCES,
               "vmagent_proxy": VMAGENT_PROXY_PROD_RESOURCES,
               "konn_server":   _r("1",    "1Gi",   "2",    "2Gi")}),
    (600,  1, {"vmagent":       VMAGENT_PROD_RESOURCES,
               "vmagent_proxy": VMAGENT_PROXY_PROD_RESOURCES,
               "konn_server":   _r("1",    "1Gi",   "2",    "2Gi")}),
    (1000, 3, {"vmagent":       VMAGENT_PROD_RESOURCES,
               "vmagent_proxy": VMAGENT_PROXY_PROD_RESOURCES,
               "konn_server":   _r("2",    "2Gi",   "2",    "4Gi")}),
    # tier 1500 needs 4 shards: 3 shards put ~5767 targets/shard which pushed
    # scrape_duration to ~5s. 4 shards -> ~4325/shard (proven-good range, tier
    # 1200 ran 4613/shard at 0.26s).
    (1500, 4, {"vmagent":       VMAGENT_PROD_RESOURCES,
               "vmagent_proxy": VMAGENT_PROXY_PROD_RESOURCES,
               "konn_server":   _r("2",    "2Gi",   "2",    "4Gi")}),
]
# Above the top bucket: shard so each vmagent holds ~TARGETS_PER_SHARD targets.
TARGETS_PER_SHARD = 3700
FAKE_ROLES_COUNT = 11  # keep in sync with len(FAKE_EXPORTER_ROLES)
TIER_RESOURCES_OVER = {
    "vmagent":       VMAGENT_PROD_RESOURCES,
    "vmagent_proxy": VMAGENT_PROXY_PROD_RESOURCES,
    "konn_server":   _r("2", "2Gi", "2", "4Gi"),
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


# Minimum konnectivity-agent replicas by DP node count, copied verbatim from
# prod's real autoscaler thresholds (aks-rp/ccp/konnectivity-agent-autoscaler/
# helmvalues/values.go, minReplicasByNodeCount) so the load test's agent
# replica count matches what prod would actually run at the same node count,
# rather than growing 1:1 with node/tier count.
KONN_AGENT_MIN_REPLICAS_BY_NODE_COUNT = [
    (50,   3),
    (100,  4),
    (250,  5),
    (500,  6),
    (1000, 7),
    (2000, 8),
    (5000, 10),
]


def konnectivity_agent_replicas_for_node_count(node_count: int) -> int:
    """Return the konnectivity-agent replica count prod would run for `node_count`."""
    if node_count <= 0:
        return 3
    for max_node_count, replicas in KONN_AGENT_MIN_REPLICAS_BY_NODE_COUNT:
        if node_count <= max_node_count:
            return replicas
    return KONN_AGENT_MIN_REPLICAS_BY_NODE_COUNT[-1][1]


# Real konnectivity-agent-autoscaler binary (aks-rp/ccp/konnectivity-agent-autoscaler),
# confirmed by the konnectivity team to accept --namespace/--target-* flags in
# this build -- unlike the shipped chart, which hardcodes kube-system.
# imranpochi/kas-dev:multiple-ns is a team-provided TEST image only; swap for
# an official tag once one ships.
KONN_AGENT_AUTOSCALER_IMAGE = "imranpochi/kas-dev:multiple-ns"

# CP cluster node sizing. Unlike the DP nodepool (scaled purely off node
# count), the CP cluster hosts konn-server/vmagent/vmsingle whose CPU
# *requests* grow with tier (see TIER_RESOURCE_BUCKETS) -- terraform's fixed
# 7-node baseline (2 default + 5 controlplane, see terraform-inputs/azure.tfvars)
# runs out of schedulable CPU at higher tiers (observed: FailedScheduling
# "Insufficient cpu" at tier 1500, server_count=10 @ 2 cores each). Compute
# how many CP nodes are actually needed instead of relying on the fixed
# terraform default for every tier.
DEFAULT_CP_CLUSTER_NAME = "vmagent-cp"
DEFAULT_CP_NODEPOOL = "controlplane"
CP_NODE_ALLOCATABLE_CPU_MILLI = 3860  # Standard_D4_v3 allocatable (kubectl get nodes)
CP_SYSTEM_RESERVED_MILLI = 500        # headroom for kube-system/vmsingle/monitoring
CP_SURGE_FACTOR = 1.5                 # rolling-update surge + burst headroom
CP_MIN_NODES = 7                      # never scale below the terraform baseline


def compute_server_count(tier: int) -> int:
    """Return the konnectivity-server replica count for `tier`."""
    proxied_targets = tier * len(FAKE_EXPORTER_ROLES) + tier + 50
    return max(3, (proxied_targets + 1999) // 2000)


def compute_cp_nodes_needed(tier: int) -> int:
    """Return the CP cluster node count needed to schedule konn-server +
    vmagent/vmagent-proxy at `tier`, with headroom for a rolling update.
    """
    def _cpu_millicores(v: str) -> int:
        return int(v[:-1]) if v.endswith("m") else int(v) * 1000

    resources = compute_resources_for_tier(tier)
    konn_cpu = compute_server_count(tier) * _cpu_millicores(resources["konn_server"]["cpu_req"])
    vmagent_cpu = compute_shard_count(tier) * (_cpu_millicores(resources["vmagent"]["cpu_req"])
                                               + _cpu_millicores(resources["vmagent_proxy"]["cpu_req"]))
    total_milli = (konn_cpu + vmagent_cpu) * CP_SURGE_FACTOR
    usable_per_node = CP_NODE_ALLOCATABLE_CPU_MILLI - CP_SYSTEM_RESERVED_MILLI
    import math
    return max(CP_MIN_NODES, math.ceil(total_milli / usable_per_node))


# ---------------- Azure Data Explorer (ADX) export ----------------
# Defaults for vmsingle time-series export. Env vars (ADX_CLUSTER_URI,
# ADX_INGEST_URI, ADX_DATABASE, ADX_AUTH) override these at runtime.
ADX_CLUSTER_URI = "https://vmagent-loadtesting.eastus2.kusto.windows.net"
ADX_INGEST_URI = "https://ingest-vmagent-loadtesting.eastus2.kusto.windows.net"
ADX_DATABASE = "vmagentloadtest"
ADX_AUTH = "az_cli"  # or "msi"

log = logging.getLogger("loadtest")
