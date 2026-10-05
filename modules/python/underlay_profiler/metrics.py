"""Collector self-metrics in Prometheus text format (scraped by adx-mon via annotations)."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HELP = {
    "profiler_cycles_total": "Sampling cycles completed.",
    "profiler_profiles_total": "Profiles fetched, by component, kind and result.",
    "profiler_guard_skips_total": "Pods skipped by guard rails, by component and reason.",
    "profiler_rows_exported_total": "Rows exported to the sink, by table.",
    "profiler_rows_dropped_total": "Rows dropped (buffer full or export failed), by table and reason.",
    "profiler_export_failures_total": "Failed export attempts, by table.",
    "profiler_bytes_fetched_total": "Raw pprof bytes fetched, by component.",
    "profiler_targets": "Discovered candidate pods, by component.",
    "profiler_enabled": "1 if collection is enabled by config, else 0.",
    "profiler_last_cycle_timestamp_seconds": "Unix time the last cycle finished.",
    "profiler_last_cycle_duration_seconds": "Duration of the last cycle.",
}
GAUGES = {"profiler_targets", "profiler_enabled", "profiler_last_cycle_timestamp_seconds",
          "profiler_last_cycle_duration_seconds"}


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._v: dict[tuple[str, tuple], float] = {}

    @staticmethod
    def _key(name: str, labels: dict | None) -> tuple[str, tuple]:
        return name, tuple(sorted((labels or {}).items()))

    def inc(self, name: str, labels: dict | None = None, by: float = 1.0) -> None:
        with self._lock:
            k = self._key(name, labels)
            self._v[k] = self._v.get(k, 0.0) + by

    def set(self, name: str, value: float, labels: dict | None = None) -> None:
        with self._lock:
            self._v[self._key(name, labels)] = value

    def get(self, name: str, labels: dict | None = None) -> float:
        with self._lock:
            return self._v.get(self._key(name, labels), 0.0)

    def render(self) -> str:
        with self._lock:
            items = sorted(self._v.items())
        out, seen = [], set()
        for (name, labels), value in items:
            if name not in seen:
                seen.add(name)
                out.append(f"# HELP {name} {HELP.get(name, name)}")
                out.append(f"# TYPE {name} {'gauge' if name in GAUGES else 'counter'}")
            lab = "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""
            out.append(f"{name}{lab} {value:g}")
        return "\n".join(out) + "\n"


def serve(metrics: Metrics, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        # The method name is fixed by BaseHTTPRequestHandler.
        def do_GET(self):  # pylint: disable=invalid-name
            if self.path == "/healthz":
                body, ctype = b"ok\n", "text/plain"
            elif self.path == "/metrics":
                body, ctype = metrics.render().encode(), "text/plain; version=0.0.4"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
