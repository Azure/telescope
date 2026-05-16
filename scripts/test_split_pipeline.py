#!/usr/bin/env python3
"""Tests for split_pipeline.py using file-based test cases.

Each test case is a folder under testdata/ containing:
  - config.yaml: { max_size_bytes: <int>, max_files: <int> (optional), expect_error: <str> (optional) }
  - source/pipeline.yaml: the input pipeline
  - expected/: the expected output files after splitting (not needed for error cases)
"""

import os
import shutil
import tempfile
import unittest

import yaml

from split_pipeline import PipelineSplitter, SplitError

TESTDATA_DIR = os.path.join(os.path.dirname(__file__), "testdata")


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def list_yaml_files(directory: str) -> list[str]:
    """List all .yaml files in a directory, returning relative names sorted."""
    files = []
    for name in os.listdir(directory):
        if name.endswith(".yaml"):
            files.append(name)
    return sorted(files)


class TestSplitPipelineFromFiles(unittest.TestCase):
    """Dynamically generated tests from testdata/ folders."""
    pass


def make_test(case_dir: str):
    """Create a test method for a given test case directory."""
    def test_method(self):
        config = load_yaml(os.path.join(case_dir, "config.yaml"))
        max_size = config["max_size_bytes"]
        max_files = config.get("max_files", 100)
        expect_error = config.get("expect_error")
        source_dir = os.path.join(case_dir, "source")
        expected_dir = os.path.join(case_dir, "expected")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy source files to temp dir
            for name in os.listdir(source_dir):
                shutil.copy2(os.path.join(source_dir, name), os.path.join(tmpdir, name))

            pipeline_path = os.path.join(tmpdir, "pipeline.yaml")
            splitter = PipelineSplitter(max_size_bytes=max_size, max_files=max_files)

            if expect_error:
                with self.assertRaises(SplitError) as ctx:
                    splitter.split(pipeline_path)
                self.assertIn(expect_error, str(ctx.exception))
                return

            splitter.split(pipeline_path)

            # Compare all expected files with actual output
            expected_files = list_yaml_files(expected_dir)
            actual_files = list_yaml_files(tmpdir)

            self.assertEqual(
                actual_files, expected_files,
                f"File list mismatch.\nExpected: {expected_files}\nActual: {actual_files}"
            )

            for name in expected_files:
                expected_data = load_yaml(os.path.join(expected_dir, name))
                actual_data = load_yaml(os.path.join(tmpdir, name))
                self.assertEqual(
                    actual_data, expected_data,
                    f"Content mismatch in {name}"
                )

    return test_method


# Discover test cases and add them to the test class
for case_name in sorted(os.listdir(TESTDATA_DIR)):
    case_dir = os.path.join(TESTDATA_DIR, case_name)
    if os.path.isdir(case_dir) and os.path.exists(os.path.join(case_dir, "config.yaml")):
        test_name = f"test_{case_name}"
        setattr(TestSplitPipelineFromFiles, test_name, make_test(case_dir))


if __name__ == "__main__":
    unittest.main()
