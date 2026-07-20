"""Focused tests for the inter-scenario ClusterMesh health gate."""

import json
import os
import stat
import subprocess
import textwrap
import time
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "config"
    / "scenario-health-gate.sh"
)


def _write_fake_tools(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    clock_file = tmp_path / "clock"
    clock_file.write_text("0\n", encoding="utf-8")
    poll_file = tmp_path / "poll"
    poll_file.write_text("0\n", encoding="utf-8")

    fake_date = fake_bin / "date"
    fake_date.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            now=$(cat "$FAKE_CLOCK")
            if [[ " $* " == *" +%s "* ]]; then
              printf '%s\\n' "$now"
            else
              printf '2026-07-20T08:00:%02dZ\\n' "$now"
            fi
            """
        ),
        encoding="utf-8",
    )

    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            now=$(cat "$FAKE_CLOCK")
            printf '%s\\n' "$((now + ${1:?seconds required}))" > "$FAKE_CLOCK"
            """
        ),
        encoding="utf-8",
    )

    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            args="$*"
            poll=$(cat "$FAKE_POLL")

            if [[ " $args " == *" get namespaces -o name "* ]]; then
              poll=$((poll + 1))
              printf '%s\\n' "$poll" > "$FAKE_POLL"
              if [ "$FAKE_MODE" = "transient-cleanup" ] && [ "$poll" -eq 1 ]; then
                echo "Unable to connect to the server: connection reset" >&2
                exit 1
              fi
              exit 0
            elif [[ " $args " == *" get containernetworklogs.acn.azure.com -o name "* ]]; then
              echo 'No resources found' >&2
              if { [ "$FAKE_MODE" = "transient-cleanup" ] && [ "$poll" -eq 1 ]; } ||
                 [ "$FAKE_MODE" = "timeout" ]; then
                printf '%s\\n' 'containernetworklog.acn.azure.com/old-log'
              fi
            elif [[ " $args " == *" get containernetworkmetrics.acn.azure.com -o name "* ]]; then
              echo 'No resources found' >&2
            elif [[ " $args " == *" get ciliumendpoints.cilium.io -A "* ]]; then
              echo 'No resources found in all namespaces' >&2
              if [ "$FAKE_MODE" = "transient-cleanup" ] && [ "$poll" -eq 1 ]; then
                printf '%s\\n' 'clustermesh-old'
              else
                printf '%s\\n' 'kube-system' 'mock-clustermesh'
              fi
            elif [[ " $args " == *" api-resources --api-group=monitoring.coreos.com "* ]]; then
              printf '%s\\n' \
                'podmonitors.monitoring.coreos.com' \
                'prometheuses.monitoring.coreos.com'
            elif [[ " $args " == *" -n monitoring get all,configmaps,secrets,serviceaccounts,persistentvolumeclaims,roles.rbac.authorization.k8s.io,rolebindings.rbac.authorization.k8s.io"* ]]; then
              if [ "$FAKE_MODE" = "transient-cleanup" ] && [ "$poll" -eq 1 ]; then
                cat <<'JSON'
            {"items":[
              {"kind":"Deployment","metadata":{"name":"prometheus-operator"}},
              {"kind":"Deployment","metadata":{"name":"kube-state-metrics"}},
              {"kind":"ConfigMap","metadata":{"name":"ama-metrics-settings"}},
              {"kind":"PodMonitor","metadata":{"name":"ama-metrics"}},
              {"kind":"PodMonitor","metadata":{"name":"controlplane-apiserver"}},
              {"kind":"Prometheus","metadata":{"name":"managed-prometheus"}},
              {"kind":"PodMonitor","metadata":{"name":"hubble-metrics-old"}},
              {"kind":"Deployment","metadata":{"name":"apiserver-backend-exporter-old"}}
            ]}
            JSON
              else
                cat <<'JSON'
            {"items":[
              {"kind":"Deployment","metadata":{"name":"prometheus-operator"}},
              {"kind":"Deployment","metadata":{"name":"kube-state-metrics"}},
              {"kind":"ConfigMap","metadata":{"name":"ama-metrics-settings"}},
              {"kind":"PodMonitor","metadata":{"name":"ama-metrics"}},
              {"kind":"PodMonitor","metadata":{"name":"controlplane-apiserver"}},
              {"kind":"Prometheus","metadata":{"name":"managed-prometheus"}}
            ]}
            JSON
              fi
            elif [[ " $args " == *" get clusterroles.rbac.authorization.k8s.io,clusterrolebindings.rbac.authorization.k8s.io -o json "* ]]; then
              if [ "$FAKE_MODE" = "transient-cleanup" ] && [ "$poll" -eq 1 ]; then
                printf '%s\\n' \
                  '{"items":[{"kind":"ClusterRole","metadata":{"name":"prometheus-operator"}},{"kind":"ClusterRole","metadata":{"name":"apiserver-backend-exporter-old"}}]}'
              else
                printf '%s\\n' \
                  '{"items":[{"kind":"ClusterRole","metadata":{"name":"prometheus-operator"}}]}'
              fi
            elif [[ " $args " == *" -n kube-system get daemonset cilium -o json "* ]]; then
              printf '%s\\n' \
                '{"status":{"desiredNumberScheduled":1,"numberReady":1}}'
            elif [[ " $args " == *" get nodes -l type=kwok -o json "* ]]; then
              cat <<'JSON'
            {"items":[
              {"status":{"conditions":[{"type":"Ready","status":"True"}]}},
              {"status":{"conditions":[{"type":"Ready","status":"True"}]}}
            ]}
            JSON
            elif [[ " $args " == *" -n mock-clustermesh get pods -l app=mock-cilium-agent -o json "* ]]; then
              printf '%s\\n' \
                '{"items":[{"status":{"phase":"Running"}},{"status":{"phase":"Running"}}]}'
            elif [[ " $args " == *" -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg status "* ]]; then
              printf '%s\\n' 'ClusterMesh: 0/0 remote clusters ready.'
            elif [[ " $args " == *" get ciliumidentities.cilium.io -o name "* ]]; then
              echo 'No resources found' >&2
              count=5
              if [ "$FAKE_MODE" = "instability" ] && [ "$poll" -ge 3 ]; then
                count=6
              fi
              for ((i=1; i<=count; i++)); do
                printf 'ciliumidentity.cilium.io/%s\\n' "$i"
              done
            elif [[ " $args " == *" get services -A -o json "* ]]; then
              printf '%s\\n' \
                '{"items":[{"metadata":{"annotations":{"service.cilium.io/global":"true"}}}]}'
            else
              echo "Unexpected kubectl command: $args" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )

    for tool in (fake_date, fake_sleep, fake_kubectl):
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return fake_bin, clock_file, poll_file


def _run_gate(
    tmp_path: Path,
    mode: str,
    *,
    quiet_window: int,
    timeout: int,
) -> tuple[subprocess.CompletedProcess[str], dict, int]:
    fake_bin, clock_file, poll_file = _write_fake_tools(tmp_path)
    inventory = tmp_path / "clusters.json"
    inventory.write_text(
        json.dumps(
            [
                {
                    "role": "mesh-1",
                    "name": "cluster-a",
                    "context": "cluster-a",
                    "kubeconfig": "/fake/mesh-1.config",
                }
            ]
        ),
        encoding="utf-8",
    )
    summary_file = tmp_path / "health-summary.json"
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_CLOCK": str(clock_file),
            "FAKE_POLL": str(poll_file),
            "FAKE_MODE": mode,
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--clusters",
            str(inventory),
            "--scenario",
            "pod-churn-combined",
            "--expected-mock-count",
            "2",
            "--expected-remote-count",
            "0",
            "--timeout-seconds",
            str(timeout),
            "--quiet-window-seconds",
            str(quiet_window),
            "--poll-interval-seconds",
            "1",
            "--summary-file",
            str(summary_file),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    poll_count = int(poll_file.read_text(encoding="utf-8"))
    return result, summary, poll_count


def test_health_gate_succeeds_after_transient_cleanup(tmp_path):
    result, summary, poll_count = _run_gate(
        tmp_path,
        "transient-cleanup",
        quiet_window=2,
        timeout=10,
    )

    assert result.returncode == 0
    assert poll_count == 4
    assert summary["success"] is True
    assert summary["scenario"] == "pod-churn-combined"
    assert summary["stable_seconds"] == 2
    assert summary["clusters"][0]["healthy"] is True
    assert summary["clusters"][0]["cleanup"]["scenario_namespace_count"] == 0
    assert summary["clusters"][0]["cleanup"]["container_network_log_count"] == 0
    assert summary["clusters"][0]["cleanup"]["container_network_metric_count"] == 0
    assert summary["clusters"][0]["cleanup"]["cilium_endpoint_total"] == 2
    assert (
        summary["clusters"][0]["cleanup"]["scenario_monitoring_resource_count"]
        == 0
    )
    assert summary["clusters"][0]["mock"]["ready_nodes"] == 2
    assert summary["clusters"][0]["fingerprint"]["cilium_identities"] == 5
    assert "get namespaces failed: Unable to connect" in result.stderr
    assert "PodMonitor/hubble-metrics-old" in result.stderr
    assert "ClusterRole/apiserver-backend-exporter-old" in result.stderr


def test_health_gate_resets_quiet_window_when_fingerprint_changes(tmp_path):
    result, summary, poll_count = _run_gate(
        tmp_path,
        "instability",
        quiet_window=2,
        timeout=10,
    )

    assert result.returncode == 0
    assert poll_count == 5
    assert summary["success"] is True
    assert summary["clusters"][0]["fingerprint"]["cilium_identities"] == 6
    assert "Health fingerprint changed; resetting quiet window" in result.stderr


def test_health_gate_times_out_with_actionable_summary(tmp_path):
    result, summary, poll_count = _run_gate(
        tmp_path,
        "timeout",
        quiet_window=2,
        timeout=2,
    )

    assert result.returncode == 1
    assert poll_count == 2
    assert summary["success"] is False
    cluster = summary["clusters"][0]
    assert cluster["healthy"] is False
    assert cluster["cleanup"]["container_network_log_count"] == 1
    assert any(
        "ContainerNetworkLog resource(s) remain" in failure
        for failure in cluster["failures"]
    )
    assert "ClusterMesh scenario health gate timed out" in result.stderr
    assert "before starting another observation cycle" in result.stderr


def test_health_gate_hard_bounds_a_hung_kubectl(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\\n' "$*" >> "$HUNG_KUBECTL_LOG"
            sleep 30
            """
        ),
        encoding="utf-8",
    )
    fake_kubectl.chmod(fake_kubectl.stat().st_mode | stat.S_IXUSR)
    inventory = tmp_path / "clusters.json"
    inventory.write_text(
        json.dumps(
            [
                {
                    "role": "mesh-1",
                    "name": "cluster-a",
                    "kubeconfig": "/fake/mesh-1.config",
                }
            ]
        ),
        encoding="utf-8",
    )
    summary_file = tmp_path / "health-summary.json"
    kubectl_log = tmp_path / "kubectl.log"
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    environment["HUNG_KUBECTL_LOG"] = str(kubectl_log)

    started = time.monotonic()
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--clusters",
            str(inventory),
            "--scenario",
            "hung-kubectl",
            "--expected-mock-count",
            "0",
            "--expected-remote-count",
            "0",
            "--timeout-seconds",
            "2",
            "--cycle-timeout-seconds",
            "1",
            "--quiet-window-seconds",
            "1",
            "--poll-interval-seconds",
            "1",
            "--summary-file",
            str(summary_file),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=8,
    )
    elapsed = time.monotonic() - started

    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    kubectl_calls = (
        kubectl_log.read_text(encoding="utf-8").splitlines()
        if kubectl_log.exists()
        else []
    )
    assert result.returncode == 1
    assert 0.8 <= elapsed < 6
    assert len(kubectl_calls) <= 1
    if kubectl_calls:
        assert "--request-timeout=1s" in kubectl_calls[0]
    assert summary["success"] is False
    assert summary["cycle_timeout_seconds"] == 1
    assert any(
        "kubectl timed out after" in failure
        or "observation cycle deadline exhausted" in failure
        for failure in summary["clusters"][0]["failures"]
    )
    assert "ClusterMesh scenario health gate timed out" in result.stderr
