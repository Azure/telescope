import gzip
import http.client
import json
import os
import random
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent_sandbox import generator as g


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def ms(self, mono=None):  # pylint: disable=unused-argument
        return self.now


def claim(name, ns="p0", ready=False, sandbox=""):
    obj = {"metadata": {"name": name, "namespace": ns}, "status": {}}
    if sandbox:
        obj["status"]["sandbox"] = {"name": sandbox}
    if ready:
        obj["status"]["conditions"] = [{"type": "Ready", "status": "True"}]
    return obj


def meta(name, ns="p0", owner=None, launch=None):
    m = {"metadata": {"name": name, "namespace": ns}}
    if owner:
        m["metadata"]["ownerReferences"] = [{"kind": "SandboxClaim", "name": owner}]
    if launch:
        m["metadata"]["labels"] = {g.LAUNCH_LABEL: launch}
    return m


class TestArrivals(unittest.TestCase):
    def test_uniform_is_evenly_spaced(self):
        offsets = g.arrival_offsets("uniform", 10, 2, random.Random(1))
        self.assertEqual(len(offsets), 19)  # 0.1 ... 1.9; 2.0 is the end of the phase
        self.assertAlmostEqual(offsets[0], 0.1)
        self.assertAlmostEqual(offsets[-1], 1.9)

    def test_poisson_count_is_close_to_rate_times_duration(self):
        offsets = g.arrival_offsets("poisson", 300, 60, random.Random(7))
        self.assertTrue(17000 < len(offsets) < 19000)
        self.assertEqual(offsets, sorted(offsets))
        self.assertTrue(all(0 < o < 60 for o in offsets))

    def test_no_arrivals_for_zero_rate_or_duration(self):
        self.assertEqual(g.arrival_offsets("poisson", 0, 60, random.Random(1)), [])
        self.assertEqual(g.arrival_offsets("poisson", 10, 0, random.Random(1)), [])


class TestClaimReadySandbox(unittest.TestCase):
    def test_ready_with_sandbox(self):
        self.assertEqual(g.claim_ready_sandbox(claim("c", ready=True, sandbox="s")), (True, "s"))

    def test_not_ready(self):
        self.assertEqual(g.claim_ready_sandbox(claim("c", sandbox="s")), (False, "s"))
        self.assertEqual(g.claim_ready_sandbox({}), (False, ""))

    def test_capitalized_sandbox_name(self):
        obj = claim("c", ready=True)
        obj["status"]["sandbox"] = {"Name": "s"}
        self.assertEqual(g.claim_ready_sandbox(obj), (True, "s"))


class TestTracker(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.tracker = g.Tracker(self.clock)
        self.readied = []
        self.tracker.on_ready = lambda key, record: self.readied.append(key)
        self.key = ("p0", "c1")
        self.tracker.add(self.key, {"ns": "p0", "pool": "wp", "phase": "rate-10", "seq": 0, "sched": 0.0})

    def record(self):
        return self.tracker.claims[self.key]

    def test_full_lifecycle(self):
        t = self.tracker
        t.created(self.key, True, sent=1.0, ret=5.0, code=201)
        self.assertIn(self.key, t.awaiting)
        self.clock.now = 6.0
        t.claim_event("ADDED", claim("c1"))
        self.clock.now = 7.0
        t.sandbox_event("MODIFIED", meta("s1", owner="c1", launch="warm"))
        self.clock.now = 9.0
        t.claim_event("MODIFIED", claim("c1", ready=True, sandbox="s1"))
        self.clock.now = 10.0
        t.claim_event("MODIFIED", claim("c1", ready=True, sandbox="s1"))  # a later update does not fire again
        r = self.record()
        self.assertEqual((r["seen"], r["adopt"], r["ready"], r["sbx"], r["launch"], r["outcome"]),
                         (6.0, 7.0, 9.0, "s1", "warm", "ready"))
        self.assertEqual(self.readied, [self.key])
        self.assertNotIn(self.key, t.awaiting)
        self.assertEqual(t.pending("rate-10", 1000), 1)  # Ready, not deleted yet
        t.update(self.key, delSent=20.0, delRet=25.0, delCode=200)
        self.clock.now = 30.0
        self.assertEqual(t.pending("rate-10", 1000), 1)  # pod not gone yet
        t.sandbox_event("DELETED", meta("s1", owner="c1", launch="warm"))
        t.pod_event("DELETED", meta("s1"))
        self.assertEqual((r["sbxGone"], r["podGone"]), (30.0, 30.0))
        self.assertEqual(t.pending("rate-10", 1000), 0)
        t.claim_event("DELETED", claim("c1"))  # ignored

    def test_sandbox_mapped_from_claim_status_before_adoption_is_seen(self):
        t = self.tracker
        t.created(self.key, True, sent=1.0, ret=5.0, code=201)
        self.clock.now = 8.0
        t.claim_event("MODIFIED", claim("c1", ready=True, sandbox="s1"))
        self.clock.now = 9.0
        t.sandbox_event("MODIFIED", meta("s1", launch="cold"))  # no owner reference in this update
        self.assertEqual((self.record()["adopt"], self.record()["launch"]), (9.0, "cold"))

    def test_events_for_other_objects_are_ignored(self):
        t = self.tracker
        t.claim_event("ADDED", claim("other"))
        t.sandbox_event("MODIFIED", meta("warm-1", owner="someone-else"))
        t.pod_event("DELETED", meta("warm-1"))
        t.pod_event("MODIFIED", meta("warm-1"))
        self.assertEqual(set(t.claims), {self.key})
        self.assertNotIn("seen", self.record())

    def test_ready_before_create_returns(self):
        t = self.tracker
        self.clock.now = 3.0
        t.claim_event("MODIFIED", claim("c1", ready=True, sandbox="s1"))
        t.created(self.key, True, sent=1.0, ret=5.0, code=201)
        self.assertEqual(self.record()["outcome"], "ready")
        self.assertNotIn(self.key, t.awaiting)

    def test_expire(self):
        t = self.tracker
        t.created(self.key, True, sent=1.0, ret=5.0, code=201)
        self.assertEqual(t.expire(60000, now=59000), [])
        self.assertEqual(t.expire(60000, now=60001), [self.key])
        self.assertEqual(self.record()["outcome"], "timeout")
        self.clock.now = 60002
        t.claim_event("MODIFIED", claim("c1", ready=True, sandbox="s1"))  # too late: stays a timeout
        self.assertEqual(self.record()["outcome"], "timeout")
        self.assertEqual(self.readied, [])

    def test_create_error_is_final(self):
        self.tracker.created(self.key, False, sent=1.0, ret=2.0, code=429, outcome="create_error", err="slow down")
        self.assertNotIn(self.key, self.tracker.awaiting)
        self.assertEqual(self.tracker.pending("rate-10", 1000), 0)


class TestIsPending(unittest.TestCase):
    def test_cases(self):
        cases = [
            ({}, 100.0, True),
            ({"outcome": "dropped"}, 100.0, False),
            ({"outcome": "create_error"}, 100.0, False),
            ({"outcome": "ready"}, 100.0, True),
            ({"outcome": "ready", "delRet": 10.0, "sbx": "s"}, 100.0, True),
            ({"outcome": "ready", "delRet": 10.0, "sbx": "s", "podGone": 20.0}, 100.0, False),
            ({"outcome": "timeout", "delRet": 10.0}, 100.0, False),  # never bound a Sandbox: nothing to wait for
            ({"outcome": "ready", "delRet": 10.0, "sbx": "s"}, 2000.0, False),  # teardown timeout passed
        ]
        for record, now, want in cases:
            self.assertEqual(g.is_pending(record, now, 1000.0), want, record)


class FakeResponse:
    def __init__(self, status, lines=(), body=b""):
        self.status = status
        self.lines = list(lines)
        self.body = body

    def readline(self):
        return self.lines.pop(0) if self.lines else b""

    def read(self):
        return self.body


class FakeConn:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.requests = []
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        if self.error:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


class FakeKube:
    def __init__(self, pages, stream):
        self.pages = list(pages)
        self.stream = stream
        self.paths = []

    def request(self, method, path, body=None, accept=None):  # pylint: disable=unused-argument
        self.paths.append(path)
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return 200, page

    def connect(self, timeout=None):  # pylint: disable=unused-argument
        return FakeConn(self.stream)

    def headers(self, accept):
        return {"Accept": accept}


class TestWatcher(unittest.TestCase):
    pages = [{"metadata": {"resourceVersion": "10", "continue": "next"}, "items": [{"metadata": {"name": "a"}}]},
             {"metadata": {"resourceVersion": "10"}, "items": [{"metadata": {"name": "b"}}]}]
    lines = [b'{"type":"ADDED","object":{"metadata":{"name":"c","resourceVersion":"11"}}}\n',
             b'{"type":"BOOKMARK","object":{"metadata":{"resourceVersion":"12"}}}\n',
             b'{"type":"DELETED","object":{"metadata":{"name":"a","resourceVersion":"13"}}}\n']

    def test_list_pages_and_watch_events(self):
        seen = []
        kube = FakeKube(self.pages, FakeResponse(200, self.lines))
        w = g.Watcher(kube, "/api/v1/namespaces/p0/pods", lambda kind, obj: seen.append((kind, obj["metadata"]["name"])),
                      True, threading.Event())
        self.assertEqual(w.list(), "10")
        self.assertIn("continue=next", kube.paths[1])
        self.assertEqual(w.watch("10"), "13")
        self.assertEqual(seen, [("MODIFIED", "a"), ("MODIFIED", "b"), ("ADDED", "c"), ("DELETED", "a")])
        self.assertEqual((w.stats["events"], w.stats["streamEnds"]), (2, 1))

    def test_watch_error_event_asks_for_a_relist(self):
        w = g.Watcher(FakeKube([], FakeResponse(200, [b'{"type":"ERROR","object":{"code":410}}\n'])), "/p",
                      lambda kind, obj: None, False, threading.Event())
        self.assertIsNone(w.watch("5"))

    def test_failed_watch_and_list(self):
        w = g.Watcher(FakeKube([{"metadata": {}}], FakeResponse(500)), "/p", lambda kind, obj: None, False,
                      threading.Event())
        with self.assertRaises(RuntimeError):
            w.watch("5")

    def test_run_retries_after_errors_until_stopped(self):
        stop = threading.Event()
        pages = [RuntimeError("API unavailable")] + self.pages
        kube = FakeKube(pages, FakeResponse(200, self.lines))

        def handler(kind, obj):  # pylint: disable=unused-argument
            if kind == "ADDED":
                stop.set()

        w = g.Watcher(kube, "/p", handler, True, stop)
        with patch.object(g.time, "sleep"):
            w.run()
        self.assertEqual((w.stats["errors"], w.stats["relists"]), (1, 1))
        self.assertTrue(w.synced.is_set())


class TestKube(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        token = os.path.join(self.dir.name, "token")
        with open(token, "w", encoding="utf-8") as f:
            f.write("t0ken\n")
        self.kube = g.Kube("10.0.0.1", "443", token, os.path.join(self.dir.name, "ca.crt"), 5)

    def tearDown(self):
        self.dir.cleanup()

    def test_retries_once_on_a_closed_reused_connection(self):
        stale = FakeConn(error=http.client.RemoteDisconnected("closed"))
        fresh = FakeConn(FakeResponse(201, body=b'{"kind":"SandboxClaim"}'))
        self.kube.local.conn = stale
        with patch.object(self.kube, "connect", return_value=fresh):
            status, body = self.kube.request("POST", "/x", {"a": 1})
        self.assertEqual((status, body), (201, {"kind": "SandboxClaim"}))
        self.assertTrue(stale.closed)
        self.assertIs(self.kube.local.conn, fresh)
        method, path, data, headers = fresh.requests[0]
        self.assertEqual((method, path, json.loads(data)), ("POST", "/x", {"a": 1}))
        self.assertEqual(headers["Authorization"], "Bearer t0ken")
        self.assertEqual(headers["Content-Type"], g.JSON)

    def test_new_connection_errors_are_raised(self):
        with patch.object(self.kube, "connect", return_value=FakeConn(error=OSError("refused"))):
            with self.assertRaises(OSError):
                self.kube.request("GET", "/x")

    def test_body_that_is_not_json(self):
        with patch.object(self.kube, "connect", return_value=FakeConn(FakeResponse(500, body=b"oops"))):
            self.assertEqual(self.kube.request("GET", "/x"), (500, None))

    def test_in_cluster(self):
        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.2", "KUBERNETES_SERVICE_PORT": "6443"}):
            kube = g.Kube.in_cluster(7)
        self.assertEqual((kube.host, kube.port, kube.timeout), ("10.0.0.2", 6443, 7))
        self.assertTrue(kube.token_file.endswith("/token"))

    def test_connect(self):
        with patch.object(g.ssl, "create_default_context"):
            conn = self.kube.connect(timeout=3)
        self.assertEqual((conn.host, conn.port, conn.timeout), ("10.0.0.1", 443, 3))


class FakeApi:
    """Answers the generator's requests the way the API server and the agent-sandbox controller would."""

    def __init__(self, gen, fail=(), never_ready=False):
        self.gen, self.fail, self.never_ready = gen, set(fail), never_ready

    def request(self, method, path, body=None, accept=None):  # pylint: disable=unused-argument
        t = self.gen.tracker
        if method == "GET":
            return 200, {"spec": {"replicas": 2}, "status": {"readyReplicas": 2}}
        if method == "POST":
            name, ns = body["metadata"]["name"], body["metadata"]["namespace"]
            if name in self.fail:
                return 429, {"message": "too many requests"}
            if not self.never_ready:
                t.sandbox_event("MODIFIED", meta("s-" + name, ns, owner=name, launch="warm"))
                t.claim_event("MODIFIED", claim(name, ns, ready=True, sandbox="s-" + name))
            return 201, body
        ns, name = path.split("/namespaces/")[1].split("/sandboxclaims/")
        t.sandbox_event("DELETED", meta("s-" + name, ns, owner=name))
        t.pod_event("DELETED", meta("s-" + name, ns))
        return 200, {}


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with

    def tearDown(self):
        self.dir.cleanup()

    def generator(self, **plan):
        base = {"runId": "r1", "pools": [{"namespace": "p0", "name": "wp"}, {"namespace": "p1", "name": "wp"}],
                "workers": 4, "readyTimeoutSeconds": 0.3, "teardownTimeoutSeconds": 5, "drainTimeoutSeconds": 10}
        base.update(plan)
        return g.Generator(base, None, self.dir.name)

    def run_phase(self, gen, api):
        gen.kube = api
        gen.start_workers()
        try:
            gen.run_phase(0, {"name": "rate-50", "kind": "uniform", "rate": 50, "durationSeconds": 0.19,
                              "warmupSeconds": 0.05, "dwellSeconds": 0}, random.Random(1))
        finally:
            gen.stop.set()
        return {r["seq"]: r for r in gen.tracker.records()}

    def test_phase_runs_claims_through_their_lifecycle(self):
        gen = self.generator()
        records = self.run_phase(gen, FakeApi(gen, fail={"r1-0-3"}))
        self.assertEqual(len(records), 9)  # arrivals at 0.02 ... 0.18 s
        self.assertEqual((records[3]["outcome"], records[3]["code"], records[3]["err"]),
                         ("create_error", 429, "too many requests"))
        for seq, r in records.items():
            if seq != 3:
                self.assertEqual((r["outcome"], r["launch"], r["code"], r["delCode"]), ("ready", "warm", 201, 200), r)
                self.assertIsNotNone(r["podGone"])
        self.assertEqual([records[i]["ns"] for i in range(4)], ["p0", "p1", "p0", "p1"])
        self.assertEqual(len(gen.phases), 1)
        phase = gen.phases[0]
        self.assertEqual((phase["arrivals"], phase["undrained"], phase["warmupSeconds"]), (9, 0, 0.05))
        self.assertEqual(phase["poolsAtStart"], {"p0": [2, 2], "p1": [2, 2]})

        gen.write("2026-10-28T00:00:00Z")
        with gzip.open(os.path.join(self.dir.name, "claims.jsonl.gz"), "rt", encoding="utf-8") as f:
            self.assertEqual(len(f.readlines()), 9)
        with open(os.path.join(self.dir.name, "run.json"), encoding="utf-8") as f:
            run = json.load(f)
        self.assertEqual((run["runId"], run["phases"][0]["name"]), ("r1", "rate-50"))
        self.assertTrue(os.path.exists(os.path.join(self.dir.name, "DONE")))

    def test_claims_that_never_become_ready_time_out_and_are_deleted(self):
        gen = self.generator()
        records = self.run_phase(gen, FakeApi(gen, never_ready=True))
        self.assertEqual({r["outcome"] for r in records.values()}, {"timeout"})
        self.assertEqual({r["delCode"] for r in records.values()}, {200})
        self.assertEqual(gen.phases[0]["undrained"], 0)

    def test_arrivals_beyond_max_inflight_are_dropped(self):
        gen = self.generator(maxInflight=0)
        records = self.run_phase(gen, FakeApi(gen))
        self.assertEqual({r["outcome"] for r in records.values()}, {"dropped"})

    def test_main_runs_the_plan_and_writes_the_results(self):
        plan = os.path.join(self.dir.name, "plan.json")
        with open(plan, "w", encoding="utf-8") as f:
            json.dump({"runId": "r1", "pools": [], "phases": []}, f)
        with patch.object(g.Kube, "in_cluster"), patch.object(g.Generator, "run") as run:
            self.assertEqual(g.main(["--plan", plan, "--out", self.dir.name, "--linger-seconds", "0"]), 0)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
