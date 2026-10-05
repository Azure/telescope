"""Kusto schema for profile data: tables, ingestion mappings and the stored
functions that turn raw stacks into "where to look" / "how much could we save".

Tables are keyed so lab (Telescope) and prod (underlay collector) data can live
side by side: every row carries Env / Underlay / Namespace / Component / Pod.
"""

from .categories import kql_category_function, kql_stack_category_function
from .config import log

COMMON_COLUMNS = [
    ("Timestamp", "datetime"),
    ("RunId", "string"),
    ("Env", "string"),
    ("Underlay", "string"),
    ("Namespace", "string"),
    ("Tier", "int"),
    ("RunLabel", "string"),
    ("Component", "string"),
    ("Pod", "string"),
    ("Container", "string"),
]

# One row per (profile, sample type, unique stack).
PROFILE_SAMPLES_COLUMNS = COMMON_COLUMNS + [
    ("ProfileType", "string"),   # cpu | heap | allocs | goroutine
    ("SampleType", "string"),    # cpu | inuse_space | alloc_space | goroutine
    ("Unit", "string"),
    ("DurationSec", "real"),
    ("Value", "long"),
    ("Stack", "dynamic"),        # frames, leaf first
    ("Leaf", "string"),
    ("LeafPackage", "string"),
]

# One row per (profile, sample type): totals used to reconcile and sanity-check.
PROFILE_META_COLUMNS = COMMON_COLUMNS + [
    ("ProfileType", "string"),
    ("SampleType", "string"),
    ("Unit", "string"),
    ("DurationSec", "real"),
    ("TotalValue", "long"),
    ("ProfiledCores", "real"),   # cpu only: total samples / duration
    ("StackCount", "int"),
    ("File", "string"),
]

# One row per (pod, container, snapshot): includes containers that cannot be
# profiled with pprof (e.g. the Python vmagent-proxy sidecar).
COMPONENT_USAGE_COLUMNS = COMMON_COLUMNS + [
    ("Role", "string"),          # cp | dp
    ("Node", "string"),
    ("Image", "string"),
    ("UsageCores", "real"),
    ("UsageMemBytes", "long"),
    ("CpuReqCores", "real"),
    ("CpuLimCores", "real"),
    ("MemReqBytes", "long"),
    ("MemLimBytes", "long"),
]

# Compact roll-up written by the continuous collector (see rollup.py): ~60 rows
# per profile, Kind in total | category | function | other.
PROFILE_ROLLUP_COLUMNS = COMMON_COLUMNS + [
    ("Image", "string"),
    ("ProfileType", "string"),
    ("SampleType", "string"),
    ("Unit", "string"),
    ("DurationSec", "real"),
    ("Kind", "string"),
    ("Name", "string"),
    ("Flat", "long"),
    ("Cum", "long"),
]

TABLES = {
    "ProfileSamples": PROFILE_SAMPLES_COLUMNS,
    "ProfileRollup": PROFILE_ROLLUP_COLUMNS,
    "ProfileMeta": PROFILE_META_COLUMNS,
    "ComponentUsage": COMPONENT_USAGE_COLUMNS,
}


def mapping_name(table: str) -> str:
    return f"{table}Mapping"


def create_table_cmd(table: str) -> str:
    cols = ",\n    ".join(f"{n}: {t}" for n, t in TABLES[table])
    return f".create-merge table {table} (\n    {cols}\n)"


def create_mapping_cmd(table: str) -> str:
    items = ",".join(
        '{"column":"%s","Properties":{"Path":"$.%s"}}' % (n, n) for n, _ in TABLES[table]
    )
    return (f".create-or-alter table {table} ingestion json mapping "
            f"'{mapping_name(table)}' '[{items}]'")


# Category rules live in categories.py (shared with the continuous collector);
# these functions are generated from them so Kusto and Python cannot drift.
PROFILE_CATEGORY_FN = "\n" + kql_category_function()
PROFILE_STACK_CATEGORY_FN = "\n" + kql_stack_category_function()

# ASSUMPTIONS, not measurements: fraction of a category's CPU that realistic
# tuning could remove. Edit freely -- the savings model is just attributed
# cores x these fractions x the fleet multiplier.
PROFILE_CATEGORY_REDUCTION_FN = r'''
.create-or-alter function with (docstring='Assumed reducible CPU fraction per category (low/likely/high)', folder='Profiling')
ProfileCategoryReduction() {
    datatable(Category: string, Low: real, Likely: real, High: real, Lever: string) [
        "gc-and-allocation",   0.05, 0.15, 0.30, "GOGC/GOMEMLIMIT tuning, buffer pooling, fewer allocs",
        "scheduler-and-idle",  0.00, 0.00, 0.10, "mostly inherent; check GOMAXPROCS vs CPU limit",
        "syscall-and-network-io", 0.00, 0.05, 0.10, "batching / connection reuse",
        "compression",         0.10, 0.25, 0.50, "lower level / skip for in-cluster hops",
        "tls-and-crypto",      0.00, 0.05, 0.15, "session reuse, tunnel reuse",
        "grpc-and-http2",      0.00, 0.05, 0.15, "keepalive / stream tuning",
        "metrics-pipeline",    0.05, 0.15, 0.30, "drop series / relabel less / larger scrape interval",
        "logging",             0.30, 0.50, 0.80, "lower verbosity (--v)",
        "stdlib-misc",         0.00, 0.05, 0.15, "hot-path review",
        "other",               0.00, 0.00, 0.00, "unclassified"
    ]
}
'''

PROFILE_TOP_FUNCTIONS_FN = r'''
.create-or-alter function with (docstring='Top functions (flat+cum) for a component, pooled across pods', folder='Profiling')
ProfileTopFunctions(runId: string, tier: int, component: string, sampleType: string, n: int = 20) {
    let rows = ProfileSamples
        | where RunId == runId and Tier == tier and Component == component and SampleType == sampleType;
    let total = toscalar(rows | summarize sum(Value));
    let flat = rows | summarize Flat = sum(Value) by Function = Leaf;
    let cum = rows
        | extend Uniq = set_union(Stack, dynamic([]))
        | mv-expand Function = Uniq to typeof(string)
        | summarize Cum = sum(Value) by Function;
    flat
    | join kind=fullouter cum on Function
    | project Function = coalesce(Function, Function1), Flat = coalesce(Flat, 0), Cum = coalesce(Cum, 0)
    | extend FlatPct = round(100.0 * Flat / total, 2), CumPct = round(100.0 * Cum / total, 2),
             Category = ProfileCategory(Function)
    | top n by Flat desc
}
'''

PROFILE_CPU_SAVINGS_FN = r'''
.create-or-alter function with (docstring='Cores attributable per component/category and modelled savings for a tier', folder='Profiling')
ProfileCpuSavings(runId: string, tier: int, fleetMultiplier: real = 1.0) {
    ProfileSamples
    | where RunId == runId and Tier == tier and SampleType == "cpu"
    | extend Category = ProfileStackCategory(Stack, Leaf)
    | summarize Cores = sum(Value) / 1e9 / max(DurationSec) by Component, Pod, Category
    | summarize LabCores = sum(Cores) by Component, Category
    | join kind=leftouter ProfileCategoryReduction() on Category
    | project Component, Category, LabCores, Lever,
              SavedLow = LabCores * Low, SavedLikely = LabCores * Likely, SavedHigh = LabCores * High,
              FleetSavedLikely = LabCores * Likely * fleetMultiplier
    | order by Component asc, LabCores desc
}
'''

PROFILE_RIGHT_SIZING_FN = r'''
.create-or-alter function with (docstring='Requested vs used cores/memory per container for a tier (all containers, incl. non-pprof ones)', folder='Profiling')
ProfileRightSizing(runId: string, tier: int) {
    ComponentUsage
    | where RunId == runId and Tier == tier
    | summarize UsageCores = avg(UsageCores), PeakCores = max(UsageCores),
                UsageMemMiB = avg(UsageMemBytes) / 1048576.0, PeakMemMiB = max(UsageMemBytes) / 1048576.0,
                CpuReq = max(CpuReqCores), CpuLim = max(CpuLimCores),
                MemReqMiB = max(MemReqBytes) / 1048576.0, MemLimMiB = max(MemLimBytes) / 1048576.0
        by Component, Container, Pod
    | summarize Replicas = count(), UsageCores = sum(UsageCores), PeakCores = sum(PeakCores),
                UsageMemMiB = sum(UsageMemMiB), PeakMemMiB = sum(PeakMemMiB),
                CpuReq = sum(CpuReq), CpuLim = sum(CpuLim),
                MemReqMiB = sum(MemReqMiB), MemLimMiB = sum(MemLimMiB)
        by Component, Container
    | extend CpuSlack = CpuReq - PeakCores, MemSlackMiB = MemReqMiB - PeakMemMiB,
             CpuUtilOfReqPct = round(100.0 * PeakCores / CpuReq, 1),
             MemUtilOfReqPct = round(100.0 * PeakMemMiB / MemReqMiB, 1)
    | order by UsageCores desc
}
'''

PROFILE_ROLLUP_TOP_FN = r'''
.create-or-alter function with (docstring='Top functions from continuous roll-ups, pooled across sampled pods over a lookback window', folder='Profiling')
ProfileRollupTop(component: string, sampleType: string, n: int = 20, lookback: timespan = 7d, underlay: string = "") {
    let rows = ProfileRollup
        | where Timestamp > ago(lookback) and Component == component and SampleType == sampleType
        | where underlay == "" or Underlay == underlay;
    let total = toscalar(rows | where Kind == "total" | summarize sum(Flat));
    let profiles = toscalar(rows | where Kind == "total" | count);
    rows
    | where Kind == "function"
    | summarize Flat = sum(Flat), Cum = sum(Cum) by Function = Name
    | extend FlatPct = round(100.0 * Flat / total, 2), CumPct = round(100.0 * Cum / total, 2),
             Category = ProfileCategory(Function), Profiles = profiles
    | top n by Flat desc
}
'''

PROFILE_ROLLUP_CPU_SAVINGS_FN = r'''
.create-or-alter function with (docstring='Average cores per sampled pod by category from continuous roll-ups, and modelled savings x instance count', folder='Profiling')
ProfileRollupCpuSavings(lookback: timespan = 7d, instances: real = 1.0, underlay: string = "") {
    let cpu = ProfileRollup
        | where Timestamp > ago(lookback) and SampleType == "cpu" and DurationSec > 0
        | where underlay == "" or Underlay == underlay;
    let profiles = cpu | where Kind == "total" | summarize Profiles = count() by Component;
    cpu
    | where Kind == "category"
    | extend Category = Name
    | summarize Cores = sum(Flat / 1e9 / DurationSec) by Component, Category
    | join kind=inner profiles on Component
    | extend AvgCoresPerPod = Cores / Profiles
    | join kind=leftouter ProfileCategoryReduction() on Category
    | project Component, Category, Profiles, AvgCoresPerPod, Lever,
              SavedLow = AvgCoresPerPod * Low, SavedLikely = AvgCoresPerPod * Likely, SavedHigh = AvgCoresPerPod * High,
              FleetSavedLikely = AvgCoresPerPod * Likely * instances
    | order by Component asc, AvgCoresPerPod desc
}
'''

STORED_FUNCTIONS = [
    PROFILE_CATEGORY_FN,
    PROFILE_STACK_CATEGORY_FN,
    PROFILE_CATEGORY_REDUCTION_FN,
    PROFILE_TOP_FUNCTIONS_FN,
    PROFILE_CPU_SAVINGS_FN,
    PROFILE_RIGHT_SIZING_FN,
    PROFILE_ROLLUP_TOP_FN,
    PROFILE_ROLLUP_CPU_SAVINGS_FN,
]


def ensure_profile_schema(data_client, database: str) -> None:
    """Create profile tables, mappings and stored functions (idempotent)."""
    for table in TABLES:
        data_client.execute_mgmt(database, create_table_cmd(table))
        data_client.execute_mgmt(database, create_mapping_cmd(table))
    for fn in STORED_FUNCTIONS:
        data_client.execute_mgmt(database, fn)
    log.info("ADX profile schema ready: %s/{%s} + %d stored functions",
             database, ", ".join(TABLES), len(STORED_FUNCTIONS))
