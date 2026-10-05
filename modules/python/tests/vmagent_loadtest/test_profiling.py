import gzip
import unittest

from vmagent_loadtest import profile_schema, profiling
from vmagent_loadtest.pprof import OTHER_FRAME, aggregate_stacks, parse_profile, split_go_func


def _varint(n: int) -> bytes:
    n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field(number: int, wire: int, payload) -> bytes:
    key = _varint((number << 3) | wire)
    if wire == 0:
        return key + _varint(payload)
    return key + _varint(len(payload)) + payload


def build_profile(duration_ns=30_000_000_000) -> bytes:
    """cpu profile: stacks  main>work>alloc (x3) and main>work (x1), values are ns."""
    strings = ["", "samples", "count", "cpu", "nanoseconds", "pkg/a.main", "pkg/a.work", "runtime.mallocgc"]
    msg = b""
    msg += _field(1, 2, _field(1, 0, 1) + _field(2, 0, 2))  # samples/count
    msg += _field(1, 2, _field(1, 0, 3) + _field(2, 0, 4))  # cpu/nanoseconds
    for fid, name_idx in ((1, 5), (2, 6), (3, 7)):
        msg += _field(5, 2, _field(1, 0, fid) + _field(2, 0, name_idx))
    for loc_id, fid in ((1, 1), (2, 2), (3, 3)):
        line = _field(1, 0, fid)
        msg += _field(4, 2, _field(1, 0, loc_id) + _field(4, 2, line))
    # packed location ids (leaf first) / packed values; negative value exercises int64 decode
    s1 = _field(1, 2, b"".join(_varint(i) for i in (3, 2, 1))) + _field(2, 2, _varint(3) + _varint(3_000))
    s2 = _field(1, 2, b"".join(_varint(i) for i in (2, 1))) + _field(2, 2, _varint(1) + _varint(1_000))
    msg += _field(2, 2, s1) + _field(2, 2, s2)
    for s in strings:
        msg += _field(6, 2, s.encode())
    msg += _field(9, 0, 1_700_000_000_000_000_000)
    msg += _field(10, 0, duration_ns)
    return gzip.compress(msg)


class PprofTest(unittest.TestCase):
    def test_parse_and_aggregate(self):
        prof = parse_profile(build_profile())
        self.assertEqual(prof.sample_types, [("samples", "count"), ("cpu", "nanoseconds")])
        stacks, total = aggregate_stacks(prof, "cpu")
        self.assertEqual(total, 4_000)
        self.assertEqual(stacks[0], (("runtime.mallocgc", "pkg/a.work", "pkg/a.main"), 3_000))
        self.assertEqual(stacks[1], (("pkg/a.work", "pkg/a.main"), 1_000))

    def test_top_k_folds_remainder_into_other(self):
        prof = parse_profile(build_profile())
        stacks, total = aggregate_stacks(prof, "cpu", top_k=1)
        self.assertEqual(total, 4_000)
        self.assertEqual(stacks[-1], ((OTHER_FRAME,), 1_000))
        self.assertEqual(sum(v for _, v in stacks), total)

    def test_split_go_func(self):
        self.assertEqual(split_go_func("runtime.mallocgc"), ("runtime", "mallocgc"))
        self.assertEqual(split_go_func("github.com/x/y/lib/promscrape.(*scrapeWork).run"),
                         ("github.com/x/y/lib/promscrape", "(*scrapeWork).run"))
        self.assertEqual(split_go_func("main"), ("", "main"))


class ProfilingTest(unittest.TestCase):
    CTX = {"RunId": "r", "Env": "lab", "Underlay": "u", "Namespace": "ns", "Tier": 500, "RunLabel": "l"}

    def test_profile_rows_cpu_cores(self):
        meta, samples = profiling.profile_rows(self.CTX, "vmagent", "vmagent-0", "vmagent", "cpu",
                                               build_profile(duration_ns=2_000))
        self.assertEqual(len(meta), 1)
        self.assertEqual(meta[0]["TotalValue"], 4_000)
        self.assertAlmostEqual(meta[0]["ProfiledCores"], 4_000 / 1e9 / (2_000 / 1e9))
        self.assertEqual([s["Leaf"] for s in samples], ["runtime.mallocgc", "pkg/a.work"])
        self.assertEqual(samples[0]["LeafPackage"], "runtime")
        self.assertEqual(samples[0]["Stack"][-1], "pkg/a.main")

    def test_missing_sample_type_is_skipped(self):
        meta, samples = profiling.profile_rows(self.CTX, "vmagent", "p", "vmagent", "heap", build_profile())
        self.assertEqual((meta, samples), ([], []))

    def test_top_functions(self):
        _, samples = profiling.profile_rows(self.CTX, "vmagent", "p", "vmagent", "cpu", build_profile())
        top = profiling.top_functions(samples, "vmagent", "cpu")
        self.assertEqual(top[0]["function"], "runtime.mallocgc")
        self.assertEqual(top[0]["flat_pct"], 75.0)
        self.assertEqual(top[1]["cum_pct"], 100.0)

    def test_quantities(self):
        self.assertEqual(profiling.parse_cpu("250m"), 0.25)
        self.assertEqual(profiling.parse_cpu("2"), 2.0)
        self.assertEqual(profiling.parse_cpu(None), 0.0)
        self.assertEqual(profiling.parse_mem("256Mi"), 256 * 1024 ** 2)
        self.assertEqual(profiling.parse_mem("2Gi"), 2 * 1024 ** 3)
        self.assertEqual(profiling.parse_mem("500M"), 500_000_000)

    def test_parse_top(self):
        out = profiling._parse_top(  # pylint: disable=protected-access
            "vmagent-0  vmagent  1200m  345Mi\nvmagent-0  vmagent-proxy  2  90Mi\n")
        self.assertEqual(out[("vmagent-0", "vmagent")], (1.2, 345 * 1024 ** 2))
        self.assertEqual(out[("vmagent-0", "vmagent-proxy")][0], 2.0)


class SchemaTest(unittest.TestCase):
    def test_commands_cover_every_column(self):
        for table, cols in profile_schema.TABLES.items():
            create = profile_schema.create_table_cmd(table)
            mapping = profile_schema.create_mapping_cmd(table)
            for name, typ in cols:
                self.assertIn(f"{name}: {typ}", create)
                self.assertIn(f'"$.{name}"', mapping)


if __name__ == "__main__":
    unittest.main()
