import unittest

from tests.underlay_profiler.pprof_builder import GC_WORKER, ZSTD, build, cpu_profile, heap_profile
from vmagent_loadtest import categories, profile_schema
from vmagent_loadtest.pprof import parse_profile
from vmagent_loadtest.rollup import build_rollup, rollup_rows

CTX = {"RunId": "continuous", "Env": "prod", "Underlay": "u1", "Namespace": "ns", "Tier": 0, "RunLabel": ""}


class CategoriesTest(unittest.TestCase):
    def test_stack_rules_beat_leaf(self):
        # leaf alone would be gc-and-allocation / syscall; the stack says otherwise
        self.assertEqual(categories.categorize_stack(GC_WORKER), "gc-and-allocation")
        self.assertEqual(categories.categorize_stack(["runtime.cgocall"] + ZSTD), "compression")

    def test_leaf_rules(self):
        self.assertEqual(categories.categorize_leaf("runtime.futex"), "scheduler-and-idle")
        self.assertEqual(categories.categorize_leaf("syscall.write"), "syscall-and-network-io")
        self.assertEqual(categories.categorize_leaf("runtime.mallocgc"), "gc-and-allocation")
        self.assertEqual(categories.categorize_leaf("crypto/tls.(*Conn).Write"), "tls-and-crypto")
        self.assertEqual(categories.categorize_leaf("k8s.io/klog/v2.(*loggingT).output"), "logging")
        self.assertEqual(categories.categorize_leaf("example.com/x.Y"), "other")
        self.assertEqual(categories.categorize_stack([]), "other")

    def test_kql_generated_from_the_same_rules(self):
        leaf, stack = profile_schema.PROFILE_CATEGORY_FN, profile_schema.PROFILE_STACK_CATEGORY_FN
        for rx, cat in categories.LEAF_RULES:
            self.assertIn(f'@"{rx}", "{cat}"', leaf)
        for _kind, needle, cat in categories.STACK_RULES:
            self.assertIn(needle, stack)
            self.assertIn(f'"{cat}"', stack)


class RollupTest(unittest.TestCase):
    def test_cpu_rollup_reconciles(self):
        roll = build_rollup(parse_profile(cpu_profile()), "cpu")
        self.assertEqual(roll.total, 7_500)
        self.assertEqual(roll.categories, {"gc-and-allocation": 4_500, "compression": 2_000, "metrics-pipeline": 1_000})
        self.assertEqual(sum(f for _, f, _ in roll.functions) + roll.other_flat, roll.total)
        self.assertEqual(roll.duration_sec, 10.0)

    def test_top_limits_and_other_row(self):
        roll = build_rollup(parse_profile(cpu_profile()), "cpu", top_flat=1, top_cum=0)
        self.assertEqual(len(roll.functions), 1)
        self.assertEqual(roll.functions[0][0], "runtime.scanobject")
        self.assertEqual(roll.other_flat, 7_500 - 4_000)

    def test_root_frames_excluded_from_cum_ranking(self):
        data = build([("samples", "count"), ("cpu", "nanoseconds")],
                     [(["a", "mid", "runtime.goexit"], [1, 100]), (["b", "runtime.goexit"], [1, 100])],
                     duration_ns=1_000_000_000)
        roll = build_rollup(parse_profile(data), "cpu", top_flat=0, top_cum=10)
        names = {n for n, _, _ in roll.functions}
        self.assertNotIn("runtime.goexit", names)  # in every stack: no signal
        self.assertIn("mid", names)

    def test_ties_are_broken_by_name_so_output_is_deterministic(self):
        # ten functions with identical flat/cum; only the name can decide which three survive
        stacks = [([f"fn{i}", "main.main"], [1, 100]) for i in reversed(range(10))]
        data = build([("samples", "count"), ("cpu", "nanoseconds")], stacks, duration_ns=1_000_000_000)
        roll = build_rollup(parse_profile(data), "cpu", top_flat=3, top_cum=0)
        self.assertEqual([n for n, _, _ in roll.functions], ["fn0", "fn1", "fn2"])

    def test_rows_shape(self):
        rows = rollup_rows(CTX, "vmagent", "vmagent-0", "vmagent", "img:v1", "cpu", cpu_profile(), top_flat=2, top_cum=0)
        self.assertEqual({r["Kind"] for r in rows}, {"total", "category", "function", "other"})
        total = next(r for r in rows if r["Kind"] == "total")
        self.assertEqual((total["Flat"], total["DurationSec"], total["Image"], total["Underlay"]), (7_500, 10.0, "img:v1", "u1"))
        cores = sum(r["Flat"] for r in rows if r["Kind"] == "category") / 1e9 / total["DurationSec"]
        self.assertAlmostEqual(cores, 7_500 / 1e9 / 10)
        for r in rows:
            self.assertEqual(set(r), {c for c, _ in profile_schema.PROFILE_ROLLUP_COLUMNS})

    def test_heap_has_no_duration_and_missing_type_is_empty(self):
        rows = rollup_rows(CTX, "vmagent", "p", "vmagent", "", "heap", heap_profile())
        self.assertEqual({r["DurationSec"] for r in rows}, {0.0})
        self.assertEqual(next(r for r in rows if r["Kind"] == "total")["Flat"], 8_000)
        self.assertEqual(rollup_rows(CTX, "vmagent", "p", "vmagent", "", "heap", cpu_profile()), [])


if __name__ == "__main__":
    unittest.main()
