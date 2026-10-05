"""Collect CPU/memory profiles from every replica of the load-test stack and
land them in Kusto (ProfileSamples / ProfileMeta / ComponentUsage).

Runs at steady state of a ramp tier (see runner.run_real_targets_ramp). pprof
covers the Go components; container usage + requests/limits are captured for
*all* containers so non-Go sidecars (vmagent-proxy) still show up in sizing.
"""

import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import config as _config
from .config import log
from .pprof import OTHER_FRAME, PROFILE_KINDS, Profile, aggregate_stacks, parse_profile, split_go_func
from .quantity import parse_cpu, parse_mem  # noqa: F401  (re-exported)
from .profile_schema import ensure_profile_schema, mapping_name
from .utils import PortForward, kubectl

# role: which cluster; pprof_port: admin/http port serving /debug/pprof.
PPROF_COMPONENTS = [
    {"component": "konn-server", "role": "cp", "selector": "app=konnectivity-server", "port": 8096},
    {"component": "vmagent", "role": "cp", "selector": "app=vmagent", "port": 8429},
    {"component": "vmsingle", "role": "cp", "selector": "app=vmsingle", "port": 8428},
    {"component": "konn-agent", "role": "dp", "selector": "app=konnectivity-agent", "port": 8094},
]

CONTAINER_COMPONENT = {
    "konnectivity-server": "konn-server",
    "konnectivity-agent": "konn-agent",
    "vmagent": "vmagent",
    "vmagent-proxy": "vmagent-proxy",
    "vmsingle": "vmsingle",
}

def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc).isoformat()


# ---------------------------------------------------------------- row building

def profile_rows(ctx: dict, component: str, pod: str, container: str, kind: str,
                 data: bytes, file_name: str = "", top_k: int = 2000) -> tuple[list[dict], list[dict]]:
    """Flatten one pprof payload into (ProfileMeta rows, ProfileSamples rows)."""
    prof: Profile = parse_profile(data)
    _endpoint, sample_type = PROFILE_KINDS[kind]
    try:
        idx = prof.sample_type_index(sample_type)
    except KeyError:
        log.warning("  %s/%s %s: sample type %s missing (have %s)",
                    component, pod, kind, sample_type, prof.sample_types)
        return [], []
    unit = prof.sample_types[idx][1]
    stacks, total = aggregate_stacks(prof, sample_type, top_k=top_k)
    duration = prof.duration_nanos / 1e9 if kind == "cpu" else 0.0
    ts = _iso(prof.time_nanos / 1e9 if prof.time_nanos else None)
    base = {**ctx, "Timestamp": ts, "Component": component, "Pod": pod, "Container": container,
            "ProfileType": kind, "SampleType": sample_type, "Unit": unit, "DurationSec": duration}

    meta = {**base, "TotalValue": total, "StackCount": len(stacks), "File": file_name,
            "ProfiledCores": (total / 1e9 / duration) if kind == "cpu" and duration > 0 else 0.0}
    samples = []
    for frames, value in stacks:
        leaf = frames[0] if frames else OTHER_FRAME
        samples.append({**base, "Value": value, "Stack": list(frames), "Leaf": leaf,
                        "LeafPackage": split_go_func(leaf)[0]})
    return [meta], samples


# ------------------------------------------------------------------- collection

def _list_pods(kubeconfig: str, namespace: str, selector: str = "") -> list[dict]:
    args = ["-n", namespace, "get", "pods", "-o", "json"]
    if selector:
        args += ["-l", selector]
    out = kubectl(kubeconfig, *args).stdout
    return [p for p in json.loads(out).get("items", [])
            if p.get("status", {}).get("phase") == "Running"]


def _fetch(url: str, timeout: int) -> bytes:
    import requests  # pylint: disable=import-outside-toplevel
    with requests.Session() as session:
        session.trust_env = False  # localhost port-forward must bypass proxy env vars
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content


def _collect_pod(kubeconfig: str, namespace: str, pod: str, port: int,
                 cpu_seconds: int, attempts: int = 3) -> dict[str, bytes]:
    """Fetch every profile kind from one pod over a dedicated port-forward."""
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            got: dict[str, bytes] = {}
            with PortForward(kubeconfig, namespace, f"pod/{pod}", port, 0) as pf:
                for kind, (endpoint, _st) in PROFILE_KINDS.items():
                    url = pf.url + endpoint.format(seconds=cpu_seconds)
                    try:
                        got[kind] = _fetch(url, timeout=cpu_seconds + 30)
                    except Exception as e:  # keep the other kinds if one endpoint fails
                        log.warning("  %s %s: FAILED %s", pod, kind, e)
            return got
        except Exception as e:
            last_err = e
            log.warning("  %s: port-forward attempt %d/%d failed: %s", pod, attempt, attempts, e)
            time.sleep(3)
    log.warning("  %s: giving up: %s", pod, last_err)
    return {}


def _parse_top(text: str) -> dict[tuple[str, str], tuple[float, int]]:
    """`kubectl top pod --containers --no-headers` -> {(pod, container): (cores, mem_bytes)}"""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            out[(parts[0], parts[1])] = (parse_cpu(parts[2]), parse_mem(parts[3]))
    return out


def collect_usage(kubeconfig: str, namespace: str, role: str, ctx: dict) -> list[dict]:
    """Snapshot per-container usage (metrics-server) + requests/limits."""
    try:
        top = _parse_top(kubectl(kubeconfig, "-n", namespace, "top", "pod",
                                 "--containers", "--no-headers").stdout)
    except Exception as e:
        log.warning("kubectl top failed for %s/%s: %s", role, namespace, e)
        return []
    rows = []
    now = _iso()
    for pod in _list_pods(kubeconfig, namespace):
        pod_name = pod["metadata"]["name"]
        for c in pod["spec"]["containers"]:
            res = c.get("resources", {})
            req, lim = res.get("requests", {}), res.get("limits", {})
            cores, mem = top.get((pod_name, c["name"]), (0.0, 0))
            rows.append({**ctx, "Timestamp": now,
                         "Component": CONTAINER_COMPONENT.get(c["name"], c["name"]),
                         "Pod": pod_name, "Container": c["name"], "Role": role,
                         "Node": pod["spec"].get("nodeName", ""), "Image": c.get("image", ""),
                         "UsageCores": cores, "UsageMemBytes": mem,
                         "CpuReqCores": parse_cpu(req.get("cpu")), "CpuLimCores": parse_cpu(lim.get("cpu")),
                         "MemReqBytes": parse_mem(req.get("memory")), "MemLimBytes": parse_mem(lim.get("memory"))})
    return rows


# ----------------------------------------------------------------------- export

def _kusto_target() -> tuple[str, str]:
    uri = os.environ.get("ADX_CLUSTER_URI", "").strip() or _config.ADX_CLUSTER_URI
    db = os.environ.get("ADX_DATABASE", "").strip() or _config.ADX_DATABASE
    return uri, db


def export_rows(tables: dict[str, list[dict]]) -> dict[str, int]:
    """Ingest rows into Kusto (queued ingestion). Returns rows queued per table."""
    # The Azure SDK is imported lazily on purpose: the export is non-fatal when it is not installed.
    # pylint: disable=import-outside-toplevel
    from azure.kusto.data.data_format import DataFormat
    from azure.kusto.ingest import IngestionProperties, StreamDescriptor
    from .adx import _kusto_clients

    uri, db = _kusto_target()
    if not uri or not db:
        log.info("Profile export skipped (no ADX cluster/database configured)")
        return {}
    data_client, ingest_client = _kusto_clients(uri)
    ensure_profile_schema(data_client, db)
    queued = {}
    for table, rows in tables.items():
        if not rows:
            continue
        payload = "\n".join(json.dumps(r) for r in rows).encode("utf-8")
        props = IngestionProperties(database=db, table=table, data_format=DataFormat.MULTIJSON,
                                    ingestion_mapping_reference=mapping_name(table))
        ingest_client.ingest_from_stream(StreamDescriptor(io.BytesIO(payload), is_compressed=False),
                                         ingestion_properties=props)
        queued[table] = len(rows)
    log.info("Profile export queued to %s/%s: %s", uri, db, queued)
    return queued


def top_functions(sample_rows: list[dict], component: str, sample_type: str, n: int = 10) -> list[dict]:
    """Local flat/cum summary (pooled across pods) for logs and the results JSON."""
    flat: dict[str, int] = {}
    cum: dict[str, int] = {}
    total = 0
    for r in sample_rows:
        if r["Component"] != component or r["SampleType"] != sample_type:
            continue
        v = r["Value"]
        total += v
        flat[r["Leaf"]] = flat.get(r["Leaf"], 0) + v
        for fn in set(r["Stack"]):
            cum[fn] = cum.get(fn, 0) + v
    if not total:
        return []
    return [{"function": fn, "flat": v, "flat_pct": round(100.0 * v / total, 2),
             "cum_pct": round(100.0 * cum.get(fn, 0) / total, 2)}
            for fn, v in sorted(flat.items(), key=lambda kv: kv[1], reverse=True)[:n]]


def collect_and_export(cp_kubeconfig: str, dp_kubeconfig: str, namespace: str,
                       work_dir: Path, results_dir: Path | None, run_id: str, tier: int,
                       run_label: str = "", underlay: str = "", cpu_seconds: int = 30,
                       max_workers: int = 8) -> dict:
    """Profile every replica, snapshot usage, write raw files and export to Kusto."""
    kubeconfigs = {"cp": cp_kubeconfig, "dp": dp_kubeconfig}
    ctx = {"RunId": run_id, "Env": os.environ.get("PROFILE_ENV", "lab"),
           "Underlay": underlay, "Namespace": namespace, "Tier": tier, "RunLabel": run_label}
    raw_dir = work_dir / "pprof" / namespace / f"tier{tier}"
    raw_dir.mkdir(parents=True, exist_ok=True)

    usage_rows: list[dict] = []
    for role, kc in kubeconfigs.items():
        usage_rows += collect_usage(kc, namespace, role, ctx)

    jobs = []
    for comp in PPROF_COMPONENTS:
        for pod in _list_pods(kubeconfigs[comp["role"]], namespace, comp["selector"]):
            jobs.append((comp, pod["metadata"]["name"]))
    log.info("Profiling %d pods (cpu=%ds, workers=%d)...", len(jobs), cpu_seconds, max_workers)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(
            lambda j: _collect_pod(kubeconfigs[j[0]["role"]], namespace, j[1], j[0]["port"], cpu_seconds),
            jobs))
    log.info("Profile collection took %.0fs", time.time() - t0)

    meta_rows: list[dict] = []
    sample_rows: list[dict] = []
    for (comp, pod), got in zip(jobs, results):
        for kind, data in got.items():
            fname = f"{comp['component']}-{pod}-{kind}.pb.gz"
            (raw_dir / fname).write_bytes(data)
            try:
                m, s = profile_rows(ctx, comp["component"], pod, comp["component"], kind, data, fname)
            except Exception as e:
                log.warning("  %s %s: could not parse profile: %s", pod, kind, e)
                continue
            meta_rows += m
            sample_rows += s

    # second usage snapshot so peak/avg are not a single instant
    for role, kc in kubeconfigs.items():
        usage_rows += collect_usage(kc, namespace, role, ctx)

    tables = {"ProfileSamples": sample_rows, "ProfileMeta": meta_rows, "ComponentUsage": usage_rows}
    try:
        queued = export_rows(tables)
    except Exception as e:
        log.warning("Profile export failed (non-fatal): %s", e)
        queued = {}

    summary = {
        "run_id": run_id, "tier": tier, "namespace": namespace, "raw_dir": str(raw_dir),
        "pods_profiled": len(jobs), "rows": {t: len(r) for t, r in tables.items()}, "queued": queued,
        "cpu_cores_profiled": {
            c["component"]: round(sum(m["ProfiledCores"] for m in meta_rows
                                      if m["Component"] == c["component"] and m["ProfileType"] == "cpu"), 3)
            for c in PPROF_COMPONENTS},
        "top_cpu": {c["component"]: top_functions(sample_rows, c["component"], "cpu", 8)
                    for c in PPROF_COMPONENTS},
        "top_heap": {c["component"]: top_functions(sample_rows, c["component"], "inuse_space", 8)
                     for c in PPROF_COMPONENTS},
    }
    if results_dir is not None:
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / f"profile-summary-{namespace}-tier{tier}.json").write_text(json.dumps(summary, indent=2))
    return summary
