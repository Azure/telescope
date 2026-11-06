"""Exercise the generated CL2 polling script without a Kubernetes cluster."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class RunClusterLoader2Tests(unittest.TestCase):
    def run_poll(self, conditions, apply_status=0, job_error=False, pod_error=False):
        pipeline = yaml.safe_load(
            (ROOT / "kcl/example_pipeline/pipeline.yaml").read_text()
        )
        step = next(
            step
            for job in pipeline["jobs"]
            for step in job["steps"]
            if step.get("displayName") == "Run cluster loader 2"
        )
        script = step["inputs"]["inlineScript"]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls"
            error_file = Path(directory) / "kubectl_err"
            script = script.replace("$(Pipeline.Workspace)", directory)
            script = script.replace("/tmp/kubectl_err", str(error_file))
            setup = """
kubectl() {
  echo "$1 $2" >> "$CALLS"
  case "$1 $2" in
    "create namespace") return 0 ;;
    "apply -f") return "$APPLY_STATUS" ;;
    "get job")
      if [ "$JOB_ERROR" = 1 ]; then
        echo "Job unavailable" >&2
        return 1
      fi
      if [ -f "$CALLS.polled" ]; then
        printf '%s\\n' "$NEXT_CONDITIONS"
      else
        touch "$CALLS.polled"
        printf '%s\\n' "$CONDITIONS"
      fi
      ;;
    "get pods") return "$POD_ERROR" ;;
    *) return 99 ;;
  esac
}
sleep() { :; }
"""
            result = subprocess.run(
                ["bash", "-c", setup + script],
                env={
                    **os.environ,
                    "CALLS": str(log),
                    "CONDITIONS": conditions,
                    "NEXT_CONDITIONS": "Complete",
                    "APPLY_STATUS": str(apply_status),
                    "JOB_ERROR": str(int(job_error)),
                    "POD_ERROR": str(int(pod_error)),
                },
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return result, log.read_text().splitlines()

    def test_complete_without_pods(self):
        result, calls = self.run_poll("Complete")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("get pods", calls)

    def test_failed_without_pods(self):
        result, calls = self.run_poll("Failed BackoffLimitExceeded Retry limit reached")
        self.assertEqual(result.returncode, 1)
        self.assertIn("BackoffLimitExceeded Retry limit reached", result.stdout)
        self.assertNotIn("get pods", calls)

    def test_nonterminal_empty_pods_keeps_polling(self):
        result, calls = self.run_poll("")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls.count("get job"), 2)
        self.assertEqual(calls.count("get pods"), 1)

    def test_failure_target_is_not_terminal(self):
        result, calls = self.run_poll("FailureTarget BackoffLimitExceeded")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls.count("get job"), 2)

    def test_job_read_errors_are_bounded(self):
        result, calls = self.run_poll("", job_error=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls.count("get job"), 20)
        self.assertNotIn("get pods", calls)

    def test_apply_failure_stops_before_polling(self):
        result, calls = self.run_poll("", apply_status=1)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("get job", calls)

    def test_pod_listing_failure_does_not_override_job_status(self):
        result, calls = self.run_poll("", pod_error=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Unable to list cl2 pods", result.stdout)
        self.assertEqual(calls.count("get job"), 2)


if __name__ == "__main__":
    unittest.main()
