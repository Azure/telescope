import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


@unittest.skipUnless(shutil.which("bash"), "Bash is required to test pipeline setup")
class TestAKSPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[3]
        with (cls.root / "steps" / "setup-tests.yml").open(encoding="utf-8") as handle:
            steps = yaml.safe_load(handle)["steps"]
        cls.dependencies_script = next(
            step["script"] for step in steps if step.get("displayName") == "Install Dependencies"
        ).replace("$(Pipeline.Workspace)", "$TEST_WORKSPACE")
        execute = cls.root / "steps" / "engine" / "clusterloader2" / "cri" / "execute.yml"
        with execute.open(encoding="utf-8") as handle:
            steps = yaml.safe_load(handle)["steps"]
        cls.prepare_script = next(iter(steps[0].values()))[0]["script"]
        install = cls.root / "steps" / "cloud" / "azure" / "install-kubelogin.yml"
        with install.open(encoding="utf-8") as handle:
            cls.configure_script = yaml.safe_load(handle)["steps"][-1]["script"]

    def run_script(self, script, environment):
        return subprocess.run(
            [shutil.which("bash"), "--noprofile", "--norc"],
            input=script,
            env={**os.environ, **environment},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def run_dependencies(self, bc_present="true", nc_present="true", mode="success"):
        mocks = """
pip3() { return 0; }
sleep() { return 0; }
command() {
  if [[ "$1" == "-v" && "$2" == "bc" ]]; then
    [[ "$BC_PRESENT" == "true" ]]
  elif [[ "$1" == "-v" && "$2" == "nc" ]]; then
    [[ "$NC_PRESENT" == "true" ]]
  else
    builtin command "$@"
  fi
}
sudo() {
  echo "sudo $*" >&2
  if [[ "$*" == *" update" && "$MODE" == "update_error" ]]; then
    return 100
  fi
  if [[ "$*" == *" install "* && "$MODE" == "install_error" ]]; then
    echo "Package manager failure" >&2
    return 100
  fi
}
"""
        return self.run_script(mocks + self.dependencies_script, {
            "BC_PRESENT": bc_present, "NC_PRESENT": nc_present, "MODE": mode,
            "TEST_WORKSPACE": "unused",
        })

    def test_installed_dependencies_skip_apt(self):
        result = self.run_dependencies()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("sudo ", result.stderr)
        self.assertIn("skipping APT", result.stdout)

    def test_only_missing_packages_are_installed_with_lock_wait(self):
        for bc_present, nc_present, packages in (
            ("true", "false", "netcat-openbsd"),
            ("false", "true", "bc"),
            ("false", "false", "bc netcat-openbsd"),
        ):
            with self.subTest(packages=packages):
                result = self.run_dependencies(bc_present, nc_present)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    f"sudo apt-get -o DPkg::Lock::Timeout=900 -o Acquire::Retries=3 -y install {packages}",
                    result.stderr,
                )
                self.assertNotIn("dpkg --configure", result.stderr)

    def test_package_failures_are_not_ignored(self):
        for mode, status in (("update_error", 1), ("install_error", 100)):
            with self.subTest(mode=mode):
                result = self.run_dependencies("false", "false", mode)
                self.assertEqual(result.returncode, status, result.stderr)
                if mode == "update_error":
                    self.assertNotIn("-y install", result.stderr)

    def run_prepare(self, exec_command, mode="success"):
        with tempfile.TemporaryDirectory() as directory:
            kubelogin = Path(directory) / "kubelogin"
            kubelogin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            kubelogin.chmod(0o755)
            mocks = """
kubectl() { echo "$EXEC_COMMAND"; }
docker() {
  echo "docker $*" >&2
  if [[ "$1" == "build" ]]; then
    [[ -f "${@: -1}/kubelogin" ]] || return 97
    [[ "$MODE" != "build_error" ]] || return 7
    echo "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  elif [[ "$1" == "run" ]]; then
    [[ "$MODE" != "tools_error" ]] || return 9
  else
    return 99
  fi
}
"""
            if os.name == "nt":
                mocks += 'CL2_DOCKERFILE=$(cygpath -u "$CL2_DOCKERFILE")\n'
            return self.run_script(mocks + self.prepare_script, {
                "PATH": directory + os.pathsep + os.environ["PATH"],
                "EXEC_COMMAND": exec_command,
                "MODE": mode,
                "CL2_BASE_IMAGE": "ghcr.io/azure/clusterloader2:v20250513",
                "CL2_DOCKERFILE": str(
                    self.root / "modules" / "python" / "clusterloader2" / "Dockerfile.aks"
                ),
            })

    def test_entra_image_preserves_base_and_checks_auth_tools(self):
        for command in ("kubelogin", "/usr/local/bin/kubelogin"):
            with self.subTest(command=command):
                result = self.run_prepare(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("BASE_IMAGE=ghcr.io/azure/clusterloader2:v20250513", result.stderr)
                self.assertIn("az version && kubelogin --version", result.stderr)
                self.assertIn("variable=CRI_CL2_IMAGE]sha256:", result.stdout)

    def test_non_entra_cluster_keeps_original_image(self):
        result = self.run_prepare("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("docker ", result.stderr)
        self.assertIn("variable=CRI_CL2_IMAGE]ghcr.io/azure/clusterloader2:v20250513", result.stdout)

    def test_failed_build_or_missing_tools_does_not_publish_image(self):
        for mode, status in (("build_error", 7), ("tools_error", 9)):
            with self.subTest(mode=mode):
                result = self.run_prepare("kubelogin", mode)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertNotIn("variable=CRI_CL2_IMAGE]", result.stdout)

    def test_noninteractive_conversion_propagates_errors(self):
        for status in (0, 1):
            with self.subTest(status=status):
                mock = """
kubelogin() {
  echo "kubelogin $*" >&2
  if [[ "$1" == "convert-kubeconfig" ]]; then
    return "$CONVERT_STATUS"
  fi
}
"""
                result = self.run_script(mock + self.configure_script, {"CONVERT_STATUS": str(status)})
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn("kubelogin convert-kubeconfig -l azurecli", result.stderr)
