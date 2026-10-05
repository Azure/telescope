# The tests exercise discovery's private candidate builder directly.
# pylint: disable=protected-access
import os
import random
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import yaml

from tests.underlay_profiler.pprof_builder import cpu_profile, heap_profile
from underlay_profiler import discovery as disc
from underlay_profiler.collector import Collector
from underlay_profiler.config import SinkConfig, parse_config
from underlay_profiler.discovery import Candidate, Guard, K8sDiscovery
from underlay_profiler.metrics import Metrics
from underlay_profiler.sink import BatchingSink

NOW = 1_000_000.0


def make_cfg(**collector):
    return parse_config({
        "cluster": {"env": "lab", "underlay": "u1", "tier": 500},
        "collector": {"cycleSeconds": 60, "minPodAgeSeconds": 600, **collector},
        "sink": {"type": "file", "fileDir": "/tmp/unused"},
        "targets": [{"component": "vmagent", "selector": "app=vmagent", "port": 8429, "perCycle": 2,
                     "profiles": {"cpu": {"seconds": 5}, "heap": {}, "allocs": {"everyCycles": 3}}}],
    })


def make_cands(cfg, n, age=3600, mem_limit=0, cpu_limit=0.0):
    t = cfg.targets[0]
    return [Candidate(target=t, namespace=f"ns{i}", pod=f"vmagent-{i}", ip=f"10.0.0.{i}", container="vmagent",
                      image="img:v1", port=8429, scheme="http", created=NOW - age, mem_limit=mem_limit,
                      cpu_limit=cpu_limit) for i in range(n)]


class FakeDiscovery:
    def __init__(self, cands=None, error=None):
        self.cands, self.error = cands or [], error

    def candidates(self, _target):
        if self.error:
            raise self.error
        return self.cands


class FakeFetcher:
    def __init__(self, fail_kinds=(), delay=0.0):
        self.calls, self.fail_kinds, self.delay = [], set(fail_kinds), delay
        self._lock, self.cpu_now, self.cpu_max = threading.Lock(), 0, 0
        self.payload = {"cpu": cpu_profile(), "heap": heap_profile(), "allocs": heap_profile()}

    def fetch(self, cand, kind, _seconds):
        with self._lock:
            self.calls.append((cand.pod, kind))
            if kind == "cpu":
                self.cpu_now += 1
                self.cpu_max = max(self.cpu_max, self.cpu_now)
        try:
            time.sleep(self.delay)
            if kind in self.fail_kinds:
                raise RuntimeError("boom")
            return self.payload[kind]
        finally:
            if kind == "cpu":
                with self._lock:
                    self.cpu_now -= 1


class ListSink:
    def __init__(self):
        self.rows, self.flushes = [], 0

    def write(self, table, rows):
        assert table == "ProfileRollup"
        self.rows.extend(rows)

    def flush(self):
        self.flushes += 1


class FakeMetricsApi:
    def __init__(self, usage=None, error=None):
        self.usage, self.error = usage or {}, error

    def get_namespaced_custom_object(self, _group, _version, _ns, _plural, name):
        if self.error:
            raise self.error
        cpu, mem = self.usage[name]
        return {"containers": [{"name": "vmagent", "usage": {"cpu": cpu, "memory": mem}}]}


def build_collector(cfg, cands, fetcher=None, metrics_api=None, discovery=None):
    metrics, sink = Metrics(), ListSink()
    c = Collector(cfg, discovery or FakeDiscovery(cands), fetcher or FakeFetcher(),
                  Guard(cfg, custom_api=metrics_api or FakeMetricsApi(), now=lambda: NOW),
                  sink, metrics, rng=random.Random(7), now=lambda: NOW)
    return c, sink, metrics


class SelectionTest(unittest.TestCase):
    def test_per_cycle_cap_and_rotation_covers_every_pod(self):
        cfg = make_cfg()  # perCycle = 2
        c, sink, _ = build_collector(cfg, make_cands(cfg, 5))
        per_cycle = []
        for cycle in range(1, 4):
            before = len(sink.rows)
            c.run_cycle(cycle)
            per_cycle.append({r["Pod"] for r in sink.rows[before:]})
        self.assertEqual([len(p) for p in per_cycle], [2, 2, 2])
        self.assertFalse(per_cycle[0] & per_cycle[1])  # least-recently-profiled first: no repeats yet
        self.assertEqual(set().union(*per_cycle), {f"vmagent-{i}" for i in range(5)})

    def test_everycycles_schedule(self):
        cfg = make_cfg()
        f = FakeFetcher()
        c, _, _ = build_collector(cfg, make_cands(cfg, 1), f)
        c.run_cycle(0)
        self.assertEqual({k for _, k in f.calls}, {"cpu", "heap", "allocs"})
        f.calls.clear()
        c.run_cycle(1)
        self.assertEqual({k for _, k in f.calls}, {"cpu", "heap"})

    def test_rows_carry_context(self):
        cfg = make_cfg()
        c, sink, _ = build_collector(cfg, make_cands(cfg, 1))
        c.run_cycle(1)
        r = sink.rows[0]
        self.assertEqual((r["Env"], r["Underlay"], r["Tier"], r["Namespace"], r["Image"], r["Container"]),
                         ("lab", "u1", 500, "ns0", "img:v1", "vmagent"))
        self.assertEqual(sink.flushes, 1)


class GuardTest(unittest.TestCase):
    def test_young_pods_skipped(self):
        cfg = make_cfg()
        f = FakeFetcher()
        cands = make_cands(cfg, 3, age=60) + make_cands(cfg, 1, age=3600)[:0]
        c, _, m = build_collector(cfg, cands, f)
        c.run_cycle(1)
        self.assertEqual(f.calls, [])
        self.assertEqual(m.get("profiler_guard_skips_total", {"component": "vmagent", "reason": "young"}), 3)

    def test_memory_pressure_skips_pod_and_picks_next(self):
        cfg = make_cfg()
        cands = make_cands(cfg, 3, mem_limit=1000 * 1024 * 1024)
        api = FakeMetricsApi({"vmagent-0": ("100m", "900Mi"), "vmagent-1": ("100m", "900Mi"),
                              "vmagent-2": ("100m", "100Mi")})
        f = FakeFetcher()
        c, _, m = build_collector(cfg, cands, f, api)
        c.run_cycle(1)
        self.assertEqual({p for p, _ in f.calls}, {"vmagent-2"})
        self.assertEqual(m.get("profiler_guard_skips_total", {"component": "vmagent", "reason": "memory"}), 2)

    def test_busy_cpu_skips_only_cpu_profile(self):
        cfg = make_cfg()
        cands = make_cands(cfg, 1, cpu_limit=1.0)
        f = FakeFetcher()
        c, _, m = build_collector(cfg, cands, f, FakeMetricsApi({"vmagent-0": ("900m", "10Mi")}))
        c.run_cycle(1)
        self.assertEqual({k for _, k in f.calls}, {"heap"})
        self.assertEqual(m.get("profiler_guard_skips_total", {"component": "vmagent", "reason": "cpu_busy"}), 1)

    def test_metrics_api_unavailable_fails_open(self):
        cfg = make_cfg()
        cands = make_cands(cfg, 1, mem_limit=1 << 30)
        f = FakeFetcher()
        c, _, m = build_collector(cfg, cands, f, FakeMetricsApi(error=RuntimeError("404")))
        c.run_cycle(1)
        self.assertEqual({k for _, k in f.calls}, {"cpu", "heap"})
        self.assertEqual(m.get("profiler_guard_skips_total", {"component": "vmagent", "reason": "metrics_unavailable"}), 1)


class ResilienceTest(unittest.TestCase):
    def test_fetch_error_does_not_stop_other_kinds(self):
        cfg = make_cfg()
        c, sink, m = build_collector(cfg, make_cands(cfg, 1), FakeFetcher(fail_kinds={"cpu"}))
        c.run_cycle(1)
        self.assertEqual({r["ProfileType"] for r in sink.rows}, {"heap"})
        self.assertEqual(m.get("profiler_profiles_total", {"component": "vmagent", "kind": "cpu", "result": "error"}), 1)
        self.assertEqual(m.get("profiler_profiles_total", {"component": "vmagent", "kind": "heap", "result": "ok"}), 1)

    def test_discovery_error_is_non_fatal(self):
        cfg = make_cfg()
        c, _, m = build_collector(cfg, [], discovery=FakeDiscovery(error=RuntimeError("api down")))
        summary = c.run_cycle(1)
        self.assertEqual(summary["pods"], 0)
        self.assertEqual(m.get("profiler_cycles_total"), 1)

    def test_cpu_profiles_respect_concurrency_cap(self):
        cfg = make_cfg(maxConcurrentCpu=1, maxWorkers=4)
        cfg.targets[0].per_cycle = 4
        f = FakeFetcher(delay=0.05)
        c, _, _ = build_collector(cfg, make_cands(cfg, 4), f)
        c.run_cycle(1)
        self.assertEqual(f.cpu_max, 1)
        self.assertEqual(sum(1 for _, k in f.calls if k == "cpu"), 4)

    def test_disabled_collector_collects_nothing(self):
        cfg = make_cfg(enabled=False)
        self.assertFalse(cfg.enabled)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.yaml")
            raw = {"collector": {"enabled": False}, "sink": {"type": "file", "fileDir": d},
                   "targets": [{"component": "vmagent", "selector": "app=vmagent", "port": 8429}]}
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(raw, f)
            fetcher = FakeFetcher()
            c, _, m = build_collector(cfg, make_cands(cfg, 2), fetcher)
            stop = threading.Event()
            threading.Timer(0.3, stop.set).start()
            c.run_forever(path, stop)
            self.assertEqual(fetcher.calls, [])
            self.assertEqual(m.get("profiler_enabled"), 0.0)


class SinkTest(unittest.TestCase):
    class Backend:
        def __init__(self, fail_times=0):
            self.sent, self.fail_times = [], fail_times

        def send(self, table, rows):
            if self.fail_times > 0:
                self.fail_times -= 1
                raise RuntimeError("ingest down")
            self.sent.append((table, len(rows)))

    def sink(self, backend, **kw):
        cfg = SinkConfig(type="file", file_dir="x", max_batch_rows=kw.get("batch", 10), max_buffer_rows=kw.get("buf", 100))
        return BatchingSink(backend, cfg, m := Metrics(), retries=3, backoff=0, sleep=lambda s: None), m

    def test_flush_splits_into_batches(self):
        b = self.Backend()
        s, m = self.sink(b)
        s.write("T", [{"a": i} for i in range(25)])  # >= batch size: flushes on write
        s.write("T", [{"a": 1}])
        s.flush()
        self.assertEqual(b.sent, [("T", 10), ("T", 10), ("T", 5), ("T", 1)])
        self.assertEqual(m.get("profiler_rows_exported_total", {"table": "T"}), 26)

    def test_retry_then_success(self):
        b = self.Backend(fail_times=2)
        s, m = self.sink(b)
        s.write("T", [{"a": 1}])
        s.flush()
        self.assertEqual(b.sent, [("T", 1)])
        self.assertEqual(m.get("profiler_export_failures_total", {"table": "T"}), 2)

    def test_gives_up_and_counts_drops(self):
        b = self.Backend(fail_times=99)
        s, m = self.sink(b)
        s.write("T", [{"a": 1}] * 3)
        s.flush()
        self.assertEqual(b.sent, [])
        self.assertEqual(m.get("profiler_rows_dropped_total", {"table": "T", "reason": "export_failed"}), 3)

    def test_buffer_cap_drops_oldest(self):
        b = self.Backend()
        s, m = self.sink(b, batch=1000, buf=5)
        s.write("T", [{"a": i} for i in range(8)])
        self.assertEqual(m.get("profiler_rows_dropped_total", {"table": "T", "reason": "buffer_full"}), 3)
        s.flush()
        self.assertEqual(b.sent, [("T", 5)])


class ConfigTest(unittest.TestCase):
    def test_validation(self):
        base = {"sink": {"type": "file", "fileDir": "x"}, "targets": [{"component": "c", "selector": "a=b", "port": 1}]}
        parse_config(base)
        bad = [
            {**base, "targets": [{"component": "c"}]},
            {**base, "targets": [{"component": "c", "selector": "a=b", "port": 1, "profiles": {"bogus": {}}}]},
            {**base, "targets": [{"component": "c", "selector": "a=b", "port": 1, "scheme": "ftp"}]},
            {**base, "sink": {"type": "kusto"}},
            {**base, "collector": {"cycleSeconds": 5}},
            {**base, "sink": {"type": "kusto", "kusto": {"clusterUri": "u", "database": "d", "auth": "password"}}},
        ]
        for raw in bad:
            with self.assertRaises(ValueError, msg=str(raw)[:80]):
                parse_config(raw)

    def test_defaults_and_static_targets(self):
        cfg = parse_config({"sink": {"type": "file", "fileDir": "x"},
                            "targets": [{"component": "c", "staticUrls": ["http://127.0.0.1:8429"]}]})
        self.assertEqual(set(cfg.targets[0].profiles), {"cpu", "heap"})
        self.assertEqual((cfg.cycle_seconds, cfg.max_concurrent_cpu, cfg.enabled), (600, 2, True))


def pod(name, ns="ns", ip="10.0.0.1", ready=True, annotations=None, containers=None, age=3600):
    containers = containers or [NS(name="vmagent", image="img:v1",
                                    resources=NS(limits={"memory": "1Gi", "cpu": "500m"}))]
    return NS(metadata=NS(name=name, namespace=ns, annotations=annotations,
                          creation_timestamp=datetime.fromtimestamp(NOW - age, tz=timezone.utc)),
              status=NS(pod_ip=ip, conditions=[NS(type="Ready", status="True" if ready else "False")]),
              spec=NS(containers=containers))


class DiscoveryTest(unittest.TestCase):
    TARGET = make_cfg().targets[0]

    def test_candidate_filtering_and_limits(self):
        t = self.TARGET
        c = disc._to_candidate(t, pod("p"))
        self.assertEqual((c.image, c.mem_limit, c.cpu_limit, c.base_url), ("img:v1", 1 << 30, 0.5, "http://10.0.0.1:8429"))
        self.assertIsNone(disc._to_candidate(t, pod("p", ready=False)))
        self.assertIsNone(disc._to_candidate(t, pod("p", ip="")))
        self.assertIsNone(disc._to_candidate(t, pod("p", annotations={disc.OPT_OUT_ANNOTATION: "true"})))

    def test_container_selection_and_ipv6(self):
        t = self.TARGET
        t2 = type(t)(**{**t.__dict__, "container": "sidecar"})
        cs = [NS(name="vmagent", image="a", resources=None), NS(name="sidecar", image="b", resources=None)]
        c = disc._to_candidate(t2, pod("p", ip="fd00::1", containers=cs))
        self.assertEqual((c.container, c.image, c.base_url), ("sidecar", "b", "http://[fd00::1]:8429"))

    def test_pagination(self):
        pages = [NS(items=[pod("a"), pod("b")], metadata=NS(_continue="tok")), NS(items=[pod("c")], metadata=NS(_continue=None))]
        calls = []

        class Api:
            def list_pod_for_all_namespaces(self, **kw):
                calls.append(kw.get("_continue"))
                return pages[len(calls) - 1]

        out = K8sDiscovery(core_api=Api()).candidates(self.TARGET)
        self.assertEqual([c.pod for c in out], ["a", "b", "c"])
        self.assertEqual(calls, [None, "tok"])


class MetricsTest(unittest.TestCase):
    def test_render(self):
        m = Metrics()
        m.inc("profiler_cycles_total")
        m.inc("profiler_profiles_total", {"component": "vmagent", "kind": "cpu", "result": "ok"}, 2)
        m.set("profiler_enabled", 1)
        text = m.render()
        self.assertIn("# TYPE profiler_cycles_total counter", text)
        self.assertIn('profiler_profiles_total{component="vmagent",kind="cpu",result="ok"} 2', text)
        self.assertIn("# TYPE profiler_enabled gauge", text)


if __name__ == "__main__":
    unittest.main()
