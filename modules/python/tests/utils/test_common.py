import unittest
import os
import json
import tempfile
from utils.common import extract_parameter, save_info_to_file


class TestCommon(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
