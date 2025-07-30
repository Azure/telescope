"""
Calculate duration between start epoch and current time.
Returns duration in minutes with 2 decimal precision.

This module also provides functionality to get the current epoch time.

Usage:
    python calculate_duration.py <start_epoch>  # Calculate duration from start_epoch to now
    python calculate_duration.py --current      # Get current epoch time
"""

import sys
import time
from datetime import datetime

def get_current_epoch():
    """
    Get the current time as epoch seconds.
    
    Returns:
        int: Current time in epoch seconds
    """
    current_epoch = int(time.time())

    # Format timestamp for logging
    current_time = datetime.fromtimestamp(current_epoch).strftime('%Y-%m-%d %H:%M:%S UTC')

    # Print debug information to stderr
    print(f"Current time: {current_time}", file=sys.stderr)
    print(f"Current epoch: {current_epoch}", file=sys.stderr)

    return current_epoch

def calculate_duration(start_epoch):
    """
    Calculate duration between start epoch and current time.
    
    Args:
        start_epoch (int): Start time in epoch seconds
        
    Returns:
        float: Duration in minutes with 2 decimal precision
        
    Raises:
        ValueError: If start_epoch is invalid
    """
    try:
        start_epoch = int(start_epoch)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid start_epoch: {start_epoch}. Must be a valid integer.") from exc

    if start_epoch <= 0:
        raise ValueError(f"Invalid start_epoch: {start_epoch}. Must be greater than 0.")

    # Get current time
    end_epoch = get_current_epoch()

    # Calculate duration in minutes
    duration_seconds = end_epoch - start_epoch
    duration_minutes = round(duration_seconds / 60, 2)

    # Format timestamps for logging
    start_time = datetime.fromtimestamp(start_epoch).strftime('%Y-%m-%d %H:%M:%S UTC')
    end_time = datetime.fromtimestamp(end_epoch).strftime('%Y-%m-%d %H:%M:%S UTC')

    # Print debug information to stderr (so it doesn't interfere with the return value)
    print(f"Step execution start time: {start_time}", file=sys.stderr)
    print(f"Step execution end time: {end_time}", file=sys.stderr)
    print(f"Duration in minutes: {duration_minutes}", file=sys.stderr)

    return duration_minutes


def main():
    """Main function for command line usage."""
    if len(sys.argv) == 2 and sys.argv[1] == "--current":
        # Get current epoch time
        try:
            epoch = get_current_epoch()
            print(epoch)
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)
    elif len(sys.argv) == 2:
        # Calculate duration from start epoch
        try:
            start_epoch = sys.argv[1]
            duration = calculate_duration(start_epoch)

            # Output only the duration value to stdout for bash consumption
            print(duration)

        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Usage:", file=sys.stderr)
        print("  python calculate_duration.py <start_epoch>    # Calculate duration", file=sys.stderr)
        print("  python calculate_duration.py --current        # Get current epoch", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
