"""Timestamp formatting and parsing shared by the node startup measurement.

Whole-second values match the v1 benchmark's format exactly. The `*_precise`
values carry microseconds and are only produced where the source has them.
"""
from datetime import datetime

WHOLE_SECOND_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
PRECISE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def format_timestamp(ts):
    if ts is None:
        return None
    return ts.strftime(WHOLE_SECOND_FORMAT)


def format_precise_timestamp(ts):
    if ts is None:
        return None
    return ts.strftime(PRECISE_FORMAT)


def parse_timestamp(value):
    """Parse a whole-second "...Z" timestamp. Python 3.10 fromisoformat rejects "Z"."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_log_timestamp(value):
    """Parse a kubelet RFC3339Nano log timestamp, truncating nanoseconds to microseconds."""
    parts = value.rstrip("Z").split(".")
    if len(parts) == 2:
        fraction = parts[1][:6].ljust(6, "0")
        return datetime.fromisoformat(f"{parts[0]}.{fraction}+00:00")
    return datetime.fromisoformat(f"{parts[0]}+00:00")


def condition_transition_time(conditions, condition_type):
    if not conditions:
        return None
    for condition in conditions:
        if condition.type == condition_type:
            return format_timestamp(condition.last_transition_time)
    return None
