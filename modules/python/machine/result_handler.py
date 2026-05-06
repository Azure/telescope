"""Persist per-operation results to JSON.

Differences from ado-telescope's k8s/result_handler.py:
- Output is a NESTED dict {"config": ..., "response": ...}
  (not flat **-spread that overwrites overlapping keys).
- UTC timestamp in filename.
- Uses utils.common.save_info_to_file when feasible.
"""
import functools
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

from utils.common import save_info_to_file
from utils.logger_config import get_logger

logger = get_logger(__name__)


def _serialize(obj):
    """Convert dataclasses to dicts; pass everything else through unchanged."""
    if is_dataclass(obj):
        return asdict(obj)
    return obj


def save_test_result(func):
    """Decorator that writes the wrapped method's response to a JSON file.

    The file path is derived from ``self.config`` (cloud / cluster_name /
    machine_name|agentpool_name) plus a UTC unix timestamp. Persistence
    failures are logged but never propagated, so test orchestration is
    insulated from disk errors.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        response = func(self, *args, **kwargs)
        try:
            config = self.config
            op_name = response.operation_name
            suffix = config.machine_name or config.agentpool_name
            timestamp = int(datetime.now(timezone.utc).timestamp())
            filename = f"{op_name}-{config.cloud}-{config.cluster_name}-{suffix}-{timestamp}.json"
            path = os.path.join(config.result_dir, filename)
            os.makedirs(config.result_dir, exist_ok=True)
            payload = {
                "config": _serialize(config),
                "response": _serialize(response),
            }
            save_info_to_file(payload, path)
            logger.info("Wrote result to %s", path)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to save result: %s", exc)
        return response
    return wrapper
