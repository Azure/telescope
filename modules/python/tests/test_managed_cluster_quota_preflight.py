"""Tests for the AKS ManagedClusters regional quota preflight."""

import json
import os
import subprocess
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SETUP_TEMPLATE_PATH = REPOSITORY_ROOT / "steps" / "setup-tests.yml"
PIPELINE_PATH = (
    REPOSITORY_ROOT / "pipelines" / "system" / "new-pipeline-test.yml"
)
STEP_DISPLAY_NAME = "Preflight ClusterMesh managed-cluster quota"


def _step():
    document = yaml.safe_load(SETUP_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return next(
        step for step in document["steps"]
        if step.get("displayName") == STEP_DISPLAY_NAME
    )


def _run(tmp_path, current, limit, **overrides):
    fake_az = tmp_path / "az"
    fake_az.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "if [ \"$1\" = account ] && [ \"$2\" = show ]; then\n"
        "  printf '%s\\n' \"${FAKE_ACTUAL_SUBSCRIPTION_ID}\"\n"
        "elif [ \"$1\" = rest ]; then\n"
        "  printf '%s\\n' \"${FAKE_MANAGED_CLUSTER_USAGE}\"\n"
        "else\n"
        "  echo \"unexpected az invocation: $*\" >&2\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_az.chmod(0o755)
    usage = {
        "value": [
            {
                "currentValue": current,
                "limit": limit,
                "name": {
                    "localizedValue": "Managed Clusters",
                    "value": "ManagedClusters",
                },
                "unit": "Count",
            }
        ]
    }
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "AZURE_SUBSCRIPTION_ID": "sub-1",
        "FAKE_ACTUAL_SUBSCRIPTION_ID": "sub-1",
        "FAKE_MANAGED_CLUSTER_USAGE": json.dumps(usage),
        "REGION": "centraluseuap",
        "CLUSTER_COUNT": "100",
        "CLUSTERMESH_REQUIRED_MANAGED_CLUSTERS": "100",
        "CLUSTERMESH_MANAGED_CLUSTER_QUOTA_HEADROOM": "5",
        **overrides,
    }
    return subprocess.run(
        ["bash", "-c", _step()["script"]],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=10,
    )


def test_managed_cluster_quota_accepts_central_us_euap_capacity(tmp_path):
    result = _run(tmp_path, current=106, limit=263)

    assert result.returncode == 0, result.stderr
    assert "available=157" in result.stdout
    assert "run requirement=100 clusters + reserved headroom=5 clusters" in result.stdout


def test_managed_cluster_quota_rejects_canada_shortfall(tmp_path):
    result = _run(tmp_path, current=7, limit=99)

    assert result.returncode == 1
    assert "need 105 available clusters, have 92" in result.stderr


def test_managed_cluster_quota_verifies_selected_subscription(tmp_path):
    result = _run(
        tmp_path,
        current=0,
        limit=200,
        FAKE_ACTUAL_SUBSCRIPTION_ID="different-subscription",
    )

    assert result.returncode == 1
    assert "Expected Azure subscription sub-1" in result.stderr


def test_managed_cluster_quota_rejects_missing_usage(tmp_path):
    result = _run(
        tmp_path,
        current=0,
        limit=200,
        FAKE_MANAGED_CLUSTER_USAGE='{"value":[]}',
    )

    assert result.returncode == 1
    assert "Unable to resolve Microsoft.ContainerService ManagedClusters quota" in result.stderr


def test_managed_cluster_quota_step_is_fail_fast_and_region_scoped():
    step = _step()

    assert "CLUSTERMESH_QUOTA_PREFLIGHT_ENABLED" in step["condition"]
    assert step["env"]["REGION"] == "${{ parameters.region }}"
    assert "Microsoft.ContainerService/locations/${REGION}/usages" in step["script"]


def test_headline_stages_reserve_managed_cluster_headroom():
    pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
    n2_start = pipeline.index(
        "- stage: azure_centraluseuap_n2_mock_full_telemetry"
    )
    n2_end = pipeline.index("- stage: azure_eastus2euap_n2_mock", n2_start)
    n100_start = pipeline.index("- stage: azure_centraluseuap_n100_mock")
    n100_end = pipeline.index("- stage: azure_eastus2euap_n1_mock_5k", n100_start)
    n2_stage = pipeline[n2_start:n2_end]
    n100_stage = pipeline[n100_start:n100_end]

    assert 'CLUSTERMESH_REQUIRED_MANAGED_CLUSTERS: "2"' in n2_stage
    assert 'CLUSTERMESH_MANAGED_CLUSTER_QUOTA_HEADROOM: "2"' in n2_stage
    assert 'CLUSTERMESH_REQUIRED_MANAGED_CLUSTERS: "100"' in n100_stage
    assert 'CLUSTERMESH_MANAGED_CLUSTER_QUOTA_HEADROOM: "5"' in n100_stage
