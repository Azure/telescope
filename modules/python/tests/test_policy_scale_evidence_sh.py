"""Tests for config/policy-scale-evidence.sh (active + deleted phases).

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
    / "policy-scale-evidence.sh"
)


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_script_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"bash -n failed: stderr={result.stderr}"


def _fake_kubectl(counts_dir, namespaces):
    """Builds a fake kubectl backed by per-namespace count files under
    `counts_dir` (one file per namespace, named "<ns>.count", containing an
    integer). `namespaces` is the list of clustermesh-pscale-* namespace
    names to report from `get ns`."""
    ns_lines = "\n".join(f'  echo "namespace/{ns}"' for ns in namespaces)
    return f"""#!/bin/bash
if [ "$1" = "get" ] && [ "$2" = "ns" ]; then
{ns_lines}
  echo "namespace/kube-system"
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "ciliumnetworkpolicies" ]; then
  ns=""
  prev=""
  for a in "$@"; do
    if [ "$prev" = "-n" ]; then ns="$a"; fi
    prev="$a"
  done
  count=$(cat "{counts_dir}/${{ns}}.count" 2>/dev/null || echo 0)
  for i in $(seq 1 "$count"); do echo "cnp$i"; done
  exit 0
fi
exit 0
"""


def _set_counts(counts_dir, counts_by_ns):
    counts_dir.mkdir(parents=True, exist_ok=True)
    for ns, count in counts_by_ns.items():
        (counts_dir / f"{ns}.count").write_text(str(count), encoding="utf-8")


def _run(tmp_path, phase, namespaces, cnp_per_namespace, kubectl_script,
         report_path=None, poll_timeout=2):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    _write_executable(fake_bin / "kubectl", kubectl_script)
    if report_path is None:
        report_path = tmp_path / "PolicyScaleEvidence.json"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        [
            "bash", str(SCRIPT), phase,
            str(namespaces), str(cnp_per_namespace), str(report_path), str(poll_timeout),
        ],
        check=False, capture_output=True, text=True, env=env, timeout=30,
    )
    return result, report_path


def test_active_phase_exact_counts_pass(tmp_path):
    ns_names = ["clustermesh-pscale-1", "clustermesh-pscale-2"]
    counts_dir = tmp_path / "counts"
    _set_counts(counts_dir, {"clustermesh-pscale-1": 3, "clustermesh-pscale-2": 3})
    kubectl = _fake_kubectl(counts_dir, ns_names)

    result, report_path = _run(tmp_path, "active", 2, 3, kubectl)

    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(report_path.read_text())
    assert data["active"]["verified"] is True
    assert data["active"]["observed_total"] == 6
    assert data["active"]["expected_total"] == 6
    assert data["active"]["namespace_counts"] == {
        "clustermesh-pscale-1": 3, "clustermesh-pscale-2": 3,
    }
    assert data["deleted"] is None


def test_active_phase_per_namespace_mismatch_fails(tmp_path):
    ns_names = ["clustermesh-pscale-1", "clustermesh-pscale-2"]
    counts_dir = tmp_path / "counts"
    # Namespace 2 only has 2 CNPs instead of the expected 3 -> total is
    # short by 1 even though it could coincidentally match elsewhere.
    _set_counts(counts_dir, {"clustermesh-pscale-1": 3, "clustermesh-pscale-2": 2})
    kubectl = _fake_kubectl(counts_dir, ns_names)

    result, report_path = _run(tmp_path, "active", 2, 3, kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["active"]["verified"] is False
    assert data["active"]["observed_total"] == 5
    assert data["active"]["namespace_counts"]["clustermesh-pscale-2"] == 2


def test_active_phase_missing_namespace_fails(tmp_path):
    # Only one of the two expected namespaces exists at all.
    ns_names = ["clustermesh-pscale-1"]
    counts_dir = tmp_path / "counts"
    _set_counts(counts_dir, {"clustermesh-pscale-1": 3})
    kubectl = _fake_kubectl(counts_dir, ns_names)

    result, report_path = _run(tmp_path, "active", 2, 3, kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["active"]["verified"] is False
    assert data["active"]["observed_namespace_count"] == 1
    assert data["active"]["expected_namespace_count"] == 2


def test_deleted_phase_zero_remaining_passes(tmp_path):
    ns_names = ["clustermesh-pscale-1", "clustermesh-pscale-2"]
    counts_dir = tmp_path / "counts"
    _set_counts(counts_dir, {"clustermesh-pscale-1": 3, "clustermesh-pscale-2": 3})
    kubectl = _fake_kubectl(counts_dir, ns_names)

    active_result, report_path = _run(tmp_path, "active", 2, 3, kubectl)
    assert active_result.returncode == 0

    _set_counts(counts_dir, {"clustermesh-pscale-1": 0, "clustermesh-pscale-2": 0})
    deleted_result, report_path = _run(
        tmp_path, "deleted", 2, 3, kubectl, report_path=report_path,
    )

    assert deleted_result.returncode == 0, deleted_result.stdout + deleted_result.stderr
    data = json.loads(report_path.read_text())
    assert data["deleted"]["verified"] is True
    assert data["deleted"]["observed_count"] == 0
    # Active section must still be present after the merge.
    assert data["active"]["verified"] is True
    # Sidecar cleaned up.
    assert not (Path(str(report_path) + ".active-section.json")).exists()


def test_deleted_phase_nonzero_remaining_fails(tmp_path):
    ns_names = ["clustermesh-pscale-1", "clustermesh-pscale-2"]
    counts_dir = tmp_path / "counts"
    _set_counts(counts_dir, {"clustermesh-pscale-1": 3, "clustermesh-pscale-2": 3})
    kubectl = _fake_kubectl(counts_dir, ns_names)

    active_result, report_path = _run(tmp_path, "active", 2, 3, kubectl)
    assert active_result.returncode == 0

    # Simulate a stuck/leaked CNP: namespace 1 never reaches zero.
    _set_counts(counts_dir, {"clustermesh-pscale-1": 1, "clustermesh-pscale-2": 0})
    deleted_result, report_path = _run(
        tmp_path, "deleted", 2, 3, kubectl, report_path=report_path, poll_timeout=1,
    )

    assert deleted_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["deleted"]["verified"] is False
    assert data["deleted"]["observed_count"] == 1


def test_deleted_phase_without_prior_active_fails_cleanly(tmp_path):
    ns_names = ["clustermesh-pscale-1"]
    counts_dir = tmp_path / "counts"
    _set_counts(counts_dir, {"clustermesh-pscale-1": 0})
    kubectl = _fake_kubectl(counts_dir, ns_names)

    result, report_path = _run(tmp_path, "deleted", 1, 3, kubectl)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["active"] is None
    assert data.get("error") == "missing_active_sidecar"


# ---------------------------------------------------------------------------
# Individual kubectl-query failures must never be coerced into a numeric
# zero CNPs / zero namespaces / verified=true — see policy-scale-evidence.sh's
# discover_namespaces/count_cnp_in_namespace comments for why a naive
# `kubectl ... 2>/dev/null | wc -l` false-passes here.
# ---------------------------------------------------------------------------

def _failing_kubectl(fail_on, ns_names, counts_by_ns=None):
    """Builds a fake kubectl where exactly one of the underlying queries
    ("ns" for namespace discovery, "cnp" for the CiliumNetworkPolicy count)
    always fails (nonzero exit + stderr message)."""
    counts_by_ns = counts_by_ns or {}
    ns_lines = "\n".join(f'  echo "namespace/{ns}"' for ns in ns_names)
    case_lines = "".join(
        f'    {ns}) count={counts_by_ns.get(ns, 0)} ;;\n' for ns in ns_names
    )
    return f"""#!/bin/bash
if [ "$1" = "get" ] && [ "$2" = "ns" ]; then
  if [ "{fail_on}" = "ns" ]; then
    echo "boom: apiserver unreachable (get ns)" >&2
    exit 1
  fi
{ns_lines}
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "ciliumnetworkpolicies" ]; then
  if [ "{fail_on}" = "cnp" ]; then
    echo "boom: apiserver unreachable (get cnp)" >&2
    exit 1
  fi
  ns=""
  prev=""
  for a in "$@"; do
    if [ "$prev" = "-n" ]; then ns="$a"; fi
    prev="$a"
  done
  count=0
  case "$ns" in
{case_lines}
  esac
  for i in $(seq 1 "$count"); do echo "cnp$i"; done
  exit 0
fi
exit 0
"""


def test_active_phase_namespace_discovery_failure_never_passes(tmp_path):
    ns_names = ["clustermesh-pscale-1", "clustermesh-pscale-2"]
    kubectl = _failing_kubectl("ns", ns_names, {"clustermesh-pscale-1": 3, "clustermesh-pscale-2": 3})

    result, report_path = _run(tmp_path, "active", 2, 3, kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["active"]["verified"] is False
    assert data["active"]["query_success"] is False
    assert "boom" in data["active"]["query_errors"]["namespace_discovery"]
    # Discovery failed outright -- must not be reported as "0 matching
    # namespaces found" being indistinguishable from a real empty result.
    assert data["active"]["observed_namespace_count"] == 0


def test_active_phase_cnp_query_failure_never_passes_as_zero(tmp_path):
    # Regression test: CNP_PER_NAMESPACE=0 is the critical case -- if a
    # failed per-namespace CNP query were silently coerced to 0 (the old
    # `kubectl ... 2>/dev/null | wc -l` bug), 0 would exactly equal the
    # expected per-namespace count and the phase would false-pass as
    # "verified" even though kubectl never actually confirmed anything.
    ns_names = ["clustermesh-pscale-1", "clustermesh-pscale-2"]
    kubectl = _failing_kubectl("cnp", ns_names, {"clustermesh-pscale-1": 0, "clustermesh-pscale-2": 0})

    result, report_path = _run(tmp_path, "active", 2, 0, kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["active"]["observed_total"] == 0
    assert data["active"]["expected_total"] == 0
    # Despite the numeric total matching exactly, verified must be False
    # because the underlying queries never actually succeeded.
    assert data["active"]["verified"] is False
    assert data["active"]["query_success"] is False
    assert "boom" in data["active"]["query_errors"]["namespace_counts"]["clustermesh-pscale-1"]
    assert "boom" in data["active"]["query_errors"]["namespace_counts"]["clustermesh-pscale-2"]


def test_deleted_phase_persistent_cnp_api_failure_not_accepted_as_zero(tmp_path):
    # This is the critical regression test: for the deleted phase, "0 CNPs
    # remaining" IS the success condition, so a query failure silently
    # coerced to 0 would be indistinguishable from confirmed deletion.
    ns_names = ["clustermesh-pscale-1", "clustermesh-pscale-2"]
    active_kubectl = _failing_kubectl("none", ns_names, {"clustermesh-pscale-1": 3, "clustermesh-pscale-2": 3})
    active_result, report_path = _run(tmp_path, "active", 2, 3, active_kubectl)
    assert active_result.returncode == 0

    deleted_kubectl = _failing_kubectl("cnp", ns_names, {"clustermesh-pscale-1": 0, "clustermesh-pscale-2": 0})
    deleted_result, report_path = _run(
        tmp_path, "deleted", 2, 3, deleted_kubectl, report_path=report_path, poll_timeout=1,
    )

    assert deleted_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["deleted"]["observed_count"] == 0
    # The observed count numerically looks like a clean deletion, but the
    # query never actually succeeded -- verified must be False.
    assert data["deleted"]["verified"] is False
    assert data["deleted"]["query_success"] is False
    assert "boom" in data["deleted"]["query_error"]
    # Active section must still be preserved through the merge.
    assert data["active"]["verified"] is True


def test_deleted_phase_persistent_namespace_discovery_failure_not_accepted_as_zero(tmp_path):
    ns_names = ["clustermesh-pscale-1", "clustermesh-pscale-2"]
    active_kubectl = _failing_kubectl("none", ns_names, {"clustermesh-pscale-1": 3, "clustermesh-pscale-2": 3})
    active_result, report_path = _run(tmp_path, "active", 2, 3, active_kubectl)
    assert active_result.returncode == 0

    deleted_kubectl = _failing_kubectl("ns", ns_names, {"clustermesh-pscale-1": 0, "clustermesh-pscale-2": 0})
    deleted_result, report_path = _run(
        tmp_path, "deleted", 2, 3, deleted_kubectl, report_path=report_path, poll_timeout=1,
    )

    assert deleted_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["deleted"]["verified"] is False
    assert data["deleted"]["query_success"] is False
    assert "boom" in data["deleted"]["query_error"]
