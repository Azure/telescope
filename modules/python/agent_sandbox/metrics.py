"""Per-rate claim metrics and verdicts for the Agent Sandbox benchmark.

A claim's latency runs from its scheduled arrival to the moment the generator saw it Ready; claims that never became
Ready count as infinitely slow. A rate passes when, after its warmup, at most 0.1% of claims fail, at least 99% of Ready
claims got a pre-warmed Sandbox, teardown keeps up, latency does not drift, the generator kept its schedule and p99
latency is at most 1 s. The p90 verdict applies the same checks with p90 <= 200 ms instead of the p99 limit.
"""

import math

P90_MS = 200.0
P99_MS = 1000.0
MAX_ERROR = 0.001
MIN_WARM = 0.99
TEARDOWN_P99_S = 30.0
DRIFT = 0.10
DRIFT_MIN_MS = 50.0  # drift must also exceed this, so that 50 -> 60 ms is not a failure
LATENESS_P99_MS = 50.0
INF = float("inf")


def pct(sorted_values, p):
    """Nearest-rank percentile of an ascending list; None when empty."""
    if not sorted_values:
        return None
    rank = max(1, int(math.ceil(p / 100.0 * len(sorted_values))))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _median(values):
    return pct(sorted(v for v in values if v is not None), 50)


def _latency(claim):
    if claim.get("outcome") == "ready" and claim.get("ready") is not None:
        return claim["ready"] - claim["sched"]
    return INF


def _between(claims, first, second):
    return [c[second] - c[first] for c in claims if c.get(first) is not None and c.get(second) is not None]


def claim_metrics(claims, t0, t1):
    """Metrics over the claims whose scheduled arrival falls in [t0, t1) (ms since the run started)."""
    sel = [c for c in claims if t0 <= c["sched"] < t1]
    n = len(sel)
    if n == 0:
        return {"arrivals": 0}
    lat, warm_lat, outcomes = [], [], {}
    ready = warm = 0
    for c in sel:
        outcome = c.get("outcome") or "unknown"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        v = _latency(c)
        lat.append(v)
        if v != INF:
            ready += 1
            if c.get("launch") == "warm":
                warm += 1
                warm_lat.append(v)
    lat.sort()
    warm_lat.sort()
    late = sorted(_between(sel, "sched", "sent"))
    seconds = (t1 - t0) / 1000.0
    m = {"arrivals": n, "ready": ready, "outcomes": outcomes, "errorRate": (n - ready) / n,
         "p50": pct(lat, 50), "p90": pct(lat, 90), "p99": pct(lat, 99), "max": lat[-1],
         "warmP90": pct(warm_lat, 90), "warmP99": pct(warm_lat, 99), "warmHit": warm / ready if ready else None,
         "goodputPerS": ready / seconds, "offeredPerS": n / seconds, "latenessP99": pct(late, 99), "sent": len(late),
         "stageMedians": {"create": _median(_between(sel, "sent", "ret")),
                          "adoption": _median(_between(sel, "ret", "adopt")),
                          "status": _median(_between(sel, "adopt", "ready"))}}
    # drift: p90 of the last third of the window against the first third
    third = (t1 - t0) / 3.0
    first, last = (pct(sorted(_latency(c) for c in sel if a <= c["sched"] < b), 90)
                   for a, b in ((t0, t0 + third), (t1 - third, t1)))
    m["driftP90FirstLast"] = [first, last]
    m["driftP90"] = (last / first - 1) if first not in (None, 0, INF) and last not in (None, INF) else None
    teardown = sorted(v / 1000.0 for v in _between(sel, "delRet", "podGone"))
    m["teardownP99S"] = pct(teardown, 99)
    m["teardownSeen"] = len(teardown)
    return m


def verdict(m):
    """(p99 verdict, reasons, p90 verdict) for the metrics of one rate."""
    if m.get("arrivals", 0) == 0:
        return "no-data", ["no arrivals"], "no-data"
    reasons = []
    if m["errorRate"] > MAX_ERROR:
        reasons.append(f"errors {m['errorRate'] * 100:.2f}% > {MAX_ERROR * 100:.1f}%")
    if m.get("warmHit") is not None and m["warmHit"] < MIN_WARM:
        reasons.append(f"warm hit {m['warmHit'] * 100:.1f}% < {MIN_WARM * 100:.0f}%")
    if m.get("teardownP99S") is not None and m["teardownP99S"] > TEARDOWN_P99_S:
        reasons.append(f"teardown p99 {m['teardownP99S']:.0f} s > {TEARDOWN_P99_S:.0f}")
    if m.get("driftP90") is not None and m["driftP90"] > DRIFT:
        first, last = m["driftP90FirstLast"]
        if last - first > DRIFT_MIN_MS:
            reasons.append(f"p90 drift +{m['driftP90'] * 100:.0f}% ({first:.0f} to {last:.0f} ms)")
    if m.get("latenessP99") is not None and m["latenessP99"] > LATENESS_P99_MS:
        reasons.append(f"INVALID: generator lateness p99 {m['latenessP99']:.0f} ms")
    p99 = not reasons and m["p99"] is not None and m["p99"] <= P99_MS
    if not reasons and not p99:
        reasons.append(f"p99 {m['p99']:.0f} ms > {P99_MS:.0f}")
    p90 = not [r for r in reasons if not r.startswith("p99 ")] and m["p90"] is not None and m["p90"] <= P90_MS
    return ("pass" if p99 else "fail"), reasons, ("pass" if p90 else "fail")


def phase_results(run, claims):
    """One result per phase (rate) of a generator run (run.json content), measured after the phase's warmup."""
    out = []
    for phase in run["phases"]:
        t0 = phase["t0"] + phase.get("warmupSeconds", 0) * 1000.0
        m = claim_metrics(claims, t0, phase["t1"])
        p99, reasons, p90 = verdict(m)
        out.append({"phase": phase["name"], "kind": phase.get("kind"), "rate": phase["rate"],
                    "durationSeconds": phase["durationSeconds"], "warmupSeconds": phase.get("warmupSeconds", 0),
                    "dwellSeconds": phase.get("dwellSeconds", 0), "undrained": phase.get("undrained", 0),
                    "verdict": p99, "verdictP90": p90, "reasons": reasons, "metrics": finite(m)})
    return out


def finite(value):
    """Replaces infinities, which JSON cannot carry, with None."""
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite(v) for v in value]
    if isinstance(value, float) and math.isinf(value):
        return None
    return value
