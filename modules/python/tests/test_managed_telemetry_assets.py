"""Static tests for the managed-Prometheus telemetry wiring."""

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
TELEMETRY_DIR = (
    REPO_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "telemetry"
)


def test_control_plane_settings_disable_duplicate_cluster_scrapes():
    config = yaml.safe_load(
        (TELEMETRY_DIR / "ama-metrics-settings-configmap.yaml").read_text(
            encoding="utf-8"
        )
    )

    cluster = config["data"]["cluster-metrics"]
    control_plane = config["data"]["controlplane-metrics"]

    assert "enabled = false" in cluster
    assert "enabled = false" in control_plane
    for target in (
        "kubelet",
        "coredns",
        "cadvisor",
        "kubeproxy",
        "apiserver",
        "kubestate",
        "nodeexporter",
        "networkobservabilityRetina",
        "networkobservabilityHubble",
        "networkobservabilityCilium",
    ):
        assert f"{target} = false" in cluster
    assert "prometheuscollectorhealth = true" in cluster
    assert 'podannotationnamespaceregex = "$^"' in cluster
    assert "kube-scheduler = true" in control_plane
    assert "kube-controller-manager = true" in control_plane
    assert "ksm-config" not in config["data"]


def test_managed_monitor_only_scrapes_apiserver_backend_exporter():
    monitors = list(
        yaml.safe_load_all(
            (
                TELEMETRY_DIR
                / "azure-monitor-control-plane-monitors.yaml"
            ).read_text(encoding="utf-8")
        )
    )

    assert [monitor["metadata"]["name"] for monitor in monitors] == [
        "apiserver-backend-exporter"
    ]


def test_native_snapshot_relabel_uses_streaming_block_rewriter():
    relabel = (
        TELEMETRY_DIR / "relabel-prometheus-snapshots.sh"
    ).read_text(encoding="utf-8")
    rewriter = (
        TELEMETRY_DIR / "tsdb-index-relabel" / "main.go"
    ).read_text(encoding="utf-8")

    assert 'go_version="${GO_VERSION:-1.25.5}"' in relabel
    assert "9e9b755d63b36acf30c12a9a3fc379243714c1c6d3dd72861da637f336ebb35b" in relabel
    assert "tsdb-index-relabel" in relabel
    assert 'GOTOOLCHAIN=local' in relabel
    assert '--label "run=$run_label"' in relabel
    assert '--label "build=$build_label"' in relabel
    assert '--label "tier=$tier_label"' in relabel
    assert '--label "snapshot_cluster=$snapshot_cluster"' in relabel
    assert "tools bucket rewrite" not in relabel
    assert "index.NewWriter" in rewriter
    assert "rawChunkWriter" in rewriter
    assert "writeRemappedTombstones" in rewriter
    assert "compareChunkMetas" in rewriter
    assert "atomicExchangeDirectories" in rewriter
    assert 'rm -rf "$snapshot_work"' in relabel


def test_provider_registration_retries_transient_cli_failure(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_file = tmp_path / "state"
    show_count_file = tmp_path / "show-count"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${1:-} ${2:-}" = "provider show" ]; then
              count=0
              [ ! -f "$SHOW_COUNT_FILE" ] || count=$(cat "$SHOW_COUNT_FILE")
              count=$((count + 1))
              echo "$count" > "$SHOW_COUNT_FILE"
              if [ "$count" -eq 1 ]; then
                echo "Connection reset by peer" >&2
                exit 1
              fi
              if [ -f "$STATE_FILE" ]; then
                echo Registered
              else
                echo NotRegistered
              fi
              exit 0
            fi
            if [ "${1:-} ${2:-}" = "provider register" ]; then
              touch "$STATE_FILE"
              echo "Connection reset by peer" >&2
              exit 1
            fi
            echo "Unexpected az command: $*" >&2
            exit 1
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' "
        "'{\"status\":\"success\",\"data\":{\"result\":["
        "{\"metric\":{\"cluster\":\"test_run_mesh_1\"},"
        "\"values\":[[1,\"1\"]]}]}}'\n",
        encoding="utf-8",
    )
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)
    common_script = TELEMETRY_DIR / "managed-prometheus-common.sh"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "STATE_FILE": str(state_file),
            "SHOW_COUNT_FILE": str(show_count_file),
            "AKS_PROVIDER_REGISTRATION_TIMEOUT_SECONDS": "5",
            "AKS_PROVIDER_REGISTRATION_POLL_SECONDS": "0",
        }
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{common_script}"; '
            "ensure_azure_provider_registered Microsoft.Monitor",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert state_file.is_file()
    assert "Unable to query resource provider" in result.stdout
    assert "registration request" in result.stdout
    assert "is registered" in result.stdout


def test_provider_registration_can_force_preview_reregistration(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    register_count_file = tmp_path / "register-count"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${1:-} ${2:-}" = "provider show" ]; then
              echo Registered
              exit 0
            fi
            if [ "${1:-} ${2:-}" = "provider register" ]; then
              count=0
              [ ! -f "$REGISTER_COUNT_FILE" ] || count=$(cat "$REGISTER_COUNT_FILE")
              count=$((count + 1))
              echo "$count" > "$REGISTER_COUNT_FILE"
              if [ "$count" -eq 1 ]; then
                echo "Connection reset by peer" >&2
                exit 1
              fi
              exit 0
            fi
            echo "Unexpected az command: $*" >&2
            exit 1
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    common_script = TELEMETRY_DIR / "managed-prometheus-common.sh"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "REGISTER_COUNT_FILE": str(register_count_file),
            "AKS_PROVIDER_REGISTRATION_TIMEOUT_SECONDS": "5",
            "AKS_PROVIDER_REGISTRATION_POLL_SECONDS": "0",
        }
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{common_script}"; '
            "ensure_azure_provider_registered Microsoft.ContainerService true",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert register_count_file.read_text(encoding="utf-8").strip() == "2"
    assert "Forcing resource provider re-registration" in result.stdout
    assert "Forced resource provider registration request" in result.stdout
    assert "is registered" in result.stdout


def test_configure_batches_two_cluster_workspaces_and_maps_manifest(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_file = tmp_path / "workspaces-created"
    az_log = tmp_path / "az.log"
    kubectl_log = tmp_path / "kubectl.log"
    kubectl_apply_failure_state = tmp_path / "kubectl-apply-failed-once"
    arm_template_copy = tmp_path / "arm-template.json"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "$*" >> "$FAKE_AZ_LOG"
            arg_value() {
              local target="$1"
              shift
              while [ "$#" -gt 0 ]; do
                if [ "$1" = "$target" ]; then
                  printf '%s' "$2"
                  return
                fi
                shift
              done
            }
            if [ "${1:-} ${2:-}" = "feature show" ]; then
              echo Registered
            elif [ "${1:-} ${2:-}" = "provider show" ]; then
              echo Registered
            elif [ "${1:-} ${2:-}" = "account show" ]; then
              echo sub-1
            elif [ "${1:-} ${2:-}" = "group show" ]; then
              exit 0
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor account show" ]; then
              name=$(arg_value --name "$@")
              [ -f "$STATE_FILE" ] || exit 1
              if [[ " $* " == *" --output json "* ]]; then
                cat <<JSON
            {"id":"/subscriptions/sub-1/resourceGroups/telemetry-rg/providers/Microsoft.Monitor/accounts/$name",
             "metrics":{"prometheusQueryEndpoint":"https://$name.example"}}
            JSON
              fi
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor account list" ]; then
              echo '[]'
            elif [ "${1:-} ${2:-} ${3:-}" = "deployment group create" ]; then
              template=$(arg_value --template-file "$@")
              cp "$template" "$ARM_TEMPLATE_COPY"
              touch "$STATE_FILE"
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor metrics list" ]; then
              if [[ " $* " == *" TimeSeriesSamplesDropped "* ]]; then
                cat <<'JSON'
            {"value":[
              {"name":{"value":"TimeSeriesSamplesDropped"},"timeseries":[]},
              {"name":{"value":"EventsDropped"},"timeseries":[]}
            ]}
            JSON
              else
                cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":0}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":0}]}]}
            ]}
            JSON
              fi
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor log-analytics workspace" ]; then
              if [ "${4:-}" = "show" ]; then
                cat <<'JSON'
            {"id":"law-resource-id","customerId":"law-customer-id"}
            JSON
              fi
            elif [ "${1:-} ${2:-}" = "aks get-credentials" ]; then
              file=$(arg_value --file "$@")
              mkdir -p "$(dirname "$file")"
              touch "$file"
            elif [ "${1:-} ${2:-}" = "aks update" ]; then
              if [ -n "${CAPACITY_AFTER_AKS_UPDATE:-}" ]; then
                tmp=$(mktemp)
                jq --argjson value "$CAPACITY_AFTER_AKS_UPDATE" \
                  'with_entries(.value = $value)' \
                  "$CAPACITY_FILE" > "$tmp"
                mv "$tmp" "$CAPACITY_FILE"
              fi
              exit 0
            elif [ "${1:-} ${2:-}" = "aks show" ]; then
              echo true
            elif [ "${1:-} ${2:-}" = "resource show" ]; then
              echo Succeeded
            elif [[ " $* " == *" diagnostic-settings categories list "* ]]; then
              cat <<'JSON'
            {"value":[
              {"categoryType":"Logs","name":"kube-audit"},
              {"categoryType":"Metrics","name":"AllMetrics"}
            ]}
            JSON
            elif [[ " $* " == *" diagnostic-settings create "* ]]; then
              exit 0
            else
              echo "Unexpected az command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "$*" >> "$FAKE_KUBECTL_LOG"
            if [ "${1:-} ${2:-}" = "create namespace" ]; then
              printf '%s\\n' 'apiVersion: v1' 'kind: Namespace' 'metadata:' '  name: monitoring'
            elif [ "${1:-} ${2:-} ${3:-}" = "apply -f -" ]; then
              cat >/dev/null
            elif [[ " $* " == *"azure-monitor-control-plane-monitors.yaml"* ]]; then
              if [ "${FAIL_CONTROL_PLANE_APPLY_ONCE:-false}" = "true" ] &&
                 [ ! -f "$KUBECTL_APPLY_FAILURE_STATE" ]; then
                touch "$KUBECTL_APPLY_FAILURE_STATE"
                echo 'error: the server is currently unable to handle the request' >&2
                exit 1
              fi
            elif [[ " $* " == *" -n kube-system get configmap cilium-config -o jsonpath="* ]]; then
              printf default
            elif [[ " $* " == *" -n kube-system get configmap cilium-config -o json "* ]]; then
              printf '%s\\n' '{"metadata":{"resourceVersion":"10"},"data":{"enable-policy":"default"}}'
            elif [[ " $* " == *" -n kube-system get daemonset cilium -o json "* ]]; then
              printf '%s\\n' '{"metadata":{"generation":3},"spec":{"template":{"metadata":{"annotations":{"cilium.io/cilium-configmap-checksum":"abc"}}}},"status":{"desiredNumberScheduled":2,"numberReady":2,"updatedNumberScheduled":2,"observedGeneration":3}}'
            else
              exit 0
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_kubectl.chmod(fake_kubectl.stat().st_mode | stat.S_IXUSR)
    clusters_file = tmp_path / "clusters.json"
    clusters_file.write_text(
        json.dumps(
            [
                {"role": "mesh-1", "name": "aks-1", "rg": "run-rg"},
                {"role": "mesh-2", "name": "aks-2", "rg": "run-rg"},
            ]
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "run-manifest.json"
    environment = os.environ.copy()
    environment.update(
        {
            "AKS_CONTROL_PLANE_METRICS_ENABLED": "true",
            "AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW": "false",
            "AKS_CONTROL_PLANE_AMW_RESOURCE_GROUP": "telemetry-rg",
            "AKS_CONTROL_PLANE_AMW_NAME_PREFIX": "test-amw",
            "AKS_AMW_ARM_BATCH_SIZE": "10",
            "AKS_AMW_METRICS_QUERY_ATTEMPTS": "1",
            "AKS_AMW_METRICS_QUERY_RETRY_SECONDS": "0",
            "AKS_MANAGED_MONITORING_CONVERGENCE_ENABLED": "true",
            "AKS_MANAGED_MONITORING_CONVERGENCE_TIMEOUT_SECONDS": "5",
            "AKS_MANAGED_MONITORING_CILIUM_QUIET_SECONDS": "0",
            "AKS_MANAGED_MONITORING_POLL_SECONDS": "0",
            "AKS_MANAGED_PROMETHEUS_APPLY_ATTEMPTS": "3",
            "AKS_MANAGED_PROMETHEUS_APPLY_RETRY_SECONDS": "0",
            "RUN_ID": "build-123",
            "REGION": "eastus2euap",
            "CLUSTERS_FILE": str(clusters_file),
            "CONFIGMAP_PATH": str(
                TELEMETRY_DIR / "ama-metrics-settings-configmap.yaml"
            ),
            "CONTROL_PLANE_MONITORS_PATH": str(
                TELEMETRY_DIR / "azure-monitor-control-plane-monitors.yaml"
            ),
            "MANIFEST_PATH": str(manifest_path),
            "STATE_FILE": str(state_file),
            "FAKE_AZ_LOG": str(az_log),
            "FAKE_KUBECTL_LOG": str(kubectl_log),
            "FAIL_CONTROL_PLANE_APPLY_ONCE": "true",
            "KUBECTL_APPLY_FAILURE_STATE": str(kubectl_apply_failure_state),
            "ARM_TEMPLATE_COPY": str(arm_template_copy),
            "HOME": str(tmp_path),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "configure-managed-prometheus.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )

    assert kubectl_apply_failure_state.exists()
    assert "transient telemetry manifest apply failure" in result.stderr
    assert "telemetry manifest apply recovered on attempt 2/3" in result.stdout
    assert kubectl_log.read_text(encoding="utf-8").count(
        "azure-monitor-control-plane-monitors.yaml"
    ) == 3
    arm_template = json.loads(arm_template_copy.read_text(encoding="utf-8"))
    assert {
        resource["name"] for resource in arm_template["resources"]
    } == {"test-amw-mesh-1", "test-amw-mesh-2"}
    assert all(
        resource["tags"]["gc_skip"] == "true"
        for resource in arm_template["resources"]
    )
    assert az_log.read_text(encoding="utf-8").count(
        "deployment group create"
    ) == 1
    assert az_log.read_text(encoding="utf-8").count(
        "resource show --ids"
    ) == 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert len(manifest["workspaces"]) == 2
    assert {
        cluster["workspace"]["name"] for cluster in manifest["clusters"]
    } == {"test-amw-mesh-1", "test-amw-mesh-2"}
    assert manifest["processing"] == {
        "amw_reconstruction": "deferred",
        "law_export": "deferred",
        "aksinfra_export": "deferred",
    }


def test_amw_capacity_guard_accepts_headroom_and_rejects_throttling(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${FAIL_QUERY:-false}" = "true" ]; then
              exit 1
            elif [[ " $* " == *" TimeSeriesSamplesDropped "* ]]; then
              if [ "${THROTTLED:-false}" = "true" ]; then
                events=200
                samples=100
              else
                events=0
                samples=0
              fi
              cat <<JSON
            {"value":[
              {"name":{"value":"TimeSeriesSamplesDropped"},"timeseries":[{
                "metadatavalues":[{"name":{"value":"Reason"},"value":"LimitThrottling"}],
                "data":[{"total":$samples}]
              }]},
              {"name":{"value":"EventsDropped"},"timeseries":[{
                "metadatavalues":[{"name":{"value":"Reason"},"value":"LimitThrottling"}],
                "data":[{"total":$events}]
              }]}
            ]}
            JSON
            elif [ "${PARTIAL:-false}" = "true" ]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":200000}]}]}
            ]}
            JSON
            elif [ "${IDLE:-false}" = "true" ]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":0}]}]},
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":0}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":0}]}]}
            ]}
            JSON
            elif [ "${HIGH_UTILIZATION:-false}" = "true" ]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":488181}]}]},
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":48.8181}]}]},
              {"name":{"value":"EventsPerMinuteIngested"},"timeseries":[{"data":[{"maximum":1345995}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":134.5995}]}]}
            ]}
            JSON
            elif [ "${THROTTLED:-false}" = "true" ]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":1265508}]}]},
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":126.5508}]}]},
              {"name":{"value":"EventsPerMinuteIngested"},"timeseries":[{"data":[{"maximum":3900000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":390}]}]}
            ]}
            JSON
            else
              cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":200000}]}]},
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":20}]}]},
              {"name":{"value":"EventsPerMinuteIngested"},"timeseries":[{"data":[{"maximum":300000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":30}]}]}
            ]}
            JSON
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    common_script = TELEMETRY_DIR / "managed-prometheus-common.sh"
    raw_path = tmp_path / "capacity.json"
    summary_path = tmp_path / "capacity-summary.json"
    markdown_path = tmp_path / "capacity-summary.md"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "AKS_AMW_METRICS_QUERY_ATTEMPTS": "1",
            "AKS_AMW_METRICS_QUERY_RETRY_SECONDS": "0",
        }
    )
    command = (
        f'source "{common_script}"; '
        f'capture_amw_capacity test-amw start end "{raw_path}" '
        f'"{summary_path}"; '
        f'write_amw_capacity_markdown "{summary_path}" "{markdown_path}"; '
        f'amw_capacity_preflight_ok "{summary_path}" 50'
    )

    healthy = subprocess.run(
        ["bash", "-c", command],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert healthy.returncode == 0
    assert json.loads(summary_path.read_text(encoding="utf-8"))[
        "capacity_ok"
    ] is True
    assert json.loads(summary_path.read_text(encoding="utf-8"))[
        "capacity_samples_complete"
    ] is True
    assert "Status: **complete**" in markdown_path.read_text(encoding="utf-8")

    environment["IDLE"] = "true"
    idle = subprocess.run(
        ["bash", "-c", command],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert idle.returncode == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["capacity_samples"]["events_per_minute"] is False
    assert summary["capacity_samples_complete"] is True
    assert summary["capacity_ok"] is True

    environment["IDLE"] = "false"
    environment["HIGH_UTILIZATION"] = "true"
    runtime_command = (
        f'source "{common_script}"; '
        f'capture_amw_capacity test-amw start end "{raw_path}" '
        f'"{summary_path}"; '
        f'write_amw_capacity_markdown "{summary_path}" "{markdown_path}"; '
        f'amw_capacity_runtime_ok "{summary_path}"'
    )
    high_utilization = subprocess.run(
        ["bash", "-c", runtime_command],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert high_utilization.returncode == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["within_nominal_limits"] is False
    assert summary["capacity_ok"] is True
    assert "Status: **complete (above nominal utilization)**" in (
        markdown_path.read_text(encoding="utf-8")
    )

    environment["HIGH_UTILIZATION"] = "false"
    environment["PARTIAL"] = "true"
    partial = subprocess.run(
        ["bash", "-c", command],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert partial.returncode != 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["has_capacity_samples"] is True
    assert summary["capacity_samples_complete"] is False
    assert "Status: **unverifiable**" in markdown_path.read_text(
        encoding="utf-8"
    )

    environment["PARTIAL"] = "false"
    environment["THROTTLED"] = "true"
    throttled = subprocess.run(
        ["bash", "-c", command],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert throttled.returncode != 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["capacity_ok"] is False
    assert summary["limit_throttling"] == {
        "events_dropped": 200,
        "time_series_samples_dropped": 100,
    }

    environment["THROTTLED"] = "false"
    environment["FAIL_QUERY"] = "true"
    failed_query = subprocess.run(
        ["bash", "-c", command],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert failed_query.returncode != 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["query_succeeded"] is False
    assert summary["capacity_ok"] is False
    assert "Status: **unverifiable**" in markdown_path.read_text(
        encoding="utf-8"
    )


def test_wait_marks_throttled_amw_unready(tmp_path):
    output_dir = tmp_path / "output"
    manifest_path = tmp_path / "run-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": "test-run",
                "configured_at": "2026-07-14T00:00:00Z",
                "workspace": {"mode": "per-cluster"},
                "workspaces": [
                    {
                        "slot": "mesh-1",
                        "name": "test-amw-mesh-1",
                        "id": "test-amw",
                        "prometheus_query_endpoint": "https://example",
                        "capacity_guard": {
                            "monitoring_window_start": "2026-07-14T00:00:00Z"
                        },
                    }
                ],
                "query": {
                    "resource_endpoint": "https://example",
                    "resource_scope": "/subscriptions/test",
                },
                "logs": {"workspace": {"customer_id": "law-id"}},
                "clusters": [
                    {
                        "role": "mesh-1",
                        "id": "cluster-id",
                        "prometheus_cluster_alias": "test_run_mesh_1",
                        "workspace": {
                            "slot": "mesh-1",
                            "name": "test-amw-mesh-1",
                            "id": "test-amw",
                            "prometheus_query_endpoint": "https://example",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ " $* " == *" TimeSeriesSamplesDropped "* ]]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"TimeSeriesSamplesDropped"},"timeseries":[{
                "metadatavalues":[{"name":{"value":"Reason"},"value":"LimitThrottling"}],
                "data":[{"total":100}]
              }]},
              {"name":{"value":"EventsDropped"},"timeseries":[{
                "metadatavalues":[{"name":{"value":"Reason"},"value":"LimitThrottling"}],
                "data":[{"total":200}]
              }]}
            ]}
            JSON
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor metrics list" ]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":1265508}]}]},
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":126.5508}]}]},
              {"name":{"value":"EventsPerMinuteIngested"},"timeseries":[{"data":[{"maximum":3900000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":390}]}]}
            ]}
            JSON
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor log-analytics query" ]; then
              echo 1
            elif [ "${1:-} ${2:-}" = "account get-access-token" ]; then
              echo fake-token
            else
              echo "Unexpected az command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    environment = os.environ.copy()
    environment.update(
        {
            "AKS_CONTROL_PLANE_METRICS_ENABLED": "true",
            "MANIFEST_PATH": str(manifest_path),
            "OUTPUT_DIR": str(output_dir),
            "RUN_ID": "test-run",
            "AKS_PLATFORM_METRICS_TIMEOUT_SECONDS": "0",
            "AKS_MANAGED_PROMETHEUS_TIMEOUT_SECONDS": "1",
            "AKS_MANAGED_PROMETHEUS_POLL_SECONDS": "0",
            "AKS_AMW_METRICS_QUERY_ATTEMPTS": "1",
            "AKS_AMW_METRICS_QUERY_RETRY_SECONDS": "0",
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "wait-managed-prometheus.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert "platform CPU/memory metrics are optional" in result.stdout

    collection = json.loads(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert collection["platform_metrics_ready"] is False
    assert collection["platform_metrics_window"]["wait_enabled"] is False
    assert collection["managed_prometheus_ready"] is False
    assert collection["managed_prometheus_throttled"] is True
    assert collection["amw_capacity_verified"] is True
    assert collection["capacity_audits"][0]["summary"]["capacity_ok"] is False
    assert "Status: **throttled**" in (
        output_dir
        / "workspace-mesh-1"
        / "amw-capacity-summary.md"
    ).read_text(encoding="utf-8")

    audit_script = tmp_path / "audit.py"
    audit_script.write_text(
        textwrap.dedent(
            """\
            import json
            import pathlib
            import sys
            prefix = pathlib.Path(sys.argv[sys.argv.index("--output-prefix") + 1])
            prefix.with_suffix(".json").write_text(json.dumps({"complete": True}))
            prefix.with_suffix(".md").write_text("# audit\\n")
            """
        ),
        encoding="utf-8",
    )
    platform_script = tmp_path / "platform.py"
    platform_script.write_text(
        textwrap.dedent(
            """\
            import json
            import pathlib
            import sys
            output = pathlib.Path(sys.argv[sys.argv.index("--output") + 1])
            manifest = pathlib.Path(sys.argv[sys.argv.index("--manifest") + 1])
            output.write_text("azure_platform_test 1 1783987200\\n# EOF\\n")
            manifest.write_text(json.dumps({"exported": ["test"]}))
            """
        ),
        encoding="utf-8",
    )
    environment.update(
        {
            "AUDIT_SCRIPT": str(audit_script),
            "PLATFORM_EXPORT_SCRIPT": str(platform_script),
        }
    )
    audit = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "audit-managed-prometheus.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert audit.returncode != 0
    assert "capacity audit failed" in audit.stdout
    assert (output_dir / "telemetry-audit-managed.json").is_file()
    assert (output_dir / "aks-platform-mesh-1.openmetrics").is_file()


def test_required_platform_metrics_make_wait_task_fail_after_preserving_manifest(
    tmp_path,
):
    manifest_path = tmp_path / "run-manifest.json"
    output_dir = tmp_path / "output"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": "test-run",
                "configured_at": "2026-07-14T00:00:00Z",
                "workspace": {"mode": "per-cluster"},
                "workspaces": [
                    {
                        "slot": "mesh-1",
                        "name": "test-amw-mesh-1",
                        "id": "test-amw",
                        "capacity_guard": {
                            "monitoring_window_start": "2026-07-14T00:00:00Z"
                        },
                    }
                ],
                "clusters": [
                    {
                        "role": "mesh-1",
                        "id": "cluster-id",
                        "prometheus_cluster_alias": "test_run_mesh_1",
                        "workspace": {
                            "slot": "mesh-1",
                            "name": "test-amw-mesh-1",
                            "id": "test-amw",
                            "prometheus_query_endpoint": "https://example",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ " $* " == *" TimeSeriesSamplesDropped "* ]]; then
              printf '%s\\n' '{"value":[]}'
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor metrics list" ]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":10}]}]},
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":1}]}]},
              {"name":{"value":"EventsPerMinuteIngested"},"timeseries":[{"data":[{"maximum":20}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":2}]}]}
            ]}
            JSON
            else
              echo "Unexpected az command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    environment = os.environ.copy()
    environment.update(
        {
            "AKS_CONTROL_PLANE_METRICS_ENABLED": "true",
            "AKS_PLATFORM_METRICS_REQUIRED": "true",
            "AKS_PLATFORM_METRICS_TIMEOUT_SECONDS": "0",
            "AKS_MANAGED_PROMETHEUS_TIMEOUT_SECONDS": "0",
            "AKS_AMW_METRICS_QUERY_ATTEMPTS": "1",
            "AKS_AMW_METRICS_QUERY_RETRY_SECONDS": "0",
            "MANIFEST_PATH": str(manifest_path),
            "OUTPUT_DIR": str(output_dir),
            "RUN_ID": "test-run",
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "wait-managed-prometheus.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 1
    assert "Required AKS platform CPU/memory metrics did not cover" in result.stdout
    collection = json.loads(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert collection["platform_metrics_ready"] is False
    assert collection["capacity_audits"][0]["summary"]["capacity_ok"] is True


def test_platform_readiness_requires_recent_samples_on_every_cluster(tmp_path):
    manifest_path = tmp_path / "run-manifest.json"
    output_dir = tmp_path / "output"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": "test-run",
                "clusters": [
                    {"role": "mesh-1", "id": "cluster-id-1"},
                    {"role": "mesh-2", "id": "cluster-id-2"},
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            cat <<'JSON'
            {"value":[
              {"name":{"value":"apiserver_cpu_usage_percentage"},"timeseries":[{"data":[{"timeStamp":"2026-07-14T00:06:00+00:00","average":1},{"timeStamp":"2026-07-14T00:07:00+00:00","average":1},{"timeStamp":"2026-07-14T00:08:00+00:00","average":1},{"timeStamp":"2026-07-14T00:09:00+00:00","average":1},{"timeStamp":"2026-07-14T00:10:00+00:00","average":1}]}]},
              {"name":{"value":"apiserver_memory_usage_percentage"},"timeseries":[{"data":[{"timeStamp":"2026-07-14T00:06:00+00:00","average":1},{"timeStamp":"2026-07-14T00:07:00+00:00","average":1},{"timeStamp":"2026-07-14T00:08:00+00:00","average":1},{"timeStamp":"2026-07-14T00:09:00+00:00","average":1},{"timeStamp":"2026-07-14T00:10:00+00:00","average":1}]}]},
              {"name":{"value":"etcd_cpu_usage_percentage"},"timeseries":[{"data":[{"timeStamp":"2026-07-14T00:06:00+00:00","average":1},{"timeStamp":"2026-07-14T00:07:00+00:00","average":1},{"timeStamp":"2026-07-14T00:08:00+00:00","average":1},{"timeStamp":"2026-07-14T00:09:00+00:00","average":1},{"timeStamp":"2026-07-14T00:10:00+00:00","average":1}]}]},
              {"name":{"value":"etcd_memory_usage_percentage"},"timeseries":[{"data":[{"timeStamp":"2026-07-14T00:06:00+00:00","average":1},{"timeStamp":"2026-07-14T00:07:00+00:00","average":1},{"timeStamp":"2026-07-14T00:08:00+00:00","average":1},{"timeStamp":"2026-07-14T00:09:00+00:00","average":1},{"timeStamp":"2026-07-14T00:10:00+00:00","average":1}]}]}
            ]}
            JSON
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    environment = os.environ.copy()
    environment.update(
        {
            "MANIFEST_PATH": str(manifest_path),
            "OUTPUT_DIR": str(output_dir),
            "RUN_ID": "test-run",
            "AKS_PLATFORM_METRICS_READINESS_NOW": "2026-07-14T00:10:00Z",
            "AKS_PLATFORM_METRICS_READINESS_TIMEOUT_SECONDS": "0",
            "AKS_PLATFORM_METRICS_READINESS_MIN_SAMPLES": "5",
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "wait-platform-metrics-ready.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (output_dir / "platform-readiness.json").read_text(encoding="utf-8")
    )
    assert report["ready"] is True
    assert len(report["clusters"]) == 2
    assert all(cluster["ready"] for cluster in report["clusters"])


def test_platform_readiness_fails_before_cl2_when_metrics_are_absent(tmp_path):
    manifest_path = tmp_path / "run-manifest.json"
    output_dir = tmp_path / "output"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": "test-run",
                "clusters": [{"role": "mesh-1", "id": "cluster-id-1"}],
            }
        ),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_az = fake_bin / "az"
    fake_az.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' '{\"value\":[]}'\n",
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    environment = os.environ.copy()
    environment.update(
        {
            "MANIFEST_PATH": str(manifest_path),
            "OUTPUT_DIR": str(output_dir),
            "RUN_ID": "test-run",
            "AKS_PLATFORM_METRICS_READINESS_NOW": "2026-07-14T00:10:00Z",
            "AKS_PLATFORM_METRICS_READINESS_TIMEOUT_SECONDS": "0",
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "wait-platform-metrics-ready.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 1
    assert "refusing to spend the scenario budget" in result.stdout
    report = json.loads(
        (output_dir / "platform-readiness.json").read_text(encoding="utf-8")
    )
    assert report["ready"] is False
    assert report["clusters"][0]["ready"] is False


def test_platform_window_coverage_accepts_azure_offset_timestamps(tmp_path):
    manifest_path = tmp_path / "run-manifest.json"
    output_dir = tmp_path / "output"
    scenario_meta = tmp_path / "share-infra-meta.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": "test-run",
                "configured_at": "2026-07-14T00:00:00Z",
                "workspace": {"mode": "per-cluster"},
                "workspaces": [
                    {
                        "slot": "mesh-1",
                        "name": "test-amw-mesh-1",
                        "id": "test-amw",
                        "capacity_guard": {
                            "monitoring_window_start": "2026-07-14T00:00:00Z"
                        },
                    }
                ],
                "clusters": [
                    {
                        "role": "mesh-1",
                        "id": "cluster-id",
                        "prometheus_cluster_alias": "test_run_mesh_1",
                        "workspace": {
                            "slot": "mesh-1",
                            "name": "test-amw-mesh-1",
                            "id": "test-amw",
                            "prometheus_query_endpoint": "https://example",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scenario_meta.write_text(
        json.dumps(
            [
                {
                    "scenario": "event-throughput",
                    "start_timestamp": "2026-07-14T00:01:00Z",
                    "end_timestamp": "2026-07-14T00:10:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ " $* " == *" TimeSeriesSamplesDropped "* ]]; then
              printf '%s\\n' '{"value":[]}'
            elif [[ " $* " == *" apiserver_cpu_usage_percentage "* ]]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"apiserver_cpu_usage_percentage"},"timeseries":[{"data":[{"timeStamp":"2026-07-14T00:01:00+00:00","average":1},{"timeStamp":"2026-07-14T00:10:00+00:00","average":1}]}]},
              {"name":{"value":"apiserver_memory_usage_percentage"},"timeseries":[{"data":[{"timeStamp":"2026-07-14T00:01:00+00:00","average":1},{"timeStamp":"2026-07-14T00:10:00+00:00","average":1}]}]},
              {"name":{"value":"etcd_cpu_usage_percentage"},"timeseries":[{"data":[{"timeStamp":"2026-07-14T00:01:00+00:00","average":1},{"timeStamp":"2026-07-14T00:10:00+00:00","average":1}]}]},
              {"name":{"value":"etcd_memory_usage_percentage"},"timeseries":[{"data":[{"timeStamp":"2026-07-14T00:01:00+00:00","average":1},{"timeStamp":"2026-07-14T00:10:00+00:00","average":1}]}]}
            ]}
            JSON
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor metrics list" ]; then
              cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":10}]}]},
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":1}]}]},
              {"name":{"value":"EventsPerMinuteIngested"},"timeseries":[{"data":[{"maximum":20}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":2}]}]}
            ]}
            JSON
            elif [ "${1:-} ${2:-}" = "account get-access-token" ]; then
              echo fake-token
            else
              echo "Unexpected az command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' "
        "'{\"status\":\"success\",\"data\":{\"result\":[]}}'\n",
        encoding="utf-8",
    )
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)
    environment = os.environ.copy()
    environment.update(
        {
            "AKS_CONTROL_PLANE_METRICS_ENABLED": "true",
            "AKS_PLATFORM_METRICS_REQUIRED": "true",
            "AKS_PLATFORM_METRICS_REQUIRE_WINDOW_COVERAGE": "true",
            "AKS_PLATFORM_METRICS_MIN_COVERAGE_PERCENT": "0",
            "AKS_PLATFORM_METRICS_TIMEOUT_SECONDS": "2",
            "AKS_PLATFORM_METRICS_COVERAGE_GRACE_SECONDS": "0",
            "AKS_MANAGED_PROMETHEUS_TIMEOUT_SECONDS": "0",
            "AKS_AMW_METRICS_QUERY_ATTEMPTS": "1",
            "AKS_AMW_METRICS_QUERY_RETRY_SECONDS": "0",
            "MANIFEST_PATH": str(manifest_path),
            "SHARE_INFRA_META": str(scenario_meta),
            "OUTPUT_DIR": str(output_dir),
            "RUN_ID": "test-run",
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "wait-managed-prometheus.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    collection = json.loads(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert collection["platform_metrics_ready"] is True
    assert collection["platform_metrics_window"] == {
        "start": "2026-07-14T00:01:00Z",
        "end": "2026-07-14T00:10:00Z",
        "wait_enabled": True,
        "full_window_required": True,
        "minimum_coverage_percent": 0,
    }


def test_scripts_use_current_aks_profile_and_full_export():
    configure = (
        TELEMETRY_DIR / "configure-managed-prometheus.sh"
    ).read_text(encoding="utf-8")
    common = (
        TELEMETRY_DIR / "managed-prometheus-common.sh"
    ).read_text(encoding="utf-8")
    collect = (
        TELEMETRY_DIR / "collect-managed-prometheus.sh"
    ).read_text(encoding="utf-8")
    wait = (
        TELEMETRY_DIR / "wait-managed-prometheus.sh"
    ).read_text(encoding="utf-8")
    audit = (
        TELEMETRY_DIR / "audit-managed-prometheus.sh"
    ).read_text(encoding="utf-8")
    reconstruct = (
        TELEMETRY_DIR / "reconstruct-managed-prometheus.sh"
    ).read_text(encoding="utf-8")
    upload = (
        TELEMETRY_DIR / "upload-managed-prometheus.sh"
    ).read_text(encoding="utf-8")
    collect_template = (
        REPO_ROOT
        / "steps"
        / "topology"
        / "clustermesh-scale"
        / "collect-control-plane-metrics.yml"
    ).read_text(encoding="utf-8")

    assert "azureMonitorProfile.metrics.enabled" in configure
    assert "azureMonitorProfile.metrics.controlPlane.enabled" in configure
    assert "Microsoft.OperationalInsights" in configure
    assert "az monitor diagnostic-settings categories list" in configure
    assert "--export-to-resource-specific true" in configure
    assert "ensure_azure_provider_registered" in configure
    assert "capture_amw_capacity" in configure
    assert "amw_capacity_preflight_ok" in configure
    assert "AKS_AMW_PREFLIGHT_MAX_UTILIZATION_PERCENT:-40" in configure
    assert "AKS_AMW_ARM_BATCH_SIZE:-10" in configure
    assert "az deployment group create" in configure
    assert "cannot be used for a multi-cluster run" in configure
    assert "schema_version: 2" in configure
    assert "workspaces: $workspaces" in configure
    assert "CONTROL_PLANE_MONITORS_PATH" in configure
    assert "CUSTOM_SCRAPES_PATH" not in configure
    assert "MOCK_MONITOR_PATH" not in configure
    assert configure.index('-f "$rendered_config"') < configure.index(
        "--enable-azure-monitor-metrics"
    )
    assert 'ensure_azure_provider_registered "$namespace" true' in configure
    assert 'force_container_service_reregistration=true' in configure
    assert 'AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW:-false' in configure
    assert "--wait" not in configure
    assert "wait-managed-prometheus.sh" in collect
    assert "audit-managed-prometheus.sh" in collect
    assert "upload-managed-prometheus.sh" in collect
    assert "wait_for_platform_metrics" in wait
    assert "wait_for_logs" not in wait
    assert "deferred: true" in wait
    assert (
        ".workspace.prometheus_query_endpoint // .query.resource_endpoint"
        in wait
    )
    assert "managed_prometheus_throttled" in wait
    assert 'request_timeout=$remaining' in wait
    assert "amw-capacity-summary.json" in wait
    assert "AKSControlPlane" not in audit
    assert "log-analytics query" not in audit
    assert '"$PLATFORM_EXPORT_SCRIPT"' in audit
    assert "AKS_AMW_CAPACITY_AUDITED]$capacity_audit_ok" in audit
    assert "Reconstruct managed Prometheus TSDB" not in collect_template
    assert "--arg end " not in common
    assert "--arg window_end " in common
    assert '"end": $window_end' in common
    assert '"$TSDB_EXPORT_SCRIPT"' in reconstruct
    assert 'if [ "$managed_prometheus_ready" != "true" ]' in reconstruct
    assert "tsdb create-blocks-from" not in reconstruct
    assert "az storage blob upload" in upload
    assert 'find "$OUTPUT_DIR" -type f -print0' in upload


def test_split_collection_scripts_handoff_and_preserve_outputs(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    scenario_meta = tmp_path / "share-infra-meta.json"
    scenario_meta.write_text(
        json.dumps(
            [
                {
                    "scenario": "pod-churn-combined",
                    "start_timestamp": "2026-07-14T00:00:00Z",
                    "end_timestamp": "2026-07-14T00:30:00Z",
                    "result_code": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "run-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": "test-run",
                "configured_at": "2026-07-14T00:00:00Z",
                "workspace": {"mode": "per-cluster"},
                "workspaces": [
                    {
                        "slot": "mesh-1",
                        "name": "test-amw-mesh-1",
                        "id": "test-amw",
                        "prometheus_query_endpoint": (
                            "https://example.prometheus.monitor.azure.com"
                        ),
                        "capacity_guard": {
                            "monitoring_window_start": "2026-07-14T00:00:00Z"
                        },
                    }
                ],
                "query": {
                    "resource_endpoint": "https://example.prometheus.monitor.azure.com",
                    "resource_scope": "/subscriptions/sub-1/resourceGroups/run-rg",
                },
                "logs": {"workspace": {"customer_id": "law-id"}},
                "clusters": [
                    {
                        "role": "mesh-1",
                        "id": "/subscriptions/sub-1/resourceGroups/run-rg/"
                        "providers/Microsoft.ContainerService/managedClusters/aks-1",
                        "prometheus_cluster_alias": "test_run_mesh_1",
                        "workspace": {
                            "slot": "mesh-1",
                            "name": "test-amw-mesh-1",
                            "id": "test-amw",
                            "prometheus_query_endpoint": (
                                "https://example.prometheus.monitor.azure.com"
                            ),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az_log = tmp_path / "az.log"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "$*" >> "$FAKE_AZ_LOG"
            command="${1:-} ${2:-} ${3:-}"
            if [ "$command" = "monitor metrics list" ]; then
              if [[ " $* " == *" TimeSeriesSamplesDropped "* ]]; then
                cat <<'JSON'
            {"value":[
              {"name":{"value":"TimeSeriesSamplesDropped"},"timeseries":[{
                "metadatavalues":[{"name":{"value":"Reason"},"value":"LimitThrottling"}],
                "data":[{"total":0}]
              }]},
              {"name":{"value":"EventsDropped"},"timeseries":[{
                "metadatavalues":[{"name":{"value":"Reason"},"value":"LimitThrottling"}],
                "data":[{"total":0}]
              }]}
            ]}
            JSON
              elif [[ " $* " == *" ActiveTimeSeries "* ]]; then
                cat <<'JSON'
            {"value":[
              {"name":{"value":"ActiveTimeSeries"},"timeseries":[{"data":[{"maximum":200000}]}]},
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":20}]}]},
              {"name":{"value":"EventsPerMinuteIngested"},"timeseries":[{"data":[{"maximum":300000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":30}]}]}
            ]}
            JSON
              else
              cat <<'JSON'
            {"value":[
              {"timeseries":[{"data":[{"average":1}]}]},
              {"timeseries":[{"data":[{"average":1}]}]},
              {"timeseries":[{"data":[{"average":1}]}]},
              {"timeseries":[{"data":[{"average":1}]}]}
            ]}
            JSON
              fi
            elif [ "$command" = "monitor log-analytics query" ]; then
              if [[ " $* " == *" --query length(@) "* ]]; then
                echo 1
              else
                echo '[]'
              fi
            elif [ "${1:-} ${2:-}" = "account get-access-token" ]; then
              echo fake-token
            elif [ "$command" = "storage blob upload" ]; then
              exit 0
            else
              echo "Unexpected az command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' "
        "'{\"status\":\"success\",\"data\":{\"result\":["
        "{\"metric\":{\"cluster\":\"test_run_mesh_1\"},"
        "\"values\":[[1,\"1\"]]}]}}'\n",
        encoding="utf-8",
    )
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)

    audit_script = tmp_path / "audit.py"
    audit_script.write_text(
        textwrap.dedent(
            """\
            import json
            import pathlib
            import sys
            prefix = pathlib.Path(sys.argv[sys.argv.index("--output-prefix") + 1])
            prefix.with_suffix(".json").write_text(json.dumps({"complete": False}))
            prefix.with_suffix(".md").write_text("# audit\\n")
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    platform_script = tmp_path / "platform.py"
    platform_script.write_text(
        textwrap.dedent(
            """\
            import json
            import pathlib
            import sys
            output = pathlib.Path(sys.argv[sys.argv.index("--output") + 1])
            manifest = pathlib.Path(sys.argv[sys.argv.index("--manifest") + 1])
            output.write_text("azure_platform_test 1 1783987200\\n# EOF\\n")
            manifest.write_text(json.dumps({"exported": ["test"]}))
            """
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "AKS_CONTROL_PLANE_METRICS_ENABLED": "true",
            "MANIFEST_PATH": str(manifest_path),
            "OUTPUT_DIR": str(output_dir),
            "RUN_ID": "test-run",
            "SHARE_INFRA_META": str(scenario_meta),
            "AUDIT_SCRIPT": str(audit_script),
            "PLATFORM_EXPORT_SCRIPT": str(platform_script),
            "BUILD_BRANCH": "test-branch",
            "FAKE_AZ_LOG": str(az_log),
            "AKS_PLATFORM_METRICS_TIMEOUT_SECONDS": "0",
            "AKS_MANAGED_PROMETHEUS_TIMEOUT_SECONDS": "5",
            "AKS_MANAGED_PROMETHEUS_POLL_SECONDS": "0",
            "AKS_AMW_METRICS_QUERY_ATTEMPTS": "1",
            "AKS_AMW_METRICS_QUERY_RETRY_SECONDS": "0",
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    for script_name in (
        "wait-managed-prometheus.sh",
        "audit-managed-prometheus.sh",
    ):
        subprocess.run(
            ["bash", str(TELEMETRY_DIR / script_name)],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            timeout=20,
        )

    manifest_path.unlink()
    subprocess.run(
        ["bash", str(TELEMETRY_DIR / "upload-managed-prometheus.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
    )

    collection_manifest = json.loads(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert collection_manifest["collected_at"]
    assert collection_manifest["audit_window"]["start"]
    assert collection_manifest["logs_window"]["start"]
    assert collection_manifest["logs_window"]["end"] is None
    assert collection_manifest["logs_window"]["deferred"] is True
    assert collection_manifest["scenario_windows"] == [
        {
            "scenario": "pod-churn-combined",
            "start_timestamp": "2026-07-14T00:00:00Z",
            "end_timestamp": "2026-07-14T00:30:00Z",
            "result_code": 0,
        }
    ]
    assert collection_manifest["managed_prometheus_ready"] is True
    assert collection_manifest["managed_prometheus_throttled"] is False
    assert collection_manifest["amw_capacity_verified"] is True
    assert collection_manifest["capacity_audits"][0]["summary"]["capacity_ok"] is True
    assert (output_dir / "telemetry-audit-managed.json").is_file()
    assert (
        output_dir / "workspace-mesh-1" / "amw-capacity-summary.json"
    ).is_file()
    assert (
        output_dir / "workspace-mesh-1" / "amw-capacity-summary.md"
    ).is_file()
    assert (output_dir / "aks-platform-mesh-1.openmetrics").is_file()
    uploads = az_log.read_text(encoding="utf-8")
    assert "storage blob upload" in uploads
    assert "workspace-mesh-1/amw-capacity-summary.json" in uploads


def test_reconstruction_skips_when_managed_samples_are_not_ready(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest_path = tmp_path / "source-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "configured_at": "2026-07-14T00:00:00Z",
                "query": {
                    "resource_endpoint": "https://example",
                    "resource_scope": "/subscriptions/sub/resourceGroups/rg",
                },
                "logs": {"workspace": {"customer_id": "law-id"}},
                "clusters": [],
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "run-manifest.json").write_text(
        json.dumps(
            {
                "collected_at": "2026-07-14T00:10:00Z",
                "audit_window": {"start": "2026-07-14T00:00:00Z"},
                "logs_window": {"end": "2026-07-14T00:10:00Z"},
                "managed_prometheus_ready": False,
            }
        ),
        encoding="utf-8",
    )
    marker = tmp_path / "snapshot-called"
    snapshot_script = tmp_path / "snapshot.py"
    snapshot_script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "AKS_CONTROL_PLANE_METRICS_ENABLED": "true",
            "MANIFEST_PATH": str(manifest_path),
            "OUTPUT_DIR": str(output_dir),
            "RUN_ID": "test-run",
            "BUILD_ID": "123",
            "SNAPSHOT_TIER": "n2",
            "TSDB_EXPORT_SCRIPT": str(snapshot_script),
        }
    )

    result = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "reconstruct-managed-prometheus.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
    )

    assert "not ready; skipping" in result.stdout
    assert not marker.exists()


# ---------------------------------------------------------------------------
# Bounded Azure Monitor workspace generation rotation
# (configure-managed-prometheus.sh). Build 74208 (commit e39c832) failed
# before scenarios started because both fixed n2 AMWs were already at
# 46.1408%/45.3612% active-series utilization, above the 40% preflight
# threshold, and the script had no fallback besides failing outright or
# reusing the same saturated pair. These tests drive the real script
# end-to-end with a fake `az`/`kubectl` on PATH so the selection algorithm
# (candidate order, bounded ring wrap, "missing == fresh", "metrics-query
# failure == unusable, never assumed fresh") is proven, not just asserted.
# ---------------------------------------------------------------------------


def _write_rotation_fake_az(fake_bin: Path) -> None:
    fake_az = fake_bin / "az"
    fake_az.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "$*" >> "$FAKE_AZ_LOG"
            arg_value() {
              local target="$1"
              shift
              while [ "$#" -gt 0 ]; do
                if [ "$1" = "$target" ]; then
                  printf '%s' "$2"
                  return
                fi
                shift
              done
            }
            if [ "${1:-} ${2:-}" = "feature show" ]; then
              echo Registered
            elif [ "${1:-} ${2:-}" = "provider show" ]; then
              echo Registered
            elif [ "${1:-} ${2:-}" = "account show" ]; then
              echo sub-1
            elif [ "${1:-} ${2:-}" = "group show" ]; then
              exit 0
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor account show" ]; then
              name=$(arg_value --name "$@")
              [ -f "$WORKSPACE_DIR/$name" ] || exit 1
              if [[ " $* " == *" --output json "* ]]; then
                cat <<JSON
            {"id":"/subscriptions/sub-1/resourceGroups/telemetry-rg/providers/Microsoft.Monitor/accounts/$name",
             "metrics":{"prometheusQueryEndpoint":"https://$name.example"}}
            JSON
              fi
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor account list" ]; then
              existing_count=$(find "$WORKSPACE_DIR" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')
              extra="${REGIONAL_ACCOUNTS_EXTRA:-0}"
              total=$((existing_count + extra))
              jq -n --arg region "$REGION" --argjson total "$total" \
                '[range(0; $total) | {location: $region, name: ("existing-account-" + (. | tostring))}]'
            elif [ "${1:-} ${2:-} ${3:-}" = "deployment group create" ]; then
              template=$(arg_value --template-file "$@")
              resource_type=$(jq -r '.resources[0].type // empty' "$template")
              if [ "$resource_type" = "Microsoft.Monitor/accounts/metricsContainers" ]; then
                if [ -n "${LIMITS_ARM_TEMPLATE_COPY:-}" ]; then
                  cp "$template" "$LIMITS_ARM_TEMPLATE_COPY"
                fi
              else
                cp "$template" "$ARM_TEMPLATE_COPY"
                for created_name in $(jq -r '.resources[].name' "$template"); do
                  touch "$WORKSPACE_DIR/$created_name"
                done
              fi
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor metrics list" ]; then
              resource=$(arg_value --resource "$@")
              name=$(basename "$resource")
              capacity_value=$(jq -r --arg name "$name" '.[$name] // "20"' "$CAPACITY_FILE")
              if [ "$capacity_value" = "FAIL" ]; then
                echo "simulated metrics query failure for $name" >&2
                exit 1
              fi
              if [[ " $* " == *" TimeSeriesSamplesDropped "* ]]; then
                cat <<'JSON'
            {"value":[
              {"name":{"value":"TimeSeriesSamplesDropped"},"timeseries":[]},
              {"name":{"value":"EventsDropped"},"timeseries":[]}
            ]}
            JSON
              else
                cat <<JSON
            {"value":[
              {"name":{"value":"ActiveTimeSeriesLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"ActiveTimeSeriesPercentUtilization"},"timeseries":[{"data":[{"maximum":$capacity_value}]}]},
              {"name":{"value":"EventsPerMinuteIngestedLimit"},"timeseries":[{"data":[{"maximum":1000000}]}]},
              {"name":{"value":"EventsPerMinuteIngestedPercentUtilization"},"timeseries":[{"data":[{"maximum":$capacity_value}]}]}
            ]}
            JSON
              fi
            elif [ "${1:-} ${2:-}" = "resource show" ]; then
              # Fresh, unattached Azure Monitor workspaces may never emit an
              # ActiveTimeSeriesLimit/EventsPerMinuteIngestedLimit metric
              # sample, so the real script verifies the requested ingestion
              # limits by reading the metricsContainers/default ARM child
              # resource directly instead. Simulate that here, including
              # optional query failures and delayed convergence, driven by
              # LIMITS_FILE.
              resource_ids=$(arg_value --ids "$@")
              name=$(echo "$resource_ids" | sed -E 's#.*/accounts/([^/]+)/metricsContainers/default$#\\1#')
              if [ -n "${LIMITS_FILE:-}" ] && [ -s "$LIMITS_FILE" ]; then
                query_fails=$(jq -r --arg name "$name" '.[$name].fail // false' "$LIMITS_FILE")
                if [ "$query_fails" = "true" ]; then
                  echo "simulated metricsContainers query failure for $name" >&2
                  exit 1
                fi
                converge_after_attempt=$(jq -r --arg name "$name" '.[$name].converge_after_attempt // 1' "$LIMITS_FILE")
                attempt=1
                if [ -n "${RESOURCE_SHOW_STATE_DIR:-}" ]; then
                  mkdir -p "$RESOURCE_SHOW_STATE_DIR"
                  state_file="$RESOURCE_SHOW_STATE_DIR/$name"
                  attempt=$(( $(cat "$state_file" 2>/dev/null || echo 0) + 1 ))
                  echo "$attempt" > "$state_file"
                fi
                if [ "$attempt" -lt "$converge_after_attempt" ]; then
                  active_limit=$(jq -r --arg name "$name" '.[$name].pending_active_limit // 0' "$LIMITS_FILE")
                  events_limit=$(jq -r --arg name "$name" '.[$name].pending_events_limit // 0' "$LIMITS_FILE")
                else
                  active_limit=$(jq -r --arg name "$name" '.[$name].active_limit // 1000000' "$LIMITS_FILE")
                  events_limit=$(jq -r --arg name "$name" '.[$name].events_limit // 1000000' "$LIMITS_FILE")
                fi
              else
                active_limit=1000000
                events_limit=1000000
              fi
              jq -n --argjson active "$active_limit" --argjson events "$events_limit" \
                '{properties:{limits:{maxActiveTimeSeries:$active,maxEventsPerMinute:$events}}}'
            elif [ "${1:-} ${2:-} ${3:-}" = "monitor log-analytics workspace" ]; then
              if [ "${4:-}" = "show" ]; then
                cat <<'JSON'
            {"id":"law-resource-id","customerId":"law-customer-id"}
            JSON
              fi
            elif [ "${1:-} ${2:-}" = "aks get-credentials" ]; then
              file=$(arg_value --file "$@")
              mkdir -p "$(dirname "$file")"
              touch "$file"
            elif [ "${1:-} ${2:-}" = "aks update" ]; then
              if [ -n "${CAPACITY_AFTER_AKS_UPDATE:-}" ]; then
                tmp=$(mktemp)
                jq --argjson value "$CAPACITY_AFTER_AKS_UPDATE" \
                  'with_entries(.value = $value)' \
                  "$CAPACITY_FILE" > "$tmp"
                mv "$tmp" "$CAPACITY_FILE"
              fi
              exit 0
            elif [ "${1:-} ${2:-}" = "aks show" ]; then
              echo true
            elif [[ " $* " == *" diagnostic-settings categories list "* ]]; then
              cat <<'JSON'
            {"value":[
              {"categoryType":"Logs","name":"kube-audit"},
              {"categoryType":"Metrics","name":"AllMetrics"}
            ]}
            JSON
            elif [[ " $* " == *" diagnostic-settings create "* ]]; then
              exit 0
            else
              echo "Unexpected az command: $*" >&2
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_az.chmod(fake_az.stat().st_mode | stat.S_IXUSR)


def _write_rotation_fake_kubectl(fake_bin: Path) -> None:
    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${1:-} ${2:-}" = "create namespace" ]; then
              printf '%s\\n' 'apiVersion: v1' 'kind: Namespace' 'metadata:' '  name: monitoring'
            elif [ "${1:-} ${2:-} ${3:-}" = "apply -f -" ]; then
              cat >/dev/null
            else
              exit 0
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_kubectl.chmod(fake_kubectl.stat().st_mode | stat.S_IXUSR)


def _run_rotation_configure(
    tmp_path,
    *,
    roles,
    existing_workspaces=None,
    capacity=None,
    limits=None,
    regional_accounts_extra=0,
    env_overrides=None,
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_rotation_fake_az(fake_bin)
    _write_rotation_fake_kubectl(fake_bin)

    workspace_dir = tmp_path / "workspaces"
    workspace_dir.mkdir()
    for name in existing_workspaces or []:
        (workspace_dir / name).write_text("pre-existing", encoding="utf-8")

    capacity_file = tmp_path / "capacity.json"
    capacity_file.write_text(json.dumps(capacity or {}), encoding="utf-8")
    limits_file = tmp_path / "limits.json"
    limits_file.write_text(json.dumps(limits or {}), encoding="utf-8")

    az_log = tmp_path / "az.log"
    arm_template_copy = tmp_path / "arm-template.json"
    limits_arm_template_copy = tmp_path / "limits-arm-template.json"

    clusters_file = tmp_path / "clusters.json"
    clusters_file.write_text(
        json.dumps(
            [
                {"role": role, "name": f"aks-{role}", "rg": "run-rg"}
                for role in roles
            ]
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "run-manifest.json"

    environment = os.environ.copy()
    environment.update(
        {
            "AKS_CONTROL_PLANE_METRICS_ENABLED": "true",
            "AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW": "false",
            "AKS_CONTROL_PLANE_AMW_RESOURCE_GROUP": "telemetry-rg",
            "AKS_CONTROL_PLANE_AMW_NAME_PREFIX": "test-amw",
            "AKS_AMW_ARM_BATCH_SIZE": "10",
            "AKS_AMW_METRICS_QUERY_ATTEMPTS": "1",
            "AKS_AMW_METRICS_QUERY_RETRY_SECONDS": "0",
            "AKS_AMW_LIMIT_VERIFY_ATTEMPTS": "1",
            "AKS_AMW_LIMIT_VERIFY_RETRY_SECONDS": "0",
            "RUN_ID": "build-123",
            "REGION": "eastus2euap",
            "CLUSTERS_FILE": str(clusters_file),
            "CONFIGMAP_PATH": str(
                TELEMETRY_DIR / "ama-metrics-settings-configmap.yaml"
            ),
            "CONTROL_PLANE_MONITORS_PATH": str(
                TELEMETRY_DIR / "azure-monitor-control-plane-monitors.yaml"
            ),
            "MANIFEST_PATH": str(manifest_path),
            "FAKE_AZ_LOG": str(az_log),
            "WORKSPACE_DIR": str(workspace_dir),
            "CAPACITY_FILE": str(capacity_file),
            "LIMITS_FILE": str(limits_file),
            "RESOURCE_SHOW_STATE_DIR": str(tmp_path / "resource-show-state"),
            "REGIONAL_ACCOUNTS_EXTRA": str(regional_accounts_extra),
            "ARM_TEMPLATE_COPY": str(arm_template_copy),
            "LIMITS_ARM_TEMPLATE_COPY": str(limits_arm_template_copy),
            "HOME": str(tmp_path),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )
    environment.update(env_overrides or {})

    result = subprocess.run(
        ["bash", str(TELEMETRY_DIR / "configure-managed-prometheus.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )
    manifest = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return result, manifest, workspace_dir, az_log


def test_rotation_selects_base_when_missing(tmp_path):
    result, manifest, workspace_dir, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        env_overrides={
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "8",
            "BUILD_ID": "100",
        },
    )

    assert result.returncode == 0, result.stderr
    assert manifest["workspace_rotation"] == {
        "enabled": True,
        "slot_count": 8,
        "base_prefix": "test-amw",
        "selected_prefix": "test-amw",
        "generation": "base",
        "build_id": "100",
    }
    assert manifest["workspaces"][0]["name"] == "test-amw-mesh-1"
    assert manifest["workspaces"][0]["generation"] == "base"
    assert manifest["workspaces"][0]["prefix"] == "test-amw"
    assert (workspace_dir / "test-amw-mesh-1").exists()


def test_rotation_selects_base_when_under_threshold(tmp_path):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        existing_workspaces=["test-amw-mesh-1"],
        capacity={"test-amw-mesh-1": 10},
        env_overrides={
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "8",
            "BUILD_ID": "100",
        },
    )

    assert result.returncode == 0, result.stderr
    assert manifest["workspace_rotation"]["selected_prefix"] == "test-amw"
    assert manifest["workspace_rotation"]["generation"] == "base"


def test_rotation_over_threshold_chooses_deterministic_ring_slot(tmp_path):
    # BUILD_ID % slot_count == 100 % 8 == 4, so the first ring candidate
    # tried must be "-r4" -- deterministic, not the smallest free slot.
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        existing_workspaces=["test-amw-mesh-1"],
        capacity={"test-amw-mesh-1": 90},
        env_overrides={
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "8",
            "BUILD_ID": "100",
        },
    )

    assert result.returncode == 0, result.stderr
    assert manifest["workspace_rotation"]["selected_prefix"] == "test-amw-r4"
    assert manifest["workspace_rotation"]["generation"] == "r4"


def test_rotation_wraps_ring_when_first_ring_slot_is_also_full(tmp_path):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        existing_workspaces=["test-amw-mesh-1", "test-amw-r4-mesh-1"],
        capacity={"test-amw-mesh-1": 90, "test-amw-r4-mesh-1": 95},
        env_overrides={
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "8",
            "BUILD_ID": "100",
        },
    )

    assert result.returncode == 0, result.stderr
    assert manifest["workspace_rotation"]["selected_prefix"] == "test-amw-r5"
    assert manifest["workspace_rotation"]["generation"] == "r5"


def test_rotation_fails_clearly_when_all_bounded_candidates_are_full(tmp_path):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        existing_workspaces=[
            "test-amw-mesh-1",
            "test-amw-r0-mesh-1",
            "test-amw-r1-mesh-1",
        ],
        capacity={
            "test-amw-mesh-1": 90,
            "test-amw-r0-mesh-1": 91,
            "test-amw-r1-mesh-1": 92,
        },
        env_overrides={
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "2",
            "BUILD_ID": "0",
        },
    )

    assert result.returncode != 0
    assert manifest is None
    assert "over the 40% preflight threshold" in result.stderr
    assert "bounded ring slot" in result.stderr
    assert "refusing to synthesize an unbounded workspace name" in result.stderr


def test_rotation_metric_query_failure_rejects_candidate_not_assumed_fresh(
    tmp_path,
):
    # The base workspace EXISTS but its capacity query genuinely fails; that
    # must reject the base candidate outright rather than treat it as fresh.
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        existing_workspaces=["test-amw-mesh-1"],
        capacity={"test-amw-mesh-1": "FAIL"},
        env_overrides={
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "8",
            "BUILD_ID": "100",
        },
    )

    assert result.returncode == 0, result.stderr
    assert manifest["workspace_rotation"]["selected_prefix"] != "test-amw"
    assert manifest["workspace_rotation"]["selected_prefix"] == "test-amw-r4"
    assert manifest["workspace_rotation"]["generation"] == "r4"


def test_rotation_enforces_63_char_name_limit_per_candidate(tmp_path):
    long_prefix = "x" * 60
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        env_overrides={
            "AKS_CONTROL_PLANE_AMW_NAME_PREFIX": long_prefix,
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "2",
            "BUILD_ID": "0",
        },
    )

    assert result.returncode != 0
    assert manifest is None
    assert "exceeds 63 characters" in result.stderr


def test_rotation_rejects_legacy_amw_name(tmp_path):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        env_overrides={
            "AKS_CONTROL_PLANE_AMW_NAME": "legacy-shared-amw",
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "2",
            "BUILD_ID": "0",
        },
    )

    assert result.returncode != 0
    assert manifest is None
    assert (
        "AKS_CONTROL_PLANE_AMW_NAME cannot be combined with "
        "AKS_AMW_ROTATION_ENABLED"
    ) in result.stderr


def test_rotation_slot_count_bounded_to_16(tmp_path):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        env_overrides={
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_AMW_ROTATION_SLOT_COUNT": "17",
            "BUILD_ID": "0",
        },
    )

    assert result.returncode != 0
    assert manifest is None
    assert (
        "AKS_AMW_ROTATION_SLOT_COUNT must be a positive integer no greater "
        "than 16"
    ) in result.stderr


def test_rotation_disabled_still_tags_generation_and_preserves_existing_tags(
    tmp_path,
):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1", "mesh-2"],
        env_overrides={"BUILD_ID": "77"},
    )

    assert result.returncode == 0, result.stderr
    arm_template = json.loads(
        (tmp_path / "arm-template.json").read_text(encoding="utf-8")
    )
    assert arm_template["resources"]
    for resource in arm_template["resources"]:
        assert resource["tags"]["gc_skip"] == "true"
        assert resource["tags"]["persistent"] == "true"
        assert resource["tags"]["workspace_generation"] == "base"
        assert resource["tags"]["created_build_id"] == "77"
    assert manifest["workspace_rotation"] == {
        "enabled": False,
        "slot_count": 1,
        "base_prefix": "test-amw",
        "selected_prefix": "test-amw",
        "generation": "base",
        "build_id": "77",
    }
    for workspace in manifest["workspaces"]:
        assert workspace["generation"] == "base"
        assert workspace["prefix"] == "test-amw"


# ---------------------------------------------------------------------------
# AMW sharding (AKS_AMW_CLUSTERS_PER_WORKSPACE), regional workspace quota
# (AKS_AMW_REGIONAL_WORKSPACE_LIMIT), and per-workspace ingestion limit
# overrides (AKS_AMW_MAX_ACTIVE_TIME_SERIES / AKS_AMW_MAX_EVENTS_PER_MINUTE)
# in configure-managed-prometheus.sh. Azure Monitor allows only 100
# Microsoft.Monitor/accounts per subscription per region; a strict
# one-workspace-per-cluster design does not scale (n=100 would need 100
# workspaces on its own), so a bounded number of clusters can share a
# workspace, and the regional quota is checked BEFORE any ARM creation.
# ---------------------------------------------------------------------------


def test_clusters_per_workspace_default_preserves_per_role_workspace_names(
    tmp_path,
):
    # AKS_AMW_CLUSTERS_PER_WORKSPACE defaults to 1: identical, backwards
    # compatible role-derived slot/workspace names.
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1", "mesh-2"],
    )

    assert result.returncode == 0, result.stderr
    assert {w["name"] for w in manifest["workspaces"]} == {
        "test-amw-mesh-1",
        "test-amw-mesh-2",
    }
    assert {w["slot"] for w in manifest["workspaces"]} == {"mesh-1", "mesh-2"}
    assert manifest["workspace_sharding"] == {
        "clusters_per_workspace": 1,
        "cluster_count": 2,
        "workspace_count": 2,
    }
    for workspace in manifest["workspaces"]:
        assert workspace["clusters_per_workspace"] == 1


def test_forced_shard_naming_rebalances_existing_one_cluster_workspaces(
    tmp_path,
):
    existing = ["test-amw-shard-001", "test-amw-shard-002"]
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1", "mesh-2"],
        existing_workspaces=existing,
        capacity={name: 95 for name in existing},
        env_overrides={
            "AKS_AMW_CLUSTERS_PER_WORKSPACE": "1",
            "AKS_AMW_FORCE_SHARD_NAMING": "true",
            "AKS_AMW_PREFLIGHT_MAX_UTILIZATION_PERCENT": "90",
            "AKS_MANAGED_PROMETHEUS_REBALANCE_EXISTING": "true",
            "AKS_AMW_REBALANCE_SETTLE_SECONDS": "0",
            "AKS_AMW_REBALANCE_WINDOW_MINUTES": "1",
            "AKS_AMW_REBALANCE_VERIFY_ATTEMPTS": "1",
            "AKS_AMW_REBALANCE_VERIFY_RETRY_SECONDS": "0",
            "CAPACITY_AFTER_AKS_UPDATE": "20",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "allowing configuration to continue" in result.stdout
    assert "rebalance capacity verified across 2 workspace(s)" in result.stdout
    assert {w["name"] for w in manifest["workspaces"]} == set(existing)
    assert {w["slot"] for w in manifest["workspaces"]} == {
        "shard-001",
        "shard-002",
    }
    assert all(
        workspace["capacity_guard"]["rebalance_override"]
        for workspace in manifest["workspaces"]
    )
    cluster_by_role = {c["role"]: c for c in manifest["clusters"]}
    assert (
        cluster_by_role["mesh-1"]["workspace"]["name"]
        == "test-amw-shard-001"
    )
    assert (
        cluster_by_role["mesh-2"]["workspace"]["name"]
        == "test-amw-shard-002"
    )


def test_sharding_100_clusters_at_cpw2_creates_50_deterministic_shards(
    tmp_path,
):
    # CLUSTERS_FILE order is deliberately NOT sorted (descending) to prove
    # the script sorts by numeric mesh role before sharding, rather than
    # depending on on-disk row order.
    roles = [f"mesh-{i}" for i in range(100, 0, -1)]
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=roles,
        env_overrides={"AKS_AMW_CLUSTERS_PER_WORKSPACE": "2"},
    )

    assert result.returncode == 0, result.stderr
    assert manifest["workspace_sharding"] == {
        "clusters_per_workspace": 2,
        "cluster_count": 100,
        "workspace_count": 50,
    }
    expected_names = {f"test-amw-shard-{i:03d}" for i in range(1, 51)}
    assert {w["name"] for w in manifest["workspaces"]} == expected_names

    cluster_by_role = {c["role"]: c for c in manifest["clusters"]}
    assert (
        cluster_by_role["mesh-1"]["workspace"]["name"]
        == "test-amw-shard-001"
    )
    assert (
        cluster_by_role["mesh-2"]["workspace"]["name"]
        == "test-amw-shard-001"
    )
    assert (
        cluster_by_role["mesh-99"]["workspace"]["name"]
        == "test-amw-shard-050"
    )
    assert (
        cluster_by_role["mesh-100"]["workspace"]["name"]
        == "test-amw-shard-050"
    )


def test_sharding_odd_cluster_count_leaves_final_shard_partial(tmp_path):
    roles = [f"mesh-{i}" for i in range(1, 6)]  # 5 clusters, cpw=2 -> 3 shards
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=roles,
        env_overrides={"AKS_AMW_CLUSTERS_PER_WORKSPACE": "2"},
    )

    assert result.returncode == 0, result.stderr
    assert manifest["workspace_sharding"] == {
        "clusters_per_workspace": 2,
        "cluster_count": 5,
        "workspace_count": 3,
    }
    cluster_by_role = {c["role"]: c for c in manifest["clusters"]}
    assert (
        cluster_by_role["mesh-1"]["workspace"]["name"]
        == cluster_by_role["mesh-2"]["workspace"]["name"]
        == "test-amw-shard-001"
    )
    assert (
        cluster_by_role["mesh-3"]["workspace"]["name"]
        == cluster_by_role["mesh-4"]["workspace"]["name"]
        == "test-amw-shard-002"
    )
    assert cluster_by_role["mesh-5"]["workspace"]["name"] == "test-amw-shard-003"


def test_regional_workspace_quota_fails_before_any_arm_creation(tmp_path):
    # 5 missing candidate workspaces + 96 pre-existing regional accounts ==
    # 101, over the default AKS_AMW_REGIONAL_WORKSPACE_LIMIT of 100. Must
    # fail BEFORE any "deployment group create" call / workspace file.
    roles = [f"mesh-{i}" for i in range(1, 6)]
    result, manifest, workspace_dir, az_log = _run_rotation_configure(
        tmp_path,
        roles=roles,
        regional_accounts_extra=96,
    )

    assert result.returncode != 0
    assert manifest is None
    assert list(workspace_dir.iterdir()) == []
    assert "deployment group create" not in az_log.read_text(
        encoding="utf-8"
    )
    combined_output = result.stdout + result.stderr
    assert "existing=96" in combined_output
    assert "missing_candidate=5" in combined_output
    assert "projected_total=101" in combined_output
    assert "limit=100" in combined_output
    assert (
        "exceeding AKS_AMW_REGIONAL_WORKSPACE_LIMIT" in result.stderr
    )


def test_regional_workspace_quota_passes_under_limit(tmp_path):
    roles = [f"mesh-{i}" for i in range(1, 6)]
    result, manifest, _, az_log = _run_rotation_configure(
        tmp_path,
        roles=roles,
        regional_accounts_extra=94,
    )

    assert result.returncode == 0, result.stderr
    assert "deployment group create" in az_log.read_text(encoding="utf-8")
    assert manifest["workspace_regional_quota"] == {
        "region": "eastus2euap",
        "limit": 100,
        "existing_before_run": 94,
        "created_this_run": 5,
        "projected_total": 99,
    }


def test_manifest_records_sharding_limits_and_regional_quota(tmp_path):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1", "mesh-2"],
        regional_accounts_extra=5,
    )

    assert result.returncode == 0, result.stderr
    assert manifest["workspace_sharding"] == {
        "clusters_per_workspace": 1,
        "cluster_count": 2,
        "workspace_count": 2,
    }
    assert manifest["workspace_ingestion_limits"] == {
        "max_active_time_series": 1000000,
        "max_events_per_minute": 1000000,
        "overrides_requested": False,
    }
    assert manifest["workspace_regional_quota"] == {
        "region": "eastus2euap",
        "limit": 100,
        "existing_before_run": 5,
        "created_this_run": 2,
        "projected_total": 7,
    }
    for workspace in manifest["workspaces"]:
        assert workspace["requested_limits"] == {
            "max_active_time_series": 1000000,
            "max_events_per_minute": 1000000,
        }


def test_ingestion_limit_override_deploys_metrics_container_child_resource(
    tmp_path,
):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        limits={
            "test-amw-mesh-1": {
                "active_limit": 2000000,
                "events_limit": 2000000,
            }
        },
        env_overrides={
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
        },
    )

    assert result.returncode == 0, result.stderr

    arm_template = json.loads(
        (tmp_path / "arm-template.json").read_text(encoding="utf-8")
    )
    for resource in arm_template["resources"]:
        assert resource["tags"]["clusters_per_workspace"] == "1"
        assert resource["tags"]["requested_max_active_time_series"] == "2000000"
        assert resource["tags"]["requested_max_events_per_minute"] == "2000000"

    limits_arm_template = json.loads(
        (tmp_path / "limits-arm-template.json").read_text(encoding="utf-8")
    )
    assert limits_arm_template["resources"] == [
        {
            "type": "Microsoft.Monitor/accounts/metricsContainers",
            "apiVersion": "2025-05-03-preview",
            "name": "test-amw-mesh-1/default",
            "location": "eastus2euap",
            "properties": {
                "limits": {
                    "maxActiveTimeSeries": 2000000,
                    "maxEventsPerMinute": 2000000,
                }
            },
        }
    ]

    assert (
        "Verified Azure Monitor workspace test-amw-mesh-1 ingestion limits "
        "meet the requested values." in result.stdout
    )
    assert manifest["workspace_ingestion_limits"] == {
        "max_active_time_series": 2000000,
        "max_events_per_minute": 2000000,
        "overrides_requested": True,
    }
    for workspace in manifest["workspaces"]:
        assert workspace["clusters_per_workspace"] == 1
        assert workspace["requested_limits"] == {
            "max_active_time_series": 2000000,
            "max_events_per_minute": 2000000,
        }


def test_ingestion_limit_verification_fails_closed_when_limit_not_met(
    tmp_path,
):
    # Reported active-series limit (1.5M) never reaches the requested 2M.
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        limits={
            "test-amw-mesh-1": {
                "active_limit": 1500000,
                "events_limit": 2000000,
            }
        },
        env_overrides={
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
        },
    )

    assert result.returncode != 0
    assert manifest is None
    assert "did not reach the requested values" in result.stderr
    assert "failing closed" in result.stderr


def test_ingestion_limit_verification_fails_closed_on_query_failure(
    tmp_path,
):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        limits={"test-amw-mesh-1": {"fail": True}},
        env_overrides={
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
        },
    )

    assert result.returncode != 0
    assert manifest is None
    assert "Unable to query ingestion limits" in result.stderr
    assert "failing closed" in result.stderr


def test_ingestion_limit_verification_succeeds_on_delayed_convergence(
    tmp_path,
):
    # The metricsContainers/default ARM child resource reports the
    # pre-override limits on the first two polls (simulating the ARM
    # override not having converged yet) and only reflects the requested
    # 2M limits starting on the third poll. Verification must retry and
    # ultimately succeed rather than failing closed on the earlier polls.
    result, manifest, _, az_log = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        limits={
            "test-amw-mesh-1": {
                "active_limit": 2000000,
                "events_limit": 2000000,
                "pending_active_limit": 1000000,
                "pending_events_limit": 1000000,
                "converge_after_attempt": 3,
            }
        },
        env_overrides={
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
            "AKS_AMW_LIMIT_VERIFY_ATTEMPTS": "5",
            "AKS_AMW_LIMIT_VERIFY_RETRY_SECONDS": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (
        "not yet applied" in result.stderr
    )
    assert (
        "Verified Azure Monitor workspace test-amw-mesh-1 ingestion limits "
        "meet the requested values." in result.stdout
    )
    assert manifest["workspace_ingestion_limits"] == {
        "max_active_time_series": 2000000,
        "max_events_per_minute": 2000000,
        "overrides_requested": True,
    }
    resource_show_calls = [
        line
        for line in az_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("resource show")
    ]
    assert len(resource_show_calls) >= 3


def test_ingestion_limit_verification_queries_exact_resource_id_and_api_version(
    tmp_path,
):
    # The ARM verification must target the metricsContainers/default child
    # resource of the workspace being verified, at the same
    # 2025-05-03-preview API version used to deploy the override, and must
    # not fall back to a query that could silently target the wrong
    # resource.
    result, _, _, az_log = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        limits={
            "test-amw-mesh-1": {
                "active_limit": 2000000,
                "events_limit": 2000000,
            }
        },
        env_overrides={
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
        },
    )

    assert result.returncode == 0, result.stderr
    expected_resource_id = (
        "/subscriptions/sub-1/resourceGroups/telemetry-rg/providers/"
        "Microsoft.Monitor/accounts/test-amw-mesh-1/metricsContainers/default"
    )
    resource_show_calls = [
        line
        for line in az_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("resource show")
    ]
    assert resource_show_calls, "expected an 'az resource show' invocation"
    assert any(
        f"--ids {expected_resource_id}" in call
        and "--api-version 2025-05-03-preview" in call
        for call in resource_show_calls
    )


def test_amw_clusters_per_workspace_rejects_out_of_range_values(tmp_path):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        env_overrides={"AKS_AMW_CLUSTERS_PER_WORKSPACE": "11"},
    )

    assert result.returncode != 0
    assert manifest is None
    assert (
        "AKS_AMW_CLUSTERS_PER_WORKSPACE must be a positive integer no "
        "greater than 10" in result.stderr
    )


def test_amw_regional_workspace_limit_rejects_non_positive_values(tmp_path):
    result, manifest, _, _ = _run_rotation_configure(
        tmp_path,
        roles=["mesh-1"],
        env_overrides={"AKS_AMW_REGIONAL_WORKSPACE_LIMIT": "0"},
    )

    assert result.returncode != 0
    assert manifest is None
    assert (
        "AKS_AMW_REGIONAL_WORKSPACE_LIMIT must be a positive integer"
        in result.stderr
    )
