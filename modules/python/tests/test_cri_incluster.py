import json
from pathlib import Path
import shlex
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import yaml

from clusterloader2.cri import cri, incluster
from clusterloader2.utils import run_cl2_command


class TestCRIInCluster(unittest.TestCase):
    def setUp(self):
        self.work = Path.cwd() / (".cl2-test-" + uuid.uuid4().hex)
        self.work.mkdir()
        self.addCleanup(shutil.rmtree, self.work)
        self.config = self.work / "config"
        shutil.copytree(Path(cri.__file__).parent / "config", self.config)
        with patch.object(cri, "KubernetesClient") as client:
            kube = client.return_value
            kube.get_nodes.return_value = [SimpleNamespace(
                metadata=SimpleNamespace(name="fixture"),
                status=SimpleNamespace(allocatable={"cpu": "15800m", "memory": "64000000Ki"}))]
            kube.get_daemonsets_pods_allocated_resources.return_value = (1000, 1000000)
            kube.get_daemonsets_pods_count.return_value = 6
            cri.override_config_clusterloader2(
                10, 10, 30, 1, "3m", "memory", False, "15s", "aks",
                "akscritelescope.azurecr.io", "e2e-test-images/resource-consumer:1.13",
                "linux", True, False, "15s", True, str(self.config / "overrides.yaml"))
        self.reports = self.work / "results"
        self.image = "ghcr.io/azure/clusterloader2:v20250513"
        self.resources = incluster.build_resources(
            "cl2-cri-test", self.image, self.config, True, False, 3600)
        self.calls = []

    def test_existing_flags_and_config_preserved(self):
        for scrape_containerd in (False, True):
            with self.subTest(scrape_containerd=scrape_containerd):
                with patch("clusterloader2.utils.DockerClient") as docker:
                    docker.return_value.run_container.return_value.wait.return_value = {"StatusCode": 0}
                    run_cl2_command("kube", self.image, str(self.config), str(self.reports),
                                    "aks", overrides=True, enable_prometheus=True,
                                    tear_down_prometheus=False, scrape_kubelets=True,
                                    scrape_containerd=scrape_containerd)
                    args = shlex.split(docker.return_value.run_container.call_args.args[1])
                index = args.index("--kubeconfig")
                args[index:index + 2] = ["--run-from-cluster=true"]
                resources = incluster.build_resources(
                    "cl2-cri-test", self.image, self.config, True, scrape_containerd, 3600)
                spec = resources[-1]["spec"]["template"]["spec"]
                self.assertEqual(shlex.split(spec["containers"][0]["args"][0].splitlines()[0]),
                                 ["./clusterloader2"] + args)
                self.assertEqual(resources[-2]["data"],
                                 {p.name: p.read_text() for p in self.config.iterdir()})
                self.assertEqual(spec["containers"][0]["image"], self.image)
                self.assertTrue(spec["automountServiceAccountToken"])
                self.assertEqual(spec["serviceAccountName"], resources[1]["metadata"]["name"])
                self.assertEqual(spec["nodeSelector"]["agentpool"], "default")
                self.assertNotIn("kubeconfig", json.dumps(resources))
                self.assertNotIn("/root/.azure", json.dumps(resources))
                self.assertEqual(resources[-1]["spec"]["backoffLimit"], 0)
                self.assertEqual(resources[2]["rules"],
                                 [{"apiGroups": ["*"], "resources": ["*"], "verbs": ["*"]}])

    def test_config_size_and_flat_layout_checked(self):
        with patch.object(Path, "read_text", return_value="x" * (1024 * 1024)):
            with self.assertRaisesRegex(ValueError, "1 MiB"):
                incluster.build_resources("test", self.image, self.config, True, False, 3600)
        (self.config / "nested").mkdir()
        with self.assertRaisesRegex(ValueError, "flat"):
            incluster.build_resources("test", self.image, self.config, True, False, 3600)

    def execute(self, code=0, junit=True, phase="Running", fail=None, timeout=3600):
        def kubectl(command, **kwargs):
            args = command[6:]
            self.calls.append(args)
            self.assertEqual(command[:3], ["kubectl", "--kubeconfig", "agent-kubeconfig"])
            self.assertEqual(kwargs["timeout"], 120)
            if fail == args[0]:
                raise subprocess.CalledProcessError(1, args)
            if args[0] == "create":
                resource = json.loads(kwargs["input"])
                if fail == resource["kind"]:
                    raise subprocess.CalledProcessError(1, args)
            stdout = ""
            if args[0] == "get":
                stdout = json.dumps({"items": [{"metadata": {"name": "pod"},
                                               "status": {"phase": phase}}]})
            elif "cat" in args:
                stdout = str(code)
            elif args[0] == "cp" and junit:
                (self.reports / "junit.xml").write_text(
                    '<testsuites><testsuite tests="1" failures="0" errors="0"/></testsuites>')
                (self.reports / "PodStartupLatency_PodStartupLatency_fixture_2026.json").write_text(
                    json.dumps({"dataItems": [{"data": {"Perc50": 1}}]}))
            if args[0] == "logs":
                self.assertFalse(kwargs["text"])
                return SimpleNamespace(stdout=b"CL2 output: \xf7\n", stderr=b"", returncode=0)
            return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

        with patch.object(incluster.subprocess, "run", side_effect=kubectl):
            incluster.run_in_cluster("agent-kubeconfig", self.image, self.config, self.reports,
                                     True, False, timeout)

    def assert_cleanup(self):
        self.assertEqual([call[1] for call in self.calls if call[0] == "delete"],
                         ["Job", "ConfigMap", "ClusterRoleBinding", "ClusterRole",
                          "ServiceAccount", "Namespace"])

    def test_report_copy_before_ack_and_cleanup_and_original_collector(self):
        self.execute()
        cp = next(i for i, call in enumerate(self.calls) if call[0] == "cp")
        ack = next(i for i, call in enumerate(self.calls) if "touch" in call)
        delete = next(i for i, call in enumerate(self.calls) if call[0] == "delete")
        self.assertLess(cp, ack)
        self.assertLess(ack, delete)
        self.assert_cleanup()
        self.assertEqual((self.reports / "cl2-driver.log").read_bytes(), b"CL2 output: \xf7\n")
        result = self.work / "collected.json"
        cri.collect_clusterloader2(10, 30, 1, "memory", self.reports, "{}",
                                   "test", "", str(result), False)
        self.assertEqual(json.loads(result.read_text())["status"], "success")

    def test_nonzero_copies_reports_and_fails(self):
        with self.assertRaises(subprocess.CalledProcessError) as error:
            self.execute(code=7)
        self.assertEqual(error.exception.returncode, 7)
        self.assertTrue((self.reports / "junit.xml").is_file())
        self.assert_cleanup()

    def test_no_junit_is_failure(self):
        with self.assertRaisesRegex(RuntimeError, "no junit"):
            self.execute(junit=False)
        self.assert_cleanup()

    def test_copy_failure_never_acks_and_cleans_up(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(fail="cp")
        self.assertFalse(any("touch" in call for call in self.calls))
        self.assert_cleanup()

    def test_terminated_pod_is_failure(self):
        with self.assertRaisesRegex(RuntimeError, "terminated"):
            self.execute(phase="Failed")
        self.assert_cleanup()

    def test_timeout_cleans_up(self):
        with self.assertRaises(TimeoutError):
            self.execute(timeout=0)
        self.assert_cleanup()

    def test_partial_create_cleans_only_owned_resources(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(fail="ClusterRoleBinding")
        self.assertEqual([call[1] for call in self.calls if call[0] == "delete"],
                         ["ClusterRole", "ServiceAccount", "Namespace"])

    def test_cleanup_failure_cannot_pass(self):
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            self.execute(fail="delete")
        self.assert_cleanup()

    def test_stale_results_rejected_before_create(self):
        self.reports.mkdir()
        (self.reports / "junit.xml").touch()
        with self.assertRaisesRegex(ValueError, "empty"):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_shell_waits_for_collection_and_returns_original_status(self):
        script = self.resources[-1]["spec"]["template"]["spec"]["containers"][0]["args"][0]
        command = script.splitlines()[0]
        status, ack = self.work / "status", self.work / "ack"
        script = script.replace(incluster.STATUS, str(status)).replace(incluster.ACK, str(ack))
        ack.touch()
        for code in (0, 7):
            result = subprocess.run(["/bin/sh", "-c", script.replace(
                command, f"/bin/sh -c 'exit {code}'")], check=False, timeout=10)
            self.assertEqual(result.returncode, code)
            self.assertEqual(status.read_text(), str(code))

    def test_opt_in_and_default_dispatch(self):
        with patch.object(cri, "run_cl2_command") as docker, patch.object(cri, "run_in_cluster") as job:
            cri.execute_clusterloader2("image", "config", "reports", "kube", "aks", True, False)
            docker.assert_called_once()
            job.assert_not_called()
            cri.execute_clusterloader2("image", "config", "reports", "kube", "aks", True, False, True)
            job.assert_called_once_with("kube", "image", "config", "reports", True, False)
            with self.assertRaisesRegex(ValueError, "only on AKS"):
                cri.execute_clusterloader2("image", "config", "reports", "kube", "aws", True, False, True)

    def test_pilot_pipeline_is_opt_in_and_limits_matrix(self):
        repo = Path(cri.__file__).parents[4]
        pipeline = yaml.safe_load(
            (repo / "pipelines/perf-eval/CRI Benchmark/azurelinux-resource-consume.yml").read_text())
        self.assertFalse(pipeline["parameters"][0]["default"])
        stages = pipeline["stages"]
        matrix = stages[0]["jobs"][0]["parameters"]["matrix"]
        conditional = "${{ if not(parameters.cl2_in_cluster_pilot) }}"
        self.assertEqual(set(matrix), {"n10-p300-memory", conditional})
        self.assertEqual(set(matrix[conditional]), {"n10-p700-memory", "n10-p1100-memory"})
        self.assertEqual(matrix["n10-p300-memory"]["cl2_run_from_cluster"],
                         "${{ parameters.cl2_in_cluster_pilot }}")
        self.assertIn("not(parameters.cl2_in_cluster_pilot)", stages[1]["condition"])
        self.assertTrue(all("cl2_run_from_cluster" not in entry for entry in
                            stages[1]["jobs"][0]["parameters"]["matrix"].values()))
