"""Behavior checks for bounded initial Fleet member enrollment."""

import json
import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "staged-fleet-enrollment.sh"
)
FLEET_MODULE_PATH = (
    REPOSITORY_ROOT / "modules" / "terraform" / "azure" / "fleet" / "main.tf"
)
FLEET_VARIABLES_PATH = FLEET_MODULE_PATH.with_name("variables.tf")
AZURE_MAIN_PATH = REPOSITORY_ROOT / "modules" / "terraform" / "azure" / "main.tf"
AZURE_VARIABLES_PATH = AZURE_MAIN_PATH.with_name("variables.tf")
VALIDATE_RESOURCES_PATH = (
    REPOSITORY_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "validate-resources.yml"
)
N2_TFVARS_PATH = (
    REPOSITORY_ROOT
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "terraform-inputs"
    / "azure-2-mock-shared-dsv3.tfvars"
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_staged_join(
    tmp_path: Path,
    roles,
    failing_role=None,
    required_apply_count=1,
    batch_wait_seconds=2,
    recovery_apply_after_seconds=2,
    recovery_min_post_seconds=1,
    connected_sequence="",
):
    bin_dir = tmp_path / "bin"
    home_dir = tmp_path / "home"
    kube_dir = home_dir / ".kube"
    bin_dir.mkdir()
    kube_dir.mkdir(parents=True)

    clusters_file = kube_dir / "clustermesh-clusters.json"
    clusters_file.write_text(
        json.dumps(
            [
                {
                    "role": role,
                    "name": f"cluster-{role}",
                    "rg": "test-rg",
                }
                for role in roles
            ]
        ),
        encoding="utf-8",
    )
    for role in roles:
        (kube_dir / f"{role}.config").write_text("test", encoding="utf-8")

    command_log = tmp_path / "commands.log"
    selected_file = tmp_path / "selected.txt"
    apply_file = tmp_path / "applies.txt"
    connected_query_file = tmp_path / "connected-queries.txt"
    summary_file = tmp_path / "summary.json"

    _write_executable(
        bin_dir / "az",
        """#!/usr/bin/env bash
set -euo pipefail
echo "az $*" >> "$COMMAND_LOG"
if [[ " $* " == *" fleet member update "* ]]; then
  role=""
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--name" ]; then
      role="$2"
      break
    fi
    shift
  done
  echo "$role" >> "$SELECTED_FILE"
  exit 0
fi
if [[ " $* " == *" clustermeshprofile list-members "* ]]; then
  apply_count=$(wc -l < "$APPLY_FILE" 2>/dev/null || printf '0')
  if [[ " $* " == *"length([?meshProperties.status.state=='Failed'])"* ]]; then
    printf '0\\n'
    exit 0
  fi
  if [[ " $* " == *"meshProperties.status.state=='Connected'"* ]]; then
    if [ -n "$CONNECTED_SEQUENCE" ]; then
      query_number=$(( $(wc -l < "$CONNECTED_QUERY_FILE" 2>/dev/null || printf '0') + 1 ))
      echo query >> "$CONNECTED_QUERY_FILE"
      value=$(printf '%s\\n' "$CONNECTED_SEQUENCE" | cut -d, -f"$query_number")
      if [ -z "$value" ]; then
        value=$(printf '%s\\n' "$CONNECTED_SEQUENCE" | awk -F, '{print $NF}')
      fi
      printf '%s\\n' "$value"
      exit 0
    fi
    if [ "$apply_count" -lt "$REQUIRED_APPLY_COUNT" ]; then
      printf '0\\n'
      exit 0
    fi
  fi
  sort -u "$SELECTED_FILE" | sed '/^$/d' | wc -l
  exit 0
fi
if [[ " $* " == *" clustermeshprofile show "* ]]; then
  printf 'Succeeded\\n'
  exit 0
fi
if [[ " $* " == *" clustermeshprofile apply "* ]]; then
  echo apply >> "$APPLY_FILE"
  exit 0
fi
echo "unexpected az invocation: $*" >&2
exit 1
""",
    )
    _write_executable(
        bin_dir / "kubectl",
        """#!/usr/bin/env bash
set -euo pipefail
echo "kubectl ${KUBECONFIG:-} $*" >> "$COMMAND_LOG"
role=$(basename "${KUBECONFIG:-}" .config)
if [[ " $* " == *" get deployment clustermesh-apiserver "* ]]; then
  if [ -n "${FAILING_ROLE:-}" ] && [ "$role" = "$FAILING_ROLE" ]; then
    exit 0
  fi
  printf 'True'
  exit 0
fi
if [[ " $* " == *" get service clustermesh-apiserver "* ]]; then
  printf '10.0.0.1'
  exit 0
fi
if [[ " $* " == *" exec ds/cilium -- cilium-dbg status "* ]]; then
  count=$(sort -u "$SELECTED_FILE" | sed '/^$/d' | wc -l)
  remote=$((count - 1))
  printf 'ClusterMesh:   %s/%s remote clusters ready, 0 global-services\\n' \
    "$remote" "$remote"
  exit 0
fi
echo "unexpected kubectl invocation: $*" >&2
exit 1
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HOME": str(home_dir),
            "COMMAND_LOG": str(command_log),
            "SELECTED_FILE": str(selected_file),
            "APPLY_FILE": str(apply_file),
            "CONNECTED_QUERY_FILE": str(connected_query_file),
            "CONNECTED_SEQUENCE": connected_sequence,
            "REQUIRED_APPLY_COUNT": str(required_apply_count),
            "FAILING_ROLE": failing_role or "",
            "CLUSTERS_FILE": str(clusters_file),
            "FLEET_RG": "test-rg",
            "FLEET_NAME": "test-fleet",
            "FLEET_PROFILE": "test-profile",
            "CMP_STAGED_JOIN_ENABLED": "true",
            "CMP_STAGED_JOIN_BATCH_SIZE": "2",
            "CMP_STAGED_JOIN_BATCH_WAIT_SECONDS": str(batch_wait_seconds),
            "CMP_STAGED_JOIN_TOTAL_WAIT_SECONDS": "10",
            "CMP_STAGED_JOIN_POLL_SECONDS": "1",
            "CMP_STAGED_JOIN_CHECK_CONCURRENCY": "2",
            "CMP_STAGED_JOIN_COMMAND_TIMEOUT_SECONDS": "2",
            "CMP_STAGED_JOIN_QUERY_TIMEOUT_SECONDS": "2",
            "CMP_STAGED_JOIN_RECOVERY_APPLY_AFTER_SECONDS": str(
                recovery_apply_after_seconds
            ),
            "CMP_STAGED_JOIN_MAX_RECOVERY_APPLIES": "1",
            "CMP_STAGED_JOIN_RECOVERY_MIN_POST_SECONDS": str(
                recovery_min_post_seconds
            ),
            "CMP_STAGED_JOIN_SUMMARY_FILE": str(summary_file),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    selected = list(
        dict.fromkeys(selected_file.read_text(encoding="utf-8").splitlines())
        if selected_file.exists()
        else {}
    )
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    return result, selected, summary, command_log.read_text(encoding="utf-8")


def test_staged_join_enrolls_numeric_roles_in_bounded_batches(tmp_path):
    result, selected, summary, command_log = _run_staged_join(
        tmp_path,
        ["mesh-4", "mesh-2", "mesh-1", "mesh-3"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert selected == ["mesh-1", "mesh-2", "mesh-3", "mesh-4"]
    assert command_log.count("clustermeshprofile apply") == 2
    assert summary["status"] == "succeeded"
    assert summary["joined_members"] == 4
    assert [batch["members"] for batch in summary["batches"]] == [
        ["mesh-1", "mesh-2"],
        ["mesh-3", "mesh-4"],
    ]


def test_staged_join_stops_before_next_batch_when_convergence_fails(tmp_path):
    result, selected, summary, _ = _run_staged_join(
        tmp_path,
        ["mesh-1", "mesh-2", "mesh-3", "mesh-4", "mesh-5", "mesh-6"],
        failing_role="mesh-3",
    )

    assert result.returncode != 0
    assert selected == ["mesh-1", "mesh-2", "mesh-3", "mesh-4"]
    assert "mesh-5" not in selected
    assert "mesh-6" not in selected
    assert summary["status"] == "failed"
    assert summary["batches"][-1]["members"] == ["mesh-3", "mesh-4"]


def test_staged_join_issues_one_recovery_apply_after_stall(tmp_path):
    result, selected, summary, command_log = _run_staged_join(
        tmp_path,
        ["mesh-1", "mesh-2"],
        required_apply_count=2,
        batch_wait_seconds=5,
        recovery_apply_after_seconds=1,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert selected == ["mesh-1", "mesh-2"]
    assert command_log.count("clustermeshprofile apply") == 2
    assert "issuing single-request profile recovery apply 1/1" in result.stdout
    assert "fleet member reconcile" not in command_log
    assert summary["status"] == "succeeded"


def test_staged_join_tracks_fresh_progress_after_recovery_apply(tmp_path):
    result, selected, summary, command_log = _run_staged_join(
        tmp_path,
        ["mesh-1", "mesh-2"],
        batch_wait_seconds=7,
        recovery_apply_after_seconds=1,
        connected_sequence="0,0,0,1,2",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert selected == ["mesh-1", "mesh-2"]
    assert command_log.count("clustermeshprofile apply") == 2
    assert "connected_high_water=1" in result.stdout
    assert "connected_high_water=2" in result.stdout
    assert summary["status"] == "succeeded"


def test_staged_join_caps_profile_recovery_applies(tmp_path):
    result, _, summary, command_log = _run_staged_join(
        tmp_path,
        ["mesh-1", "mesh-2"],
        required_apply_count=99,
        batch_wait_seconds=4,
        recovery_apply_after_seconds=1,
    )

    assert result.returncode != 0
    assert command_log.count("clustermeshprofile apply") == 2
    assert summary["status"] == "failed"


def test_staged_join_skips_recovery_without_post_apply_runway(tmp_path):
    result, _, summary, command_log = _run_staged_join(
        tmp_path,
        ["mesh-1", "mesh-2"],
        required_apply_count=99,
        batch_wait_seconds=4,
        recovery_apply_after_seconds=2,
        recovery_min_post_seconds=3,
    )

    assert result.returncode != 0
    assert command_log.count("clustermeshprofile apply") == 1
    assert "skipping recovery apply" in result.stdout
    assert summary["status"] == "failed"


def test_terraform_separates_initial_member_label_from_profile_selector():
    module = FLEET_MODULE_PATH.read_text(encoding="utf-8")
    module_variables = FLEET_VARIABLES_PATH.read_text(encoding="utf-8")
    azure_main = AZURE_MAIN_PATH.read_text(encoding="utf-8")
    azure_variables = AZURE_VARIABLES_PATH.read_text(encoding="utf-8")
    validation = VALIDATE_RESOURCES_PATH.read_text(encoding="utf-8")
    staged_script = SCRIPT_PATH.read_text(encoding="utf-8")
    n2_tfvars = N2_TFVARS_PATH.read_text(encoding="utf-8")

    assert 'variable "member_initial_label_value"' in module_variables
    assert (
        '"--labels", "${var.member_label_key}=${local.member_initial_label_value}"'
        in module
    )
    assert (
        '"--selector", "${var.member_label_key}=${var.member_label_value}"'
        in module
    )
    assert "member_initial_label_value = try(" in azure_main
    assert "member_initial_label_value = optional(string, \"\")" in azure_variables
    assert 'CMP_STAGED_JOIN_ENABLED:-false' in validation
    assert "staged-fleet-enrollment.sh" in validation
    assert "--arg selector_label_value" in staged_script
    assert "--arg label " not in staged_script
    assert "CMP_STAGED_JOIN_RECOVERY_APPLY_AFTER_SECONDS" in staged_script
    assert "CMP_STAGED_JOIN_MAX_RECOVERY_APPLIES" in staged_script
    assert "CMP_STAGED_JOIN_RECOVERY_MIN_POST_SECONDS" in staged_script
    assert "az fleet member reconcile" not in staged_script
    assert "apply_profile 1" in staged_script
    assert "issuing single-request profile recovery apply" in staged_script
    assert "legacy periodic profile re-applier is disabled" in validation
    assert "applied_high_water" in staged_script
    assert "connected_high_water" in staged_script
    assert "next_reapply" not in staged_script
    assert "${var.member_label_key}=detaching" in module
    assert "values(local.member_relabel_command)" in module
    assert (
        'timeout --foreground 300s bash -c "${self.input.apply_command}"'
        in module
    )
    assert "drain_deadline=$((SECONDS + 1800))" in module
    assert "delete_deadline=$((SECONDS + 600))" in module
    assert "member_initial_label_value" not in n2_tfvars
