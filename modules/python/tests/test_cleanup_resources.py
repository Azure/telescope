import os
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml


@unittest.skipUnless(shutil.which("bash"), "Bash is required to test pipeline cleanup")
class TestCleanupResources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[3] / "steps" / "cleanup-resources.yml"
        with path.open(encoding="utf-8") as handle:
            template = yaml.safe_load(handle)
        cls.script = next(
            step["script"] for step in template["steps"]
            if step.get("displayName") == "Destroy Resource Group"
        )

    def run_cleanup(self, mode, skip=False):
        mock_az = """
deleted=false
az() {
  echo "az $*" >&2
  case "$1 $2" in
    "group exists")
      if [[ "$MODE" == "lookup_error" || ("$MODE" == "poll_error" && "$deleted" == "true") ]]; then
        echo "AuthorizationFailed" >&2
        return 9
      fi
      if [[ "$MODE" == "missing" || "$deleted" == "true" ]]; then
        echo false
      else
        echo true
      fi
      ;;
    "group delete")
      if [[ "$MODE" == "delete_error" ]]; then
        echo "AuthorizationFailed" >&2
        return 7
      fi
      deleted=true
      if [[ "$MODE" == "race" ]]; then
        echo "ResourceGroupNotFound" >&2
        return 3
      fi
      ;;
    *) return 99 ;;
  esac
}
"""
        return subprocess.run(
            [shutil.which("bash"), "--noprofile", "--norc"],
            input=mock_az + self.script,
            env={
                **os.environ,
                "MODE": mode,
                "RUN_ID": "test-run",
                "BUILD_REASON": "Manual",
                "SKIP_RESOURCE_DELETION": str(skip).lower(),
            },
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_already_deleted_group_is_success(self):
        result = self.run_cleanup("missing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already deleted", result.stdout)
        self.assertNotIn("az group delete", result.stderr)

    def test_existing_group_is_deleted(self):
        result = self.run_cleanup("existing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("az group delete --name test-run --yes --no-wait", result.stderr)
        self.assertIn("deleted successfully", result.stdout)

    def test_concurrent_deletion_is_success(self):
        result = self.run_cleanup("race")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deleted concurrently", result.stdout)

    def test_azure_errors_are_not_treated_as_deletion(self):
        for mode, exit_code in (("lookup_error", 9), ("delete_error", 7), ("poll_error", 9)):
            with self.subTest(mode=mode):
                result = self.run_cleanup(mode)
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertIn("AuthorizationFailed", result.stderr)
                self.assertNotIn("deleted successfully", result.stdout)

    def test_manual_skip_does_not_call_azure(self):
        result = self.run_cleanup("existing", skip=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("az group", result.stderr)
