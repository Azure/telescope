import base64
from functools import partial
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from clusterloader2.in_cluster import run_cl2_job
from clusterloader2.utils import run_cl2_command


class TestCL2InCluster(unittest.TestCase):
    @patch("clusterloader2.utils.run_cl2_job")
    def test_all_providers_use_job_and_return_status(self, run_job):
        for provider in ("aks", "aws", "gce", "gcp"):
            for code in (0, 7):
                with self.subTest(provider=provider, code=code):
                    run_job.reset_mock()
                    run_job.return_value = code
                    result = run_cl2_command(
                        "kubeconfig", "image:unchanged", "config", "reports", provider,
                        cl2_config_file="modules/network.yaml", overrides=True,
                        enable_prometheus=True, scrape_containerd=True,
                    )
                    self.assertEqual(result, code)
                    run_job.assert_called_once()
                    self.assertEqual(run_job.call_args.args[:4],
                                     ("kubeconfig", "image:unchanged", "config", "reports"))
                    arguments = run_job.call_args.args[4]
                    self.assertIn(f"--provider={provider}", arguments)
                    self.assertIn("--run-from-cluster=true", arguments)
                    self.assertNotIn("--kubeconfig", arguments)
                    self.assertIn("/root/perf-tests/clusterloader2/config/modules/network.yaml", arguments)
                    self.assertIn("--testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml", arguments)
                    self.assertIn("--enable-prometheus-server=True", arguments)
                    self.assertIn("--prometheus-scrape-containerd=True", arguments)

    @patch("clusterloader2.in_cluster.time.sleep")
    def test_reports_ack_cleanup_and_saved_status(self, _sleep):
        for code, failed_command, expected in ((0, None, 0), (7, None, 7),
                                               (0, "logs", 0), (0, "delete", 1),
                                               (7, "delete", 7), (0, "cp", 1)):
            with self.subTest(code=code, failed_command=failed_command):
                with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
                    config = Path(directory) / "config"
                    (config / "modules").mkdir(parents=True)
                    (config / "modules" / "network.yaml").write_bytes(b"nested config")
                    reports = Path(directory) / "reports"
                    calls, resources = [], []

                    def kubectl(command, *, calls, resources, code, failed_command, reports, **kwargs):
                        self.assertEqual(kwargs["timeout"], 120)
                        self.assertIn("--request-timeout=30s", command)
                        args = command[6:]
                        calls.append(args)
                        output = b""
                        if args[:2] == ["create", "-f"]:
                            resources.extend(json.loads(kwargs["input"])["items"])
                        elif args[0] == "get":
                            phase = "Pending" if sum(call[0] == "get" for call in calls) == 1 else "Running"
                            output = json.dumps({"items": [{
                                "metadata": {"name": "driver-pod"}, "status": {"phase": phase},
                            }]}).encode()
                        elif args[:4] == ["exec", "driver-pod", "--", "cat"]:
                            output = str(code).encode()
                        elif args[0] == "cp" and failed_command != "cp":
                            (reports / "junit.xml").write_text("<testsuites/>", encoding="utf-8")
                        elif args[0] == "logs":
                            kwargs["stdout"].write(b"raw log \xff\n")
                        return subprocess.CompletedProcess(command, int(args[0] == failed_command),
                                                           stdout=output, stderr=b"mock failure")

                    runner = partial(kubectl, calls=calls, resources=resources, code=code,
                                     failed_command=failed_command, reports=reports)
                    with patch("clusterloader2.in_cluster.subprocess.run", side_effect=runner):
                        if failed_command == "cp":
                            with self.assertRaises(RuntimeError):
                                run_cl2_job("kubeconfig", "image", config, reports, ["--run-from-cluster=true"])
                        else:
                            self.assertEqual(run_cl2_job(
                                "kubeconfig", "image", config, reports, ["--run-from-cluster=true"]), expected)

                    self.assertEqual(next(reports.glob("*.exit-code")).read_text(encoding="ascii"), str(expected))
                    self.assertEqual(next(reports.glob("*.log")).read_bytes(), b"raw log \xff\n")
                    self.assertEqual(calls[-1][0], "delete")
                    self.assertTrue(any("--timeout=90s" in call for call in calls))
                    ack = ["exec", "driver-pod", "--", "touch", "/cl2-control/reports-collected"]
                    if failed_command == "cp":
                        self.assertNotIn(ack, calls)
                    else:
                        self.assertLess(next(i for i, call in enumerate(calls) if call[0] == "cp"), calls.index(ack))
                        self.assertIn(f"--for=jsonpath={{.status.containerStatuses[0].state.terminated.exitCode}}={code}",
                                      calls[calls.index(ack) + 1])
                    config_map = next(item for item in resources if item["kind"] == "ConfigMap")
                    self.assertEqual(base64.b64decode(config_map["binaryData"]["config"]), b"nested config")
                    job = next(item for item in resources if item["kind"] == "Job")
                    pod_spec = job["spec"]["template"]["spec"]
                    self.assertEqual(pod_spec["nodeSelector"], {"kubernetes.io/os": "linux"})
                    self.assertNotIn("tolerations", pod_spec)
                    self.assertNotIn("affinity", pod_spec)
                    self.assertEqual(pod_spec["volumes"][0]["projected"]["sources"],
                                     [{"configMap": {"name": config_map["metadata"]["name"],
                                                     "items": [{"key": "config", "path": "modules/network.yaml"}]}}])
