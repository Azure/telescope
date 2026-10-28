import gzip
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agent_sandbox import main as cli
from agent_sandbox import manifests as mf


def deployment(name, namespace):
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "namespace": namespace},
            "spec": {"template": {"spec": {"containers": [{"name": "manager"}]}}}}


RELEASES = {
    mf.KWOK_URL: [{"kind": "ConfigMap", "metadata": {"name": "kwok"}, "data": {"kwok.yaml": "options: {}\n"}},
                  deployment("kwok-controller", "kube-system")],
    mf.KWOK_STAGE_URL: [{"apiVersion": "kwok.x-k8s.io/v1alpha1", "kind": "Stage", "metadata": {"name": "pod-ready"}}],
    mf.AGENT_SANDBOX_URL: [{"kind": "CustomResourceDefinition", "metadata": {"name": "sandboxes.agents.x-k8s.io"}},
                           {"kind": "Namespace", "metadata": {"name": "agent-sandbox-system"}},
                           deployment(mf.CONTROLLER_NAME, "agent-sandbox-system")],
}


class FakeKubectl:
    """Answers the kubectl calls the module makes, recording them."""

    def __init__(self, ready_nodes=24, ready_sandboxes=3000, runtime_class=True, files=None, pod_phase="Running"):
        self.ready_nodes, self.ready_sandboxes, self.runtime_class = ready_nodes, ready_sandboxes, runtime_class
        self.files, self.pod_phase = files or {}, pod_phase
        self.calls = []

    def __call__(self, args, stdin=None, timeout=600, binary=False):  # pylint: disable=unused-argument
        self.calls.append(args)
        ready = {"type": "Ready", "status": "True"}
        if args[:2] == ["get", "nodes"]:
            return json.dumps({"items": [{"status": {"conditions": [ready]}}] * self.ready_nodes})
        if args[:2] == ["get", "sandboxwarmpools"]:
            return json.dumps({"items": [{"status": {"readyReplicas": self.ready_sandboxes}}]})
        if args[:2] == ["get", "runtimeclass"]:
            if not self.runtime_class:
                raise RuntimeError("NotFound")
            return "kata-vm-isolation"
        if "exec" in args:
            script = args[-1]
            if "DONE" in script:
                return "True\n"
            for name, data in self.files.items():
                if name in script:
                    return data
            return b"" if binary else ""
        if "jsonpath={.status.phase}" in args:
            return self.pod_phase
        if "logs" in args:
            return "phase rate-50: done\n"
        return ""


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.workdir = self.dir.name
        patcher = patch.object(cli.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.dir.cleanup()


class TestConfigure(Base):
    def run_configure(self, fake):
        with patch.object(cli, "kubectl", fake), patch.object(cli, "apply") as apply, \
                patch.object(cli, "fetch", side_effect=lambda url, sha, workdir: RELEASES[url]):
            cli.main(["configure", "--workdir", self.workdir, "--node_selector", "agentpool=systempool1",
                      "--pools", "4", "--replicas_per_pool", "750", "--kwok_nodes", "24", "--pods_per_node", "1000", "--controller_cpu", "6"])
        return [call.args[0] for call in apply.call_args_list]

    def test_installs_everything_in_order(self):
        fake = FakeKubectl(runtime_class=False)
        applied = self.run_configure(fake)
        kinds = [[d["kind"] for d in docs] for docs in applied]
        self.assertEqual(kinds[0], ["ConfigMap", "Deployment"])  # KWOK
        self.assertEqual(kinds[1], ["Stage"])
        self.assertEqual(kinds[2], ["Node"] * 24)
        self.assertEqual(kinds[3], ["CustomResourceDefinition"])  # agent-sandbox CRDs first
        self.assertEqual(kinds[4], ["Namespace", "Deployment"])
        self.assertEqual(kinds[5], ["RuntimeClass"])
        self.assertEqual(kinds[6], ["Namespace", "SandboxTemplate", "SandboxWarmPool"] * 4)
        controller = applied[4][1]["spec"]["template"]["spec"]
        self.assertEqual(controller["nodeSelector"], {"agentpool": "systempool1"})
        self.assertEqual(controller["containers"][0]["resources"]["limits"]["cpu"], "6")
        self.assertIn(["wait", "--for=condition=Established", "crd/sandboxes.agents.x-k8s.io", "--timeout=300s"],
                      fake.calls)

    def test_keeps_an_existing_runtime_class(self):
        applied = self.run_configure(FakeKubectl(runtime_class=True))
        self.assertNotIn(["RuntimeClass"], [[d["kind"] for d in docs] for docs in applied])

    def test_times_out_when_the_pools_do_not_fill(self):
        with self.assertRaisesRegex(TimeoutError, "pools: not done"):
            cli.wait_for("pools", lambda: (False, 1), 0)


class TestExecuteAndCollect(Base):
    def generator_files(self):
        run = {"runId": "r1", "startedAt": "2026-10-28T00:00:00Z",
               "plan": {"runId": "r1", "pools": [{"namespace": "sbx-p0", "name": "wp"}], "phases": [], "seed": 1},
               "phases": [{"name": "rate-50", "kind": "poisson", "rate": 50.0, "durationSeconds": 2.0,
                           "warmupSeconds": 1.0, "dwellSeconds": 2.0, "t0": 0.0, "t1": 2000.0, "undrained": 0}]}
        claims = [{"sched": 1000.0 + i * 20, "sent": 1001.0 + i * 20, "ret": 1005.0 + i * 20, "adopt": 1006.0 + i * 20,
                   "ready": 1030.0 + i * 20, "outcome": "ready", "launch": "warm", "delRet": 3100.0 + i * 20,
                   "podGone": 3300.0 + i * 20} for i in range(50)]
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as f:
            f.write("".join(json.dumps(c) + "\n" for c in claims).encode())
        return {"claims.jsonl.gz": buf.getvalue(), "run.json": json.dumps(run).encode()}

    def test_execute_runs_the_generator_and_copies_its_results(self):
        fake = FakeKubectl(files=self.generator_files())
        with patch.object(cli, "kubectl", fake), patch.object(cli, "apply") as apply:
            cli.main(["execute", "--workdir", self.workdir, "--node_selector", "agentpool=systempool1",
                      "--run_id", "r1", "--rates", "50,100", "--duration", "120", "--warmup", "30"])
        (docs,) = [call.args[0] for call in apply.call_args_list]
        plan = json.loads(docs[4]["data"]["plan.json"])
        self.assertEqual([p["rate"] for p in plan["phases"]], [50.0, 100.0])
        self.assertEqual(plan["phases"][0]["durationSeconds"], 150)
        self.assertIn("class Generator", docs[4]["data"]["generator.py"])
        for name in ("claims.jsonl.gz", "run.json"):
            self.assertTrue(os.path.getsize(os.path.join(self.workdir, name)) > 0)
        self.assertTrue(any("COLLECTED" in call[-1] for call in fake.calls if "exec" in call))

    def test_execute_stops_when_the_generator_pod_fails(self):
        with patch.object(cli, "kubectl", FakeKubectl(pod_phase="Failed")), patch.object(cli, "apply"):
            with self.assertRaises(SystemExit):
                cli.main(["execute", "--workdir", self.workdir, "--node_selector", "a=b", "--run_id", "r1"])

    def test_collect_writes_one_line_per_rate(self):
        for name, data in self.generator_files().items():
            with open(os.path.join(self.workdir, name), "wb") as f:
                f.write(data)
        result = os.path.join(self.workdir, "results.json")
        cli.main(["collect", "--workdir", self.workdir, "--run_id", "r1", "--run_url", "https://run",
                  "--cloud_info", '{"cloud": "azure"}', "--result_file", result])
        with open(result, encoding="utf-8") as f:
            (row,) = [json.loads(line) for line in f]
        self.assertEqual((row["phase"], row["rate"], row["verdict"], row["verdict_p90"]), ("rate-50", 50.0, "pass", "pass"))
        self.assertEqual((row["run_id"], row["run_url"], row["cloud_info"]), ("r1", "https://run", '{"cloud": "azure"}'))
        self.assertEqual((row["duration_seconds"], row["metrics"]["arrivals"], row["metrics"]["p50"]), (1.0, 50, 30.0))
        self.assertEqual(row["configuration"]["agent_sandbox_version"], mf.AGENT_SANDBOX_VERSION)
        self.assertNotIn(None, list(row.values()))  # top-level nulls break the Kusto table helper


class TestHelpers(Base):
    def test_kubectl(self):
        ok = subprocess.CompletedProcess([], 0, stdout=b"out", stderr=b"")
        with patch.object(cli.subprocess, "run", return_value=ok) as run:
            self.assertEqual(cli.kubectl(["get", "nodes"]), "out")
            self.assertEqual(cli.kubectl(["get", "nodes"], binary=True), b"out")
        self.assertEqual(run.call_args.args[0], ["kubectl", "get", "nodes"])
        failed = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"forbidden")
        with patch.object(cli.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "forbidden"):
                cli.kubectl(["get", "nodes"])

    def test_apply_sends_a_list(self):
        with patch.object(cli, "kubectl") as kubectl:
            cli.apply([{"kind": "Namespace", "metadata": {"name": "x"}}])
        body = json.loads(kubectl.call_args.kwargs["stdin"])
        self.assertEqual((body["kind"], body["items"][0]["metadata"]["name"]), ("List", "x"))
        self.assertIn("--server-side", kubectl.call_args.args[0])

    def test_fetch_checks_the_digest_and_caches(self):
        data = b"kind: Namespace\nmetadata: {name: a}\n---\nkind: Namespace\nmetadata: {name: b}\n"
        response = MagicMock()
        response.__enter__.return_value.read.return_value = data
        url = "https://example.test/release.yaml"
        with patch.object(cli.urllib.request, "urlopen", return_value=response) as urlopen:
            docs = cli.fetch(url, hashlib.sha256(data).hexdigest(), self.workdir)
            cli.fetch(url, hashlib.sha256(data).hexdigest(), self.workdir)
            with self.assertRaisesRegex(ValueError, "sha256"):
                cli.fetch(url, "0" * 64, self.workdir)
        self.assertEqual([d["metadata"]["name"] for d in docs], ["a", "b"])
        urlopen.assert_called_once()

    def test_wait_for_retries_api_errors(self):
        answers = iter([RuntimeError("timeout"), (True, 3)])

        def check():
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer
        self.assertEqual(cli.wait_for("x", check, 60), 3)

    def test_selector(self):
        self.assertEqual(cli.selector("a=b,c=d=e"), {"a": "b", "c": "d=e"})
        self.assertEqual(cli.selector(""), {})


if __name__ == "__main__":
    unittest.main()
