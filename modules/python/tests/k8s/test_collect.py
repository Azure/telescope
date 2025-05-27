#!/usr/bin/env python3
"""
Unit tests for collect.py module
"""
import os
import json
import unittest
from unittest import mock
from pathlib import Path
import tempfile
import shutil

import sys

# Add the python directory to the path to import modules correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from k8s.collect import get_env_vars, create_result_dir, main

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
        os.environ['TEST_VAR'] = 'test_value'
        
        # Execute
        result = get_env_vars('TEST_VAR')
        
        # Verify
        self.assertEqual(result, 'test_value')

    def test_get_env_vars_missing(self):
        """Test get_env_vars when variable is missing"""
        # Setup - ensure the variable doesn't exist
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']
        
        # Execute and verify
        with self.assertRaises(RuntimeError) as context:
            get_env_vars('TEST_VAR')
        
        self.assertIn('Environment variable `TEST_VAR` not set', str(context.exception))

    def test_create_result_dir_new(self):
        """Test create_result_dir when directory doesn't exist"""
        # Setup
        test_path = os.path.join(self.test_dir, 'new_dir')
        self.assertFalse(os.path.exists(test_path))
        
        # Execute
        create_result_dir(test_path)
        
        # Verify
        self.assertTrue(os.path.exists(test_path))
        self.assertTrue(os.path.isdir(test_path))

    def test_create_result_dir_existing(self):
        """Test create_result_dir when directory already exists"""
        # Setup
        test_path = os.path.join(self.test_dir, 'existing_dir')
        os.makedirs(test_path)
        self.assertTrue(os.path.exists(test_path))
        
        # Execute
        create_result_dir(test_path)
        
        # Verify - should still exist and be a directory
        self.assertTrue(os.path.exists(test_path))
        self.assertTrue(os.path.isdir(test_path))

    @mock.patch('k8s.collect.glob.glob')
    @mock.patch('k8s.collect.logger')
    def test_main_no_json_files(self, mock_logger, mock_glob):
        """Test main function when no JSON files are found"""
        # Setup
        os.environ['RESULT_DIR'] = self.test_dir
        os.environ['RUN_URL'] = 'http://example.com/run/123'
        os.environ['RUN_ID'] = 'run-123'
        os.environ['REGION'] = 'eastus'
        
        mock_glob.return_value = []  # No JSON files found
        
        # Execute
        main()
        
        # Verify
        mock_glob.assert_called_once_with(f"{self.test_dir}/*.json")
        mock_logger.info.assert_any_call(f"environment variable RESULT_DIR: `{self.test_dir}`")
        mock_logger.info.assert_any_call(f"environment variable RUN_URL: `http://example.com/run/123`")
        
        # Ensure results.json wasn't created
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, 'results.json')))

    def test_main_with_json_files(self):
        """Test main function with JSON files to process"""
        # Setup
        os.environ['RESULT_DIR'] = self.test_dir
        os.environ['RUN_URL'] = 'http://example.com/run/123'
        os.environ['RUN_ID'] = 'run-123'
        os.environ['REGION'] = 'eastus'
        
        # Create test JSON files
        test_data1 = {
            "cluster_data": {
                "name": "test-cluster",
                "location": "eastus"
            },
            "operation_info": {
                "operation": "create_node_pool",
                "duration_seconds": 120.5,
                "success": True
            }
        }
        
        test_data2 = {
            "cluster_data": {
                "name": "test-cluster",
                "location": "eastus"
            },
            "operation_info": {
                "operation": "scale_up",
                "duration_seconds": 85.3,
                "success": True
            }
        }
        
        with open(os.path.join(self.test_dir, 'file1.json'), 'w') as f:
            json.dump(test_data1, f)
            
        with open(os.path.join(self.test_dir, 'file2.json'), 'w') as f:
            json.dump(test_data2, f)
        
        # Execute
        main()
        
        # Verify
        result_file = os.path.join(self.test_dir, 'results.json')
        self.assertTrue(os.path.exists(result_file))
        
        # Read the combined results
        with open(result_file, 'r') as f:
            content = f.read()
        
        # Split content by line and parse JSON
        lines = content.strip().split('\n')
        self.assertEqual(len(lines), 2)  # Should have 2 JSON objects
        
        result1 = json.loads(lines[0])
        result2 = json.loads(lines[1])
        
        # Check first result
        self.assertEqual(result1['region'], 'eastus')
        self.assertEqual(result1['run_id'], 'run-123')
        self.assertEqual(result1['run_url'], 'http://example.com/run/123')
        
        # Parse the JSON strings
        cluster_info1 = json.loads(result1['cluster_info'])
        operation_info1 = json.loads(result1['operation_info'])
        
        self.assertEqual(cluster_info1['name'], 'test-cluster')
        self.assertEqual(operation_info1['operation'], 'create_node_pool')
        
        # Check second result
        operation_info2 = json.loads(result2['operation_info'])
        self.assertEqual(operation_info2['operation'], 'scale_up')

    @mock.patch('k8s.collect.get_env_vars')
    def test_main_missing_env_vars(self, mock_get_env_vars):
        """Test main function when an environment variable is missing"""
        # Setup
        mock_get_env_vars.side_effect = RuntimeError("Environment variable `TEST_VAR` not set")
        
        # Execute and verify
        with self.assertRaises(RuntimeError):
            main()


if __name__ == '__main__':
    unittest.main()
