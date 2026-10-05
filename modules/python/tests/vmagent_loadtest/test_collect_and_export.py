import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from tests.underlay_profiler.pprof_builder import cpu_profile, heap_profile
from vmagent_loadtest import profiling

MIB = 1024 ** 2


def pod(name, app, containers):
    return {"metadata": {"name": name, "labels": {"app": app}},
            "spec": {"nodeName": "node-1", "containers": containers},
            "status": {"phase": "Running"}}


def container(name, cpu_req="100m", cpu_lim="1", mem_req="64Mi", mem_lim="256Mi"):
    return {"name": name, "image": f"img/{name}:v1",
            "resources": {"requests": {"cpu": cpu_req, "memory": mem_req},
                          "limits": {"cpu": cpu_lim, "memory": mem_lim}}}


PODS = [
    pod("vmagent-0", "vmagent", [container("vmagent"), container("vmagent-proxy")]),
    pod("vmsingle-abc", "vmsingle", [container("vmsingle")]),
    pod("konnectivity-server-x", "konnectivity-server", [container("konnectivity-server")]),
    pod("konnectivity-agent-y", "konnectivity-agent", [container("konnectivity-agent")]),
]
TOP = "vmagent-0  vmagent  250m  100Mi\nvmagent-0  vmagent-proxy  10m  20Mi\nvmsingle-abc  vmsingle  500m  300Mi\n"


class FakeKubectl:
    def __init__(self, fail_top=False):
        self.fail_top = fail_top

    def __call__(self, _kubeconfig, *args, **_kwargs):
        if "top" in args:
            if self.fail_top:
                raise RuntimeError("metrics API not available")
            return NS(stdout=TOP)
        selector = args[args.index("-l") + 1] if "-l" in args else ""
        items = [p for p in PODS if not selector or selector == f"app={p['metadata']['labels']['app']}"]
        return NS(stdout=json.dumps({"items": items}))


CTX = {"RunId": "r", "Env": "lab", "Underlay": "u", "Namespace": "ns", "Tier": 500, "RunLabel": "l"}


class CollectUsageTest(unittest.TestCase):
    def test_usage_requests_and_limits(self):
        with mock.patch.object(profiling, "kubectl", FakeKubectl()):
            rows = profiling.collect_usage("kc", "ns", "cp", CTX)
        by = {(r["Pod"], r["Container"]): r for r in rows}
        self.assertEqual(len(rows), 5)
        agent = by[("vmagent-0", "vmagent")]
        self.assertEqual((agent["UsageCores"], agent["UsageMemBytes"]), (0.25, 100 * MIB))
        self.assertEqual((agent["CpuReqCores"], agent["CpuLimCores"]), (0.1, 1.0))
        self.assertEqual((agent["MemReqBytes"], agent["MemLimBytes"]), (64 * MIB, 256 * MIB))
        self.assertEqual((agent["Role"], agent["Node"], agent["Image"]), ("cp", "node-1", "img/vmagent:v1"))
        self.assertEqual(by[("vmagent-0", "vmagent-proxy")]["Component"], "vmagent-proxy")
        # a container metrics-server has no sample for still gets its spec, with zero usage
        self.assertEqual(by[("konnectivity-agent-y", "konnectivity-agent")]["UsageCores"], 0.0)

    def test_top_failure_returns_no_rows(self):
        with mock.patch.object(profiling, "kubectl", FakeKubectl(fail_top=True)):
            self.assertEqual(profiling.collect_usage("kc", "ns", "cp", CTX), [])


class CollectAndExportTest(unittest.TestCase):
    def run_export(self, export_side_effect=None):
        exported = {}

        def fake_export(tables):
            if export_side_effect:
                raise export_side_effect
            exported.update(tables)
            return {t: len(r) for t, r in tables.items()}

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(profiling, "kubectl", FakeKubectl()), \
                mock.patch.object(profiling, "_collect_pod",
                                  return_value={"cpu": cpu_profile(), "heap": heap_profile()}), \
                mock.patch.object(profiling, "export_rows", side_effect=fake_export):
            work, results = Path(d, "work"), Path(d, "results")
            summary = profiling.collect_and_export("cp", "dp", "ns", work, results, "run1", 500,
                                                   run_label="lbl", underlay="u1", cpu_seconds=1)
            raw = sorted(p.name for p in (work / "pprof" / "ns" / "tier500").iterdir())
            written = json.loads((results / "profile-summary-ns-tier500.json").read_text(encoding="utf-8"))
        return summary, exported, raw, written

    def test_profiles_every_component_and_exports_all_tables(self):
        summary, tables, raw, written = self.run_export()
        self.assertEqual(summary["pods_profiled"], 4)  # one pod each: konn-server, vmagent, vmsingle, konn-agent
        self.assertEqual(len(tables["ProfileMeta"]), 8)  # 4 pods x (cpu, heap)
        self.assertTrue(tables["ProfileSamples"])
        self.assertEqual({r["Role"] for r in tables["ComponentUsage"]}, {"cp", "dp"})
        self.assertEqual({r["Component"] for r in tables["ProfileMeta"]},
                         {"konn-server", "vmagent", "vmsingle", "konn-agent"})
        meta = tables["ProfileMeta"][0]
        self.assertEqual((meta["RunId"], meta["Tier"], meta["RunLabel"], meta["Underlay"]), ("run1", 500, "lbl", "u1"))
        self.assertEqual(len(raw), 8)
        self.assertTrue(all(n.endswith(".pb.gz") for n in raw))
        self.assertEqual(summary["top_cpu"]["vmagent"][0]["function"], "runtime.scanobject")
        self.assertEqual(written["pods_profiled"], 4)
        self.assertEqual(summary["queued"], summary["rows"])

    def test_export_failure_is_not_fatal(self):
        summary, _, raw, _ = self.run_export(export_side_effect=RuntimeError("kusto down"))
        self.assertEqual(summary["queued"], {})
        self.assertEqual(len(raw), 8)  # raw profiles are still kept on disk

    def test_environment_label_comes_from_profile_env(self):
        with mock.patch.dict(os.environ, {"PROFILE_ENV": "staging"}):
            _, tables, _, _ = self.run_export()
        self.assertEqual({r["Env"] for r in tables["ProfileMeta"]}, {"staging"})


if __name__ == "__main__":
    unittest.main()
