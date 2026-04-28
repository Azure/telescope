"""Push vmsingle time-series to Azure Data Explorer (ADX).

After each tier completes, query vmsingle's /api/v1/query_range for a curated
list of metrics over the test window and ingest the rows into the ADX table
`VMAgentMetrics` (long format: one row per metric/instance/timestamp).

Env vars (any unset disables export):
  ADX_CLUSTER_URI   e.g. https://vmagent-loadtesting.eastus2.kusto.windows.net
  ADX_INGEST_URI    optional override for the ingest endpoint; defaults to
                    inserting "ingest-" after https:// in ADX_CLUSTER_URI
  ADX_DATABASE      e.g. vmagentloadtest
  ADX_AUTH          one of: az_cli (default), msi
"""

import io
import os
from datetime import datetime, timezone

from .config import log
from .utils import PortForward, retry_request
from . import config as _config


# Metrics queried from vmsingle as PromQL `query_range`.
# Each entry: (metric_name_for_kusto, promql_expression)
# Goal: comprehensive coverage of konn server/agent, vmagent, vmsingle, and
# per-target scrape health for every job. Test-target metrics (kubelet, cadvisor,
# etc.) are NOT exported — too high cardinality. Only meta-scrape data is.
TIMESERIES_METRICS = [
    # ---------------- konnectivity-server (per replica) ----------------
    ("konn_server_memory_bytes",
     'process_resident_memory_bytes{job="konnectivity-server"}'),
    ("konn_server_virtual_memory_bytes",
     'process_virtual_memory_bytes{job="konnectivity-server"}'),
    ("konn_server_cpu_seconds_total",
     'process_cpu_seconds_total{job="konnectivity-server"}'),
    ("konn_server_open_fds",
     'process_open_fds{job="konnectivity-server"}'),
    ("konn_server_threads",
     'go_threads{job="konnectivity-server"}'),
    ("konn_server_goroutines",
     'go_goroutines{job="konnectivity-server"}'),
    ("konn_server_go_memstats_alloc_bytes",
     'go_memstats_alloc_bytes{job="konnectivity-server"}'),
    ("konn_server_go_memstats_heap_inuse_bytes",
     'go_memstats_heap_inuse_bytes{job="konnectivity-server"}'),
    ("konn_server_go_gc_duration_count",
     'go_gc_duration_seconds_count{job="konnectivity-server"}'),

    ("konn_server_grpc_connections",
     'konnectivity_network_proxy_server_grpc_connections'),
    ("konn_server_grpc_connections_by_state",
     'sum(konnectivity_network_proxy_server_grpc_connections) by (instance,state)'),
    ("konn_server_ready_backend_connections",
     'konnectivity_network_proxy_server_ready_backend_connections'),
    ("konn_server_established_connections",
     'konnectivity_network_proxy_server_established_connections'),
    ("konn_server_http_connections",
     'konnectivity_network_proxy_server_http_connections'),
    ("konn_server_pending_backend_dials",
     'konnectivity_network_proxy_server_pending_backend_dials'),
    ("konn_server_dial_count_total",
     'konnectivity_network_proxy_server_dial_duration_seconds_count'),
    ("konn_server_dial_duration_sum",
     'konnectivity_network_proxy_server_dial_duration_seconds_sum'),
    ("konn_server_dial_duration_bucket",
     'sum(konnectivity_network_proxy_server_dial_duration_seconds_bucket) by (instance,le)'),
    ("konn_server_dial_failures_total",
     'konnectivity_network_proxy_server_dial_failure_count'),
    ("konn_server_dial_failures_by_reason",
     'sum(konnectivity_network_proxy_server_dial_failure_count) by (instance,reason)'),
    ("konn_server_endpoint_dial_count",
     'konnectivity_network_proxy_server_endpoint_dial_duration_seconds_count'),
    ("konn_server_endpoint_dial_sum",
     'konnectivity_network_proxy_server_endpoint_dial_duration_seconds_sum'),
    ("konn_server_endpoint_dial_bucket",
     'sum(konnectivity_network_proxy_server_endpoint_dial_duration_seconds_bucket) by (instance,le)'),
    ("konn_server_endpoint_dial_failures_total",
     'konnectivity_network_proxy_server_endpoint_dial_failure_count'),
    ("konn_server_dial_req_total",
     'sum(konnectivity_network_proxy_server_stream_packets_total{packet_type="DIAL_REQ"}) by (instance,segment)'),
    ("konn_server_dial_rsp_total",
     'sum(konnectivity_network_proxy_server_stream_packets_total{packet_type="DIAL_RSP"}) by (instance,segment)'),
    ("konn_server_dial_close_total",
     'sum(konnectivity_network_proxy_server_stream_packets_total{packet_type=~"CLOSE_REQ|CLOSE_RSP"}) by (instance,packet_type,segment)'),
    ("konn_server_data_packets_total",
     'sum(konnectivity_network_proxy_server_stream_packets_total{packet_type="DATA"}) by (instance,segment)'),
    ("konn_server_frontend_write_count",
     'konnectivity_network_proxy_server_frontend_write_duration_seconds_count'),
    ("konn_server_frontend_write_sum",
     'konnectivity_network_proxy_server_frontend_write_duration_seconds_sum'),
    ("konn_server_frontend_write_bucket",
     'sum(konnectivity_network_proxy_server_frontend_write_duration_seconds_bucket) by (instance,le)'),
    ("konn_server_frontend_write_bytes_total",
     'konnectivity_network_proxy_server_frontend_write_bytes_total'),
    ("konn_server_frontend_read_bytes_total",
     'konnectivity_network_proxy_server_frontend_read_bytes_total'),
    ("konn_server_stream_packets_total",
     'sum(konnectivity_network_proxy_server_stream_packets_total) by (instance,packet_type,segment)'),
    ("konn_server_stream_errors_total",
     'sum(konnectivity_network_proxy_server_stream_errors_total) by (instance,packet_type,segment)'),

    # ---------------- konnectivity-agent (one series per agent pod) ------
    ("konn_agent_memory_bytes",
     'process_resident_memory_bytes{job="konnectivity-agent"}'),
    ("konn_agent_virtual_memory_bytes",
     'process_virtual_memory_bytes{job="konnectivity-agent"}'),
    ("konn_agent_cpu_seconds_total",
     'process_cpu_seconds_total{job="konnectivity-agent"}'),
    ("konn_agent_open_fds",
     'process_open_fds{job="konnectivity-agent"}'),
    ("konn_agent_threads",
     'go_threads{job="konnectivity-agent"}'),
    ("konn_agent_goroutines",
     'go_goroutines{job="konnectivity-agent"}'),
    ("konn_agent_go_memstats_alloc_bytes",
     'go_memstats_alloc_bytes{job="konnectivity-agent"}'),
    ("konn_agent_go_memstats_heap_inuse_bytes",
     'go_memstats_heap_inuse_bytes{job="konnectivity-agent"}'),
    ("konn_agent_open_server_connections",
     'konnectivity_network_proxy_agent_open_server_connections'),
    ("konn_agent_open_endpoint_connections",
     'konnectivity_network_proxy_agent_open_endpoint_connections'),
    ("konn_agent_server_connection_failures_total",
     'konnectivity_network_proxy_agent_server_connection_failure_count'),
    ("konn_agent_endpoint_dial_failures_total",
     'konnectivity_network_proxy_agent_endpoint_dial_failure_count'),
    ("konn_agent_stream_packets_total",
     'sum(konnectivity_network_proxy_agent_stream_packets_total) by (pod,packet_type,segment)'),
    ("konn_agent_stream_errors_total",
     'sum(konnectivity_network_proxy_agent_stream_errors_total) by (pod,packet_type,segment)'),

    # ---------------- vmagent (the system-under-test) --------------------
    ("vmagent_memory_bytes",
     'process_resident_memory_bytes{job="vmagent-self"}'),
    ("vmagent_virtual_memory_bytes",
     'process_virtual_memory_bytes{job="vmagent-self"}'),
    ("vmagent_cpu_seconds_total",
     'process_cpu_seconds_total{job="vmagent-self"}'),
    ("vmagent_open_fds",
     'process_open_fds{job="vmagent-self"}'),
    ("vmagent_goroutines",
     'go_goroutines{job="vmagent-self"}'),
    ("vmagent_go_memstats_alloc_bytes",
     'go_memstats_alloc_bytes{job="vmagent-self"}'),
    ("vmagent_go_memstats_heap_inuse_bytes",
     'go_memstats_heap_inuse_bytes{job="vmagent-self"}'),
    ("vmagent_scrapes_total",
     'vm_promscrape_scrapes_total'),
    ("vmagent_scrapes_failed_total",
     'vm_promscrape_scrapes_failed_total'),
    ("vmagent_scrape_duration_count",
     'vm_promscrape_scrape_duration_seconds_count'),
    ("vmagent_scrape_duration_sum",
     'vm_promscrape_scrape_duration_seconds_sum'),
    ("vmagent_samples_scraped_total",
     'vm_promscrape_scraped_samples_sum'),
    ("vmagent_samples_post_relabeling_total",
     'vm_promscrape_samples_post_relabeling_sum'),
    ("vmagent_series_added_total",
     'vm_promscrape_series_added_total'),
    ("vmagent_targets_active",
     'vm_promscrape_targets{status="up"}'),
    ("vmagent_tcpdialer_dials_total",
     'vm_tcpdialer_dials_total'),
    ("vmagent_tcpdialer_dial_duration_count",
     'vm_tcpdialer_dial_duration_seconds_count'),
    ("vmagent_tcpdialer_dial_duration_sum",
     'vm_tcpdialer_dial_duration_seconds_sum'),
    ("vmagent_remote_write_pending_data_bytes",
     'vmagent_remotewrite_pending_data_bytes'),
    ("vmagent_remote_write_packets_dropped_total",
     'vmagent_remotewrite_packets_dropped_total'),
    ("vmagent_remote_write_requests_total",
     'sum(vmagent_remotewrite_requests_total) by (url,status_code)'),
    ("vmagent_remote_write_retries_total",
     'sum(vmagent_remotewrite_retries_count_total) by (url)'),

    # ---------------- vmsingle (storage receiver, for sanity) ------------
    ("vmsingle_rows_inserted_total",
     'vm_rows_inserted_total{type="promremotewrite"}'),
    ("vmsingle_http_requests_total",
     'sum(vm_http_requests_total) by (path)'),
    ("vmsingle_http_errors_total",
     'sum(vm_http_errors_total) by (path)'),
    ("vmsingle_active_timeseries",
     'vm_cache_entries{type="storage/hour_metric_ids"}'),
    ("vmsingle_new_series_created_total",
     'vm_new_timeseries_created_total'),

    # ---------------- Per-target scrape health (ALL jobs/instances) ------
    # These are auto-generated by vmagent for every scraped target. One
    # series per (job, instance) gives us full visibility into which
    # targets were healthy and how long their scrapes took.
    ("scrape_up", 'up'),
    ("scrape_duration_seconds", 'scrape_duration_seconds'),
    ("scrape_samples_scraped", 'scrape_samples_scraped'),
    ("scrape_samples_post_metric_relabeling",
     'scrape_samples_post_metric_relabeling'),
    ("scrape_series_added", 'scrape_series_added'),
    ("scrape_timeout_seconds", 'scrape_timeout_seconds'),
]


def _kusto_clients(cluster_uri: str):
    """Build (data_client, ingest_client) using env-configured auth."""
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
    from azure.kusto.ingest import QueuedIngestClient

    auth = os.environ.get("ADX_AUTH", _config.ADX_AUTH).lower()
    ingest_uri = os.environ.get("ADX_INGEST_URI", "").strip() \
        or _config.ADX_INGEST_URI \
        or cluster_uri.replace("https://", "https://ingest-")
    if auth == "msi":
        data_kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(cluster_uri)
        ingest_kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(ingest_uri)
    else:
        data_kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(cluster_uri)
        ingest_kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(ingest_uri)
    return KustoClient(data_kcsb), QueuedIngestClient(ingest_kcsb)


CREATE_TABLE_CMD = """
.create-merge table VMAgentMetrics (
    RunId: string,
    Tier: int,
    Mode: string,
    Timestamp: datetime,
    Metric: string,
    Value: real,
    Job: string,
    Instance: string,
    Pod: string,
    Labels: dynamic
)
"""

CREATE_MAPPING_CMD = """
.create-or-alter table VMAgentMetrics ingestion json mapping 'VMAgentMetricsMapping'
'['
'{"column":"RunId","Properties":{"Path":"$.RunId"}},'
'{"column":"Tier","Properties":{"Path":"$.Tier"}},'
'{"column":"Mode","Properties":{"Path":"$.Mode"}},'
'{"column":"Timestamp","Properties":{"Path":"$.Timestamp"}},'
'{"column":"Metric","Properties":{"Path":"$.Metric"}},'
'{"column":"Value","Properties":{"Path":"$.Value"}},'
'{"column":"Job","Properties":{"Path":"$.Job"}},'
'{"column":"Instance","Properties":{"Path":"$.Instance"}},'
'{"column":"Pod","Properties":{"Path":"$.Pod"}},'
'{"column":"Labels","Properties":{"Path":"$.Labels"}}'
']'
"""

# Per-tier run summary (one row per tier).
CREATE_RESULTS_TABLE_CMD = """
.create-merge table VMAgentRunSummary (
    RunId: string,
    Tier: int,
    Mode: string,
    Timestamp: datetime,
    Result: string,
    ScrapeTargetsExpected: int,
    ScrapeTargetsUp: int,
    ScrapeTargetsTotal: int,
    ScrapeSuccessRate: real,
    OomEvents: int,
    PodRestarts: int,
    KonnDialMeanSeconds: real,
    KonnDialFailures: int,
    KonnAgentDialFailures: int,
    KonnStreamErrorRate: real,
    RemoteWriteErrors: int,
    RemoteWriteRowsInserted: long,
    PassCriteria: dynamic,
    Measurements: dynamic
)
"""

CREATE_RESULTS_MAPPING_CMD = """
.create-or-alter table VMAgentRunSummary ingestion json mapping 'VMAgentRunSummaryMapping'
'['
'{"column":"RunId","Properties":{"Path":"$.RunId"}},'
'{"column":"Tier","Properties":{"Path":"$.Tier"}},'
'{"column":"Mode","Properties":{"Path":"$.Mode"}},'
'{"column":"Timestamp","Properties":{"Path":"$.Timestamp"}},'
'{"column":"Result","Properties":{"Path":"$.Result"}},'
'{"column":"ScrapeTargetsExpected","Properties":{"Path":"$.ScrapeTargetsExpected"}},'
'{"column":"ScrapeTargetsUp","Properties":{"Path":"$.ScrapeTargetsUp"}},'
'{"column":"ScrapeTargetsTotal","Properties":{"Path":"$.ScrapeTargetsTotal"}},'
'{"column":"ScrapeSuccessRate","Properties":{"Path":"$.ScrapeSuccessRate"}},'
'{"column":"OomEvents","Properties":{"Path":"$.OomEvents"}},'
'{"column":"PodRestarts","Properties":{"Path":"$.PodRestarts"}},'
'{"column":"KonnDialMeanSeconds","Properties":{"Path":"$.KonnDialMeanSeconds"}},'
'{"column":"KonnDialFailures","Properties":{"Path":"$.KonnDialFailures"}},'
'{"column":"KonnAgentDialFailures","Properties":{"Path":"$.KonnAgentDialFailures"}},'
'{"column":"KonnStreamErrorRate","Properties":{"Path":"$.KonnStreamErrorRate"}},'
'{"column":"RemoteWriteErrors","Properties":{"Path":"$.RemoteWriteErrors"}},'
'{"column":"RemoteWriteRowsInserted","Properties":{"Path":"$.RemoteWriteRowsInserted"}},'
'{"column":"PassCriteria","Properties":{"Path":"$.PassCriteria"}},'
'{"column":"Measurements","Properties":{"Path":"$.Measurements"}}'
']'
"""


def ensure_schema(cluster_uri: str, database: str) -> None:
    """Create VMAgentMetrics + VMAgentRunSummary tables and mappings (idempotent)."""
    data_client, _ = _kusto_clients(cluster_uri)
    data_client.execute_mgmt(database, CREATE_TABLE_CMD)
    data_client.execute_mgmt(database, CREATE_MAPPING_CMD)
    data_client.execute_mgmt(database, CREATE_RESULTS_TABLE_CMD)
    data_client.execute_mgmt(database, CREATE_RESULTS_MAPPING_CMD)
    log.info("ADX schema ready: %s/{VMAgentMetrics, VMAgentRunSummary}", database)


def _query_range(vm_url: str, query: str, start: float, end: float, step: int = 15):
    """Run vmsingle /api/v1/query_range. Returns list of (labels, [(ts,val)...])."""
    resp = retry_request(f"{vm_url}/api/v1/query_range", params={
        "query": query,
        "start": int(start),
        "end": int(end),
        "step": f"{step}s",
    })
    data = resp.json().get("data", {}).get("result", [])
    out = []
    for series in data:
        labels = series.get("metric", {})
        values = series.get("values", [])
        out.append((labels, values))
    return out


def export_timeseries(cp_kubeconfig: str, namespace: str,
                      cluster_uri: str, database: str,
                      run_id: str, tier: int, mode: str,
                      start_ts: float, end_ts: float | None = None,
                      step_seconds: int = 15) -> int:
    """Query vmsingle for the test window and ingest rows into ADX.

    Returns number of rows ingested.
    """
    import json as _json
    from azure.kusto.ingest import IngestionProperties, StreamDescriptor
    from azure.kusto.data.data_format import DataFormat

    if end_ts is None:
        end_ts = datetime.now(timezone.utc).timestamp()

    _, ingest_client = _kusto_clients(cluster_uri)

    rows: list[str] = []
    per_metric: dict[str, int] = {}
    with PortForward(cp_kubeconfig, namespace, "deployment/vmsingle", 8428, 18428) as pf:
        retry_request(f"{pf.url}/health", retries=2, backoff=2)
        for metric_name, promql in TIMESERIES_METRICS:
            try:
                series_list = _query_range(pf.url, promql, start_ts, end_ts, step_seconds)
            except Exception as e:
                log.warning("ADX export: query failed for %s: %s", metric_name, e)
                continue
            metric_rows = 0
            for labels, values in series_list:
                job = labels.get("job", "")
                instance = labels.get("instance", "")
                pod = labels.get("pod", "")
                for ts, val in values:
                    try:
                        v = float(val)
                    except (TypeError, ValueError):
                        continue
                    rows.append(_json.dumps({
                        "RunId": run_id,
                        "Tier": tier,
                        "Mode": mode,
                        "Timestamp": datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(),
                        "Metric": metric_name,
                        "Value": v,
                        "Job": job,
                        "Instance": instance,
                        "Pod": pod,
                        "Labels": labels,
                    }))
                    metric_rows += 1
            per_metric[metric_name] = metric_rows

    if not rows:
        log.warning("ADX export: no rows to ingest for tier %d", tier)
        return 0

    payload = "\n".join(rows).encode("utf-8")
    props = IngestionProperties(
        database=database,
        table="VMAgentMetrics",
        data_format=DataFormat.MULTIJSON,
        ingestion_mapping_reference="VMAgentMetricsMapping",
    )
    stream = StreamDescriptor(io.BytesIO(payload), is_compressed=False)
    ingest_client.ingest_from_stream(stream, ingestion_properties=props)
    empty = [m for m, n in per_metric.items() if n == 0]
    log.info("ADX export: queued %d rows across %d metrics for tier %d "
             "(window %.0fs, %d metrics empty)",
             len(rows), len(per_metric) - len(empty), tier,
             end_ts - start_ts, len(empty))
    if empty:
        log.debug("ADX export: empty metrics: %s", ", ".join(empty))
    return len(rows)


def metric_count_summary(rows: list[str]) -> str:
    """Brief summary for logging."""
    import json as _json
    from collections import Counter
    c = Counter()
    for r in rows[:5000]:  # sample
        try:
            c[_json.loads(r)["Metric"]] += 1
        except Exception:
            pass
    top = ", ".join(f"{m}={n}" for m, n in c.most_common(3))
    return f"top: {top}"


def export_if_configured(cp_kubeconfig: str, namespace: str,
                         run_id: str, tier: int, mode: str,
                         start_ts: float) -> None:
    """No-op unless ADX cluster URI + database are configured (env or config)."""
    cluster_uri = os.environ.get("ADX_CLUSTER_URI", "").strip() or _config.ADX_CLUSTER_URI
    database = os.environ.get("ADX_DATABASE", "").strip() or _config.ADX_DATABASE
    if not cluster_uri or not database:
        log.debug("ADX export disabled (no cluster URI / database configured)")
        return
    try:
        export_timeseries(cp_kubeconfig, namespace, cluster_uri, database,
                          run_id, tier, mode, start_ts)
    except Exception as e:
        log.warning("ADX export failed (non-fatal): %s", e)


def export_run_summary(cluster_uri: str, database: str, run_id: str, tier: int,
                       mode: str, result: str, measurements: dict,
                       pass_criteria: dict) -> None:
    """Ingest a single per-tier summary row into VMAgentRunSummary."""
    import json as _json
    from azure.kusto.data.data_format import DataFormat
    from azure.kusto.ingest import IngestionProperties, StreamDescriptor

    _, ingest_client = _kusto_clients(cluster_uri)
    pc = pass_criteria or {}
    m = measurements or {}
    scrape = pc.get("scrape_targets", {})
    stream_err = pc.get("konn_stream_error_rate", {})

    row = {
        "RunId": run_id,
        "Tier": int(tier),
        "Mode": mode,
        "Timestamp": datetime.now(timezone.utc).isoformat(),
        "Result": result,
        "ScrapeTargetsExpected": int(scrape.get("expected", 0) or 0),
        "ScrapeTargetsUp": int(scrape.get("up", 0) or 0),
        "ScrapeTargetsTotal": int(scrape.get("total_discovered", 0) or 0),
        "ScrapeSuccessRate": float(scrape.get("rate", 0.0) or 0.0),
        "OomEvents": int(m.get("oom_events", 0) or 0) + int(m.get("pod_oom_killed", 0) or 0),
        "PodRestarts": int(m.get("pod_restarts_total", 0) or 0),
        "KonnDialMeanSeconds": float(m.get("konn_server_dial_mean_seconds", 0.0) or 0.0),
        "KonnDialFailures": int(m.get("konn_server_dial_failure_count", 0) or 0),
        "KonnAgentDialFailures": int(m.get("konn_agent_endpoint_dial_failures", 0) or 0),
        "KonnStreamErrorRate": float(stream_err.get("actual", 0.0) or 0.0),
        "RemoteWriteErrors": int(m.get("vmsingle_http_errors_total", 0) or 0),
        "RemoteWriteRowsInserted": int(m.get("vmsingle_rows_inserted", 0) or 0),
        "PassCriteria": pc,
        "Measurements": m,
    }
    payload = (_json.dumps(row) + "\n").encode("utf-8")
    props = IngestionProperties(
        database=database,
        table="VMAgentRunSummary",
        data_format=DataFormat.MULTIJSON,
        ingestion_mapping_reference="VMAgentRunSummaryMapping",
    )
    stream = StreamDescriptor(io.BytesIO(payload), is_compressed=False)
    ingest_client.ingest_from_stream(stream, ingestion_properties=props)
    log.info("ADX summary: queued tier %d result=%s", tier, result)


def export_summary_if_configured(run_id: str, tier: int, mode: str,
                                 result: str, measurements: dict,
                                 pass_criteria: dict) -> None:
    """No-op unless ADX cluster URI + database are configured (env or config)."""
    cluster_uri = os.environ.get("ADX_CLUSTER_URI", "").strip() or _config.ADX_CLUSTER_URI
    database = os.environ.get("ADX_DATABASE", "").strip() or _config.ADX_DATABASE
    if not cluster_uri or not database:
        return
    try:
        export_run_summary(cluster_uri, database, run_id, tier, mode,
                           result, measurements, pass_criteria)
    except Exception as e:
        log.warning("ADX summary export failed (non-fatal): %s", e)
