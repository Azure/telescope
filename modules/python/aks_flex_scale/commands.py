"""Safe subprocess helpers with bounded retry."""

from __future__ import annotations

import json
import random
import subprocess
import time
from dataclasses import dataclass
from typing import Any

TRANSIENT = ("aadsts70043", "toomanyrequests", "throttl", "temporarily unavailable",
             "internalservererror", "gatewaytimeout", "serviceunavailable", "timed out",
             "connection reset", "another operation")


@dataclass
class CommandError(RuntimeError):
    args_list: list[str]
    returncode: int
    diagnostic: str

    def __str__(self) -> str:
        return f"command failed ({self.returncode}): {self.args_list[0]}: {self.diagnostic[:500]}"


def run(args: list[str], *, timeout: int = 300, attempts: int = 1,
        input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    last: subprocess.CompletedProcess | None = None
    for attempt in range(attempts):
        try:
            last = subprocess.run(args, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            if attempt + 1 == attempts:
                raise CommandError(args, 124, "bounded command timeout") from exc
            time.sleep(min(30, 2 ** attempt) + random.random())
            continue
        if last.returncode == 0 or not check:
            return last
        diagnostic = (last.stdout + b"\n" + last.stderr).decode("utf-8", "replace")
        retryable = any(marker in diagnostic.lower() for marker in TRANSIENT)
        if not retryable or attempt + 1 == attempts:
            raise CommandError(args, last.returncode, diagnostic)
        time.sleep(min(30, 2 ** attempt) + random.random())
    raise CommandError(args, 1, "command did not execute")


def text(args: list[str], **kwargs: Any) -> str:
    return run(args, **kwargs).stdout.decode("utf-8", "replace").strip()


def json_value(args: list[str], **kwargs: Any) -> Any:
    output = text(args, **kwargs)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise CommandError(args, 1, "command did not return JSON") from exc


def az(*args: str, **kwargs: Any) -> str:
    return text(["az", *args], attempts=kwargs.pop("attempts", 4), **kwargs)


def az_json(*args: str, **kwargs: Any) -> Any:
    return json_value(["az", *args, "--output", "json"], attempts=kwargs.pop("attempts", 4), **kwargs)


def kubectl_json(*args: str, **kwargs: Any) -> Any:
    return json_value(["kubectl", *args, "-o", "json"], **kwargs)
