"""UTC timestamp formatting and parsing for benchmark results.

Kubernetes object times (creation, condition transitions, container start)
only have whole seconds, so they use TIMESTAMP_SECONDS_FORMAT. Times the
benchmark observes itself, and event `eventTime`s, use
TIMESTAMP_MICROSECONDS_FORMAT.
"""
from datetime import datetime

TIMESTAMP_SECONDS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TIMESTAMP_MICROSECONDS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def format_timestamp(ts):
    if ts is None:
        return None
    return ts.strftime(TIMESTAMP_SECONDS_FORMAT)


def format_timestamp_microseconds(ts):
    if ts is None:
        return None
    return ts.strftime(TIMESTAMP_MICROSECONDS_FORMAT)


def parse_timestamp(value):
    """Parse a "...Z" timestamp in either format. Python 3.10 fromisoformat rejects "Z"."""
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
