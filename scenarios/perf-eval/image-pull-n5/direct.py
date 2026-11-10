"""Run verified full-blob GETs directly on the WSL host without kind or Kubernetes."""

from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
import http.client
import json
import os
from pathlib import Path
import socket
import threading
import time

import download
import pull
from download import DownloadError, error_message, utc


def run(
    args, *, pull_count=pull.PULL_COUNT, start_immediately=False, primary_bundle=None,
    warm_traffic=False, scale_in_threshold_bytes=pull.DEFAULT_SCALE_IN_THRESHOLD_BYTES,
    scale_out_threshold_bytes=pull.DEFAULT_SCALE_OUT_THRESHOLD_BYTES,
):
    result = {
        "timestamp": utc(time.time()), "run_id": args.run_id, "run_url": args.run_url,
        "image": args.image, "region": "local", "node_count": 1,
        "execution_backend": "direct", "namespace": None,
        "storage_role": "primary" if primary_bundle is not None else "replica",
        "start_mode": "immediate" if start_immediately else "aligned",
        "status": "failure", "expected_pulls": pull_count, "successful_pulls": 0,
        "pulls": [], "errors": [],
    }
    if warm_traffic:
        result.update(
            scenario="TC-SI-03", pulls_per_account=pull.WARM_PULLS_PER_ACCOUNT,
            scale_in_threshold_bytes=scale_in_threshold_bytes,
            scale_out_threshold_bytes=scale_out_threshold_bytes,
            server_validation_required=True,
        )
    targets = []
    cancel = threading.Event()
    executor = None
    futures = {}
    sensitive = [os.environ.get("ACR_PULL_PASSWORD", "")]
    try:
        pull.parse_image(args.image)
        if warm_traffic:
            if primary_bundle is not None or pull_count != pull.WARM_PULL_COUNT:
                raise DownloadError("Warm traffic requires six replica downloads, not primary downloads")
        elif pull_count not in pull.SUPPORTED_PULL_COUNTS:
            raise DownloadError("Expected four or five downloads")
        deadline = time.monotonic() + pull.TIMEOUT_SECONDS
        if primary_bundle is not None:
            targets = [pull.resolve_primary_target(
                args.image, primary_bundle, start_immediately=start_immediately,
            )]
        else:
            username, password = os.environ.get("ACR_PULL_USERNAME", ""), os.environ.get("ACR_PULL_PASSWORD", "")
            if any(not value or value.startswith("$(") for value in (username, password)):
                raise DownloadError("Set ACR_PULL_USERNAME and secret ACR_PULL_PASSWORD")
            if warm_traffic:
                targets = pull.resolve_warm_targets(
                    args.image, username, password, start_immediately=start_immediately,
                    scale_in_threshold_bytes=scale_in_threshold_bytes,
                    scale_out_threshold_bytes=scale_out_threshold_bytes,
                )
            else:
                targets = [pull.resolve_target(args.image, username, password, start_immediately=start_immediately)]
        sensitive.extend(target["url"] for target in targets)
        pull.ensure_schedule_fits(targets[0], deadline, pull_count=pull_count)
        result.update(
            blob_digest=targets[0]["digest"], blob_size_bytes=targets[0]["size"],
            window_start=utc(targets[0]["start"]), window_end=utc(targets[0]["end"]),
        )
        if not warm_traffic:
            result["storage_account"] = targets[0]["account"]
        if primary_bundle is not None:
            result.update(
                storage_container=targets[0]["container"],
                primary_partition_key=targets[0]["primary_location"]["PartitionKey"],
                primary_row_key=targets[0]["primary_location"]["RowKey"],
            )
        hostname = socket.gethostname()
        result["pulls"] = [
            {"worker": f"pull-{index + 1}", "node": hostname, "status": "pending"}
            for index in range(pull_count)
        ]
        executor = ThreadPoolExecutor(max_workers=pull_count, thread_name_prefix="blob-download")
        for index, entry in enumerate(result["pulls"]):
            target = targets[index // pull.WARM_PULLS_PER_ACCOUNT if warm_traffic else 0]
            future = executor.submit(download.download, target, cancel_event=cancel)
            futures[future] = (entry, target)
        for future in as_completed(futures, timeout=max(0, deadline - time.monotonic())):
            entry, target = futures[future]
            try:
                pull.record_download(entry, future.result(), target)
            except (OSError, ValueError, KeyError, TypeError, DownloadError, http.client.HTTPException, CancelledError) as error:
                details = error_message(error, sensitive)
                entry.update(status="failure", error=details)
                result["errors"].append(f"{entry['worker']}: {details}")
                cancel.set()
        for field in ("storage_request_id", "client_request_id"):
            ids = [entry[field] for entry in result["pulls"] if entry["status"] == "success"]
            if len(ids) != len(set(ids)):
                raise DownloadError(f"Expected distinct {field} values for every verified GET")
    except KeyboardInterrupt:
        result["errors"].append("Direct run interrupted; partial traffic may already have reached storage")
        raise
    except (OSError, ValueError, KeyError, TypeError, DownloadError, http.client.HTTPException) as error:
        result["errors"].append(error_message(error, sensitive))
    finally:
        cancel.set()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        for future, (entry, target) in futures.items():
            if entry["status"] != "pending":
                continue
            try:
                pull.record_download(entry, future.result(), target)
            except (OSError, ValueError, KeyError, TypeError, DownloadError, http.client.HTTPException, CancelledError) as error:
                details = error_message(error, sensitive)
                entry.update(status="failure", error=details)
                result["errors"].append(f"{entry['worker']}: {details}")
        result["finished_at"] = utc(time.time())
        pull.summarize_downloads(result, targets, warm_traffic=warm_traffic)
        if result["successful_pulls"] == pull_count and not result["errors"]:
            result["status"] = "success"
        output = Path(args.result_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    for error in result["errors"]:
        print(f"DIRECT DOWNLOAD FAILED: {error}")
    return 0 if result["status"] == "success" else 1
