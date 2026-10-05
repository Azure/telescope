"""The sampling loop: discover -> select -> guard -> fetch -> roll up -> sink."""

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from vmagent_loadtest.rollup import rollup_rows

from .config import Config, Target, load_config
from .discovery import Candidate, Guard, Verdict

log = logging.getLogger("underlay_profiler")

TABLE = "ProfileRollup"


class Collector:
    def __init__(self, cfg: Config, discovery, fetcher, guard: Guard, sink, metrics, rng=None, now=time.time):
        self.cfg, self.discovery, self.fetcher = cfg, discovery, fetcher
        self.guard, self.sink, self.metrics = guard, sink, metrics
        self._rng = rng or random.Random()
        self._now = now
        self._last: dict[tuple[str, str, str], float] = {}  # (component, ns, pod) -> last profiled

    def _select(self, target: Target, cands: list[Candidate]) -> list[tuple[Candidate, Verdict]]:
        comp = target.component
        live = {(comp, *c.key) for c in cands}
        for k in [k for k in self._last if k[0] == comp and k not in live]:
            del self._last[k]
        self.metrics.set("profiler_targets", len(cands), {"component": comp})

        # Least recently profiled first, so every pod is eventually covered; random tiebreak.
        ordered = sorted(cands, key=lambda c: (self._last.get((comp, *c.key), 0.0), self._rng.random()))
        chosen: list[tuple[Candidate, Verdict]] = []
        checked = 0
        for cand in ordered:
            if len(chosen) >= target.per_cycle or checked >= target.per_cycle * 3:
                break
            if self.guard.young(cand):
                self.metrics.inc("profiler_guard_skips_total", {"component": comp, "reason": "young"})
                continue
            checked += 1  # only pods that cost a metrics-API call count against the budget
            verdict = self.guard.evaluate(cand)
            if verdict.metrics_unavailable:
                self.metrics.inc("profiler_guard_skips_total", {"component": comp, "reason": "metrics_unavailable"})
            if verdict.skip_all:
                self.metrics.inc("profiler_guard_skips_total", {"component": comp, "reason": verdict.skip_all})
                continue
            self._last[(comp, *cand.key)] = self._now()
            chosen.append((cand, verdict))
        return chosen

    def _profile_pod(self, cand: Candidate, verdict: Verdict, due: dict, cpu_slots) -> list[dict]:
        cfg = self.cfg
        ctx = {"RunId": cfg.run_id, "Env": cfg.env, "Underlay": cfg.underlay, "Namespace": cand.namespace,
               "Tier": cfg.tier, "RunLabel": ""}
        comp = cand.target.component
        rows: list[dict] = []
        for kind, spec in due.items():
            labels = {"component": comp, "kind": kind}
            if kind == "cpu" and verdict.skip_cpu:
                self.metrics.inc("profiler_guard_skips_total", {"component": comp, "reason": verdict.skip_cpu})
                continue
            try:
                if kind == "cpu":
                    with cpu_slots:
                        data = self.fetcher.fetch(cand, kind, spec.seconds)
                else:
                    data = self.fetcher.fetch(cand, kind, spec.seconds)
                self.metrics.inc("profiler_bytes_fetched_total", {"component": comp}, len(data))
                got = rollup_rows(ctx, comp, cand.pod, cand.container, cand.image, kind, data,
                                  cfg.top_flat, cfg.top_cum)
                self.metrics.inc("profiler_profiles_total", {**labels, "result": "ok" if got else "empty"})
                rows.extend(got)
            except Exception as e:
                self.metrics.inc("profiler_profiles_total", {**labels, "result": "error"})
                log.warning("%s %s/%s %s: %s", comp, cand.namespace, cand.pod, kind, e)
        return rows

    def run_cycle(self, cycle: int) -> dict:
        cfg = self.cfg
        self.guard.cfg = cfg
        started = self._now()
        jobs = []
        for target in cfg.targets:
            due = {k: s for k, s in target.profiles.items() if cycle % s.every_cycles == 0}
            if not due:
                continue
            try:
                cands = self.discovery.candidates(target)
            except Exception as e:
                log.error("discovery failed for %s: %s", target.component, e)
                self.metrics.inc("profiler_profiles_total", {"component": target.component, "kind": "all",
                                                             "result": "discovery_error"})
                continue
            jobs += [(c, v, due) for c, v in self._select(target, cands)]

        cpu_slots = threading.BoundedSemaphore(cfg.max_concurrent_cpu)
        rows: list[dict] = []
        with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
            for got in pool.map(lambda j: self._profile_pod(j[0], j[1], j[2], cpu_slots), jobs):
                rows.extend(got)
        if rows:
            self.sink.write(TABLE, rows)
        self.sink.flush()

        elapsed = self._now() - started
        self.metrics.inc("profiler_cycles_total")
        self.metrics.set("profiler_last_cycle_timestamp_seconds", self._now())
        self.metrics.set("profiler_last_cycle_duration_seconds", elapsed)
        summary = {"cycle": cycle, "pods": len(jobs), "rows": len(rows), "seconds": round(elapsed, 1)}
        log.info("cycle %s", summary)
        return summary

    def run_forever(self, config_path: str, stop: threading.Event) -> None:
        cycle = 0
        while not stop.is_set():
            started = time.time()
            try:
                self.cfg = load_config(config_path)
            except Exception as e:  # keep running on the last good config
                log.error("config reload failed, keeping previous config: %s", e)
            self.metrics.set("profiler_enabled", 1.0 if self.cfg.enabled else 0.0)
            if self.cfg.enabled:
                try:
                    self.run_cycle(cycle)
                except Exception:
                    log.exception("cycle %d failed", cycle)
                cycle += 1
            stop.wait(max(1.0, self.cfg.cycle_seconds - (time.time() - started)))
        self.sink.flush()
