"""Tests for provision-kwok-layer.sh's optional MOCK_STATE_DIR persistence.

Runs the real vendored script end-to-end against a fake `kubectl` + `curl` on
PATH (no real cluster / network involved), consistent with the existing
node-churner.sh script tests (test_clustermesh_scale.py::TestNodeChurnerScript)
which fake `az` the same way.
"""

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scenarios"
    / "perf-eval"
    / "clustermesh-scale"
    / "mock"
    / "provision-kwok-layer.sh"
)

FAKE_KUBECTL = textwrap.dedent("""\
    #!/usr/bin/env bash
    # Fake kubectl for provision-kwok-layer.sh tests. Never touches a real
    # cluster; answers just enough of the subset of `kubectl` invocations the
    # script issues (cilium-config reads, applies, rollout status, node/pod
    # counts) to let the script run to completion deterministically.
    set -u
    args="$*"
    case "$args" in
      *"get nodes"*"-l type=kwok"*)
        n="${FAKE_NODE_COUNT:-0}"
        for ((i = 0; i < n; i++)); do
          printf 'kwok-node-%d   Ready   <none>   1m   fake\\n' "$i"
        done
        ;;
      *"get pods"*"-l app=mock-cilium-agent"*)
        n="${FAKE_NODE_COUNT:-0}"
        for ((i = 0; i < n; i++)); do
          printf 'mock-cilium-agent-%d   1/1   Running   0   1m\\n' "$i"
        done
        ;;
      *)
        : # cilium-config reads / apply / rollout status: succeed, no output.
        ;;
    esac
    exit 0
""")

FAKE_CURL = textwrap.dedent("""\
    #!/usr/bin/env bash
    # Fake curl for provision-kwok-layer.sh tests: serves a minimal static
    # kwok-controller Deployment (so the script's YAML patch step has a real
    # Deployment doc to find) instead of hitting the network.
    set -u
    out=""
    prev=""
    for arg in "$@"; do
      if [ "$prev" = "-o" ]; then out="$arg"; fi
      prev="$arg"
    done
    if [ -n "$out" ]; then
      case "$out" in
        *kwok.yaml)
          cat > "$out" <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kwok-controller
  namespace: kube-system
spec:
  replicas: 1
  selector: {matchLabels: {app: kwok-controller}}
  template:
    metadata: {labels: {app: kwok-controller}}
    spec:
      containers:
      - name: kwok-controller
        image: registry.k8s.io/kwok/kwok:fake
EOF
          ;;
        *)
          : > "$out"
          ;;
      esac
    fi
    exit 0
""")


def _make_fake_bin(tmp_path):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for script_name, content in (("kubectl", FAKE_KUBECTL), ("curl", FAKE_CURL)):
        script_path = bin_dir / script_name
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run_provision(tmp_path, *, node_count=2, mock_state_dir=None, extra_env=None):
    bin_dir = _make_fake_bin(tmp_path)
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\nkind: Config\n", encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["FAKE_NODE_COUNT"] = str(node_count)
    env["KUBECONFIG_FILE"] = str(kubeconfig)
    env["ACR_HOST"] = "fake.azurecr.io"
    env["NODE_COUNT"] = str(node_count)
    env["MOCK_CLUSTER_NAME"] = "mesh-1"
    env["MOCK_CLUSTER_ID"] = "1"
    env["CONSUME_CLUSTERMESH"] = "false"
    if mock_state_dir is not None:
        env["MOCK_STATE_DIR"] = str(mock_state_dir)
    else:
        env.pop("MOCK_STATE_DIR", None)
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        capture_output=True, text=True, env=env, check=False,
        timeout=180,
    )


class TestProvisionKwokLayerScriptSyntax(unittest.TestCase):
    def test_script_exists_and_is_executable(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"{SCRIPT_PATH} should exist")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be executable")

    def test_script_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT_PATH)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, f"bash -n failed: stderr={result.stderr}")


class TestMockStateDirPersistence(unittest.TestCase):
    """MOCK_STATE_DIR is optional: unset preserves current behavior, and when
    set the exact generated manifests + metadata are persisted atomically.
    """

    def test_state_dir_persists_exact_manifests_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / "state" / "mesh-1"
            # Pre-seed a stale leftover from a prior (different) run to prove
            # the publish step fully replaces old content rather than merging.
            state_dir.mkdir(parents=True)
            (state_dir / "stale-leftover.txt").write_text("stale", encoding="utf-8")

            result = _run_provision(
                tmp_path, node_count=2, mock_state_dir=state_dir,
                extra_env={"MOCK_RUN_ID": "run-abc123", "CONSUME_CLUSTERMESH": "false"},
            )

            self.assertEqual(result.returncode, 0, f"stdout={result.stdout}\nstderr={result.stderr}")

            self.assertFalse((state_dir / "stale-leftover.txt").exists(),
                             "atomic publish must fully replace prior state dir contents")

            nodes_yaml = (state_dir / "nodes.yaml").read_text(encoding="utf-8")
            agents_yaml = (state_dir / "agents.yaml").read_text(encoding="utf-8")
            metadata = json.loads((state_dir / "metadata.json").read_text(encoding="utf-8"))

            self.assertIn("name: kwok-node-0", nodes_yaml)
            self.assertIn("name: kwok-node-1", nodes_yaml)
            self.assertEqual(nodes_yaml.count("kind: Node"), 2)
            self.assertIn("name: mock-cilium-agent-0", agents_yaml)
            self.assertIn("name: mock-cilium-agent-1", agents_yaml)
            self.assertEqual(agents_yaml.count("kind: Pod"), 2)

            self.assertEqual(metadata["schema_version"], 2)
            self.assertEqual(metadata["node_count"], 2)
            self.assertEqual(metadata["cluster_name"], "mesh-1")
            self.assertEqual(metadata["cluster_id"], "1")
            self.assertEqual(metadata["agent_namespace"], "mock-clustermesh")
            self.assertEqual(metadata["agent_image"], "fake.azurecr.io/mock-cilium-agent:v26")
            self.assertEqual(metadata["run_id"], "run-abc123")
            self.assertIs(metadata["consume_clustermesh"], False)
            self.assertEqual(metadata["support_manifest_dir"], "support")
            self.assertEqual(metadata["support_manifests"], {
                "kwok_controller": "support/kwok-controller.yaml",
                "stage": "support/stage-fast.yaml",
                "apf": "support/kwok-apf.yaml",
                "rbac": "support/rbac.yaml",
            })

            # The exact already-rendered support manifests must be persisted
            # (never re-derived later) so a reconciler can repair support
            # infra without redownloading/rebuilding anything.
            support_dir = state_dir / "support"
            self.assertTrue((support_dir / "kwok-controller.yaml").is_file())
            self.assertTrue((support_dir / "stage-fast.yaml").is_file())
            self.assertTrue((support_dir / "kwok-apf.yaml").is_file())
            self.assertTrue((support_dir / "rbac.yaml").is_file())
            kwok_controller_yaml = (support_dir / "kwok-controller.yaml").read_text(encoding="utf-8")
            self.assertIn("kind: Deployment", kwok_controller_yaml)
            self.assertIn("name: kwok-controller", kwok_controller_yaml)

    def test_state_dir_persists_consume_clustermesh_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / "state" / "mesh-1"

            result = _run_provision(
                tmp_path, node_count=1, mock_state_dir=state_dir,
                extra_env={"MOCK_RUN_ID": "run-xyz", "CONSUME_CLUSTERMESH": "true"},
            )

            self.assertEqual(result.returncode, 0, f"stdout={result.stdout}\nstderr={result.stderr}")
            metadata = json.loads((state_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["run_id"], "run-xyz")
            self.assertIs(metadata["consume_clustermesh"], True)

    def test_unset_state_dir_preserves_current_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = _run_provision(tmp_path, node_count=1, mock_state_dir=None)

            self.assertEqual(result.returncode, 0, f"stdout={result.stdout}\nstderr={result.stderr}")
            # No state directory anywhere under the sandbox -- persistence is
            # strictly opt-in.
            leftover_state_dirs = list(tmp_path.rglob("metadata.json"))
            self.assertEqual(leftover_state_dirs, [])


if __name__ == "__main__":
    unittest.main()
