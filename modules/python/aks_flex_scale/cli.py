#!/usr/bin/env python3
"""Run the AKS Flex Node scale test from Telescope or a local workstation."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .config import load_config
from .orchestrator import (cleanup, plan, preflight, prepare_vms, provision_environment,
                           resolve_versions, run_join, validate_fleet, write_result)
from .state import RunState


def parse_override(value: str) -> tuple[str, Any]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("overrides must use key=value")
    key, raw = value.split("=", 1)
    if not key:
        raise argparse.ArgumentTypeError("override key must not be empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    return key, parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=["plan", "resolve", "preflight", "provision", "prepare-vms",
                                                   "join", "validate", "result", "cleanup", "all"])
    result.add_argument("--config", required=True)
    result.add_argument("--state-dir", default=".flex-scale-state")
    result.add_argument("--output", default="result.json")
    result.add_argument("--set", action="append", default=[], type=parse_override, metavar="KEY=VALUE")
    result.add_argument("--retain", action="store_true",
                        help="With 'all', retain resources regardless of outcome (local debugging only).")
    return result


def execute(command: str, config: dict[str, Any], state: RunState, output: str) -> Any:
    operations = {
        "plan": lambda: plan(config, state),
        "resolve": lambda: resolve_versions(config, state),
        "preflight": lambda: preflight(config, state),
        "provision": lambda: provision_environment(config, state),
        "prepare-vms": lambda: prepare_vms(config, state),
        "join": lambda: run_join(config, state),
        "validate": lambda: validate_fleet(config, state),
        "result": lambda: write_result(config, state, output),
        "cleanup": lambda: cleanup(config, state),
    }
    started_at = RunState.now()
    started = time.monotonic()
    phase = {"startedAt": started_at, "status": "running"}
    state.data.setdefault("phases", {})[command] = phase
    state.save()
    state.event("phase-started", phase=command, startedAt=started_at)
    try:
        value = operations[command]()
    except Exception as exc:
        duration = round(time.monotonic() - started, 3)
        phase.update({"completedAt": RunState.now(), "durationSeconds": duration,
                      "status": "failed", "errorType": type(exc).__name__})
        state.save()
        state.event("phase-failed", phase=command, durationSeconds=duration,
                    errorType=type(exc).__name__)
        raise
    duration = round(time.monotonic() - started, 3)
    phase.update({"completedAt": RunState.now(), "durationSeconds": duration, "status": "passed"})
    state.save()
    state.event("phase-completed", phase=command, durationSeconds=duration)
    print(f"Phase {command}: status=passed duration={duration:.3f}s", file=sys.stderr, flush=True)
    return value


def run_all(config: dict[str, Any], state: RunState, output: str, retain: bool) -> None:
    failed = False
    try:
        for command in ("plan", "resolve", "preflight", "provision", "prepare-vms", "join", "validate", "result"):
            print(f"=== {command} ===", flush=True)
            value = execute(command, config, state, output)
            print(json.dumps(value, indent=2, sort_keys=True), flush=True)
    except Exception:
        failed = True
        # Preserve a partial benchmark result before cleanup.
        try:
            write_result(config, state, output)
        except Exception as result_error:  # pylint: disable=broad-exception-caught
            print(f"warning: could not write partial result: {result_error}", file=sys.stderr)
        raise
    finally:
        retain_failure = failed and config.get("retainOnFailure") is True
        if retain or retain_failure:
            print("Environment retained; run the cleanup command when finished.", file=sys.stderr)
        else:
            print("=== cleanup ===", flush=True)
            cleanup(config, state)


def main() -> int:
    args = parser().parse_args()
    overrides = dict(args.set)
    overrides.setdefault("runId", os.environ.get("RUN_ID") or None)
    overrides = {key: value for key, value in overrides.items() if value is not None}
    try:
        config = load_config(args.config, overrides)
        state = RunState(args.state_dir)
        if args.command == "all":
            run_all(config, state, args.output, args.retain)
        else:
            value = execute(args.command, config, state, args.output)
            if value is not None:
                print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
