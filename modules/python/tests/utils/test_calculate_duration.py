#!/usr/bin/env python3
"""
Unit tests for calculate_duration module.
"""

import unittest
from unittest.mock import patch
from io import StringIO

from utils.calculate_duration import calculate_duration, get_current_epoch, main


class TestCalculateDuration(unittest.TestCase):
    """Test cases for the calculate_duration function."""

    @patch('time.time')
    def test_calculate_duration_basic(self, mock_time):
        """Test basic duration calculation."""
        # Mock current time to be 1000 seconds after start
        mock_time.return_value = 2000
        start_epoch = 1000

        result = calculate_duration(start_epoch)

        # 1000 seconds = 16.67 minutes (rounded to 2 decimals)
        expected = round(1000 / 60, 2)
        self.assertEqual(result, expected)
        self.assertEqual(result, 16.67)

    @patch('time.time')
    def test_calculate_duration_with_string_input(self, mock_time):
        """Test duration calculation with string input."""
        mock_time.return_value = 1500
        start_epoch = "1000"  # String input

        result = calculate_duration(start_epoch)

        # 500 seconds = 8.33 minutes
        expected = round(500 / 60, 2)
        self.assertEqual(result, expected)
        self.assertEqual(result, 8.33)

    def test_calculate_duration_invalid_string(self):
        """Test duration calculation with invalid string input."""
        with self.assertRaises(ValueError) as context:
            calculate_duration("invalid")

        self.assertIn("Invalid start_epoch", str(context.exception))
        self.assertIn("Must be a valid integer", str(context.exception))

    def test_calculate_duration_negative_epoch(self):
        """Test duration calculation with negative epoch."""
        with self.assertRaises(ValueError) as context:
            calculate_duration(-100)

        self.assertIn("Invalid start_epoch", str(context.exception))
        self.assertIn("Must be greater than 0", str(context.exception))

    def test_calculate_duration_zero_epoch(self):
        """Test duration calculation with zero epoch."""
        with self.assertRaises(ValueError) as context:
            calculate_duration(0)

        self.assertIn("Invalid start_epoch", str(context.exception))
        self.assertIn("Must be greater than 0", str(context.exception))

    def test_calculate_duration_none_input(self):
        """Test duration calculation with None input."""
        with self.assertRaises(ValueError) as context:
            calculate_duration(None)

        self.assertIn("Invalid start_epoch", str(context.exception))
        self.assertIn("Must be a valid integer", str(context.exception))

    @patch('time.time')
    @patch('sys.stderr', new_callable=StringIO)
    def test_get_current_epoch_basic(self, mock_stderr, mock_time):
        """Test basic current epoch retrieval."""
        mock_time.return_value = 1234567890

        result = get_current_epoch()

        self.assertEqual(result, 1234567890)
        stderr_content = mock_stderr.getvalue()
        self.assertIn("Current time:", stderr_content)
        self.assertIn("Current epoch: 1234567890", stderr_content)

class TestMainFunction(unittest.TestCase):
    """Test cases for the main function."""

    @patch('sys.argv', ['calculate_duration.py', '1000'])
    @patch('time.time')
    @patch('sys.stdout', new_callable=StringIO)
    @patch('sys.stderr', new_callable=StringIO)
    def test_main_success(self, mock_stderr, mock_stdout, mock_time):
        """Test main function with valid input."""
        mock_time.return_value = 1600

        main()

        stdout_content = mock_stdout.getvalue().strip()
        stderr_content = mock_stderr.getvalue()

        # 600 seconds = 10.0 minutes
        self.assertEqual(stdout_content, "10.0")
        # Verify debug info was written to stderr
        self.assertIn("Step execution start time:", stderr_content)
        self.assertIn("Duration in minutes: 10.0", stderr_content)

    @patch('sys.argv', ['calculate_duration.py'])
    @patch('sys.stderr', new_callable=StringIO)
    def test_main_no_arguments(self, mock_stderr):
        """Test main function with no arguments."""
        with self.assertRaises(SystemExit) as context:
            main()

        self.assertEqual(context.exception.code, 1)
        stderr_content = mock_stderr.getvalue()
        self.assertIn("Usage:", stderr_content)
        self.assertIn("python calculate_duration.py <start_epoch>", stderr_content)
        self.assertIn("python calculate_duration.py --current", stderr_content)

    @patch('sys.argv', ['calculate_duration.py', 'invalid'])
    @patch('sys.stderr', new_callable=StringIO)
    def test_main_invalid_argument(self, mock_stderr):
        """Test main function with invalid argument."""
        with self.assertRaises(SystemExit) as context:
            main()

        self.assertEqual(context.exception.code, 1)
        stderr_content = mock_stderr.getvalue()
        self.assertIn("Error:", stderr_content)
        self.assertIn("Invalid start_epoch", stderr_content)

    @patch('sys.argv', ['calculate_duration.py', '1000', 'extra'])
    @patch('sys.stderr', new_callable=StringIO)
    def test_main_too_many_arguments(self, mock_stderr):
        """Test main function with too many arguments."""
        with self.assertRaises(SystemExit) as context:
            main()

        self.assertEqual(context.exception.code, 1)
        stderr_content = mock_stderr.getvalue()
        self.assertIn("Usage:", stderr_content)
        self.assertIn("python calculate_duration.py <start_epoch>", stderr_content)
        self.assertIn("python calculate_duration.py --current", stderr_content)

    @patch('sys.argv', ['calculate_duration.py', '--current'])
    @patch('time.time')
    @patch('sys.stdout', new_callable=StringIO)
    @patch('sys.stderr', new_callable=StringIO)
    def test_main_current_option(self, mock_stderr, mock_stdout, mock_time):
        """Test main function with --current option."""
        mock_time.return_value = 1234567890

        main()

        stdout_content = mock_stdout.getvalue().strip()
        stderr_content = mock_stderr.getvalue()

        # Should output the current epoch
        self.assertEqual(stdout_content, "1234567890")
        # Verify debug info was written to stderr
        self.assertIn("Current time:", stderr_content)
        self.assertIn("Current epoch: 1234567890", stderr_content)

    @patch('sys.argv', ['calculate_duration.py', '--current'])
    @patch('time.time', side_effect=Exception("Time error"))
    @patch('sys.stderr', new_callable=StringIO)
    def test_main_current_option_error(self, mock_stderr, _):
        """Test main function with --current option when error occurs."""
        with self.assertRaises(SystemExit) as context:
            main()

        self.assertEqual(context.exception.code, 1)
        stderr_content = mock_stderr.getvalue()
        self.assertIn("Unexpected error: Time error", stderr_content)

if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)
