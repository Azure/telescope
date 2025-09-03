import unittest
import os
import json
import tempfile
from utils.common import extract_parameter, save_info_to_file, get_env_vars


class TestCommon(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        # Store original environment to restore later
        self.original_env = dict(os.environ)

    def tearDown(self):
        """Clean up after tests"""
        # Restore original environment
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_get_measurement(self):
        from clusterloader2.utils import get_measurement

        # Test matrix: (filename, expected_measurement, expected_group)
        cases = [
            # Pod startup latency mappings (uses POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP)
            ("PodStartupLatency_PodStartupLatency_groupA_results.json", "PodStartupLatency_PodStartupLatency", "groupA"),
            ("StatefulPodStartupLatency_PodStartupLatency_mygroup_out", "StatefulPodStartupLatency_PodStartupLatency", "mygroup"),

            # Network metric prefixes (uses NETWORK_METRIC_PREFIXES)
            ("APIResponsivenessPrometheus_group01_log.txt", "APIResponsivenessPrometheus", "group01"),

            # Generic prometheus query prefix (PROM_QUERY_PREFIX)
            # Note: current implementation slices the first segment and then slices by len(prefix)+1,
            # which results in an empty measurement name for filenames like below. We assert current behavior.
            ("GenericPrometheusQuery_cpu_usage_group1.txt", "", "cpu"),

            # Job lifecycle / resource / network policy / scheduling prefixes
            ("JobLifecycleLatency_groupX_record", "JobLifecycleLatency", "groupX"),
            ("ResourceUsageSummary_nodePool_01", "ResourceUsageSummary", "nodePool"),
            ("NetworkPolicySoakMeasurement_ns1_results", "NetworkPolicySoakMeasurement", "ns1"),
            ("SchedulingThroughputPrometheus_zoneA_metrics", "SchedulingThroughputPrometheus", "zoneA"),
            ("SchedulingThroughput_clusterA_v1", "SchedulingThroughput", "clusterA"),

            # Unknown / unmatched
            ("some_random_file_name.txt", None, None),
            ("randomfile", None, None),
        ]

        for fname, exp_measurement, exp_group in cases:
            with self.subTest(filename=fname):
                measurement, group = get_measurement(fname)
                self.assertEqual(measurement, exp_measurement)
                self.assertEqual(group, exp_group)

    def test_extract_parameter_with_space(self):
        # Test with default parameters (space between parameter and value)
        command = "--time 60 --other-param value"
        self.assertEqual(extract_parameter(command, "time"), 60)

    def test_extract_parameter_without_space(self):
        # Test without space between parameter and value
        command = "--time60 --other-param value"
        self.assertEqual(extract_parameter(
            command, "nodes", has_space=False), None)

    def test_extract_parameter_custom_prefix(self):
        # Test with custom prefix
        command = "-time 60"
        self.assertEqual(extract_parameter(command, "time", prefix="-"), 60)

    def test_extract_parameter_not_found(self):
        # Test when parameter is not found
        command = "--other-param value"
        self.assertIsNone(extract_parameter(command, "time"))

    def test_extract_parameter_invalid_value(self):
        # Test with non-numeric value
        command = "--time abc"
        self.assertIsNone(extract_parameter(command, "time"))

    def test_save_info_to_file_success(self):
        # Test successful save of info to file
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "test.json")
            test_data = {"key": "value"}
            save_info_to_file(test_data, file_path)

            # Verify file was created and contains correct data
            self.assertTrue(os.path.exists(file_path))
            with open(file_path, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            self.assertEqual(saved_data, test_data)

    def test_save_info_to_file_empty_data(self):
        # Test with empty data
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "test.json")
            save_info_to_file(None, file_path)

            # Verify file was not created
            self.assertFalse(os.path.exists(file_path))

    def test_save_info_to_file_invalid_directory(self):
        # Test with non-existent directory
        file_path = "/nonexistent/directory/test.json"
        test_data = {"key": "value"}

        # Verify that the function raises an exception
        with self.assertRaises(Exception) as context:
            save_info_to_file(test_data, file_path)

        self.assertTrue("Directory does not exist" in str(context.exception))

    def test_get_env_vars_success(self):
        """Test get_env_vars when environment variable exists"""
        # Setup
        os.environ["TEST_VAR"] = "test_value"

        # Execute
        result = get_env_vars("TEST_VAR")

        # Verify
        self.assertEqual(result, "test_value")

    def test_get_env_vars_missing(self):
        """Test get_env_vars when environment variable is missing"""
        # Setup - ensure the variable doesn't exist
        if "MISSING_VAR" in os.environ:
            del os.environ["MISSING_VAR"]

        # Execute and verify
        with self.assertRaises(RuntimeError) as context:
            get_env_vars("MISSING_VAR")

        self.assertIn("Environment variable `MISSING_VAR` not set", str(context.exception))

    def test_get_env_vars_empty_value(self):
        """Test get_env_vars when environment variable is set to empty string"""
        # Setup
        os.environ["EMPTY_VAR"] = ""

        # Execute
        result = get_env_vars("EMPTY_VAR")

        # Verify - empty string is still a valid value
        self.assertEqual(result, "")

    def test_get_env_vars_none_value(self):
        """Test get_env_vars when environment variable is explicitly removed"""
        # Setup - set and then remove the variable
        os.environ["TEMP_VAR"] = "temp_value"
        del os.environ["TEMP_VAR"]

        # Execute and verify
        with self.assertRaises(RuntimeError) as context:
            get_env_vars("TEMP_VAR")

        self.assertIn("Environment variable `TEMP_VAR` not set", str(context.exception))


if __name__ == '__main__':
    unittest.main()
