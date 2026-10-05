"""Output sinks. Rows are buffered and flushed in batches; export is best effort."""

import io
import json
import logging
import os
import threading
import time

from azure.identity import WorkloadIdentityCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.data_format import DataFormat
from azure.kusto.ingest import IngestionProperties, QueuedIngestClient, StreamDescriptor

from vmagent_loadtest.profile_schema import ensure_profile_schema, mapping_name

from .config import SinkConfig

log = logging.getLogger("underlay_profiler")


class FileSink:
    """JSON-lines files; for local runs and tests."""

    def __init__(self, directory: str):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)

    def send(self, table: str, rows: list[dict]) -> None:
        path = os.path.join(self.dir, f"{table}-{int(time.time() * 1000)}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")


class KustoSink:
    def __init__(self, cfg: SinkConfig):
        k = cfg.kusto
        kcsb = KustoConnectionStringBuilder
        ingest_uri = k.ingest_uri or k.cluster_uri.replace("https://", "https://ingest-")
        if k.auth == "msi":
            kw = {"client_id": k.client_id} if k.client_id else {}
            data_kcsb = kcsb.with_aad_managed_service_identity_authentication(k.cluster_uri, **kw)
            ingest_kcsb = kcsb.with_aad_managed_service_identity_authentication(ingest_uri, **kw)
        elif k.auth == "workload":
            cred = WorkloadIdentityCredential()
            data_kcsb = kcsb.with_azure_token_credential(k.cluster_uri, cred)
            ingest_kcsb = kcsb.with_azure_token_credential(ingest_uri, cred)
        else:
            data_kcsb = kcsb.with_az_cli_authentication(k.cluster_uri)
            ingest_kcsb = kcsb.with_az_cli_authentication(ingest_uri)
        self.database = k.database
        self._ingest = QueuedIngestClient(ingest_kcsb)
        if k.ensure_schema:
            ensure_profile_schema(KustoClient(data_kcsb), k.database)

    def send(self, table: str, rows: list[dict]) -> None:
        payload = "\n".join(json.dumps(r) for r in rows).encode()
        props = IngestionProperties(database=self.database, table=table, data_format=DataFormat.MULTIJSON,
                                    ingestion_mapping_reference=mapping_name(table))
        self._ingest.ingest_from_stream(StreamDescriptor(io.BytesIO(payload), is_compressed=False),
                                        ingestion_properties=props)


class BatchingSink:
    """Buffers rows per table; drops the oldest rows rather than growing without bound."""

    def __init__(self, backend, cfg: SinkConfig, metrics, retries: int = 3, backoff: float = 2.0, sleep=time.sleep):
        self.backend, self.cfg, self.metrics = backend, cfg, metrics
        self.retries, self.backoff, self._sleep = retries, backoff, sleep
        self._buf: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def write(self, table: str, rows: list[dict]) -> None:
        with self._lock:
            buf = self._buf.setdefault(table, [])
            buf.extend(rows)
            over = len(buf) - self.cfg.max_buffer_rows
            if over > 0:
                del buf[:over]
                self.metrics.inc("profiler_rows_dropped_total", {"table": table, "reason": "buffer_full"}, over)
        self.flush(only_full=True)

    def flush(self, only_full: bool = False) -> None:
        with self._lock:
            ready = {t: b for t, b in self._buf.items()
                     if b and (not only_full or len(b) >= self.cfg.max_batch_rows)}
            for t in ready:
                self._buf[t] = []
        for table, rows in ready.items():
            for i in range(0, len(rows), self.cfg.max_batch_rows):
                self._send(table, rows[i:i + self.cfg.max_batch_rows])

    def _send(self, table: str, batch: list[dict]) -> None:
        for attempt in range(1, self.retries + 1):
            try:
                self.backend.send(table, batch)
                self.metrics.inc("profiler_rows_exported_total", {"table": table}, len(batch))
                return
            except Exception as e:
                self.metrics.inc("profiler_export_failures_total", {"table": table})
                log.warning("export of %d %s rows failed (attempt %d/%d): %s", len(batch), table, attempt,
                            self.retries, e)
                if attempt < self.retries:
                    self._sleep(self.backoff * attempt)
        self.metrics.inc("profiler_rows_dropped_total", {"table": table, "reason": "export_failed"}, len(batch))


def make_sink(cfg: SinkConfig, metrics) -> BatchingSink:
    backend = FileSink(cfg.file_dir) if cfg.type == "file" else KustoSink(cfg)
    return BatchingSink(backend, cfg, metrics)
