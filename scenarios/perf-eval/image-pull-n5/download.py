"""Download and verify one authorized blob from a fixed Azure Storage account."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


WINDOW_SECONDS = 300
LAYER_BYTES = 1073741824
WORKER_TIMEOUT_SECONDS = 1200
READ_BUFFER_BYTES = 1024 * 1024


class DownloadError(RuntimeError):
    """A safe-to-log error that never contains credentials or signed URLs."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_request(request, timeout=30):
    return urllib.request.build_opener(NoRedirect).open(request, timeout=timeout)


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def primary_location(location, digest):
    if (
        not isinstance(location, dict)
        or location.get("PrimaryCopy") is not True
        or location.get("IsElasticCopy", False) is not False
        or location.get("Status") not in (None, "", "Active")
    ):
        raise DownloadError("Expected an active PrimaryCopy=true, non-elastic BlobLocation row")
    account = location.get("StorageAccountName", "")
    container = location.get("StorageContainerName", "")
    if not isinstance(account, str) or not re.fullmatch(r"[a-z0-9]{3,24}", account):
        raise DownloadError("Primary storage account is invalid")
    if (
        not isinstance(container, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container)
        or "--" in container
    ):
        raise DownloadError("Primary storage container is invalid")
    partition = location.get("PartitionKey", "")
    if (
        not isinstance(partition, str)
        or not re.fullmatch(re.escape(digest.removeprefix("sha256:")) + r"&[0-9a-f]{32}", partition)
        or location.get("RowKey") != f"{account}&{container}"
    ):
        raise DownloadError("Primary BlobLocation keys do not match the layer or location")
    return account, container


def storage_account(url, digest, *, primary=None):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise DownloadError("Expected an HTTPS Azure Storage SAS URL")
    match = re.fullmatch(r"([a-z0-9]{3,24})\.blob\.core\.windows\.net", parsed.hostname or "")
    if not match:
        raise DownloadError("Expected a public Azure Storage blob endpoint")
    if primary is None and not any(marker in match[1] for marker in ("replica", "replstore")):
        raise DownloadError("Registry did not select an eligible replica storage account")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise DownloadError("Invalid layer digest")
    encoded = digest.removeprefix("sha256:")
    suffix = f"/v2/blobs/sha256/{encoded[:2]}/{encoded}/data"
    if not urllib.parse.unquote(parsed.path).endswith(suffix):
        raise DownloadError("Registry redirect does not point to the requested layer")
    parameters = urllib.parse.parse_qs(parsed.query)
    if not parameters.get("sig"):
        raise DownloadError("Registry redirect is missing a SAS signature")
    if primary is not None:
        account, container = primary_location(primary, digest)
        if match[1] != account or urllib.parse.unquote(parsed.path) != f"/{container}/docker/registry{suffix}":
            raise DownloadError("Signed URL does not match the verified primary account, container, and blob")
        if any(parameters.get(key) != [value] for key, value in (
            ("sp", "r"), ("sr", "b"), ("spr", "https"),
        )):
            raise DownloadError("Primary downloads require an HTTPS-only, read-only, blob-scoped SAS")
    return match[1]


def validate_layer_size(size):
    if type(size) is not int or size < LAYER_BYTES:
        raise DownloadError("Expected a layer of at least one GiB with an integer byte size")


def validate_target(target):
    role = target.get("storage_role", "replica")
    if role not in ("replica", "primary"):
        raise DownloadError("Invalid storage role")
    primary = target.get("primary_location") if role == "primary" else None
    if role == "primary" and not isinstance(primary, dict):
        raise DownloadError("Primary target is missing its BlobLocation evidence")
    account = storage_account(target["url"], target["digest"], primary=primary)
    if account != target["account"]:
        raise DownloadError("Storage account does not match the selected account")
    validate_layer_size(target["size"])
    start, end = target["start"], target["end"]
    start_mode = target.get("start_mode", "aligned")
    if start_mode not in ("aligned", "immediate"):
        raise DownloadError("Invalid download start mode")
    if type(start) is not int or type(end) is not int or end != start + WINDOW_SECONDS:
        raise DownloadError("Invalid five-minute download interval")
    if start_mode == "aligned" and start % WINDOW_SECONDS:
        raise DownloadError("Invalid aligned five-minute download window")
    parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(target["url"]).query)
    expiry = parameters.get("se", [])
    if len(expiry) != 1:
        raise DownloadError("Storage SAS must have an explicit expiry")
    try:
        expires_at = datetime.fromisoformat(expiry[0].replace("Z", "+00:00"))
        valid_from = parameters.get("st", [])
        starts_at = datetime.fromisoformat(valid_from[0].replace("Z", "+00:00")) if valid_from else None
    except ValueError:
        raise DownloadError("Invalid SAS validity timestamps") from None
    if expires_at.tzinfo is None or expires_at.timestamp() < end + 30:
        raise DownloadError("Storage SAS expires before the download window finishes")
    if starts_at is not None and (starts_at.tzinfo is None or starts_at.timestamp() > start):
        raise DownloadError("Storage SAS is not valid at the scheduled start")


def sanitize_diagnostic(message, secrets=()):
    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="replace")
    text = str(message or "").replace("\\/", "/")
    sensitive = set(value for value in secrets if value and value != "{}")
    for value in tuple(sensitive):
        if value.startswith("https://"):
            parameters = urllib.parse.parse_qs(value.partition("?")[2])
            for key in ("sig", "token", "access_token", "refresh_token"):
                sensitive.update(parameters.get(key, []))
    variants = {
        variant for value in sensitive for variant in (
            value, urllib.parse.quote(value, safe=""),
            urllib.parse.quote_plus(value), base64.b64encode(value.encode()).decode(),
        )
    }
    for value in sorted(variants, key=len, reverse=True):
        text = text.replace(value, "[redacted]")
    text = re.sub(r"""https?(?:://|%3a%2f%2f)[^\s<>"']+""", "[redacted URL]", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(Basic|Bearer)\s+[A-Za-z0-9._~+/=-]+", r"\1 [redacted]", text, flags=re.IGNORECASE)
    text = re.sub(
        r"""(?i)(["']?(?:password|access_token|refresh_token|token|sig)["']?\s*[:=]\s*)(?!\[redacted)(?:"[^"]*"|'[^']*'|[^&\s,;}\]]+)""",
        r"\1[redacted]", text,
    )
    return " ".join(text.split())[:1024]


def error_message(error, secrets=()):
    if isinstance(error, DownloadError):
        return sanitize_diagnostic(error, secrets)
    if isinstance(error, urllib.error.HTTPError):
        reason = sanitize_diagnostic(error.reason, secrets)
        return f"HTTP request failed with status {error.code} ({reason}); redirects are not followed"
    if isinstance(error, urllib.error.URLError):
        reason = sanitize_diagnostic(error.reason, secrets)
        return f"HTTP transport failed ({type(error.reason).__name__}): {reason}"
    return f"{type(error).__name__} while preparing or downloading the blob"


def download(target, *, cancel_event=None):
    validate_target(target)

    def check_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadError("Download cancelled; the run was interrupted or another worker failed")

    while time.time() < target["start"]:
        check_cancelled()
        time.sleep(max(0, min(1, target["start"] - time.time())))
    check_cancelled()
    if time.time() >= target["end"]:
        raise DownloadError("Download window expired before the request started")
    client_request_id = str(uuid.uuid4())
    request = urllib.request.Request(target["url"], headers={
        "x-ms-client-request-id": client_request_id,
        "User-Agent": "telescope-single-account/1.0",
    })
    started = time.time()
    monotonic_start = time.monotonic()
    cpu_start = time.thread_time()
    hashing_seconds = 0.0
    digest = hashlib.sha256()
    count = 0
    with open_request(request, timeout=min(30, target["end"] - started)) as response:
        headers_seconds = time.monotonic() - monotonic_start
        if response.status != 200:
            raise DownloadError("Expected HTTP 200 for a full, non-range blob download")
        if int(response.headers.get("Content-Length", "-1")) != target["size"]:
            raise DownloadError("Storage Content-Length does not match the layer size")
        request_id = response.headers.get("x-ms-request-id")
        if not request_id:
            raise DownloadError("Storage response is missing its request ID")
        buffer = bytearray(READ_BUFFER_BYTES)
        view = memoryview(buffer)
        while True:
            check_cancelled()
            received = response.readinto(buffer)
            if not received:
                break
            count += received
            if count > target["size"]:
                raise DownloadError("Storage returned more bytes than the layer size")
            if time.time() >= target["end"]:
                raise DownloadError("Download exceeded the five-minute transfer deadline")
            hash_start = time.monotonic()
            digest.update(view[:received])
            hashing_seconds += time.monotonic() - hash_start
    finished = time.time()
    actual_digest = "sha256:" + digest.hexdigest()
    if count != target["size"] or actual_digest != target["digest"]:
        raise DownloadError("Downloaded layer size or SHA-256 digest does not match")
    if finished >= target["end"]:
        raise DownloadError("Download finished outside the five-minute transfer deadline")
    return {
        "status": "success",
        "storage_account": target["account"],
        "storage_role": target.get("storage_role", "replica"),
        "blob_digest": actual_digest,
        "downloaded_bytes": count,
        "started_at": utc(started),
        "finished_at": utc(finished),
        "duration_seconds": time.monotonic() - monotonic_start,
        "time_to_headers_seconds": headers_seconds,
        "hashing_seconds": hashing_seconds,
        "cpu_seconds": time.thread_time() - cpu_start,
        "window_start": utc(target["start"]),
        "window_end": utc(target["end"]),
        "client_request_id": client_request_id,
        "storage_request_id": request_id,
    }


def worker(target_file, ready_file):
    deadline = time.monotonic() + WORKER_TIMEOUT_SECONDS
    try:
        Path(ready_file).touch()
        while time.monotonic() < deadline:
            target = json.loads(Path(target_file).read_text(encoding="utf-8"))
            if target:
                if target["end"] - time.time() > deadline - time.monotonic():
                    raise DownloadError("Download window exceeds the remaining worker lifetime")
                result = download(target)
                break
            time.sleep(2)
        else:
            raise DownloadError("Timed out waiting for the coordinator to select a blob")
    except (OSError, ValueError, KeyError, TypeError, DownloadError, http.client.HTTPException) as error:
        result = {"status": "failure", "error": error_message(error)}
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-file", default="/target/target.json")
    parser.add_argument("--ready-file", default="/tmp/ready")
    args = parser.parse_args()
    raise SystemExit(worker(args.target_file, args.ready_file))
