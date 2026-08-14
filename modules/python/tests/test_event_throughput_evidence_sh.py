"""Tests for config/event-throughput-evidence.sh (capture + verify phases).

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
    / "event-throughput-evidence.sh"
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


def _fake_kubectl(state_path, deployment_count, replicas_per_deployment, generation):
    """Builds a fake kubectl that reports `deployment_count` Deployments each
    with `replicas_per_deployment` Ready pods, and a pod-template
    restart-generation annotation read from `state_path` (so a test can flip
    pre- vs post-restart behavior between capture/verify invocations without
    rewriting the script)."""
    pod_count = deployment_count * replicas_per_deployment
    return f"""#!/bin/bash
STATE=$(cat {state_path} 2>/dev/null || echo pre)
ARGS="$*"
if [[ "$ARGS" == *"restart-generation"* ]]; then
  GEN=0
  if [ "$STATE" = "post" ]; then GEN={generation}; fi
  for i in $(seq 1 {deployment_count}); do echo "$GEN"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "deployments" ]; then
  for i in $(seq 1 {deployment_count}); do echo "ns$i dep$i 1/1 1 1 1d"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  if [[ "$ARGS" == *"status.conditions"* ]]; then
    for i in $(seq 1 {pod_count}); do echo "True"; done
    exit 0
  fi
  if [[ "$ARGS" == *"metadata.uid"* ]]; then
    for i in $(seq 1 {pod_count}); do echo "${{STATE}}-uid-$i"; done
    exit 0
  fi
  for i in $(seq 1 {pod_count}); do echo "ns$i pod$i 1/1 Running 0 1d"; done
  exit 0
fi
exit 0
"""


def _run(tmp_path, phase, namespaces, deployments_per_ns, replicas_per_deployment,
         generation=1, group="clustermesh-event-throughput", report_path=None,
         poll_timeout=5, kubectl_script=None):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    if kubectl_script is not None:
        _write_executable(fake_bin / "kubectl", kubectl_script)
    if report_path is None:
        report_path = tmp_path / "EventThroughputEvidence.json"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        [
            "bash", str(SCRIPT), phase,
            str(namespaces), str(deployments_per_ns), str(replicas_per_deployment),
            group, str(generation), str(report_path), str(poll_timeout),
        ],
        check=False, capture_output=True, text=True, env=env, timeout=30,
    )
    return result, report_path


def test_capture_phase_valid_counts_passes(tmp_path):
    state = tmp_path / "state"
    state.write_text("pre")
    kubectl = _fake_kubectl(state, deployment_count=4, replicas_per_deployment=3, generation=1)

    result, report_path = _run(tmp_path, "capture", 2, 2, 3, kubectl_script=kubectl)

    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(report_path.read_text())
    assert data["capture_valid"] is True
    assert data["pre_restart"]["deployment_count"] == 4
    assert data["pre_restart"]["pod_count"] == 12
    assert data["pre_restart"]["ready_pod_count"] == 12
    assert len(data["pre_restart"]["pod_uids"]) == 12
    assert data["pre_restart"]["generation"] == 0
    assert data["post_restart"] is None


def test_capture_phase_missing_deployment_fails(tmp_path):
    state = tmp_path / "state"
    state.write_text("pre")
    # Only 3 deployments present but 4 expected (2 ns * 2 per-ns).
    kubectl = _fake_kubectl(state, deployment_count=3, replicas_per_deployment=3, generation=1)

    result, report_path = _run(tmp_path, "capture", 2, 2, 3, kubectl_script=kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["capture_valid"] is False
    assert data["pre_restart"]["deployment_count"] == 3
    assert data["pre_restart"]["expected_deployment_count"] == 4


def test_verify_phase_valid_restart_passes(tmp_path):
    state = tmp_path / "state"
    state.write_text("pre")
    kubectl = _fake_kubectl(state, deployment_count=4, replicas_per_deployment=3, generation=1)

    cap_result, report_path = _run(tmp_path, "capture", 2, 2, 3, generation=1, kubectl_script=kubectl)
    assert cap_result.returncode == 0

    state.write_text("post")
    ver_result, report_path = _run(
        tmp_path, "verify", 2, 2, 3, generation=1, report_path=report_path, kubectl_script=kubectl,
    )

    assert ver_result.returncode == 0, ver_result.stdout + ver_result.stderr
    data = json.loads(report_path.read_text())
    assert data["restart_valid"] is True
    assert data["post_restart"]["restart_generation_verified"] is True
    assert data["post_restart"]["pre_post_uid_overlap_count"] == 0
    # Sidecars must be cleaned up after a successful merge.
    assert not (Path(str(report_path) + ".pre.env")).exists()
    assert not (Path(str(report_path) + ".pre-uids.txt")).exists()


def test_verify_phase_detects_uid_overlap(tmp_path):
    state = tmp_path / "state"
    state.write_text("pre")
    kubectl = _fake_kubectl(state, deployment_count=4, replicas_per_deployment=3, generation=1)

    cap_result, report_path = _run(tmp_path, "capture", 2, 2, 3, generation=1, kubectl_script=kubectl)
    assert cap_result.returncode == 0

    # State stays "pre" for verify too -> identical UIDs are reported both
    # times, simulating pods that were never actually recreated.
    ver_result, report_path = _run(
        tmp_path, "verify", 2, 2, 3, generation=1, report_path=report_path, kubectl_script=kubectl,
    )

    assert ver_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["restart_valid"] is False
    assert data["post_restart"]["pre_post_uid_overlap_count"] == 12


def test_verify_phase_detects_generation_not_bumped(tmp_path):
    state = tmp_path / "state"
    state.write_text("pre")
    # generation never becomes 1 post-restart (always reports 0).
    kubectl = f"""#!/bin/bash
ARGS="$*"
if [[ "$ARGS" == *"restart-generation"* ]]; then
  for i in 1 2 3 4; do echo "0"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "deployments" ]; then
  for i in 1 2 3 4; do echo "ns$i dep$i 1/1 1 1 1d"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  if [[ "$ARGS" == *"status.conditions"* ]]; then
    for i in $(seq 1 12); do echo "True"; done
    exit 0
  fi
  if [[ "$ARGS" == *"metadata.uid"* ]]; then
    STATE=$(cat {state} 2>/dev/null || echo pre)
    for i in $(seq 1 12); do echo "${{STATE}}-uid-$i"; done
    exit 0
  fi
  for i in $(seq 1 12); do echo "ns$i pod$i 1/1 Running 0 1d"; done
  exit 0
fi
exit 0
"""

    cap_result, report_path = _run(tmp_path, "capture", 2, 2, 3, generation=1, kubectl_script=kubectl)
    assert cap_result.returncode == 0

    state.write_text("post")
    ver_result, report_path = _run(
        tmp_path, "verify", 2, 2, 3, generation=1, report_path=report_path, kubectl_script=kubectl,
    )

    assert ver_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["restart_valid"] is False
    assert data["post_restart"]["restart_generation_verified"] is False


def test_verify_phase_without_prior_capture_fails_cleanly(tmp_path):
    state = tmp_path / "state"
    state.write_text("post")
    kubectl = _fake_kubectl(state, deployment_count=4, replicas_per_deployment=3, generation=1)

    result, report_path = _run(tmp_path, "verify", 2, 2, 3, generation=1, kubectl_script=kubectl)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["capture_valid"] is False
    assert data["restart_valid"] is False
    assert data.get("error") == "missing_capture_sidecar"


def test_kubectl_missing_exits_127(tmp_path):
    fake_bin = tmp_path / "empty-bin"
    fake_bin.mkdir()
    env = os.environ.copy()
    # Only keep bash's own directory on PATH (dropping /usr/local/bin,
    # /usr/bin/kubectl, etc.) so kubectl is genuinely unresolvable.
    bash_dir = str(Path(subprocess.run(["which", "bash"], capture_output=True, text=True, check=True).stdout.strip()).parent)
    env["PATH"] = f"{fake_bin}:{bash_dir}"
    report_path = tmp_path / "EventThroughputEvidence.json"
    result = subprocess.run(
        ["bash", str(SCRIPT), "capture", "2", "2", "3",
         "clustermesh-event-throughput", "1", str(report_path), "1"],
        check=False, capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 127


# ---------------------------------------------------------------------------
# Individual kubectl-query failures must never be coerced into a numeric
# zero / empty-set / verified=true — see event-throughput-evidence.sh's
# count_*/pod_uids_sorted comments for why a naive
# `kubectl ... 2>/dev/null | wc -l` false-passes here.
# ---------------------------------------------------------------------------

def _failing_kubectl(fail_query, deployment_count=4, replicas_per_deployment=3, generation=1):
    """Builds a fake kubectl where exactly one of the underlying queries
    ("deployments", "pods_total", "pods_ready", "uids", "generation")
    always fails (nonzero exit + stderr message); every other query
    returns a fully matching, otherwise-valid result."""
    pod_count = deployment_count * replicas_per_deployment
    return f"""#!/bin/bash
ARGS="$*"
if [ "$1" = "get" ] && [ "$2" = "deployments" ] && [[ "$ARGS" == *"restart-generation"* ]]; then
  if [ "{fail_query}" = "generation" ]; then
    echo "boom: apiserver unreachable (restart-generation query)" >&2
    exit 1
  fi
  for i in $(seq 1 {deployment_count}); do echo "{generation}"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "deployments" ]; then
  if [ "{fail_query}" = "deployments" ]; then
    echo "boom: connection refused (deployments query)" >&2
    exit 1
  fi
  for i in $(seq 1 {deployment_count}); do echo "ns$i dep$i 1/1 1 1 1d"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  if [[ "$ARGS" == *"metadata.uid"* ]]; then
    if [ "{fail_query}" = "uids" ]; then
      echo "boom: etcd timeout (uid query)" >&2
      exit 1
    fi
    for i in $(seq 1 {pod_count}); do echo "uid-$i"; done
    exit 0
  fi
  if [[ "$ARGS" == *"status.conditions"* ]]; then
    if [ "{fail_query}" = "pods_ready" ]; then
      echo "boom: server error (readiness query)" >&2
      exit 1
    fi
    for i in $(seq 1 {pod_count}); do echo "True"; done
    exit 0
  fi
  if [ "{fail_query}" = "pods_total" ]; then
    echo "boom: throttled (pods query)" >&2
    exit 1
  fi
  for i in $(seq 1 {pod_count}); do echo "ns$i pod$i 1/1 Running 0 1d"; done
  exit 0
fi
exit 0
"""


def test_capture_phase_failed_deployment_query_never_passes(tmp_path):
    kubectl = _failing_kubectl("deployments", deployment_count=4, replicas_per_deployment=3)

    result, report_path = _run(tmp_path, "capture", 2, 2, 3, kubectl_script=kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["capture_valid"] is False
    assert data["pre_restart"]["query_success"]["deployment_count"] is False
    # A failed query must not be coerced into 0 deployments -- the count
    # field stays at its never-observed placeholder, but the *_ok flag
    # (not the number) is what MUST gate validity.
    assert data["pre_restart"]["deployment_count"] == 0
    assert "boom" in data["pre_restart"]["query_errors"]["deployment_count"]


def test_capture_phase_failed_pod_total_query_never_passes(tmp_path):
    kubectl = _failing_kubectl("pods_total", deployment_count=4, replicas_per_deployment=3)

    result, report_path = _run(tmp_path, "capture", 2, 2, 3, kubectl_script=kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["capture_valid"] is False
    assert data["pre_restart"]["query_success"]["pod_count"] is False
    assert "boom" in data["pre_restart"]["query_errors"]["pod_count"]


def test_capture_phase_failed_ready_query_never_passes(tmp_path):
    kubectl = _failing_kubectl("pods_ready", deployment_count=4, replicas_per_deployment=3)

    result, report_path = _run(tmp_path, "capture", 2, 2, 3, kubectl_script=kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["capture_valid"] is False
    assert data["pre_restart"]["query_success"]["ready_pod_count"] is False
    assert "boom" in data["pre_restart"]["query_errors"]["ready_pod_count"]


def test_capture_phase_failed_uid_query_never_passes_even_with_exact_counts(tmp_path):
    # Regression test: deployment/pod/ready counts all EXACTLY match the
    # expected values -- only the UID query fails. Previously this false-
    # passed because the failed query's empty output was written straight
    # to the UID sidecar file (an empty UID set), which capture_valid never
    # even considered.
    kubectl = _failing_kubectl("uids", deployment_count=4, replicas_per_deployment=3)

    result, report_path = _run(tmp_path, "capture", 2, 2, 3, kubectl_script=kubectl, poll_timeout=1)

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["pre_restart"]["deployment_count"] == 4
    assert data["pre_restart"]["pod_count"] == 12
    assert data["pre_restart"]["ready_pod_count"] == 12
    assert data["capture_valid"] is False
    assert data["pre_restart"]["query_success"]["pod_uids"] is False
    assert data["pre_restart"]["pod_uids"] == []
    assert "boom" in data["pre_restart"]["query_errors"]["pod_uids"]


def test_capture_phase_partial_uid_output_never_passes(tmp_path):
    # Regression test: deployment/pod/ready counts all EXACTLY match the
    # expected values, and the UID query itself succeeds (exit 0) -- but it
    # only returns 11 UID lines for 12 expected pods (e.g. one pod's UID
    # jsonpath came back empty due to a stale/incomplete API response).
    # Previously this false-passed because capture_valid never compared the
    # UID list's length against EXPECTED_POD_COUNT, only checking pod/ready
    # counts from separate queries.
    deployment_count, replicas_per_deployment = 4, 3
    pod_count = deployment_count * replicas_per_deployment  # 12
    kubectl = f"""#!/bin/bash
ARGS="$*"
if [ "$1" = "get" ] && [ "$2" = "deployments" ]; then
  for i in $(seq 1 {deployment_count}); do echo "ns$i dep$i 1/1 1 1 1d"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  if [[ "$ARGS" == *"metadata.uid"* ]]; then
    for i in $(seq 1 {pod_count - 1}); do echo "uid-$i"; done
    exit 0
  fi
  if [[ "$ARGS" == *"status.conditions"* ]]; then
    for i in $(seq 1 {pod_count}); do echo "True"; done
    exit 0
  fi
  for i in $(seq 1 {pod_count}); do echo "ns$i pod$i 1/1 Running 0 1d"; done
  exit 0
fi
exit 0
"""

    result, report_path = _run(
        tmp_path, "capture", 2, 2, replicas_per_deployment, kubectl_script=kubectl, poll_timeout=1,
    )

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["pre_restart"]["deployment_count"] == 4
    assert data["pre_restart"]["pod_count"] == 12
    assert data["pre_restart"]["ready_pod_count"] == 12
    # The UID query itself succeeded -- it just returned too few entries.
    assert data["pre_restart"]["query_success"]["pod_uids"] is True
    assert data["pre_restart"]["uid_count"] == 11
    assert data["pre_restart"]["unique_uid_count"] == 11
    assert len(data["pre_restart"]["pod_uids"]) == 11
    assert data["capture_valid"] is False


def test_capture_phase_duplicate_uids_never_passes(tmp_path):
    # Regression test: deployment/pod/ready counts all EXACTLY match the
    # expected values, and the UID query returns exactly 12 lines for 12
    # expected pods -- but one UID is duplicated (only 11 unique values),
    # meaning one real pod's identity was never actually observed.
    # Previously this false-passed because capture_valid never checked
    # uniqueness, only that the UID list was non-empty.
    deployment_count, replicas_per_deployment = 4, 3
    pod_count = deployment_count * replicas_per_deployment  # 12
    kubectl = f"""#!/bin/bash
ARGS="$*"
if [ "$1" = "get" ] && [ "$2" = "deployments" ]; then
  for i in $(seq 1 {deployment_count}); do echo "ns$i dep$i 1/1 1 1 1d"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  if [[ "$ARGS" == *"metadata.uid"* ]]; then
    for i in $(seq 1 {pod_count - 1}); do echo "uid-$i"; done
    echo "uid-1"
    exit 0
  fi
  if [[ "$ARGS" == *"status.conditions"* ]]; then
    for i in $(seq 1 {pod_count}); do echo "True"; done
    exit 0
  fi
  for i in $(seq 1 {pod_count}); do echo "ns$i pod$i 1/1 Running 0 1d"; done
  exit 0
fi
exit 0
"""

    result, report_path = _run(
        tmp_path, "capture", 2, 2, replicas_per_deployment, kubectl_script=kubectl, poll_timeout=1,
    )

    assert result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["pre_restart"]["deployment_count"] == 4
    assert data["pre_restart"]["pod_count"] == 12
    assert data["pre_restart"]["ready_pod_count"] == 12
    assert data["pre_restart"]["query_success"]["pod_uids"] is True
    # 12 lines returned, but only 11 distinct UIDs among them.
    assert data["pre_restart"]["uid_count"] == 12
    assert data["pre_restart"]["unique_uid_count"] == 11
    assert data["capture_valid"] is False


def test_verify_phase_partial_uid_output_never_passes(tmp_path):
    # Same partial-UID regression as capture, but at the verify/post-restart
    # phase: pre-restart capture is fully valid, but the post-restart UID
    # query returns one fewer UID than EXPECTED_POD_COUNT.
    state = tmp_path / "state"
    state.write_text("pre")
    cap_kubectl = _fake_kubectl(state, deployment_count=4, replicas_per_deployment=3, generation=1)
    cap_result, report_path = _run(tmp_path, "capture", 2, 2, 3, generation=1, kubectl_script=cap_kubectl)
    assert cap_result.returncode == 0

    ver_kubectl = """#!/bin/bash
ARGS="$*"
if [[ "$ARGS" == *"restart-generation"* ]]; then
  for i in 1 2 3 4; do echo "1"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "deployments" ]; then
  for i in 1 2 3 4; do echo "ns$i dep$i 1/1 1 1 1d"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  if [[ "$ARGS" == *"metadata.uid"* ]]; then
    for i in $(seq 1 11); do echo "post-uid-$i"; done
    exit 0
  fi
  if [[ "$ARGS" == *"status.conditions"* ]]; then
    for i in $(seq 1 12); do echo "True"; done
    exit 0
  fi
  for i in $(seq 1 12); do echo "ns$i pod$i 1/1 Running 0 1d"; done
  exit 0
fi
exit 0
"""
    ver_result, report_path = _run(
        tmp_path, "verify", 2, 2, 3, generation=1, report_path=report_path, kubectl_script=ver_kubectl,
    )

    assert ver_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["restart_valid"] is False
    assert data["post_restart"]["query_success"]["pod_uids"] is True
    assert data["post_restart"]["uid_count"] == 11
    assert data["post_restart"]["unique_uid_count"] == 11


def test_verify_phase_duplicate_uids_never_passes(tmp_path):
    # Same duplicate-UID regression as capture, but for the post-restart
    # snapshot: exactly 12 lines returned, but one UID repeated so only 11
    # are unique.
    state = tmp_path / "state"
    state.write_text("pre")
    cap_kubectl = _fake_kubectl(state, deployment_count=4, replicas_per_deployment=3, generation=1)
    cap_result, report_path = _run(tmp_path, "capture", 2, 2, 3, generation=1, kubectl_script=cap_kubectl)
    assert cap_result.returncode == 0

    ver_kubectl = """#!/bin/bash
ARGS="$*"
if [[ "$ARGS" == *"restart-generation"* ]]; then
  for i in 1 2 3 4; do echo "1"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "deployments" ]; then
  for i in 1 2 3 4; do echo "ns$i dep$i 1/1 1 1 1d"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  if [[ "$ARGS" == *"metadata.uid"* ]]; then
    for i in $(seq 1 11); do echo "post-uid-$i"; done
    echo "post-uid-1"
    exit 0
  fi
  if [[ "$ARGS" == *"status.conditions"* ]]; then
    for i in $(seq 1 12); do echo "True"; done
    exit 0
  fi
  for i in $(seq 1 12); do echo "ns$i pod$i 1/1 Running 0 1d"; done
  exit 0
fi
exit 0
"""
    ver_result, report_path = _run(
        tmp_path, "verify", 2, 2, 3, generation=1, report_path=report_path, kubectl_script=ver_kubectl,
    )

    assert ver_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["restart_valid"] is False
    assert data["post_restart"]["query_success"]["pod_uids"] is True
    assert data["post_restart"]["uid_count"] == 12
    assert data["post_restart"]["unique_uid_count"] == 11


def test_verify_phase_failed_generation_query_never_passes(tmp_path):
    # Regression test: deployment/pod/ready counts converge post-restart and
    # UIDs don't overlap -- only the restart-generation jsonpath query
    # fails. Previously this false-passed because grep -vc on the query's
    # empty (suppressed-error) output reported 0 mismatches, which looked
    # identical to "every Deployment matches the configured generation".
    state = tmp_path / "state"
    state.write_text("pre")
    cap_kubectl = _failing_kubectl("none", deployment_count=4, replicas_per_deployment=3)
    cap_result, report_path = _run(tmp_path, "capture", 2, 2, 3, generation=1, kubectl_script=cap_kubectl)
    assert cap_result.returncode == 0

    ver_kubectl = """#!/bin/bash
ARGS="$*"
if [[ "$ARGS" == *"restart-generation"* ]]; then
  echo "boom: apiserver unreachable (restart-generation query)" >&2
  exit 1
fi
if [ "$1" = "get" ] && [ "$2" = "deployments" ]; then
  for i in $(seq 1 4); do echo "ns$i dep$i 1/1 1 1 1d"; done
  exit 0
fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  if [[ "$ARGS" == *"metadata.uid"* ]]; then
    for i in $(seq 1 12); do echo "post-uid-$i"; done
    exit 0
  fi
  if [[ "$ARGS" == *"status.conditions"* ]]; then
    for i in $(seq 1 12); do echo "True"; done
    exit 0
  fi
  for i in $(seq 1 12); do echo "ns$i pod$i 1/1 Running 0 1d"; done
  exit 0
fi
exit 0
"""
    ver_result, report_path = _run(
        tmp_path, "verify", 2, 2, 3, generation=1, report_path=report_path, kubectl_script=ver_kubectl,
    )

    assert ver_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["restart_valid"] is False
    assert data["post_restart"]["query_success"]["generation"] is False
    assert data["post_restart"]["restart_generation_verified"] is False
    assert "boom" in data["post_restart"]["query_errors"]["generation"]


def test_verify_phase_failed_uid_query_never_passes_as_zero_overlap(tmp_path):
    # Regression test: the post-restart UID query fails outright. Previously
    # this false-passed as "0 overlap" because `comm -12` against an empty
    # (suppressed-error) post-UIDs file always reports zero matches -- a
    # failed query must never be indistinguishable from "verified: every
    # pod was recreated".
    state = tmp_path / "state"
    state.write_text("pre")
    cap_kubectl = _failing_kubectl("none", deployment_count=4, replicas_per_deployment=3)
    cap_result, report_path = _run(tmp_path, "capture", 2, 2, 3, generation=1, kubectl_script=cap_kubectl)
    assert cap_result.returncode == 0

    ver_kubectl = _failing_kubectl("uids", deployment_count=4, replicas_per_deployment=3, generation=1)
    ver_result, report_path = _run(
        tmp_path, "verify", 2, 2, 3, generation=1, report_path=report_path, kubectl_script=ver_kubectl,
    )

    assert ver_result.returncode == 1
    data = json.loads(report_path.read_text())
    assert data["restart_valid"] is False
    assert data["post_restart"]["query_success"]["pod_uids"] is False
    assert data["post_restart"]["pre_post_uid_overlap_count"] == 0
    assert "boom" in data["post_restart"]["query_errors"]["pod_uids"]
