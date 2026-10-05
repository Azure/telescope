"""Collector configuration (YAML, mounted from a ConfigMap and re-read every cycle)."""

from dataclasses import dataclass, field

import yaml

from vmagent_loadtest.pprof import PROFILE_KINDS

DEFAULT_PROFILES = {"cpu": {"everyCycles": 1, "seconds": 10}, "heap": {"everyCycles": 1}}


@dataclass
class ProfileSpec:
    every_cycles: int = 1
    seconds: int = 10  # CPU only


@dataclass
class Target:
    component: str
    selector: str = ""          # pod label selector, e.g. "app=vmagent"
    namespace: str = ""         # empty = all namespaces
    container: str = ""         # container to report image/limits for; empty = first
    port: int = 0
    scheme: str = "http"
    per_cycle: int = 3          # pods profiled per component per cycle
    insecure_skip_verify: bool = False
    bearer_token_file: str = ""
    static_urls: list[str] = field(default_factory=list)  # dev mode: base URLs, no Kubernetes needed
    profiles: dict[str, ProfileSpec] = field(default_factory=dict)


@dataclass
class KustoSinkConfig:
    cluster_uri: str = ""
    ingest_uri: str = ""
    database: str = ""
    auth: str = "msi"           # msi | workload | az_cli
    client_id: str = ""
    ensure_schema: bool = False  # needs table-admin rights; leave off for ingest-only identities


@dataclass
class SinkConfig:
    type: str = "kusto"         # kusto | file
    kusto: KustoSinkConfig = field(default_factory=KustoSinkConfig)
    file_dir: str = ""
    max_batch_rows: int = 20000
    max_buffer_rows: int = 200000


@dataclass
class Config:
    enabled: bool = True        # kill switch: false = idle (collector keeps running, collects nothing)
    cycle_seconds: int = 600
    max_workers: int = 8
    max_concurrent_cpu: int = 2
    min_pod_age_seconds: int = 600
    max_memory_util_pct: float = 85.0
    max_cpu_util_pct: float = 85.0
    top_flat: int = 40
    top_cum: int = 15
    env: str = "prod"
    underlay: str = ""
    run_id: str = "continuous"
    tier: int = 0
    metrics_port: int = 9102
    targets: list[Target] = field(default_factory=list)
    sink: SinkConfig = field(default_factory=SinkConfig)


def _profiles(raw: dict | None) -> dict[str, ProfileSpec]:
    out = {}
    for kind, spec in (raw or DEFAULT_PROFILES).items():
        if kind not in PROFILE_KINDS:
            raise ValueError(f"unknown profile kind {kind!r} (valid: {sorted(PROFILE_KINDS)})")
        spec = spec or {}
        every = int(spec.get("everyCycles", 1))
        if every < 1:
            raise ValueError(f"profiles.{kind}.everyCycles must be >= 1")
        out[kind] = ProfileSpec(every_cycles=every, seconds=int(spec.get("seconds", 10)))
    return out


def _target(raw: dict) -> Target:
    t = Target(
        component=raw["component"], selector=raw.get("selector", ""), namespace=raw.get("namespace", ""),
        container=raw.get("container", ""), port=int(raw.get("port", 0)), scheme=raw.get("scheme", "http"),
        per_cycle=int(raw.get("perCycle", 3)), insecure_skip_verify=bool(raw.get("insecureSkipVerify", False)),
        bearer_token_file=raw.get("bearerTokenFile", ""), static_urls=list(raw.get("staticUrls", [])),
        profiles=_profiles(raw.get("profiles")),
    )
    if not t.static_urls and not (t.selector and t.port):
        raise ValueError(f"target {t.component}: need staticUrls, or selector and port")
    if t.scheme not in ("http", "https"):
        raise ValueError(f"target {t.component}: scheme must be http or https")
    if t.per_cycle < 1:
        raise ValueError(f"target {t.component}: perCycle must be >= 1")
    return t


def parse_config(raw: dict) -> Config:
    c = raw.get("collector", {})
    cl = raw.get("cluster", {})
    cfg = Config(
        enabled=bool(c.get("enabled", True)), cycle_seconds=int(c.get("cycleSeconds", 600)),
        max_workers=int(c.get("maxWorkers", 8)), max_concurrent_cpu=int(c.get("maxConcurrentCpu", 2)),
        min_pod_age_seconds=int(c.get("minPodAgeSeconds", 600)),
        max_memory_util_pct=float(c.get("maxMemoryUtilPct", 85)), max_cpu_util_pct=float(c.get("maxCpuUtilPct", 85)),
        top_flat=int(c.get("rollup", {}).get("topFlat", 40)), top_cum=int(c.get("rollup", {}).get("topCum", 15)),
        env=cl.get("env", "prod"), underlay=cl.get("underlay", ""),
        run_id=cl.get("runId", "continuous"), tier=int(cl.get("tier", 0)),
        metrics_port=int(c.get("metricsPort", 9102)),
        targets=[_target(t) for t in raw.get("targets", [])],
    )
    s = raw.get("sink", {})
    k = s.get("kusto", {})
    cfg.sink = SinkConfig(
        type=s.get("type", "kusto"), file_dir=s.get("fileDir", ""),
        max_batch_rows=int(s.get("maxBatchRows", 20000)), max_buffer_rows=int(s.get("maxBufferRows", 200000)),
        kusto=KustoSinkConfig(cluster_uri=k.get("clusterUri", ""), ingest_uri=k.get("ingestUri", ""),
                              database=k.get("database", ""), auth=k.get("auth", "msi"),
                              client_id=k.get("clientId", ""), ensure_schema=bool(k.get("ensureSchema", False))),
    )
    if cfg.sink.type not in ("kusto", "file"):
        raise ValueError(f"sink.type must be kusto or file, got {cfg.sink.type!r}")
    if cfg.sink.type == "kusto" and not (cfg.sink.kusto.cluster_uri and cfg.sink.kusto.database):
        raise ValueError("sink.kusto.clusterUri and sink.kusto.database are required")
    if cfg.sink.type == "file" and not cfg.sink.file_dir:
        raise ValueError("sink.fileDir is required for sink.type=file")
    if cfg.sink.kusto.auth not in ("msi", "workload", "az_cli"):
        raise ValueError("sink.kusto.auth must be msi, workload or az_cli")
    if cfg.cycle_seconds < 30 or cfg.max_workers < 1 or cfg.max_concurrent_cpu < 1:
        raise ValueError("cycleSeconds must be >= 30; maxWorkers and maxConcurrentCpu must be >= 1")
    return cfg


def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as f:
        return parse_config(yaml.safe_load(f) or {})
