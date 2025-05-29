#!/usr/bin/env python3
"""
Unit tests for collect.py module
"""

import os
import json
import sys
import unittest
from unittest import mock
import tempfile
import shutil
from k8s.collect import get_env_vars, create_result_dir, main
# Add the python directory to the path to import modules correctly
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


class TestCollect(unittest.TestCase):
    """Tests for the collect.py module"""

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

    def test_create_result_dir_new(self):
        """Test create_result_dir when directory doesn't exist"""
        # Setup
        test_path = os.path.join(self.test_dir, "new_dir")
        self.assertFalse(os.path.exists(test_path))

        # Execute
        create_result_dir(test_path)

        # Verify
        self.assertTrue(os.path.exists(test_path))
        self.assertTrue(os.path.isdir(test_path))

    def test_create_result_dir_existing(self):
        """Test create_result_dir when directory already exists"""
        # Setup
        test_path = os.path.join(self.test_dir, "existing_dir")
        os.makedirs(test_path)
        self.assertTrue(os.path.exists(test_path))

        # Execute
        create_result_dir(test_path)

        # Verify - should still exist and be a directory
        self.assertTrue(os.path.exists(test_path))
        self.assertTrue(os.path.isdir(test_path))

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
        main()

        # Verify
        result_file = os.path.join(self.test_dir, "results.json")
        self.assertTrue(os.path.exists(result_file))

        # Read the combined results
        with open(result_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Split content by line and parse JSON
        lines = content.strip().split("\n")
        self.assertEqual(len(lines), 1)

        result = json.loads(lines[0])

        # Check result
        self.assertEqual(result["region"], "eastus")
        self.assertEqual(result["run_id"], "run-123")
        self.assertEqual(result["run_url"], "http://example.com/run/123")

        operation_info1 = json.loads(result["operation_info"])

        self.assertEqual(operation_info1["operation"], "create_node_pool")

    @mock.patch("k8s.collect.get_env_vars")
    def test_main_missing_env_vars(self, mock_get_env_vars):
        """Test main function when an environment variable is missing"""
        # Setup
        mock_get_env_vars.side_effect = RuntimeError(
            "Environment variable `TEST_VAR` not set"
        )

        # Execute and verify
        with self.assertRaises(RuntimeError):
            main()


if __name__ == "__main__":
    unittest.main()
