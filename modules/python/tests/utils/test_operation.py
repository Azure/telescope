#!/usr/bin/env python3
"""
Unit tests for Operation and OperationContext classes
"""

import json
import os
import tempfile
import unittest
import shutil
from datetime import datetime, timezone
from unittest import mock

from utils.operation import Operation, OperationContext


class TestOperation(unittest.TestCase):
    """Tests for the Operation class"""

    def setUp(self):
        """Set up test environment"""
        self.test_operation = Operation("test_operation")

    def test_operation_initialization(self):
        """Test Operation initialization with default values"""
        op = Operation("test_op")

        self.assertEqual(op.name, "test_op")
        self.assertIsNone(op.start_timestamp)
        self.assertIsNone(op.end_timestamp)
        self.assertIsNone(op.duration)
        self.assertEqual(op.unit, "seconds")
        self.assertTrue(op.success)
        self.assertIsNone(op.error_message)
        self.assertIsNone(op.error_traceback)
        self.assertEqual(op.metadata, {})

    def test_operation_initialization_with_metadata(self):
        """Test Operation initialization with metadata"""
        metadata = {"key": "value", "count": 42}
        op = Operation("test_op", metadata)

        self.assertEqual(op.name, "test_op")
        self.assertEqual(op.metadata, metadata)

    @mock.patch("utils.operation.datetime")
    def test_operation_start(self, mock_datetime):
        """Test operation start method"""
        # Setup
        mock_now = mock.MagicMock()
        mock_now.strftime.return_value = "2023-01-01T12:00:00Z"
        mock_datetime.now.return_value = mock_now

        # Execute
        self.test_operation.start()

        # Verify
        mock_datetime.now.assert_called_once_with(timezone.utc)
        mock_now.strftime.assert_called_once_with("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(self.test_operation.start_timestamp, "2023-01-01T12:00:00Z")

    @mock.patch("utils.operation.datetime")
    def test_operation_end_success(self, mock_datetime):
        """Test operation end method with success"""
        # Setup
        mock_now = mock.MagicMock()
        mock_now.strftime.side_effect = ["2023-01-01T12:00:00Z", "2023-01-01T12:01:30Z"]
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat.side_effect = [
            datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2023, 1, 1, 12, 1, 30, tzinfo=timezone.utc),
        ]

        # Start and end the operation
        self.test_operation.start()
        self.test_operation.end(success=True)

        # Verify
        self.assertEqual(self.test_operation.end_timestamp, "2023-01-01T12:01:30Z")
        self.assertEqual(self.test_operation.duration, 90.0)  # 1 minute 30 seconds
        self.assertTrue(self.test_operation.success)
        self.assertIsNone(self.test_operation.error_message)

    @mock.patch("utils.operation.datetime")
    def test_operation_end_with_error(self, mock_datetime):
        """Test operation end method with error"""
        # Setup
        mock_now = mock.MagicMock()
        mock_now.strftime.side_effect = ["2023-01-01T12:00:00Z", "2023-01-01T12:01:30Z"]
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat.side_effect = [
            datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2023, 1, 1, 12, 1, 30, tzinfo=timezone.utc),
        ]

        test_error = Exception("Test error")

        # Start and end the operation with error
        self.test_operation.start()
        self.test_operation.end(success=False, error=test_error)

        # Verify
        self.assertEqual(self.test_operation.end_timestamp, "2023-01-01T12:01:30Z")
        self.assertEqual(self.test_operation.duration, 90.0)
        self.assertFalse(self.test_operation.success)
        self.assertEqual(self.test_operation.error_message, "Test error")
        self.assertIsNotNone(self.test_operation.error_traceback)

    @mock.patch("utils.operation.datetime")
    def test_operation_end_duration_calculation_error(self, mock_datetime):
        """Test operation end when duration calculation fails"""
        # Setup
        mock_now = mock.MagicMock()
        mock_now.strftime.side_effect = ["2023-01-01T12:00:00Z", "2023-01-01T12:01:30Z"]
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat.side_effect = Exception("Parsing error")

        # Start and end the operation
        self.test_operation.start()
        self.test_operation.end()

        # Verify duration is None when calculation fails
        self.assertIsNone(self.test_operation.duration)
        self.assertTrue(self.test_operation.success)

    def test_set_error(self):
        """Test set_error method"""
        # Setup
        test_error = ValueError("Test error message")

        # Execute
        self.test_operation.set_error(test_error)

        # Verify
        self.assertFalse(self.test_operation.success)
        self.assertEqual(self.test_operation.error_message, "Test error message")
        self.assertIsNotNone(self.test_operation.error_traceback)

    def test_add_metadata(self):
        """Test add_metadata method"""
        # Execute
        self.test_operation.add_metadata("key1", "value1")
        self.test_operation.add_metadata("key2", 42)
        self.test_operation.add_metadata("key3", {"nested": "dict"})

        # Verify
        expected_metadata = {"key1": "value1", "key2": 42, "key3": {"nested": "dict"}}
        self.assertEqual(self.test_operation.metadata, expected_metadata)

    def test_to_dict(self):
        """Test to_dict method"""
        # Setup
        self.test_operation.start_timestamp = "2023-01-01T12:00:00Z"
        self.test_operation.end_timestamp = "2023-01-01T12:01:30Z"
        self.test_operation.duration = 90.0
        self.test_operation.success = True
        self.test_operation.add_metadata("test_key", "test_value")

        # Execute
        result = self.test_operation.to_dict()

        # Verify
        expected = {
            "name": "test_operation",
            "start_timestamp": "2023-01-01T12:00:00Z",
            "end_timestamp": "2023-01-01T12:01:30Z",
            "duration": 90.0,
            "success": True,
            "error_message": None,
            "error_traceback": None,
            "metadata": {"test_key": "test_value"},
            "unit": "seconds",
        }
        self.assertEqual(result, expected)

    def test_to_json(self):
        """Test to_json method"""
        # Setup
        self.test_operation.start_timestamp = "2023-01-01T12:00:00Z"
        self.test_operation.end_timestamp = "2023-01-01T12:01:30Z"
        self.test_operation.duration = 90.0
        self.test_operation.add_metadata("test_key", "test_value")

        # Execute
        result = self.test_operation.to_json()

        # Verify
        parsed_result = json.loads(result)
        self.assertEqual(parsed_result["name"], "test_operation")
        self.assertEqual(parsed_result["duration"], 90.0)
        self.assertEqual(parsed_result["metadata"]["test_key"], "test_value")

    def test_save_to_file(self):
        """Test save_to_file method"""
        # Setup
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "test_operation.json")
            self.test_operation.start_timestamp = "2023-01-01T12:00:00Z"
            self.test_operation.end_timestamp = "2023-01-01T12:01:30Z"
            self.test_operation.duration = 90.0

            # Execute
            self.test_operation.save_to_file(file_path)

            # Verify
            self.assertTrue(os.path.exists(file_path))
            with open(file_path, "r", encoding="utf-8") as f:
                saved_data = json.load(f)

            self.assertIn("operation_info", saved_data)
            operation_info = saved_data["operation_info"]  # It's now a dict, not a JSON string
            self.assertEqual(operation_info["name"], "test_operation")
            self.assertEqual(operation_info["duration"], 90.0)

    def test_save_to_file_creates_directory(self):
        """Test save_to_file creates directory if it doesn't exist"""
        # Setup
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_dir = os.path.join(temp_dir, "nested", "directory")
            file_path = os.path.join(nested_dir, "test_operation.json")

            # Verify directory doesn't exist
            self.assertFalse(os.path.exists(nested_dir))

            # Execute
            self.test_operation.save_to_file(file_path)

            # Verify directory was created and file exists
            self.assertTrue(os.path.exists(nested_dir))
            self.assertTrue(os.path.exists(file_path))

    def test_str_representation_success(self):
        """Test __str__ method for successful operation"""
        # Setup
        self.test_operation.duration = 45.67
        self.test_operation.success = True

        # Execute
        result = str(self.test_operation)

        # Verify
        expected = "Operation: test_operation [SUCCESS] (Duration: 45.67s)"
        self.assertEqual(result, expected)

    def test_str_representation_failure(self):
        """Test __str__ method for failed operation"""
        # Setup
        self.test_operation.duration = 30.5
        self.test_operation.success = False
        self.test_operation.error_message = "Something went wrong"

        # Execute
        result = str(self.test_operation)

        # Verify
        expected = "Operation: test_operation [FAILED] (Duration: 30.50s)\nError: Something went wrong"
        self.assertEqual(result, expected)

    def test_str_representation_no_duration(self):
        """Test __str__ method when duration is None"""
        # Setup
        self.test_operation.duration = None
        self.test_operation.success = True

        # Execute
        result = str(self.test_operation)

        # Verify
        expected = "Operation: test_operation [SUCCESS] (Duration: N/A)"
        self.assertEqual(result, expected)


class TestOperationContext(unittest.TestCase):
    """Tests for the OperationContext class"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests"""

        shutil.rmtree(self.temp_dir)

    def test_operation_context_initialization(self):
        """Test OperationContext initialization"""
        metadata = {"key": "value"}
        context = OperationContext("test_op", "azure", metadata, self.temp_dir)

        self.assertEqual(context.operation.name, "test_op")
        self.assertEqual(context.operation.metadata, metadata)
        self.assertEqual(context.result_dir, self.temp_dir)
        self.assertEqual(context.cloud, "azure")

    @mock.patch("utils.operation.datetime")
    def test_operation_context_success(self, mock_datetime):
        """Test OperationContext with successful operation"""
        # Setup
        mock_now = mock.MagicMock()
        mock_now.strftime.side_effect = [
            "2023-01-01T12:00:00Z",  # start
            "2023-01-01T12:01:00Z",  # end
            "20230101_120100",  # filename timestamp
        ]
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat.side_effect = [
            datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2023, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
        ]

        # Execute
        with OperationContext(
            "test_operation", "azure", result_dir=self.temp_dir
        ) as op:
            op.add_metadata("test_key", "test_value")

        # Verify
        self.assertTrue(op.success)
        self.assertIsNotNone(op.start_timestamp)
        self.assertIsNotNone(op.end_timestamp)
        self.assertEqual(op.duration, 60.0)  # 1 minute

        # Check file was saved
        files = os.listdir(self.temp_dir)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].startswith("azure_test_operation_"))
        self.assertTrue(files[0].endswith(".json"))

    @mock.patch("utils.operation.datetime")
    def test_operation_context_failure(self, mock_datetime):
        """Test OperationContext with failed operation"""
        # Setup
        mock_now = mock.MagicMock()
        mock_now.strftime.side_effect = [
            "2023-01-01T12:00:00Z",  # start
            "2023-01-01T12:01:00Z",  # end
            "20230101_120100",  # filename timestamp
        ]
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat.side_effect = [
            datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2023, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
        ]

        # Execute with exception
        try:
            with OperationContext(
                "test_operation", "gcp", result_dir=self.temp_dir
            ) as op:
                op.add_metadata("test_key", "test_value")
                raise ValueError("Test error")
        except ValueError:
            pass  # Expected exception

        # Verify
        self.assertFalse(op.success)
        self.assertEqual(op.error_message, "Test error")
        self.assertIsNotNone(op.error_traceback)

        # Check file was saved
        files = os.listdir(self.temp_dir)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].startswith("gcp_test_operation_"))

    def test_operation_context_no_result_dir(self):
        """Test OperationContext without result directory"""
        # Execute
        with OperationContext("test_operation", "aws") as op:
            op.add_metadata("test_key", "test_value")

        # Verify operation completed but no file saved
        self.assertTrue(op.success)
        self.assertEqual(len(os.listdir(self.temp_dir)), 0)

    @mock.patch("utils.operation.datetime")
    @mock.patch("utils.operation.logger")
    def test_operation_context_save_error(self, mock_logger, mock_datetime):
        """Test OperationContext when file saving fails"""
        # Setup
        mock_now = mock.MagicMock()
        mock_now.strftime.side_effect = [
            "2023-01-01T12:00:00Z",  # start
            "2023-01-01T12:01:00Z",  # end
            "20230101_120100",  # filename timestamp
        ]
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat.side_effect = [
            datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2023, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
        ]

        # Use invalid directory to cause save error
        invalid_dir = "/invalid/path/that/does/not/exist"

        # Execute
        with OperationContext("test_operation", "azure", result_dir=invalid_dir) as op:
            pass

        # Verify operation completed but warning was logged
        self.assertTrue(op.success)
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        self.assertIn("Failed to save operation data", warning_call)

    def test_operation_context_special_characters_in_name(self):
        """Test OperationContext with special characters in operation name"""
        # Setup
        special_name = "test/operation:with\\special chars"

        # Execute
        with OperationContext(special_name, "azure", result_dir=self.temp_dir) as op:
            # Verify operation is accessible
            self.assertEqual(op.name, special_name)

        # Verify file was created with cleaned name
        files = os.listdir(self.temp_dir)
        self.assertEqual(len(files), 1)
        filename = files[0]

        # Special characters should be replaced with underscores
        self.assertIn("test_operation_with_special_chars", filename)
        self.assertTrue(filename.startswith("azure_"))
        self.assertTrue(filename.endswith(".json"))

    @mock.patch("utils.operation.datetime")
    def test_operation_context_metadata_persistence(self, mock_datetime):
        """Test that metadata is properly saved in OperationContext"""
        # Setup
        mock_now = mock.MagicMock()
        mock_now.strftime.side_effect = [
            "2023-01-01T12:00:00Z",  # start
            "2023-01-01T12:01:00Z",  # end
            "20230101_120100",  # filename timestamp
        ]
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat.side_effect = [
            datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2023, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
        ]

        initial_metadata = {"initial_key": "initial_value"}

        # Execute
        with OperationContext(
            "test_operation", "aws", initial_metadata, self.temp_dir
        ) as op:
            op.add_metadata("added_key", "added_value")
            op.add_metadata("complex_data", {"nested": {"data": [1, 2, 3]}})

        # Verify metadata in saved file
        files = os.listdir(self.temp_dir)
        with open(os.path.join(self.temp_dir, files[0]), "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        operation_info = saved_data["operation_info"]  # It's now a dict, not a JSON string
        metadata = operation_info["metadata"]

        self.assertEqual(metadata["initial_key"], "initial_value")
        self.assertEqual(metadata["added_key"], "added_value")
        self.assertEqual(metadata["complex_data"], {"nested": {"data": [1, 2, 3]}})


if __name__ == "__main__":
    unittest.main()
