"""Tests for propagation-probe.sh's workload-readiness barrier.

Target script: modules/python/clusterloader2/clustermesh-scale/config/propagation-probe.sh

Build 74164 evidence: the host-side probe orchestrator relied on a FIXED
prewait sleep (execute.yml's CL2_PROBE_PREWAIT_S) before creating probe
Pods. That prewait ended while CL2 was still mid-setup (ACNS/Prometheus
configuration running concurrently), so all 3 probes ran before CL2 had
even created the propagation-probe backend Deployment/Service in every
cluster — every probe Pod got no IP and PropagationTimings.jsonl ended
up with 0 rows.

propagation-probe.sh now runs its own bounded workload-readiness barrier
(namespace + Deployment(group=clustermesh-propagation-probe, fully
available/updated) + Service(same label), per cluster in CLUSTERS_JSON)
BEFORE cilium preflight and any probe Pod creation. These tests exercise
that barrier in isolation via a fake `kubectl` on PATH (and, for the
timeout-related cases, fake `date`/`sleep` binaries that advance a
simulated clock so the tests are fast and deterministic rather than
depending on wall-clock time).

A purely static "is the barrier wired in before preflight" check would
not prove the retry/timeout/API-failure semantics actually work, so each
test here executes the real bash script end-to-end with a fake kubectl
standing in for the Kubernetes API.
"""

import json
import os
import stat
import subprocess
import textwrap
import time
from pathlib import Path


PROBE_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "propagation-probe.sh"
)

PROBE_NS = "clustermesh-probe-1"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _clusters_json(tmp_path: Path) -> Path:
    clusters = [
        {"name": "ctx0", "kubeconfig": str(tmp_path / "kc0"), "role": "mesh-1"},
        {"name": "ctx1", "kubeconfig": str(tmp_path / "kc1"), "role": "mesh-2"},
    ]
    path = tmp_path / "clusters.json"
    path.write_text(json.dumps(clusters), encoding="utf-8")
    return path


def _clusters_json_n(tmp_path: Path, n: int) -> Path:
    clusters = [
        {
            "name": f"ctx{i}",
            "kubeconfig": str(tmp_path / f"kc{i}"),
            "role": f"mesh-{i + 1}",
        }
        for i in range(n)
    ]
    path = tmp_path / "clusters.json"
    path.write_text(json.dumps(clusters), encoding="utf-8")
    return path


def _run_probe_script(tmp_path: Path, env_overrides: dict, timeout: int = 10):
    output_dir = tmp_path / "output"
    environment = os.environ.copy()
    environment.update(env_overrides)
    environment.setdefault("OUTPUT_DIR", str(output_dir))
    result = subprocess.run(
        [
            "bash",
            str(PROBE_SCRIPT),
            "1",  # PROBE_COUNT
            "1",  # PROBE_INTERVAL_S
            PROBE_NS,
            "1",  # PEER_SAMPLE_MAX
            "1",  # PEER_TIMEOUT_S
            str(env_overrides["CLUSTERS_JSON"]),
            str(output_dir),
            "false",  # ENABLE_CONNECTIVITY
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=timeout,
    )
    return result, output_dir


def test_workload_readiness_delayed_then_ready_proceeds_past_barrier(tmp_path):
    """Namespace/Deployment/Service are NOT ready for the first two polls,
    then become ready on the third — the barrier must retry rather than
    fail immediately, and once satisfied must proceed to cilium preflight
    (not silently skip it)."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    counter_file = tmp_path / "poll-count"
    counter_file.write_text("0", encoding="utf-8")
    fake_kubectl = fake_bin / "kubectl"
    _write_executable(
        fake_kubectl,
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        args="$*"

        # One increment per outer barrier iteration: cluster ctx0's
        # namespace check always fires first in each round.
        if [[ "$args" == *"--context ctx0 get namespace"* ]]; then
          c=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
          c=$((c + 1))
          echo "$c" > "$COUNTER_FILE"
        fi
        c=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
        ready=false
        [ "$c" -ge "$READY_AFTER" ] && ready=true

        if [[ "$args" == *"get namespace "* ]]; then
          $ready && exit 0 || exit 1
        elif [[ "$args" == *"get deployment -l group=clustermesh-propagation-probe -o json"* ]]; then
          if $ready; then
            printf '%s' '{"items":[{"metadata":{"name":"probe-dep"},"spec":{"replicas":1},"status":{"availableReplicas":1,"updatedReplicas":1}}]}'
          else
            printf '%s' '{"items":[]}'
          fi
        elif [[ "$args" == *"get svc -l group=clustermesh-propagation-probe -o json"* ]]; then
          if $ready; then
            printf '%s' '{"items":[{"metadata":{"name":"probe-svc"}}]}'
          else
            printf '%s' '{"items":[]}'
          fi
        elif [[ "$args" == *"-n kube-system get pod -l"* ]]; then
          # No Cilium pod anywhere — deliberately makes preflight fail so
          # the script exits quickly right after the barrier succeeds.
          printf ''
        else
          echo "Unexpected kubectl command: $args" >&2
          exit 1
        fi
        """,
    )

    clusters_json = _clusters_json(tmp_path)
    result, output_dir = _run_probe_script(
        tmp_path,
        {
            "CLUSTERS_JSON": str(clusters_json),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "COUNTER_FILE": str(counter_file),
            "READY_AFTER": "3",
            "PROBE_WORKLOAD_READY_TIMEOUT_S": "60",
            "PROBE_WORKLOAD_READY_POLL_S": "0",
        },
    )

    assert "workload-readiness barrier: satisfied on all 2 clusters" in result.stdout
    # Must have actually retried (not been ready on the very first poll).
    assert int(counter_file.read_text(encoding="utf-8").strip()) >= 3
    # Barrier success must lead to preflight running (and failing, since
    # no Cilium pod exists) — proves the barrier gates the next stage
    # rather than the script silently skipping straight to probing.
    assert "PREFLIGHT FAIL" in result.stderr
    assert result.returncode == 1
    assert (output_dir / "PropagationTimings.jsonl").read_text(
        encoding="utf-8"
    ) == ""


def test_workload_readiness_persistent_not_ready_times_out(tmp_path):
    """Namespace never appears on either cluster. Using fake date/sleep to
    advance a simulated clock (no real wall-clock wait), the barrier must
    give up once PROBE_WORKLOAD_READY_TIMEOUT_S elapses and fail with
    per-cluster diagnostics rather than hang or silently proceed."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    clock_file = tmp_path / "clock"
    clock_file.write_text("0", encoding="utf-8")

    fake_kubectl = fake_bin / "kubectl"
    _write_executable(
        fake_kubectl,
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        args="$*"
        if [[ "$args" == *"get namespace "* ]]; then
          exit 1
        else
          echo "Unexpected kubectl command: $args" >&2
          exit 1
        fi
        """,
    )
    fake_date = fake_bin / "date"
    _write_executable(
        fake_date,
        """\
        #!/usr/bin/env bash
        if [ "${1:-}" = "+%s" ]; then
          cat "$CLOCK_FILE"
        else
          exec /usr/bin/date "$@"
        fi
        """,
    )
    fake_sleep = fake_bin / "sleep"
    _write_executable(
        fake_sleep,
        """\
        #!/usr/bin/env bash
        cur=$(cat "$CLOCK_FILE")
        new=$(( cur + ${1%.*} ))
        echo "$new" > "$CLOCK_FILE"
        """,
    )

    clusters_json = _clusters_json(tmp_path)
    result, output_dir = _run_probe_script(
        tmp_path,
        {
            "CLUSTERS_JSON": str(clusters_json),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CLOCK_FILE": str(clock_file),
            "PROBE_WORKLOAD_READY_TIMEOUT_S": "30",
            "PROBE_WORKLOAD_READY_POLL_S": "10",
        },
    )

    assert result.returncode == 1
    assert "WORKLOAD-READINESS TIMEOUT after 30s" in result.stderr
    assert "cluster[0] (ctx0): namespace" in result.stderr
    assert "cluster[1] (ctx1): namespace" in result.stderr
    assert "not found" in result.stderr
    # Never reached preflight/probing.
    assert "PREFLIGHT" not in result.stderr
    assert (output_dir / "PropagationTimings.jsonl").read_text(
        encoding="utf-8"
    ) == ""
    # Simulated clock must have actually advanced to/past the deadline.
    assert int(clock_file.read_text(encoding="utf-8").strip()) >= 30


def test_workload_readiness_api_failure_is_not_accepted_as_ready(tmp_path):
    """Namespace exists, but the Deployment list call fails outright (API
    error: non-zero exit + empty output) on every poll. That must NOT be
    treated as "zero Deployments found" readiness-wise — it must be
    flagged as an API error and the cluster kept not-ready until the
    barrier times out."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    clock_file = tmp_path / "clock"
    clock_file.write_text("0", encoding="utf-8")

    fake_kubectl = fake_bin / "kubectl"
    _write_executable(
        fake_kubectl,
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        args="$*"
        if [[ "$args" == *"get namespace "* ]]; then
          exit 0
        elif [[ "$args" == *"get deployment -l group=clustermesh-propagation-probe -o json"* ]]; then
          # Simulate a transient API error: no stdout, non-zero exit.
          exit 1
        else
          echo "Unexpected kubectl command: $args" >&2
          exit 1
        fi
        """,
    )
    fake_date = fake_bin / "date"
    _write_executable(
        fake_date,
        """\
        #!/usr/bin/env bash
        if [ "${1:-}" = "+%s" ]; then
          cat "$CLOCK_FILE"
        else
          exec /usr/bin/date "$@"
        fi
        """,
    )
    fake_sleep = fake_bin / "sleep"
    _write_executable(
        fake_sleep,
        """\
        #!/usr/bin/env bash
        cur=$(cat "$CLOCK_FILE")
        new=$(( cur + ${1%.*} ))
        echo "$new" > "$CLOCK_FILE"
        """,
    )

    clusters_json = _clusters_json(tmp_path)
    result, output_dir = _run_probe_script(
        tmp_path,
        {
            "CLUSTERS_JSON": str(clusters_json),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CLOCK_FILE": str(clock_file),
            "PROBE_WORKLOAD_READY_TIMEOUT_S": "20",
            "PROBE_WORKLOAD_READY_POLL_S": "10",
        },
    )

    assert result.returncode == 1
    assert "WORKLOAD-READINESS TIMEOUT after 20s" in result.stderr
    assert (
        "cluster[0] (ctx0): API error listing Deployments "
        "(group=clustermesh-propagation-probe)" in result.stderr
    )
    assert (
        "cluster[1] (ctx1): API error listing Deployments "
        "(group=clustermesh-propagation-probe)" in result.stderr
    )
    assert (output_dir / "PropagationTimings.jsonl").read_text(
        encoding="utf-8"
    ) == ""


def test_workload_readiness_kills_hung_kubectl_within_bound(tmp_path):
    """A kubectl invocation that hangs (e.g. an unreachable apiserver or a
    stuck exec-credential plugin) must be killed within the configured
    process-timeout bound rather than block the barrier -- and therefore
    the whole host-side orchestrator -- indefinitely. Also asserts the
    server-side --request-timeout flag is actually passed through to
    kubectl."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    hung_log = tmp_path / "hung-kubectl.log"
    fake_kubectl = fake_bin / "kubectl"
    _write_executable(
        fake_kubectl,
        """\
        #!/usr/bin/env bash
        args="$*"
        # The unrelated best-effort probe-pod cleanup trap (EXIT) also
        # shells out to kubectl -- only the workload-readiness barrier's
        # own get-namespace/get-deployment/get-svc calls are under test
        # here, so let cleanup's delete calls return immediately instead
        # of hanging (keeps this test scoped to the barrier alone).
        if [[ "$args" == *"delete pod"* ]]; then
          exit 0
        fi
        printf '%s\\n' "$args" >> "$HUNG_KUBECTL_LOG"
        sleep 30
        """,
    )

    clusters_json = _clusters_json(tmp_path)
    environment_overrides = {
        "CLUSTERS_JSON": str(clusters_json),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HUNG_KUBECTL_LOG": str(hung_log),
        "PROBE_WORKLOAD_READY_TIMEOUT_S": "3",
        "PROBE_WORKLOAD_READY_POLL_S": "0",
        "PROBE_WORKLOAD_READY_KUBECTL_REQUEST_TIMEOUT_S": "1",
        "PROBE_WORKLOAD_READY_KUBECTL_PROCESS_TIMEOUT_S": "1",
    }

    started = time.monotonic()
    result, output_dir = _run_probe_script(
        tmp_path, environment_overrides, timeout=20
    )
    elapsed = time.monotonic() - started

    # The fake kubectl sleeps 30s per call -- if it were not bounded by
    # BOTH the outer process timeout AND kubectl's own --request-timeout,
    # this test would hang for a very long time (many hung calls back to
    # back) instead of finishing in low single-digit seconds.
    assert elapsed < 15
    assert result.returncode == 1
    assert "WORKLOAD-READINESS TIMEOUT after 3s" in result.stderr
    assert "timed out after 1s" in result.stderr
    hung_calls = (
        hung_log.read_text(encoding="utf-8").splitlines()
        if hung_log.exists()
        else []
    )
    assert len(hung_calls) >= 1
    assert "--request-timeout=1s" in hung_calls[0]
    assert (output_dir / "PropagationTimings.jsonl").read_text(
        encoding="utf-8"
    ) == ""


def test_workload_readiness_parallel_checks_succeed_quickly(tmp_path):
    """With many clusters, the barrier must check clusters with bounded
    PARALLELISM rather than fully serially -- one slow-but-healthy
    apiserver call per cluster must not multiply out to
    CLUSTER_COUNT x per-call-latency wall time. Uses a fake kubectl that
    sleeps briefly (simulating real but non-hung API latency) and always
    reports ready; a fully serial implementation (concurrency=1) would
    take CLUSTER_COUNT x 3 calls x sleep, while bounded parallelism at
    concurrency=4 should finish in a small fraction of that time, and
    still correctly conclude the barrier is satisfied."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_kubectl = fake_bin / "kubectl"
    _write_executable(
        fake_kubectl,
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        args="$*"
        # Only the barrier's own get-namespace/get-deployment/get-svc
        # calls simulate real (non-hung) API latency here -- preflight's
        # pod lookup and the unrelated best-effort cleanup-trap delete
        # calls return immediately so this test's timing measures ONLY
        # the barrier's parallelism, not unrelated script stages.
        if [[ "$args" == *"get namespace "* ]]; then
          sleep 0.4
          exit 0
        elif [[ "$args" == *"get deployment -l group=clustermesh-propagation-probe -o json"* ]]; then
          sleep 0.4
          printf '%s' '{"items":[{"metadata":{"name":"probe-dep"},"spec":{"replicas":1},"status":{"availableReplicas":1,"updatedReplicas":1}}]}'
        elif [[ "$args" == *"get svc -l group=clustermesh-propagation-probe -o json"* ]]; then
          sleep 0.4
          printf '%s' '{"items":[{"metadata":{"name":"probe-svc"}}]}'
        elif [[ "$args" == *"-n kube-system get pod -l"* ]]; then
          # No Cilium pod anywhere -- makes preflight fail so the script
          # exits quickly right after the barrier succeeds.
          printf ''
        elif [[ "$args" == *"delete pod"* ]]; then
          exit 0
        else
          echo "Unexpected kubectl command: $args" >&2
          exit 1
        fi
        """,
    )

    cluster_count = 8
    clusters_json = _clusters_json_n(tmp_path, cluster_count)
    environment_overrides = {
        "CLUSTERS_JSON": str(clusters_json),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PROBE_WORKLOAD_READY_TIMEOUT_S": "60",
        "PROBE_WORKLOAD_READY_POLL_S": "0",
        "PROBE_WORKLOAD_READY_CONCURRENCY": "4",
    }

    started = time.monotonic()
    result, output_dir = _run_probe_script(
        tmp_path, environment_overrides, timeout=20
    )
    elapsed = time.monotonic() - started

    # Serial would be cluster_count(8) x 3 calls x 0.4s = 9.6s minimum.
    # Bounded parallelism at concurrency=4 should take roughly
    # ceil(8/4) x 3 x 0.4s = 2.4s (plus process/subshell overhead). A
    # generous 6s bound clearly distinguishes "actually parallel" from
    # "serial" while tolerating CI scheduling noise.
    assert elapsed < 6
    assert (
        f"workload-readiness barrier: satisfied on all {cluster_count} clusters"
        in result.stdout
    )
    assert "concurrency=4" in result.stdout
    assert "PREFLIGHT FAIL" in result.stderr
    assert result.returncode == 1
    assert (output_dir / "PropagationTimings.jsonl").read_text(
        encoding="utf-8"
    ) == ""
