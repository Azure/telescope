"""Tests for isolation target stimulus verification."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    REPO_ROOT
    / "modules"
    / "python"
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "isolation-churn.sh"
)
SCALE_PATH = SCRIPT.parents[1] / "scale.py"
SPEC = importlib.util.spec_from_file_location("clustermesh_scale", SCALE_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"Unable to load {SCALE_PATH}")
SCALE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCALE)


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_target(tmp_path, killer_output, killer_rc=0):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "kubectl",
        """#!/bin/bash
set -euo pipefail
if [[ "$*" == *"config current-context"* ]]; then
  echo clustermesh-1
  exit 0
fi
exit 1
""",
    )
    killer = tmp_path / "killer.sh"
    _write_executable(
        killer,
        f"""#!/bin/bash
printf '%s\\n' {killer_output!r}
exit {killer_rc}
""",
    )
    report_dir = tmp_path / "report"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "POD_CHURN_KILLER_SCRIPT": str(killer),
        }
    )
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "clustermesh-1",
            "10",
            "1",
            "5",
            "clustermesh-isolation",
            str(report_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    timing_path = report_dir / "IsolationChurnTimings_clustermesh-1.json"
    return result, json.loads(timing_path.read_text(encoding="utf-8"))


def test_target_requires_nonzero_verified_deletions(tmp_path):
    result, timing = _run_target(
        tmp_path,
        "killer: done duration=10s rounds=3 cumulative=15",
    )

    assert result.returncode == 0
    assert timing["stimulus_valid"] is True
    assert timing["rounds"] == 3
    assert timing["killed_total"] == 15


def test_target_rejects_zero_deletions(tmp_path):
    result, timing = _run_target(
        tmp_path,
        "killer: done duration=10s rounds=3 cumulative=0",
    )

    assert result.returncode == 1
    assert timing["stimulus_valid"] is False
    assert timing["killed_total"] == 0


def test_collect_emits_isolation_churn_summary(tmp_path):
    timing = {
        "target_context": "clustermesh-1",
        "rounds": 3,
        "killed_total": 15,
        "killer_exit_code": 0,
        "stimulus_valid": True,
    }
    (tmp_path / "IsolationChurnTimings_clustermesh-1.json").write_text(
        json.dumps(timing),
        encoding="utf-8",
    )
    result_file = tmp_path / "results.jsonl"
    result_file.write_text("", encoding="utf-8")
    template = {"status": "success", "cluster": "mesh-1"}

    SCALE._emit_isolation_churn_timing_rows(  # pylint: disable=protected-access
        str(tmp_path),
        template,
        str(result_file),
    )

    row = json.loads(result_file.read_text(encoding="utf-8"))
    assert row["measurement"] == "IsolationChurnSummary"
    assert row["result"]["data"]["killed_total"] == 15
