"""
Operation Module.

This module provides functionality for tracking, timing, and recording operation
data such as name, start/end time, duration, success status, error messages, and
metadata for operations performed in the Telescope project.
"""

import json
import os
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from utils.logger_config import get_logger, setup_logging
# Configure logging
setup_logging()
logger = get_logger(__name__)


class Operation:
    """
    A class for tracking and recording operation data.

    This class helps track operation details such as name, start/end time,
    duration, success status, error messages, and additional metadata.
    """

    def __init__(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize a new Operation with a name and optional metadata.

        Args:
            name: The name of the operation.
            metadata: Optional dictionary of metadata to associate with the operation.
        """
        self.name = name
        self.start_timestamp = None
        self.end_timestamp = None
        self.duration = None
        self.success = True
        self.error_message = None
        self.error_traceback = None
        self.metadata = metadata or {}

    def start(self) -> None:
        """
        Start the operation by recording the current time.
        """
        self.start_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def end(self, success: bool = True, error: Optional[Exception] = None) -> None:
        """
        End the operation by recording the end time and calculating the duration.

        Args:
            success: Whether the operation was successful.
            error: Optional exception that occurred during the operation.
        """
        self.end_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Calculate duration if we have both timestamps
        if self.start_timestamp and self.end_timestamp:
            try:
                start_dt = datetime.fromisoformat(
                    self.start_timestamp.replace("Z", "+00:00")
                )
                end_dt = datetime.fromisoformat(
                    self.end_timestamp.replace("Z", "+00:00")
                )
                self.duration = (end_dt - start_dt).total_seconds()
            except Exception:
                # If there's any issue parsing timestamps, don't set duration
                self.duration = None

        self.success = success

        if error:
            self.set_error(error)

    def set_error(self, error: Exception) -> None:
        """
        Set error information for the operation.

        Args:
            error: The exception that occurred during the operation.
        """
        self.success = False
        self.error_message = str(error)
        self.error_traceback = traceback.format_exc()

    def add_metadata(self, key: str, value: Any) -> None:
        """
        Add metadata to the operation.

        Args:
            key: The metadata key.
            value: The metadata value.
        """
        self.metadata[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the operation to a dictionary.

        Returns:
            A dictionary representation of the operation.
        """
        return {
            "name": self.name,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "duration": self.duration,
            "success": self.success,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert the operation to a JSON string.

        Args:
            indent: Number of spaces for JSON indentation.

        Returns:
            A JSON string representation of the operation.
        """
        return json.dumps(self.to_dict(), indent=indent)

    def save_to_file(self, file_path: str) -> None:
        """
        Save the operation data to a JSON file.

        Args:
            file_path: The path to the file where the operation data should be saved.
        """
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        with open(file_path, "w", encoding="utf-8") as f:
            operation_info = {
                "operation_info": self.to_json(),
            }
            f.write(json.dumps(operation_info))

    def __str__(self) -> str:
        """
        Return a string representation of the operation.

        Returns:
            A string representation of the operation.
        """
        status = "SUCCESS" if self.success else "FAILED"
        duration_str = f"{self.duration:.2f}s" if self.duration is not None else "N/A"

        result = f"Operation: {self.name} [{status}] (Duration: {duration_str})"
        if not self.success and self.error_message:
            result += f"\nError: {self.error_message}"

        return result


class OperationContext:
    """
    Context manager for tracking operations.

    This class provides a context manager interface for easily tracking
    operations using the Operation class.
    """

    def __init__(
        self,
        name: str,
        cloud: str,
        metadata: Optional[Dict[str, Any]] = None,
        result_dir: Optional[str] = None,
    ):
        """
        Initialize a new OperationContext.

        Args:
            name: The name of the operation.
            cloud: The cloud provider  where the operation is executed
            metadata: Optional dictionary of metadata to associate with the operation.
            result_dir: Optional directory to save operation results to. If provided, operation data
                        will be automatically saved to a file when the context exits.
        """
        self.operation = Operation(name, metadata)
        self.result_dir = result_dir
        self.cloud = cloud

    def __enter__(self) -> Operation:
        """
        Start the operation when entering the context.

        Returns:
            The Operation instance.
        """
        self.operation.start()
        return self.operation

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        End the operation when exiting the context.

        Args:
            exc_type: The exception type if an exception occurred, None otherwise.
            exc_val: The exception value if an exception occurred, None otherwise.
            exc_tb: The traceback if an exception occurred, None otherwise.
        """
        success = exc_type is None
        error = exc_val if exc_type is not None else None
        self.operation.end(success=success, error=error)

        # Automatically save the operation data to a file when result_dir is provided
        if self.result_dir:
            try:
                # Create a filename based on the operation name and timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                clean_op_name = (
                    self.operation.name.replace(" ", "_")
                    .replace("/", "_")
                    .replace("\\", "_")
                    .replace(":", "_")
                )
                filename = f"{self.cloud}_{clean_op_name}_{timestamp}.json"
                file_path = os.path.join(self.result_dir, filename)

                # Save the operation data
                self.operation.save_to_file(file_path)
            except Exception as e:
                # Log the error but don't raise it
                logger.warning(f"Failed to save operation data: {str(e)}")
