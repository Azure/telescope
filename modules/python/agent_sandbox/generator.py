"""Agent Sandbox claim load generator.

Runs inside the cluster as a pod with a service account and uses only the Python standard library, so it needs no
image of its own. For each phase of a plan it creates SandboxClaims at a target rate (Poisson arrivals), follows every
claim, its Sandbox and its pod through watches, deletes each claim a fixed dwell time after it is Ready, and writes one
record per claim (times in ms since the run started):

    sched    scheduled arrival
    sent     create request sent        ret      create response received   code     create HTTP status
    seen     claim first seen on the watch
    adopt    Sandbox first seen owned by the claim
    ready    claim seen Ready=True with status.sandbox.name set
    sbx      bound Sandbox (and pod) name        launch   Sandbox launch-type label: warm or cold
    delSent  delete request sent        delRet   delete response received  delCode  delete HTTP status
    sbxGone  Sandbox deletion seen      podGone  pod deletion seen
    outcome  ready | timeout | create_error | dropped

Usage: python3 generator.py --plan plan.json --out DIR
"""

import argparse
import gzip
import heapq
import http.client
import json
import os
import queue
import random
import ssl
import sys
import threading
import time
from urllib.parse import urlencode

CLAIMS_API = "/apis/extensions.agents.x-k8s.io/v1beta1"
SANDBOXES_API = "/apis/agents.x-k8s.io/v1beta1"
PODS_API = "/api/v1"
LAUNCH_LABEL = "agents.x-k8s.io/launch-type"
RUN_LABEL = "agent-sandbox-benchmark/run"
PHASE_LABEL = "agent-sandbox-benchmark/phase"
JSON = "application/json"
META = "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1," + JSON
META_LIST = "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1," + JSON
SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"


def log(message):
    print(time.strftime("%H:%M:%S ", time.gmtime()) + message, flush=True)


def arrival_offsets(kind, rate, duration, rng):
    """Arrival times in seconds from the phase start: Poisson at rate per second, or evenly spaced ("uniform")."""
    if rate <= 0 or duration <= 0:
        return []
    out, t = [], 0.0
    while True:
        t += rng.expovariate(rate) if kind == "poisson" else 1.0 / rate
        if t >= duration:
            return out
        out.append(t)


def claim_ready_sandbox(obj):
    """(ready, sandbox name) of a SandboxClaim: Ready=True, and the bound Sandbox from status.sandbox.name."""
    status = obj.get("status") or {}
    sandbox = status.get("sandbox") or {}
    name = sandbox.get("name") or sandbox.get("Name") or ""
    for cond in status.get("conditions") or []:
        if cond.get("type") == "Ready" and cond.get("status") == "True":
            return True, name
    return False, name


def claim_name(run, phase_index, seq):
    """A DNS-1123 name unique within the run."""
    return f"{run}-{phase_index}-{seq}"


def is_pending(record, now, teardown_ms):
    """Whether a claim still needs time: no outcome yet, a delete not yet done, or (for a claim that bound a
    Sandbox) a pod not yet gone within teardown_ms of the delete returning."""
    outcome = record.get("outcome")
    if outcome is None:
        return True
    if outcome not in ("ready", "timeout"):
        return False
    if record.get("delRet") is None:
        return True
    return bool(record.get("sbx")) and record.get("podGone") is None and now - record["delRet"] < teardown_ms


class Clock:
    """Milliseconds since the run started, on the monotonic clock."""

    def __init__(self):
        self.start = time.monotonic()

    def ms(self, mono=None):
        return round(((time.monotonic() if mono is None else mono) - self.start) * 1000.0, 3)


class Tracker:
    """Per-claim records, updated by the request workers and the watch handlers."""

    def __init__(self, clock):
        self.clock = clock
        self.lock = threading.Lock()
        self.claims = {}  # (namespace, claim name) -> record
        self.by_phase = {}  # phase name -> claim keys
        self.awaiting = set()  # created, not Ready and not timed out yet
        self.sandboxes = {}  # (namespace, sandbox name) -> claim key
        self.on_ready = None  # callback(key, record), called once per claim, outside the lock

    def add(self, key, record):
        with self.lock:
            self.claims[key] = record
            self.by_phase.setdefault(record["phase"], []).append(key)

    def update(self, key, **fields):
        with self.lock:
            record = self.claims.get(key)
            if record is not None:
                record.update(fields)

    def created(self, key, ok, **fields):
        with self.lock:
            record = self.claims[key]
            record.update(fields)
            if ok and record.get("outcome") is None:
                self.awaiting.add(key)

    def expire(self, limit_ms, now=None):
        """Marks claims not Ready within limit_ms of their scheduled arrival as timed out; returns their keys."""
        now = self.clock.ms() if now is None else now
        with self.lock:
            expired = [k for k in self.awaiting if now - self.claims[k]["sched"] > limit_ms]
            for key in expired:
                self.awaiting.discard(key)
                self.claims[key]["outcome"] = "timeout"
        return expired

    def claim_event(self, kind, obj, now=None):
        meta = obj.get("metadata") or {}
        key = (meta.get("namespace"), meta.get("name"))
        now = self.clock.ms() if now is None else now
        fire = None
        with self.lock:
            record = self.claims.get(key)
            if record is None or kind == "DELETED":
                return
            record.setdefault("seen", now)
            ready, sandbox = claim_ready_sandbox(obj)
            if sandbox and not record.get("sbx"):
                record["sbx"] = sandbox
                self.sandboxes[(key[0], sandbox)] = key
            if ready and sandbox and record.get("outcome") is None:
                record["ready"] = now
                record["outcome"] = "ready"
                self.awaiting.discard(key)
                fire = record
        if fire is not None and self.on_ready is not None:
            self.on_ready(key, fire)

    def sandbox_event(self, kind, obj, now=None):
        meta = obj.get("metadata") or {}
        namespace, name = meta.get("namespace"), meta.get("name")
        now = self.clock.ms() if now is None else now
        with self.lock:
            key = self.sandboxes.get((namespace, name))
            if key is None:
                for ref in meta.get("ownerReferences") or []:
                    if ref.get("kind") == "SandboxClaim" and (namespace, ref.get("name")) in self.claims:
                        key = (namespace, ref.get("name"))
                        self.sandboxes[(namespace, name)] = key
                        break
            if key is None:
                return
            record = self.claims[key]
            record.setdefault("adopt", now)
            record.setdefault("sbx", name)
            launch = (meta.get("labels") or {}).get(LAUNCH_LABEL)
            if launch:
                record["launch"] = launch
            if kind == "DELETED":
                record.setdefault("sbxGone", now)

    def pod_event(self, kind, obj, now=None):
        if kind != "DELETED":
            return
        meta = obj.get("metadata") or {}
        now = self.clock.ms() if now is None else now
        with self.lock:
            key = self.sandboxes.get((meta.get("namespace"), meta.get("name")))
            if key is not None:
                self.claims[key].setdefault("podGone", now)

    def pending(self, phase, teardown_ms):
        """Number of claims of a phase that still need time (see is_pending)."""
        with self.lock:
            keys = list(self.by_phase.get(phase, ()))
        now = self.clock.ms()
        # Reading records outside the lock is safe enough here: each field is set atomically.
        return sum(1 for k in keys if is_pending(self.claims[k], now, teardown_ms))

    def records(self):
        with self.lock:
            return [dict(r) for r in self.claims.values()]


class Kube:
    """A minimal Kubernetes API client for in-cluster use, with one keep-alive connection per thread."""

    def __init__(self, host, port, token_file, ca_file, timeout):
        self.host, self.port, self.token_file, self.timeout = host, int(port), token_file, timeout
        self.ca_file = ca_file
        self.local = threading.local()
        self.token, self.token_read = "", -1e9

    @classmethod
    def in_cluster(cls, timeout):
        return cls(os.environ["KUBERNETES_SERVICE_HOST"], os.environ.get("KUBERNETES_SERVICE_PORT", "443"),
                   os.path.join(SA_DIR, "token"), os.path.join(SA_DIR, "ca.crt"), timeout)

    def headers(self, accept):
        if time.monotonic() - self.token_read > 60:  # projected service account tokens rotate
            with open(self.token_file, encoding="utf-8") as f:
                self.token, self.token_read = f.read().strip(), time.monotonic()
        return {"Authorization": "Bearer " + self.token, "Accept": accept}

    def connect(self, timeout=None):
        context = ssl.create_default_context(cafile=self.ca_file)
        return http.client.HTTPSConnection(self.host, self.port, context=context,
                                           timeout=self.timeout if timeout is None else timeout)

    def request(self, method, path, body=None, accept=JSON):
        """(status, parsed body or None). Retries once when the server had closed a reused connection."""
        data = None if body is None else json.dumps(body).encode()
        for attempt in (0, 1):
            conn = getattr(self.local, "conn", None)
            reused = conn is not None
            if conn is None:
                conn = self.local.conn = self.connect()
            try:
                headers = self.headers(accept)
                if data is not None:
                    headers["Content-Type"] = JSON
                conn.request(method, path, body=data, headers=headers)
                resp = conn.getresponse()
                payload = resp.read()
            except (http.client.HTTPException, OSError):
                conn.close()
                self.local.conn = None
                if attempt or not reused:
                    raise
                continue
            try:
                return resp.status, json.loads(payload) if payload else None
            except ValueError:
                return resp.status, None
        raise RuntimeError("unreachable")


class Watcher(threading.Thread):
    """Lists, then watches, one collection, calling handler(event type, object) for every object and event."""

    def __init__(self, kube, path, handler, metadata_only, stop, query=None):
        super().__init__(daemon=True, name="watch " + path)
        self.kube, self.path, self.handler, self.metadata_only, self.stop = kube, path, handler, metadata_only, stop
        self.query = dict(query or {})
        self.stats = {"path": path, "events": 0, "relists": 0, "streamEnds": 0, "errors": 0}
        self.synced = threading.Event()

    def list(self):
        """Feeds every current object to the handler; returns the list's resourceVersion."""
        token, rv = "", None
        while True:
            params = dict(self.query, limit="500")
            if token:
                params["continue"] = token
            status, body = self.kube.request("GET", self.path + "?" + urlencode(params),
                                             accept=META_LIST if self.metadata_only else JSON)
            if status != 200:
                raise RuntimeError(f"list {self.path}: HTTP {status}")
            for item in body.get("items") or []:
                self.handler("MODIFIED", item)
            meta = body.get("metadata") or {}
            rv = rv or meta.get("resourceVersion")
            token = meta.get("continue")
            if not token:
                return rv

    def watch(self, rv):
        """Watches from rv until the stream ends; returns the last resourceVersion, or None to relist."""
        params = dict(self.query, watch="1", allowWatchBookmarks="true", resourceVersion=rv, timeoutSeconds="600")
        conn = self.kube.connect(timeout=900)
        try:
            conn.request("GET", self.path + "?" + urlencode(params),
                         headers=self.kube.headers(META if self.metadata_only else JSON))
            resp = conn.getresponse()
            if resp.status != 200:
                raise RuntimeError(f"watch {self.path}: HTTP {resp.status}")
            while not self.stop.is_set():
                line = resp.readline()
                if not line:
                    self.stats["streamEnds"] += 1
                    return rv
                event = json.loads(line)
                kind, obj = event.get("type"), event.get("object") or {}
                if kind == "ERROR":
                    return None  # usually 410 Gone: relist
                rv = (obj.get("metadata") or {}).get("resourceVersion") or rv
                if kind != "BOOKMARK":
                    self.stats["events"] += 1
                    self.handler(kind, obj)
            return rv
        finally:
            conn.close()

    def run(self):
        rv = None
        while not self.stop.is_set():
            try:
                if rv is None:
                    rv = self.list()
                    self.stats["relists"] += 1
                    self.synced.set()
                rv = self.watch(rv)
            except Exception:
                self.stats["errors"] += 1
                rv = None
                time.sleep(1)


class Generator:
    """Drives the phases of a plan and writes the claim records."""

    def __init__(self, plan, kube, out):
        self.plan, self.kube, self.out = plan, kube, out
        self.clock = Clock()
        self.tracker = Tracker(self.clock)
        self.tracker.on_ready = self.ready
        self.stop = threading.Event()
        self.creates = queue.Queue()
        self.deletes = queue.Queue()
        self.timers = []  # heap of (monotonic due time, sequence, claim key)
        self.timer_lock = threading.Lock()
        self.timer_seq = 0
        self.inflight = 0
        self.inflight_lock = threading.Lock()
        self.dwell = {}  # phase name -> seconds between Ready and delete
        self.phases = []
        self.watchers = []

    # ---- requests

    def ready(self, key, record):
        self.after(self.dwell.get(record["phase"], 0.0), key)

    def after(self, seconds, key):
        with self.timer_lock:
            self.timer_seq += 1
            heapq.heappush(self.timers, (time.monotonic() + seconds, self.timer_seq, key))

    def timer_loop(self):
        while not self.stop.is_set():
            now, due = time.monotonic(), []
            with self.timer_lock:
                while self.timers and self.timers[0][0] <= now:
                    due.append(heapq.heappop(self.timers)[2])
            for key in due:
                self.deletes.put(key)
            time.sleep(0.005)

    def create_worker(self):
        while True:
            key, record = self.creates.get()
            namespace, name = key
            body = {"apiVersion": "extensions.agents.x-k8s.io/v1beta1", "kind": "SandboxClaim",
                    "metadata": {"name": name, "namespace": namespace,
                                 "labels": {RUN_LABEL: self.plan["runId"], PHASE_LABEL: record["phase"]}},
                    "spec": {"warmPoolRef": {"name": record["pool"]}}}
            self.tracker.update(key, sent=self.clock.ms())
            try:
                status, resp = self.kube.request("POST", f"{CLAIMS_API}/namespaces/{namespace}/sandboxclaims", body)
                err = "" if status in (200, 201) else str((resp or {}).get("message", ""))[:200]
            except Exception as e:
                status, err = 0, str(e)[:200]
            if status == 409 and "already exists" in err:
                status, err = 201, ""  # a retried create whose first attempt had reached the server
            fields = {"ret": self.clock.ms(), "code": status}
            ok = status in (200, 201)
            if not ok:
                fields.update(outcome="create_error", err=err)
            self.tracker.created(key, ok, **fields)
            with self.inflight_lock:
                self.inflight -= 1

    def delete_worker(self):
        while True:
            key = self.deletes.get()
            self.tracker.update(key, delSent=self.clock.ms())
            try:
                status, _ = self.kube.request("DELETE", f"{CLAIMS_API}/namespaces/{key[0]}/sandboxclaims/{key[1]}")
            except Exception:
                status = 0
            self.tracker.update(key, delRet=self.clock.ms(), delCode=status)

    def timeout_loop(self):
        """Claims not Ready within readyTimeoutSeconds of their scheduled arrival time out and are deleted."""
        limit = float(self.plan.get("readyTimeoutSeconds", 60)) * 1000.0
        while not self.stop.is_set():
            for key in self.tracker.expire(limit):
                self.deletes.put(key)
            time.sleep(0.5)

    def start_workers(self):
        workers = int(self.plan.get("workers", 64))
        targets = [self.create_worker] * workers + [self.delete_worker] * workers + [self.timer_loop, self.timeout_loop]
        for target in targets:
            threading.Thread(target=target, daemon=True).start()

    # ---- pools

    def wait_pools(self, fraction, timeout):
        """Waits until every pool has at least fraction of its replicas Ready; returns the counts last seen."""
        end, counts = time.monotonic() + timeout, {}
        while True:
            ok = True
            for pool in self.plan["pools"]:
                status, body = self.kube.request(
                    "GET", f"{CLAIMS_API}/namespaces/{pool['namespace']}/sandboxwarmpools/{pool['name']}")
                body = body or {}
                want = (body.get("spec") or {}).get("replicas", 0)
                have = (body.get("status") or {}).get("readyReplicas", 0)
                counts[pool["namespace"]] = [have, want]
                ok = ok and status == 200 and have >= fraction * want
            if ok or time.monotonic() > end:
                return counts
            time.sleep(5)

    # ---- phases

    def run_phase(self, index, phase, rng):
        name = phase["name"]
        self.dwell[name] = float(phase.get("dwellSeconds", 0))
        pools = self.wait_pools(float(self.plan.get("poolReadyFraction", 0.95)),
                                float(self.plan.get("poolReadyTimeoutSeconds", 900)))
        duration, rate = float(phase["durationSeconds"]), float(phase["rate"])
        offsets = arrival_offsets(phase.get("kind", "poisson"), rate, duration, rng)
        max_inflight = int(self.plan.get("maxInflight", 2000))
        log(f"phase {name}: {len(offsets)} arrivals at {rate:.1f}/s over {duration:.0f} s (pools ready: {pools})")
        start = time.monotonic()
        for seq, offset in enumerate(offsets):
            due = start + offset
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            pool = self.plan["pools"][seq % len(self.plan["pools"])]
            key = (pool["namespace"], claim_name(self.plan["runId"], index, seq))
            self.tracker.add(key, {"ns": key[0], "pool": pool["name"], "phase": name, "seq": seq,
                                   "sched": self.clock.ms(due)})
            with self.inflight_lock:
                drop = self.inflight >= max_inflight
                if not drop:
                    self.inflight += 1
            if drop:
                self.tracker.update(key, outcome="dropped")
            else:
                self.creates.put((key, {"phase": name, "pool": pool["name"]}))
        teardown_ms = float(self.plan.get("teardownTimeoutSeconds", 120)) * 1000.0
        drain_end = time.monotonic() + float(self.plan.get("drainTimeoutSeconds", 300))
        while self.tracker.pending(name, teardown_ms) and time.monotonic() < drain_end:
            time.sleep(0.2)
        left = self.tracker.pending(name, teardown_ms)
        self.phases.append({"name": name, "kind": phase.get("kind", "poisson"), "rate": rate,
                            "durationSeconds": duration, "warmupSeconds": float(phase.get("warmupSeconds", 0)),
                            "dwellSeconds": self.dwell[name], "t0": self.clock.ms(start),
                            "t1": self.clock.ms(start + duration), "arrivals": len(offsets), "undrained": left,
                            "poolsAtStart": pools})
        log(f"phase {name}: done, {left} claims not drained")

    def run(self):
        self.start_workers()
        tracker = self.tracker
        self.watchers = [Watcher(self.kube, CLAIMS_API + "/sandboxclaims", tracker.claim_event, False, self.stop,
                                 {"labelSelector": RUN_LABEL + "=" + self.plan["runId"]})]
        for pool in self.plan["pools"]:
            ns = pool["namespace"]
            self.watchers.append(Watcher(self.kube, f"{SANDBOXES_API}/namespaces/{ns}/sandboxes",
                                         tracker.sandbox_event, True, self.stop))
            self.watchers.append(Watcher(self.kube, f"{PODS_API}/namespaces/{ns}/pods", tracker.pod_event, True,
                                         self.stop))
        for w in self.watchers:
            w.start()
        for w in self.watchers:
            w.synced.wait(120)
        rng = random.Random(int(self.plan.get("seed", 1)))
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for index, phase in enumerate(self.plan["phases"]):
            self.run_phase(index, phase, rng)
        self.stop.set()
        self.write(started)

    def write(self, started):
        os.makedirs(self.out, exist_ok=True)
        with gzip.open(os.path.join(self.out, "claims.jsonl.gz"), "wt", encoding="utf-8") as f:
            for record in self.tracker.records():
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        meta = {"runId": self.plan["runId"], "startedAt": started, "plan": self.plan, "phases": self.phases,
                "watches": [w.stats for w in self.watchers]}
        with open(os.path.join(self.out, "run.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)
        with open(os.path.join(self.out, "DONE"), "w", encoding="utf-8") as f:
            f.write(started + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--linger-seconds", type=float, default=3600,
                        help="keep running after the run so the results can be copied, until OUT/COLLECTED appears")
    args = parser.parse_args(argv)
    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    Generator(plan, Kube.in_cluster(float(plan.get("requestTimeoutSeconds", 30))), args.out).run()
    log("done")
    end = time.monotonic() + args.linger_seconds
    while time.monotonic() < end and not os.path.exists(os.path.join(args.out, "COLLECTED")):
        time.sleep(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
