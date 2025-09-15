import os
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile

from clusterloader2.large_cluster.base import ClusterLoader2Base


class PerformTestArgsParser(ClusterLoader2Base.ArgsParser):
    def __init__(self):
        super().__init__(description="perform test")

    def add_configure_args(self, parser):
        parser.add_argument("cl2_override_file")

    def add_validate_args(self, parser):
        parser.add_argument("node_count", type=int)
        parser.add_argument("operation_timeout", type=int)

    def add_execute_args(self, parser):
        parser.add_argument("kubeconfig")
        parser.add_argument("cl2_image")
        parser.add_argument("cl2_config_dir")
        parser.add_argument("cl2_report_dir")
        parser.add_argument("provider")
        # keep optional to mirror real signature (default matches base Runner)
        parser.add_argument("--cl2_config_file", default="config.yaml")

    def add_collect_args(self, parser):
        parser.add_argument("cl2_report_dir")
        parser.add_argument("result_file")


class PerformTestRunner(ClusterLoader2Base.Runner):
    def __init__(self):
        self.configure_called = False
        self.configure_args = None
        self.validate_called = False
        self.validate_args = None
        self.execute_called = False
        self.execute_args = None
        self.collect_called = False
        self.collect_args = None

    # Return deterministic config dict for configure branch
    def configure(self, **kwargs):
        self.configure_called = True
        self.configure_args = kwargs
        return {
            "ALPHA": "one",
            "BETA": 2,
            "GAMMA": None,   # to test bare key formatting
        }

    def validate(self, **kwargs):
        self.validate_called = True
        self.validate_args = kwargs

    #pylint: disable=arguments-differ
    def execute(self, **kwargs):  # override to avoid real docker usage
        self.execute_called = True
        self.execute_args = kwargs

    def collect(self, **kwargs):
        self.collect_called = True
        self.collect_args = kwargs
        # Return content to be written to result_file
        return "COLLECTED_RESULTS_PAYLOAD"


class PerformTestConcrete(ClusterLoader2Base):
    def __init__(self):
        self._parser = PerformTestArgsParser()
        self._runner = PerformTestRunner()

    @property
    def args_parser(self) -> ClusterLoader2Base.ArgsParser:
        return self._parser

    @property
    def runner(self) -> ClusterLoader2Base.Runner:
        return self._runner


class TestClusterLoader2BaseHelpers(unittest.TestCase):

    def setUp(self):
        self.impl = PerformTestConcrete()

    def test_convert_config_to_str_basic_and_none_values(self):
        config = {
            "KEY1": "value1",
            "KEY2": 123,
            "KEY3": None,          # Should render as just the key name
            "KEY4": "another",     # Ensure ordering preserved
        }
        result = self.impl.convert_config_to_str(config)
        # Expected order is insertion order (Python 3.7+ guarantees dict order)
        expected = "KEY1: value1\nKEY2: 123\nKEY3\nKEY4: another"
        self.assertEqual(result, expected)

    def test_write_to_file_creates_parent_and_writes_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = os.path.join(tmpdir, "a", "b", "c")
            target_file = os.path.join(nested_dir, "output.txt")
            content = "LINE1\nLINE2"
            self.impl.write_to_file(target_file, content)

            self.assertTrue(os.path.exists(target_file))
            with open(target_file, "r", encoding="utf-8") as f:
                read_back = f.read()
            self.assertEqual(read_back, content)

    def _make_junit_xml(self, tests: int, failures: int, errors: int = 0) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="e2e.test.suite" tests="{tests}" failures="{failures}" errors="{errors}">
    <testcase name="case1" classname="suite" time="1.23"/>
    <testcase name="case2" classname="suite" time="0.50"/>
  </testsuite>
</testsuites>
"""

    def test_parse_test_results_success(self):
        with tempfile.TemporaryDirectory() as report_dir:
            junit_path = os.path.join(report_dir, "junit.xml")
            with open(junit_path, "w", encoding="utf-8") as f:
                f.write(self._make_junit_xml(tests=2, failures=0))

            status, suites = self.impl.parse_test_results(report_dir)
            self.assertEqual(status, "success")
            self.assertEqual(len(suites), 1)
            self.assertEqual(suites[0]["failures"], 0)
            self.assertEqual(suites[0]["tests"], 2)

    def test_parse_test_results_failure(self):
        with tempfile.TemporaryDirectory() as report_dir:
            junit_path = os.path.join(report_dir, "junit.xml")
            with open(junit_path, "w", encoding="utf-8") as f:
                f.write(self._make_junit_xml(tests=2, failures=1))

            status, suites = self.impl.parse_test_results(report_dir)
            self.assertEqual(status, "failure")
            self.assertEqual(suites[0]["failures"], 1)

    def test_parse_test_results_no_testsuites_raises(self):
        # Provide malformed xml that yields zero testsuites
        with tempfile.TemporaryDirectory() as report_dir:
            junit_path = os.path.join(report_dir, "junit.xml")
            with open(junit_path, "w", encoding="utf-8") as f:
                f.write("""<?xml version="1.0" encoding="UTF-8"?><root></root>""")

            with self.assertRaises(Exception) as ctx:
                _ = self.impl.parse_test_results(report_dir)
            self.assertIn("No testsuites found", str(ctx.exception))

    def test_perform_configure_writes_file(self):
        with tempfile.TemporaryDirectory() as tempd:
            override_path = Path(tempd) / "results" / "overrides.xml"
            argv = [
                "./module.py",
                "configure",
                str(override_path)
            ]
            with patch.object(sys, "argv", argv):
                self.impl.perform()
            self.assertTrue(self.impl.runner.configure_called, "configure() is not invoked")
            self.assertTrue(override_path.exists(), "Override file not created")
            content = override_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(content, [
                "ALPHA: one",
                "BETA: 2",
                "GAMMA"
            ])

    def test_perform_validate_calls_validate(self):
        argv = [
            "prog",
            "validate",
            "10",     # node_count
            "15",     # operation_timeout
        ]
        with patch.object(sys, "argv", argv):
            self.impl.perform()
        self.assertTrue(self.impl.runner.validate_called, "validate() not invoked")
        self.assertEqual(self.impl.runner.validate_args["node_count"], 10)
        self.assertEqual(self.impl.runner.validate_args["operation_timeout"], 15)

    def test_perform_execute_calls_execute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            argv = [
                "prog",
                "execute",
                str(Path(tmpdir) / "kubeconfig"),  # kubeconfig
                "cl2-image:latest",               # cl2_image
                str(Path(tmpdir) / "config"),      # cl2_config_dir
                str(Path(tmpdir) / "reports"),     # cl2_report_dir
                "azure",                           # provider
                "--cl2_config_file",
                "custom.yaml",
            ]
            with patch.object(sys, "argv", argv):
                self.impl.perform()

        self.assertTrue(self.impl.runner.execute_called, "execute() not invoked")
        self.assertEqual(self.impl.runner.execute_args["provider"], "azure")
        self.assertEqual(self.impl.runner.execute_args["cl2_config_file"], "custom.yaml")

    def _write_junit(self, directory: str, failures: int = 0):
        junit_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="suite" tests="1" failures="{failures}" errors="0">
    <testcase name="case1" classname="suite" time="0.1"/>
  </testsuite>
</testsuites>
"""
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "junit.xml"), "w", encoding="utf-8") as f:
            f.write(junit_xml)

    def test_perform_collect_writes_results_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            self._write_junit(str(report_dir), failures=0)
            result_file = Path(tmpdir) / "results" / "out.jsonl"

            argv = [
                "prog",
                "collect",
                str(report_dir),            # cl2_report_dir
                str(result_file),           # result_file
            ]
            with patch.object(sys, "argv", argv):
                self.impl.perform()

            self.assertTrue(self.impl.runner.collect_called, "collect() not invoked")
            self.assertTrue(result_file.exists(), "result file not written")
            written = result_file.read_text(encoding="utf-8")
            self.assertEqual(written, "COLLECTED_RESULTS_PAYLOAD")
            # Ensure test_status passed as success from junit (0 failures)
            self.assertEqual(self.impl.runner.collect_args["test_status"], "success")
            self.assertIn("test_results", self.impl.runner.collect_args)

    def test_perform_collect_failure_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            self._write_junit(str(report_dir), failures=2)
            result_file = Path(tmpdir) / "res" / "out.txt"

            argv = [
                "prog",
                "collect",
                str(report_dir),
                str(result_file),
            ]
            with patch.object(sys, "argv", argv):
                self.impl.perform()

            self.assertEqual(self.impl.runner.collect_args["test_status"], "failure")

if __name__ == "__main__":
    unittest.main()
