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


def test_maximal_settings_disable_minimal_ingestion_safely():
    config = yaml.safe_load(
        (TELEMETRY_DIR / "ama-metrics-settings-configmap.yaml").read_text(
            encoding="utf-8"
        )
    )

    cluster = config["data"]["cluster-metrics"]
    control_plane = config["data"]["controlplane-metrics"]
    ksm = yaml.safe_load(config["data"]["ksm-config"])

    assert "enabled = false" in cluster
    assert "enabled = false" in control_plane
    assert "kube-scheduler = true" in control_plane
    assert "kube-controller-manager = true" in control_plane
    assert ksm["labels_allow_list"]["pods"] == ["*"]
    assert "configmaps" not in ksm["annotations_allow_list"]


def test_custom_scrapes_cover_hidden_and_mock_targets():
    config = yaml.safe_load(
        (TELEMETRY_DIR / "ama-metrics-custom-scrapes.yaml").read_text(
            encoding="utf-8"
        )
    )
    scrape_config = yaml.safe_load(config["data"]["prometheus-config"])
    jobs = {job["job_name"] for job in scrape_config["scrape_configs"]}

    assert jobs == {
        "cilium-hubble-full",
        "clustermesh-apiserver-full",
        "kvstoremesh-full",
        "kwok-resource",
    }


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


def test_scripts_use_current_aks_profile_and_full_export():
    configure = (
        TELEMETRY_DIR / "configure-managed-prometheus.sh"
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

    assert "azureMonitorProfile.metrics.enabled" in configure
    assert "azureMonitorProfile.metrics.controlPlane.enabled" in configure
    assert "Microsoft.OperationalInsights" in configure
    assert "az monitor diagnostic-settings categories list" in configure
    assert "--export-to-resource-specific true" in configure
    assert "wait-managed-prometheus.sh" in collect
    assert "audit-managed-prometheus.sh" in collect
    assert "reconstruct-managed-prometheus.sh" in collect
    assert "upload-managed-prometheus.sh" in collect
    assert "wait_for_platform_metrics" in wait
    assert "wait_for_logs" in wait
    assert "AKSControlPlane" in audit
    assert "AKSAudit" in audit
    assert "AKSAuditAdmin" in audit
    assert '"$PLATFORM_EXPORT_SCRIPT"' in audit
    assert '"$TSDB_EXPORT_SCRIPT"' in reconstruct
    assert "tsdb create-blocks-from" not in reconstruct
    assert "az storage blob upload" in upload


def test_split_collection_scripts_handoff_and_preserve_outputs(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest_path = tmp_path / "run-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "test-run",
                "configured_at": "2026-07-14T00:00:00Z",
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
              cat <<'JSON'
            {"value":[
              {"timeseries":[{"data":[{"average":1}]}]},
              {"timeseries":[{"data":[{"average":1}]}]},
              {"timeseries":[{"data":[{"average":1}]}]},
              {"timeseries":[{"data":[{"average":1}]}]}
            ]}
            JSON
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
    snapshot_script = tmp_path / "snapshot.py"
    snapshot_script.write_text(
        textwrap.dedent(
            """\
            import json
            import pathlib
            import sys
            output = pathlib.Path(sys.argv[sys.argv.index("--output-dir") + 1])
            labels = [
                sys.argv[index + 1]
                for index, argument in enumerate(sys.argv)
                if argument == "--block-label"
            ]
            data = output / "data"
            data.mkdir(exist_ok=True)
            (data / "amw-export-manifest.json").write_text(
                json.dumps({"samples": 1, "block_labels": labels})
            )
            (output / "prom-snapshot-amw-test.tar.gz").write_bytes(b"snapshot")
            """
        ),
        encoding="utf-8",
    )

    promtool = output_dir / "promtool-3.13.0" / "promtool"
    promtool.parent.mkdir()
    promtool.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    promtool.chmod(promtool.stat().st_mode | stat.S_IXUSR)

    environment = os.environ.copy()
    environment.update(
        {
            "AKS_CONTROL_PLANE_METRICS_ENABLED": "true",
            "MANIFEST_PATH": str(manifest_path),
            "OUTPUT_DIR": str(output_dir),
            "RUN_ID": "test-run",
            "BUILD_ID": "123",
            "SNAPSHOT_TIER": "n2-sharded",
            "AUDIT_SCRIPT": str(audit_script),
            "PLATFORM_EXPORT_SCRIPT": str(platform_script),
            "TSDB_EXPORT_SCRIPT": str(snapshot_script),
            "BUILD_BRANCH": "test-branch",
            "FAKE_AZ_LOG": str(az_log),
            "AKS_PLATFORM_METRICS_TIMEOUT_SECONDS": "1",
            "AKS_CONTROL_PLANE_LOGS_TIMEOUT_SECONDS": "1",
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )

    for script_name in (
        "wait-managed-prometheus.sh",
        "audit-managed-prometheus.sh",
        "reconstruct-managed-prometheus.sh",
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
    assert (output_dir / "telemetry-audit-managed.json").is_file()
    assert (output_dir / "aks-platform-mesh-1.openmetrics").is_file()
    assert (output_dir / "amw-export-manifest.json").is_file()
    assert (output_dir / "prom-snapshot-amw-test.tar.gz").is_file()
    export_manifest = json.loads(
        (output_dir / "amw-export-manifest.json").read_text(encoding="utf-8")
    )
    assert export_manifest["block_labels"] == [
        "run=test-run",
        "build=123",
        "tier=n2-sharded",
    ]
    uploads = az_log.read_text(encoding="utf-8")
    assert "storage blob upload" in uploads
    assert "prom-snapshot-amw-test.tar.gz" in uploads
