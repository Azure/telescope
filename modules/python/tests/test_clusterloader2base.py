import os
import unittest
import tempfile
from clusterloader2.large_cluster.base import ClusterLoader2Base


class DummyArgsParser(ClusterLoader2Base.ArgsParser):
    # We don't need real CLI parsing for these tests; required abstract methods are no-ops.
    def __init__(self):
        super().__init__(description="dummy")

    def add_configure_args(self, parser):
        pass

    def add_validate_args(self, parser):
        pass

    def add_execute_args(self, parser):
        pass

    def add_collect_args(self, parser):
        pass


class DummyRunner(ClusterLoader2Base.Runner):
    # Minimal implementations to satisfy abstract interface.
    def configure(self, *_, **__):
        return {}

    def validate(self, *_, **__):
        return None

    def collect(self, *_, **__):
        return ""


class DummyConcrete(ClusterLoader2Base):
    def __init__(self):
        self._parser = DummyArgsParser()
        self._runner = DummyRunner()

    @property
    def args_parser(self) -> ClusterLoader2Base.ArgsParser:
        return self._parser

    @property
    def runner(self) -> ClusterLoader2Base.Runner:
        return self._runner


class TestClusterLoader2BaseHelpers(unittest.TestCase):

    def setUp(self):
        self.obj = DummyConcrete()

    def test_convert_config_to_str_basic_and_none_values(self):
        config = {
            "KEY1": "value1",
            "KEY2": 123,
            "KEY3": None,          # Should render as just the key name
            "KEY4": "another",     # Ensure ordering preserved
        }
        result = self.obj.convert_config_to_str(config)
        # Expected order is insertion order (Python 3.7+ guarantees dict order)
        expected = "KEY1: value1\nKEY2: 123\nKEY3\nKEY4: another"
        self.assertEqual(result, expected)

    def test_write_to_file_creates_parent_and_writes_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = os.path.join(tmpdir, "a", "b", "c")
            target_file = os.path.join(nested_dir, "output.txt")
            content = "LINE1\nLINE2"
            self.obj.write_to_file(target_file, content)

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

            status, suites = self.obj.parse_test_results(report_dir)
            self.assertEqual(status, "success")
            self.assertEqual(len(suites), 1)
            self.assertEqual(suites[0]["failures"], 0)
            self.assertEqual(suites[0]["tests"], 2)

    def test_parse_test_results_failure(self):
        with tempfile.TemporaryDirectory() as report_dir:
            junit_path = os.path.join(report_dir, "junit.xml")
            with open(junit_path, "w", encoding="utf-8") as f:
                f.write(self._make_junit_xml(tests=2, failures=1))

            status, suites = self.obj.parse_test_results(report_dir)
            self.assertEqual(status, "failure")
            self.assertEqual(suites[0]["failures"], 1)

    def test_parse_test_results_no_testsuites_raises(self):
        # Provide malformed xml that yields zero testsuites
        with tempfile.TemporaryDirectory() as report_dir:
            junit_path = os.path.join(report_dir, "junit.xml")
            with open(junit_path, "w", encoding="utf-8") as f:
                f.write("""<?xml version="1.0" encoding="UTF-8"?><root></root>""")

            with self.assertRaises(Exception) as ctx:
                _ = self.obj.parse_test_results(report_dir)
            self.assertIn("No testsuites found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
