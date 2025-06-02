#!/usr/bin/env python3
"""
Unit tests for crud.py module (collect functionality and node pool operations)
"""

import os
import json
import unittest
from unittest import mock
import tempfile
import shutil
from crud.main import collect_benchmark_results
from utils.common import get_env_vars


class TestCrud(unittest.TestCase):
    """Tests for the crud.py module (collect functionality and node pool operations)"""

    def setUp(self):
        """Set up test environment"""
        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()

        # Clean up any existing environment variables
        self.old_environ = dict(os.environ)

    def tearDown(self):
        """Clean up after tests"""
        # Remove temp directory
        shutil.rmtree(self.test_dir)

        # Restore environment
        os.environ.clear()
        os.environ.update(self.old_environ)

    def test_get_env_vars_success(self):
        """Test get_env_vars when variable exists"""
        # Setup
        os.environ["TEST_VAR"] = "test_value"

        # Execute
        result = get_env_vars("TEST_VAR")

        # Verify
        self.assertEqual(result, "test_value")

    def test_get_env_vars_missing(self):
        """Test get_env_vars when variable is missing"""
        # Setup - ensure the variable doesn't exist
        if "TEST_VAR" in os.environ:
            del os.environ["TEST_VAR"]

        # Execute and verify
        with self.assertRaises(RuntimeError) as context:
            get_env_vars("TEST_VAR")

        self.assertIn("Environment variable `TEST_VAR` not set", str(context.exception))

    def test_main_with_json_files(self):
        """Test main function with JSON files to process"""
        # Setup
        os.environ["RESULT_DIR"] = self.test_dir
        os.environ["RUN_URL"] = "http://example.com/run/123"
        os.environ["RUN_ID"] = "run-123"
        os.environ["REGION"] = "eastus"

        # Create test JSON files
        test_data1 = {
            "cluster_data": {"name": "test-cluster", "location": "eastus"},
            "operation_info": {
                "operation": "create_node_pool",
                "duration_seconds": 120.5,
                "success": True,
            },
        }

        with open(
            os.path.join(self.test_dir, "file1.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(test_data1, f)

        # Execute
        collect_benchmark_results()

        # Verify
        result_file = os.path.join(self.test_dir, "results.json")
        self.assertTrue(os.path.exists(result_file))

        # Read the combined results
        with open(result_file, "r", encoding="utf-8") as f:
            result = json.load(f)

        # Check result
        self.assertEqual(result["region"], "eastus")
        self.assertEqual(result["run_id"], "run-123")
        self.assertEqual(result["run_url"], "http://example.com/run/123")

        operation_info1 = json.loads(result["operation_info"])

        self.assertEqual(operation_info1["operation"], "create_node_pool")

    @mock.patch("crud.main.get_env_vars")
    def test_main_missing_env_vars(self, mock_get_env_vars):
        """Test main function when an environment variable is missing"""
        # Setup
        mock_get_env_vars.side_effect = RuntimeError(
            "Environment variable `TEST_VAR` not set"
        )

        # Execute and verify
        with self.assertRaises(RuntimeError):
            collect_benchmark_results()


if __name__ == "__main__":
    unittest.main()
