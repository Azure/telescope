import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import yaml

from tests.underlay_profiler.pprof_builder import build, cpu_profile, heap_profile
from underlay_profiler import __main__ as entrypoint
from underlay_profiler import fetch
from underlay_profiler.config import parse_config
from underlay_profiler.discovery import StaticDiscovery
from underlay_profiler.metrics import Metrics, serve
from underlay_profiler.sink import FileSink, KustoSink, make_sink

PROFILES = {
    "/debug/pprof/profile": cpu_profile(),
    "/debug/pprof/heap": heap_profile(),
    "/debug/pprof/allocs": build([("alloc_objects", "count"), ("alloc_space", "bytes")],
                                 [(["runtime.mallocgc", "main.main"], [1, 500])]),
    "/debug/pprof/goroutine": build([("goroutine", "count")], [(["main.main"], [3])]),
}


class PprofHandler(BaseHTTPRequestHandler):
    seen: list = []
    fail = False

    def do_GET(self):  # pylint: disable=invalid-name
        type(self).seen.append((self.path, self.headers.get("Authorization")))
        body = PROFILES.get(self.path.split("?", maxsplit=1)[0])
        if type(self).fail:
            self.send_error(500)
        elif body is None:
            self.send_error(404)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *_args):
        pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PprofServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), PprofHandler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        PprofHandler.seen, PprofHandler.fail = [], False

    def candidate(self, **target):
        cfg = parse_config({"sink": {"type": "file", "fileDir": "x"},
                            "targets": [{"component": "vmagent", "staticUrls": [self.url], **target}]})
        return StaticDiscovery().candidates(cfg.targets[0])[0]


class FetchTest(PprofServerCase):
    def test_fetches_the_right_endpoint(self):
        data = fetch.Fetcher().fetch(self.candidate(), "cpu", 3)
        self.assertEqual(data, PROFILES["/debug/pprof/profile"])
        self.assertEqual(PprofHandler.seen[0][0], "/debug/pprof/profile?seconds=3")
        fetch.Fetcher().fetch(self.candidate(), "heap", 3)
        self.assertEqual(PprofHandler.seen[1][0], "/debug/pprof/heap")

    def test_bearer_token_is_sent(self):
        with tempfile.NamedTemporaryFile("w", suffix=".token", delete=False, encoding="utf-8") as f:
            f.write("s3cret\n")
        try:
            fetch.Fetcher().fetch(self.candidate(bearerTokenFile=f.name), "heap", 1)
        finally:
            os.unlink(f.name)
        self.assertEqual(PprofHandler.seen[0][1], "Bearer s3cret")

    def test_http_error_raises(self):
        PprofHandler.fail = True
        with self.assertRaises(Exception):
            fetch.Fetcher().fetch(self.candidate(), "heap", 1)

    def test_oversized_profile_is_rejected(self):
        with mock.patch.object(fetch, "MAX_PROFILE_BYTES", 10):
            with self.assertRaises(ValueError):
                fetch.Fetcher().fetch(self.candidate(), "heap", 1)


class EntrypointTest(PprofServerCase):
    def test_once_runs_a_full_cycle_into_the_file_sink(self):
        with tempfile.TemporaryDirectory() as d:
            raw = {"cluster": {"env": "test", "underlay": "u1"},
                   "collector": {"metricsPort": free_port()},
                   "sink": {"type": "file", "fileDir": d},
                   "targets": [{"component": "vmagent", "staticUrls": [self.url],
                                "profiles": {"cpu": {"seconds": 1}, "heap": {}, "allocs": {}, "goroutine": {}}}]}
            path = os.path.join(d, "config.yaml")
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(raw, f)
            with mock.patch.object(sys, "argv", ["underlay_profiler", "--config", path, "--once"]):
                entrypoint.main()
            files = [n for n in os.listdir(d) if n.startswith("ProfileRollup-")]
            self.assertEqual(len(files), 1)
            with open(os.path.join(d, files[0]), encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
        self.assertEqual({r["ProfileType"] for r in rows}, {"cpu", "heap", "allocs", "goroutine"})
        self.assertEqual({(r["Underlay"], r["Env"], r["Component"]) for r in rows}, {("u1", "test", "vmagent")})
        cpu_total = next(r for r in rows if r["ProfileType"] == "cpu" and r["Kind"] == "total")
        self.assertEqual(cpu_total["Flat"], 7_500)


class MetricsServerTest(unittest.TestCase):
    def test_endpoints(self):
        m = Metrics()
        m.inc("profiler_cycles_total")
        port = free_port()
        server = serve(m, port)
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(base + "/metrics", timeout=5) as r:
                self.assertIn("profiler_cycles_total 1", r.read().decode())
            with urllib.request.urlopen(base + "/healthz", timeout=5) as r:
                self.assertEqual(r.read(), b"ok\n")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                with urllib.request.urlopen(base + "/nope", timeout=5):
                    pass
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


class SinkTest(unittest.TestCase):
    def test_file_sink_via_make_sink(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = parse_config({"sink": {"type": "file", "fileDir": os.path.join(d, "out")}}).sink
            sink = make_sink(cfg, Metrics())
            sink.write("ProfileRollup", [{"a": 1}, {"a": 2}])
            sink.flush()
            out = os.path.join(d, "out")
            (name,) = os.listdir(out)
            with open(os.path.join(out, name), encoding="utf-8") as f:
                self.assertEqual([json.loads(line) for line in f], [{"a": 1}, {"a": 2}])
        self.assertIsInstance(FileSink(tempfile.gettempdir()), FileSink)

    def kusto_cfg(self, **kusto):
        return parse_config({"sink": {"type": "kusto", "kusto": {
            "clusterUri": "https://c.region.kusto.windows.net", "database": "db", **kusto}}}).sink

    def build(self, **kusto):
        with mock.patch.multiple("underlay_profiler.sink", KustoClient=mock.DEFAULT, QueuedIngestClient=mock.DEFAULT,
                                 KustoConnectionStringBuilder=mock.DEFAULT, WorkloadIdentityCredential=mock.DEFAULT,
                                 ensure_profile_schema=mock.DEFAULT) as m:
            sink = KustoSink(self.kusto_cfg(**kusto))
            return sink, m

    def test_msi_auth_with_client_id_and_derived_ingest_uri(self):
        _, m = self.build(auth="msi", clientId="abc")
        fn = m["KustoConnectionStringBuilder"].with_aad_managed_service_identity_authentication
        self.assertEqual([c.args[0] for c in fn.call_args_list],
                         ["https://c.region.kusto.windows.net", "https://ingest-c.region.kusto.windows.net"])
        self.assertTrue(all(c.kwargs == {"client_id": "abc"} for c in fn.call_args_list))
        m["ensure_profile_schema"].assert_not_called()

    def test_workload_identity_auth(self):
        _, m = self.build(auth="workload")
        self.assertEqual(m["KustoConnectionStringBuilder"].with_azure_token_credential.call_count, 2)
        m["WorkloadIdentityCredential"].assert_called_once_with()

    def test_az_cli_auth_and_ensure_schema(self):
        _, m = self.build(auth="az_cli", ensureSchema=True)
        self.assertEqual(m["KustoConnectionStringBuilder"].with_az_cli_authentication.call_count, 2)
        m["ensure_profile_schema"].assert_called_once()
        self.assertEqual(m["ensure_profile_schema"].call_args.args[1], "db")

    def test_send_ingests_json_with_the_table_mapping(self):
        sink, m = self.build(auth="msi")
        sink.send("ProfileRollup", [{"a": 1}, {"a": 2}])
        ingest = m["QueuedIngestClient"].return_value.ingest_from_stream
        ingest.assert_called_once()
        props = ingest.call_args.kwargs["ingestion_properties"]
        self.assertEqual((props.database, props.table, props.ingestion_mapping_reference),
                         ("db", "ProfileRollup", "ProfileRollupMapping"))


if __name__ == "__main__":
    unittest.main()
