"""Aggregate per-op JSONs into Kusto-shaped lines (one object per line).

Differences from ado-telescope k8s/collect_python.py:
- glob excludes results.json (no self-ingestion).
- Lines are newline-terminated (proper JSONL).
- UTC timestamp.
- Reads the new nested {config, response} payload (not flat-merged).
- Replaces filename-startswith dispatch with response.operation_name.
"""
import glob
import json
import os
from datetime import datetime, timezone
from typing import Optional

from utils.logger_config import get_logger

logger = get_logger(__name__)


def _format_record(payload: dict, region: Optional[str], run_id: str, run_url: str) -> dict:
    cfg = payload["config"]
    resp = payload["response"]
    aks_data = {
        "vm_size": cfg.get("vm_size"),
        "node_pool_name": cfg.get("agentpool_name"),
        "create_node_count": None,
        "scale_node_count": None,
        "scale_machine_count": cfg.get("scale_machine_count"),
        "feature_name": None,
        "node_pool_type": None,
        "node_pool_number": None,
        "batch_size": None,
        "region": region or cfg.get("region"),
        "use_batch_api": cfg.get("use_batch_api"),
        "machine_workers": cfg.get("machine_workers"),
        "workload_test_setting": None,
    }
    operation_info = {
        "name": resp.get("operation_name"),
        "node_readiness_time": resp.get("node_readiness_time", 0),
        "command_execution_time": resp.get("command_execution_time", 0),
        "batch_command_execution_times": resp.get("batch_command_execution_times", {}),
        "percentile_node_readiness_times": resp.get("percentile_node_readiness_times", {}),
        "unit": "seconds",
        "succeeded": resp.get("succeeded", False),
        "warning_message": resp.get("warning_message", ""),
        "data": resp.get("cloud_data"),
    }
    cloud_info = {"cloud": cfg.get("cloud"), "aks_name": cfg.get("cluster_name")}
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "region": region or cfg.get("region"),
        "aks_data": json.dumps(aks_data),
        "operation_info": json.dumps(operation_info),
        "cloud_info": json.dumps(cloud_info),
        "run_id": run_id,
        "run_url": run_url,
    }


def collect_results(run_id: str, run_url: str, region: Optional[str],
                    result_dir: str) -> int:
    """Aggregate per-op JSON files in ``result_dir`` into ``results.json`` (JSONL).

    Skips the destination file itself, ignores per-file decode/IO errors, and
    returns 0 unconditionally — caller treats "no inputs" as a no-op.
    """
    results_path = os.path.join(result_dir, "results.json")
    files = sorted(p for p in glob.glob(os.path.join(result_dir, "*.json"))
                   if os.path.basename(p) != "results.json")
    if not files:
        logger.warning("no per-op JSON files in %s", result_dir)
        return 0
    with open(results_path, "w", encoding="utf-8") as out:
        for path in files:
            try:
                with open(path, encoding="utf-8") as fh:
                    payload = json.load(fh)
                rec = _format_record(payload, region, run_id, run_url)
                out.write(json.dumps(rec) + "\n")
            except (KeyError, json.JSONDecodeError, OSError) as e:
                logger.error("skipping %s: %s", path, e)
                continue
    logger.info("wrote %d records to %s", len(files), results_path)
    return 0
