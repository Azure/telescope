import unittest

from agent_sandbox import metrics as m


def ready_claim(sched, latency, launch="warm", **extra):
    c = {"sched": sched, "sent": sched + 1, "ret": sched + 5, "adopt": sched + 6, "ready": sched + latency,
         "outcome": "ready", "launch": launch, "delRet": sched + latency + 100, "podGone": sched + latency + 600}
    c.update(extra)
    return c


class TestPct(unittest.TestCase):
    def test_nearest_rank(self):
        values = list(range(1, 101))
        self.assertEqual(m.pct(values, 50), 50)
        self.assertEqual(m.pct(values, 99), 99)
        self.assertEqual(m.pct(values, 100), 100)
        self.assertEqual(m.pct([7], 1), 7)
        self.assertIsNone(m.pct([], 50))


class TestClaimMetrics(unittest.TestCase):
    def test_latency_errors_and_warm_hit(self):
        claims = [ready_claim(i * 10.0, 20.0 + i) for i in range(98)]
        claims.append({"sched": 980.0, "sent": 981.0, "outcome": "timeout"})
        claims.append(ready_claim(990.0, 50.0, launch="cold"))
        claims.append(ready_claim(5000.0, 1.0))  # outside the window
        r = m.claim_metrics(claims, 0.0, 1000.0)
        self.assertEqual((r["arrivals"], r["ready"]), (100, 99))
        self.assertAlmostEqual(r["errorRate"], 0.01)
        self.assertEqual(r["outcomes"], {"ready": 99, "timeout": 1})
        self.assertEqual((r["p50"], r["p99"], r["max"]), (68.0, 117.0, m.INF))
        self.assertAlmostEqual(r["warmHit"], 98 / 99)
        self.assertAlmostEqual(r["offeredPerS"], 100.0)
        self.assertEqual(r["latenessP99"], 1.0)
        self.assertEqual(r["stageMedians"], {"create": 4.0, "adoption": 1.0, "status": 62.0})
        self.assertEqual(r["teardownP99S"], 0.5)

    def test_empty_window(self):
        self.assertEqual(m.claim_metrics([ready_claim(10.0, 5.0)], 100.0, 200.0), {"arrivals": 0})

    def test_drift(self):
        claims = [ready_claim(t, 50.0) for t in range(0, 300, 3)] + [ready_claim(t, 150.0) for t in range(600, 900, 3)]
        claims += [ready_claim(t, 100.0) for t in range(300, 600, 3)]
        r = m.claim_metrics(claims, 0.0, 900.0)
        self.assertEqual(r["driftP90FirstLast"], [50.0, 150.0])
        self.assertAlmostEqual(r["driftP90"], 2.0)


class TestVerdict(unittest.TestCase):
    @staticmethod
    def base(**kw):
        r = {"arrivals": 1000, "errorRate": 0.0, "warmHit": 1.0, "teardownP99S": 0.2, "driftP90": 0.0,
             "driftP90FirstLast": [40.0, 40.0], "latenessP99": 2.0, "p90": 40.0, "p99": 80.0}
        r.update(kw)
        return r

    def test_pass(self):
        self.assertEqual(m.verdict(self.base()), ("pass", [], "pass"))

    def test_slow_p99_fails_the_p99_verdict_only(self):
        self.assertEqual(m.verdict(self.base(p99=1500.0, p90=150.0)), ("fail", ["p99 1500 ms > 1000"], "pass"))

    def test_slow_p90_fails_the_p90_verdict_only(self):
        self.assertEqual(m.verdict(self.base(p90=300.0)), ("pass", [], "fail"))

    def test_each_reason(self):
        cases = [
            ({"errorRate": 0.01}, "errors 1.00% > 0.1%"),
            ({"warmHit": 0.9}, "warm hit 90.0% < 99%"),
            ({"teardownP99S": 60.0}, "teardown p99 60 s > 30"),
            ({"driftP90": 1.0, "driftP90FirstLast": [100.0, 200.0]}, "p90 drift +100% (100 to 200 ms)"),
            ({"latenessP99": 80.0}, "INVALID: generator lateness p99 80 ms"),
        ]
        for kw, reason in cases:
            self.assertEqual(m.verdict(self.base(**kw)), ("fail", [reason], "fail"), kw)

    def test_small_drift_is_not_a_failure(self):
        self.assertEqual(m.verdict(self.base(driftP90=0.2, driftP90FirstLast=[50.0, 60.0]))[0], "pass")

    def test_no_data(self):
        self.assertEqual(m.verdict({"arrivals": 0}), ("no-data", ["no arrivals"], "no-data"))


class TestPhaseResults(unittest.TestCase):
    def test_warmup_is_excluded_and_infinities_become_null(self):
        run = {"phases": [{"name": "rate-10", "kind": "poisson", "rate": 10, "durationSeconds": 2,
                           "warmupSeconds": 1, "dwellSeconds": 0, "t0": 0.0, "t1": 2000.0}]}
        claims = [{"sched": 100.0, "outcome": "timeout"}, ready_claim(1500.0, 30.0),
                  {"sched": 1600.0, "outcome": "timeout"}]
        results = m.phase_results(run, claims)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["metrics"]["arrivals"], 2)
        self.assertIsNone(r["metrics"]["max"])
        self.assertEqual((r["verdict"], r["verdictP90"]), ("fail", "fail"))
        self.assertEqual(r["reasons"], ["errors 50.00% > 0.1%"])

    def test_finite(self):
        self.assertEqual(m.finite({"a": [m.INF, 1.0], "b": {"c": m.INF}}), {"a": [None, 1.0], "b": {"c": None}})


if __name__ == "__main__":
    unittest.main()
