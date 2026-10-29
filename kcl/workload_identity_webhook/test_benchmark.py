import argparse
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import benchmark
import preflight


RUN_ID = "wi-123-1"
CLIENT_ID = "00000000-0000-0000-0000-000000000001"


def report():
    item = {
        "total": 0, "duration": "10m1.5s", "totalReceivedBytes": 100,
        "percentileLatencies": [[0.5, 0.1], [0.95, 0.2], [0.99, 0.3]],
    }
    return {"perSpecResults": [copy.deepcopy(item)], "aggregated": item}


def pod(phase="smoke"):
    return {
        "metadata": {"labels": {
            "azure.workload.identity/use": "true",
            "benchmark": "workload-identity-webhook",
            "benchmark-run": RUN_ID, "benchmark-phase": phase,
        }},
        "spec": {
            "serviceAccountName": "pod-benchmark",
            "schedulerName": "kperf-admission-only",
            "containers": [{
                "env": [
                    {"name": "AZURE_CLIENT_ID", "value": CLIENT_ID},
                    {"name": "AZURE_TENANT_ID", "value": "tenant"},
                    {"name": "AZURE_AUTHORITY_HOST", "value": "https://login.microsoftonline.com/"},
                    {"name": "AZURE_FEDERATED_TOKEN_FILE", "value": "/tokens/azure-token"},
                ],
                "volumeMounts": [{"name": "azure-token", "mountPath": "/tokens", "readOnly": True}],
            }],
            "volumes": [{"name": "azure-token", "projected": {"sources": [{
                "serviceAccountToken": {"audience": "api://AzureADTokenExchange", "path": "azure-token"},
            }]}}],
        },
    }


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.template = yaml.safe_load((benchmark.ROOT / "load-profile.yaml").read_text())

    def test_measurement_profile_exact_values(self):
        profile = benchmark.profile_for_phase(self.template, RUN_ID, "measure")
        self.assertEqual(profile["version"], 1)
        self.assertEqual(len(profile["specs"]), 1)
        spec = profile["specs"][0]
        self.assertEqual({key: spec[key] for key in (
            "rate", "duration", "total", "client", "conns", "contentType", "maxRetries",
        )}, {"rate": 600, "duration": 600, "total": 0, "client": 600, "conns": 20,
             "contentType": "json", "maxRetries": 0})
        self.assertEqual(spec["requests"], [{
            "shares": 1, "postDel": {
                "group": "", "version": "v1", "resource": "pods", "namespace": RUN_ID,
                "deleteRatio": 0, "payloadSize": 3650,
                "pod": {
                    "labels": {
                        "azure.workload.identity/use": "true",
                        "benchmark": "workload-identity-webhook",
                        "benchmark-run": RUN_ID, "benchmark-phase": "measure",
                    },
                    "serviceAccountName": "pod-benchmark",
                    "schedulerName": "kperf-admission-only",
                },
            },
        }])

    def test_smoke_and_warmup_do_not_modify_measurement(self):
        original = copy.deepcopy(self.template)
        for phase, rate, total, duration in (("smoke", 1, 3, 0), ("warmup", 5, 0, 30)):
            spec = benchmark.profile_for_phase(self.template, RUN_ID, phase)["specs"][0]
            self.assertEqual((spec["rate"], spec["total"], spec["duration"]), (rate, total, duration))
        self.assertEqual(self.template, original)
        self.assertEqual(benchmark.profile_for_phase(self.template, RUN_ID, "measure")["specs"][0]["rate"], 600)

    def test_invalid_phase_and_unresolved_placeholder(self):
        with self.assertRaises(ValueError):
            benchmark.profile_for_phase(self.template, RUN_ID, "invalid")
        with self.assertRaises(ValueError):
            benchmark.render({"name": "__UNKNOWN__"}, {})

    def test_job_profile_wiring_and_namespace_permissions(self):
        documents = list(yaml.safe_load_all((benchmark.ROOT / "workload.yaml").read_text()))
        documents = benchmark.render(documents, {
            "RUN_NAMESPACE": RUN_ID, "RUNNER_NAMESPACE": RUN_ID + "-runner",
            "RUN_ID": RUN_ID, "CLIENT_ID": CLIENT_ID,
            "RUNNER_IMAGE": "image@sha256:test", "JOB_NAME": "kperf-measure",
        })
        job = next(item for item in documents if item["kind"] == "Job")
        self.assertEqual(job["spec"]["activeDeadlineSeconds"], 900)
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        spec = job["spec"]["template"]["spec"]
        self.assertEqual(spec["restartPolicy"], "Never")
        self.assertEqual(spec["nodeSelector"], {"kubernetes.azure.com/agentpool": "workerpool"})
        self.assertEqual(spec["serviceAccountName"], "generator")
        self.assertEqual(spec["volumes"][0]["configMap"]["name"], "kperf-measure")
        container = spec["containers"][0]
        self.assertEqual(container["volumeMounts"], [
            {"name": "profile", "mountPath": "/etc/kperf", "readOnly": True},
        ])
        script = container["args"][0]
        self.assertIn("--config /etc/kperf/load-profile.yaml", script)
        self.assertIn('--kubeconfig=""', script)
        self.assertIn('exit "$status"', script)
        for option in ("--rate", "--duration", "--total", "--client", "--conns"):
            self.assertNotIn(option, script)
        self.assertNotIn("azure.workload.identity/use", job["spec"]["template"]["metadata"]["labels"])
        role = next(item for item in documents if item["kind"] == "Role")
        self.assertEqual(role["rules"], [{"apiGroups": [""], "resources": ["pods"], "verbs": ["create"]}])
        self.assertFalse(any(item["kind"] == "ResourceQuota" for item in documents))


class ResultTests(unittest.TestCase):
    def test_result_extraction_with_diagnostics(self):
        data = report()
        self.assertEqual(benchmark.extract_result(
            "warning\n" + benchmark.BEGIN + "\n" + json.dumps(data) + "\n" + benchmark.END + "\n"
        ), data)

    def test_missing_repeated_or_malformed_result(self):
        for text in ("", "{}", benchmark.BEGIN + benchmark.END,
                     benchmark.BEGIN * 2 + "{}" + benchmark.END,
                     benchmark.END + "{}" + benchmark.BEGIN):
            with self.subTest(text=text), self.assertRaises(ValueError):
                benchmark.extract_result(text)

    def test_duration_total_zero_is_not_success_count(self):
        summary = benchmark.evaluate_result(report(), 600)
        self.assertEqual(summary["runner_reported_total"], 0)
        self.assertNotIn("successful_requests", summary)
        self.assertEqual(summary["sustained_rate_acceptance"], "not-evaluated")
        self.assertEqual(summary["configured_rate_per_second"], 600)

    def test_failures_missing_fields_empty_observations_and_short_duration(self):
        changes = [
            ("errorStats", {"429": 1}), ("duration", "9m59s"),
            ("duration", "invalid"), ("percentileLatencies", []),
            ("errorStats", {"429": -1}), ("errorStats", {"429": "1"}),
            ("total", "0"), ("totalReceivedBytes", -1),
            ("percentileLatencies", "invalid"), ("percentileLatencies", [[0.5, float("nan")]]),
            ("percentileLatencies", [[50, 0.1]]),
        ]
        for key, value in changes:
            data = report()
            data["aggregated"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                benchmark.evaluate_result(data, 600)
        data = report()
        del data["aggregated"]["duration"]
        with self.assertRaises(ValueError):
            benchmark.evaluate_result(data, 600)
        with self.assertRaises(ValueError):
            benchmark.evaluate_result({"aggregated": {}}, 600)

    def test_all_requests_failed_reports_errors_without_latency_field(self):
        data = report()
        for item in (data["perSpecResults"][0], data["aggregated"]):
            item.pop("percentileLatencies")
            item["errorStats"] = {"forbidden": 3}
        with self.assertRaisesRegex(ValueError, "request failures"):
            benchmark.evaluate_result(data, 600)

    def test_go_duration_units(self):
        self.assertEqual(benchmark.parse_duration("10m1.5s"), 601.5)
        self.assertAlmostEqual(benchmark.parse_duration("1ms2us3ns"), 0.001002003)
        for value in ("", "-1s", "600", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                benchmark.parse_duration(value)


class MutationTests(unittest.TestCase):
    def test_wi_mutation(self):
        benchmark.verify_pod(pod(), RUN_ID, "smoke", CLIENT_ID)

    def test_reject_bound_wrong_scheduler_missing_mutation_and_wrong_ownership(self):
        cases = []
        item = pod()
        item["spec"]["nodeName"] = "node"
        cases.append(item)
        item = pod()
        item["spec"]["schedulerName"] = "default-scheduler"
        cases.append(item)
        item = pod()
        item["spec"]["containers"][0]["env"] = []
        cases.append(item)
        item = pod()
        item["spec"]["volumes"] = []
        cases.append(item)
        item = pod()
        item["metadata"]["labels"]["benchmark-run"] = "other"
        cases.append(item)
        for item in cases:
            with self.subTest(pod=item), self.assertRaises(ValueError):
                benchmark.verify_pod(item, RUN_ID, "smoke", CLIENT_ID)


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.args = argparse.Namespace(
            run_id=RUN_ID, artifacts=Path(self.directory.name), phase="smoke",
            client_id=CLIENT_ID, image="image@sha256:test",
        )

    @patch("benchmark.subprocess.run")
    def test_failed_job_preserves_timestamps(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="created"),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({
                "status": {"conditions": [{"type": "Failed", "status": "True", "reason": "DeadlineExceeded"}]},
            })),
        ]
        with self.assertRaisesRegex(RuntimeError, "DeadlineExceeded"):
            benchmark.run_phase(self.args)
        timing = json.loads((self.args.artifacts / "smoke-timestamps.json").read_text())
        self.assertIn("orchestration_start", timing)
        self.assertIn("orchestration_end", timing)

    @patch("benchmark.time.monotonic", side_effect=[0, 241])
    @patch("benchmark.subprocess.run")
    def test_observation_deadline(self, run, _clock):
        run.return_value = subprocess.CompletedProcess([], 0, stdout='{"status":{}}')
        with self.assertRaises(TimeoutError):
            benchmark.run_phase(self.args)

    @patch("benchmark.subprocess.run")
    def test_successful_smoke_and_paginated_snapshot(self, run):
        data = report()
        data["aggregated"]["total"] = 3
        data["perSpecResults"][0]["total"] = 3
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="created"),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({
                "status": {"conditions": [{"type": "Complete", "status": "True"}]},
            })),
            subprocess.CompletedProcess([], 0, stdout=benchmark.BEGIN + json.dumps(data) + benchmark.END),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({
                "items": [pod()], "metadata": {"continue": "page2"},
            })),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({
                "items": [pod(), pod()], "metadata": {},
            })),
        ]
        benchmark.run_phase(self.args)
        summary = json.loads((self.args.artifacts / "smoke-summary.json").read_text())
        self.assertEqual(summary["retained_pod_count"], 3)
        self.assertIn("continue=page2", run.call_args.args[0][-1])

    @patch("benchmark.subprocess.run")
    def test_collection_surfaces_errors_and_stops_active_owned_jobs(self, run):
        def execute(command, **_kwargs):
            if "nodes" in command:
                raise subprocess.CalledProcessError(1, command, stderr="forbidden")
            value = "{}"
            if "jobs" in command:
                value = json.dumps({"items": [{
                    "metadata": {"name": "kperf-measure", "labels": {"benchmark-run": RUN_ID}},
                    "status": {"active": 1},
                }]})
            return subprocess.CompletedProcess(command, 0, stdout=value)
        run.side_effect = execute
        with self.assertRaisesRegex(RuntimeError, "collection incomplete"):
            benchmark.collect(self.args)
        self.assertTrue(any("patch" in call.args[0] for call in run.call_args_list))
        failures = json.loads((self.args.artifacts / "collection.json").read_text())["failures"]
        self.assertEqual(len(failures), 1)
        self.assertIn("forbidden", failures[0])


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.skus = [
            {"name": "Standard_D2_v4", "family": "Dv4", "restrictions": []},
            {"name": "Standard_D8s_v5", "family": "DSv5", "restrictions": []},
        ]
        self.usage = [
            {"name": {"value": family}, "limit": count + 1, "currentValue": 1}
            for family, count in (("cores", 30), ("Dv4", 6), ("DSv5", 24))
        ]

    def test_exact_available_quota_passes(self):
        preflight.verify(self.skus, self.usage)

    def test_missing_sku_missing_quota_or_insufficient_quota_fails(self):
        for skus, usage in ((self.skus[:1], self.usage), (self.skus, self.usage[:1])):
            with self.assertRaises(ValueError):
                preflight.verify(skus, usage)
        self.usage[2]["limit"] -= 1
        with self.assertRaises(ValueError):
            preflight.verify(self.skus, self.usage)

    def test_location_restriction_fails(self):
        self.skus[1]["restrictions"] = [{"type": "Location"}]
        with self.assertRaises(ValueError):
            preflight.verify(self.skus, self.usage)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = yaml.safe_load((benchmark.ROOT / "pipeline.yaml").read_text())
        cls.jobs = {job["job"]: job for job in cls.pipeline["jobs"]}

    def test_manual_only_and_storage_approval(self):
        self.assertEqual(self.pipeline["trigger"], "none")
        self.assertEqual(self.pipeline["pr"], "none")
        self.assertEqual(self.pipeline["parameters"], [{
            "name": "keep_cluster",
            "displayName": "Keep cluster and benchmark Pods after benchmark",
            "type": "boolean", "default": False,
        }])
        approval = self.jobs["storage_preflight"]
        self.assertEqual(approval["pool"], "server")
        self.assertEqual(approval["steps"][0]["inputs"]["onTimeout"], "reject")
        self.assertEqual(self.jobs["benchmark"]["dependsOn"], ["setup", "storage_preflight"])
        self.assertEqual(self.jobs["benchmark"]["variables"]["KUBECONFIG"],
                         "$(Agent.TempDirectory)/$(RUN_ID).kubeconfig")

    def test_cleanup_is_always_but_deletion_is_ownership_and_retention_gated(self):
        finalize = self.jobs["finalize"]
        self.assertEqual(finalize["condition"], "always()")
        deletion = next(step for step in finalize["steps"]
                        if step.get("displayName", "").startswith("Delete resource group"))
        for keep in (True, False):
            with self.subTest(keep_cluster=keep):
                condition = deletion["condition"].replace("${{ parameters.keep_cluster }}", str(keep))
                self.assertEqual(condition,
                    f"and(always(), eq(variables['OWNED_RESOURCE_GROUP'], 'true'), not({keep}))")
        benchmark_steps = self.jobs["benchmark"]["steps"]
        for name in ("Collect diagnostics and stop any active runner",
                     "Publish benchmark results and diagnostics"):
            step = next(step for step in benchmark_steps if step.get("displayName") == name)
            self.assertEqual(step["condition"], "always()")

    def test_generated_shell_syntax(self):
        scripts = []
        for job in self.jobs.values():
            for step in job["steps"]:
                script = step.get("bash", step.get("inputs", {}).get("inlineScript"))
                if script:
                    scripts.append(script)
        documents = list(yaml.safe_load_all((benchmark.ROOT / "workload.yaml").read_text()))
        job = next(item for item in documents if item["kind"] == "Job")
        scripts.append(job["spec"]["template"]["spec"]["containers"][0]["args"][0])
        for script in scripts:
            with self.subTest(script=script[:80]):
                subprocess.run(["bash", "-n"], input=script, text=True, check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
