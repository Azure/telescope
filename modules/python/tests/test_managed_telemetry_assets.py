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
            "ARM_TEMPLATE_COPY": str(arm_template_copy),
            "HOME": str(tmp_path),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    subprocess.run(
        ["bash", str(TELEMETRY_DIR / "configure-managed-prometheus.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )

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

    collection = json.loads(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
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
