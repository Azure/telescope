"""Tests for the optional 5th TIMING_OUTPUT_PATH arg on pod-churn-killer.sh.

Uses a small in-memory fake `kubectl` placed first on PATH — consistent
with the fake-kubectl pattern in test_isolation_churn.py — instead of a
real cluster.
"""

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    REPO_ROOT
    / "modules"
    / "python"
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "pod-churn-killer.sh"
)

FAKE_KUBECTL = """#!/bin/bash
if [ "$1" = "version" ]; then echo "clientVersion: fake"; exit 0; fi
if [ "$1" = "get" ]; then
  echo "ns1/pod-a"
  echo "ns1/pod-b"
  exit 0
fi
if [ "$1" = "delete" ]; then exit 0; fi
exit 0
"""


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_script_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"bash -n failed: stderr={result.stderr}"


def _run(tmp_path, args):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    _write_executable(fake_bin / "kubectl", FAKE_KUBECTL)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        check=False, capture_output=True, text=True, env=env, timeout=30,
    )


def test_timing_output_written_when_path_provided(tmp_path):
    timing_path = tmp_path / "PodChurnEvidence.json"
    result = _run(tmp_path, ["2", "1", "2", "test-group", str(timing_path)])

    assert result.returncode == 0, result.stdout + result.stderr
    assert timing_path.exists()
    data = json.loads(timing_path.read_text())
    assert data["exit_code"] == 0
    assert data["killed_total"] > 0
    assert data["rounds"] > 0
    assert data["stimulus_valid"] is True
    assert data["workload_group"] == "test-group"
    assert data["kill_duration_seconds"] == 2
    assert data["kill_interval_seconds"] == 1
    assert data["kill_batch"] == 2
    # No leftover .tmp file from the atomic write.
    assert not (Path(str(timing_path) + ".tmp")).exists()


def test_stdout_and_exit_code_unchanged_when_path_omitted(tmp_path):
    result = _run(tmp_path, ["1", "1", "2", "test-group"])

    assert result.returncode == 0
    assert "killer: done duration=1s" in result.stdout
    # No timing file should appear anywhere in the working dir.
    assert not any(tmp_path.glob("*Evidence*"))
    assert not any(tmp_path.glob("*.json"))


def test_timing_output_written_on_kubectl_missing(tmp_path):
    fake_bin = tmp_path / "empty-bin"
    fake_bin.mkdir()
    env = os.environ.copy()
    bash_dir = str(Path(subprocess.run(["which", "bash"], capture_output=True, text=True, check=True).stdout.strip()).parent)
    env["PATH"] = f"{fake_bin}:{bash_dir}"
    timing_path = tmp_path / "PodChurnEvidence.json"

    result = subprocess.run(
        ["bash", str(SCRIPT), "2", "1", "2", "test-group", str(timing_path)],
        check=False, capture_output=True, text=True, env=env, timeout=10,
    )

    assert result.returncode == 127
    data = json.loads(timing_path.read_text())
    assert data["exit_code"] == 127
    assert data["stimulus_valid"] is False
    assert data["killed_total"] == 0
    assert data["error"] == "kubectl_unavailable"


def test_timing_output_reflects_zero_kills_as_invalid_stimulus(tmp_path):
    # Fake kubectl returns no candidates -> killed_total stays 0, which the
    # script itself must reflect as stimulus_valid:false (even though the
    # run "succeeded" with exit_code 0 — a stimulus that killed nothing is
    # not evidence the stimulus happened).
    no_candidates_kubectl = """#!/bin/bash
if [ "$1" = "version" ]; then echo "clientVersion: fake"; exit 0; fi
if [ "$1" = "get" ]; then exit 0; fi
exit 0
"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    _write_executable(fake_bin / "kubectl", no_candidates_kubectl)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    timing_path = tmp_path / "PodChurnEvidence.json"

    result = subprocess.run(
        ["bash", str(SCRIPT), "1", "1", "2", "test-group", str(timing_path)],
        check=False, capture_output=True, text=True, env=env, timeout=30,
    )

    assert result.returncode == 0
    data = json.loads(timing_path.read_text())
    assert data["killed_total"] == 0
    assert data["stimulus_valid"] is False
