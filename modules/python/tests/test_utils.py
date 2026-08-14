"""Tests for clusterloader2.utils.run_cl2_command's Azure CLI cache mount.

Focused on the CL2_AZURE_CONFIG_DIR override added to isolate each
clustermesh-scale parallel CL2 worker's Azure CLI (MSAL token) cache from
the host's shared ~/.azure, per provider=aks. `DockerClient` is mocked
throughout so no real docker daemon is required and we can inspect exactly
which host path gets bind-mounted to /root/.azure.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from clusterloader2.utils import run_cl2_command


def _mock_docker_client_class():
    """Build a mock DockerClient class whose run_container returns a
    container stub with empty logs and a zero exit code, and captures the
    volumes dict it was called with for assertions."""
    container = MagicMock()
    container.logs.return_value = iter([])
    container.wait.return_value = {"StatusCode": 0}

    instance = MagicMock()
    instance.run_container.return_value = container

    docker_client_cls = MagicMock(return_value=instance)
    return docker_client_cls, instance


class TestRunCl2CommandAzureCacheIsolation(unittest.TestCase):
    def _run(self, provider, **kwargs):
        docker_client_cls, instance = _mock_docker_client_class()
        with patch("clusterloader2.utils.DockerClient", docker_client_cls):
            run_cl2_command(
                kubeconfig="/kube/config",
                cl2_image="test-image",
                cl2_config_dir="/cl2/config",
                cl2_report_dir="/cl2/report",
                provider=provider,
                **kwargs,
            )
        return instance.run_container.call_args

    def test_aks_default_mounts_host_azure_dir_when_env_unset(self):
        """No CL2_AZURE_CONFIG_DIR -> existing ~/.azure behavior is preserved."""
        env = os.environ.copy()
        env.pop("CL2_AZURE_CONFIG_DIR", None)
        with patch.dict(os.environ, env, clear=True):
            call_args = self._run("aks")

        volumes = call_args.args[2]
        expected_host_path = os.path.expanduser("~/.azure")
        self.assertIn(expected_host_path, volumes)
        self.assertEqual(
            volumes[expected_host_path], {"bind": "/root/.azure", "mode": "rw"}
        )

    def test_aks_uses_override_dir_when_set(self):
        with tempfile.TemporaryDirectory() as override_dir:
            env = os.environ.copy()
            env["CL2_AZURE_CONFIG_DIR"] = override_dir
            with patch.dict(os.environ, env, clear=True):
                call_args = self._run("aks")

        volumes = call_args.args[2]
        self.assertIn(override_dir, volumes)
        self.assertEqual(
            volumes[override_dir], {"bind": "/root/.azure", "mode": "rw"}
        )
        # The host cache must NOT also be mounted when the override is used.
        self.assertNotIn(os.path.expanduser("~/.azure"), volumes)

    def test_aks_override_missing_dir_raises(self):
        env = os.environ.copy()
        env["CL2_AZURE_CONFIG_DIR"] = "/nonexistent/path/does-not-exist"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                self._run("aks")

    def test_aks_override_pointing_to_file_raises(self):
        with tempfile.NamedTemporaryFile() as tmp_file:
            env = os.environ.copy()
            env["CL2_AZURE_CONFIG_DIR"] = tmp_file.name
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    self._run("aks")

    def test_non_aks_provider_ignores_override_and_mounts_nothing_azure(self):
        env = os.environ.copy()
        env["CL2_AZURE_CONFIG_DIR"] = "/nonexistent/path/does-not-exist"
        with patch.dict(os.environ, env, clear=True):
            call_args = self._run("gce")

        volumes = call_args.args[2]
        self.assertNotIn(os.path.expanduser("~/.azure"), volumes)
        self.assertNotIn("/nonexistent/path/does-not-exist", volumes)
        # No exception raised even though the override path doesn't exist,
        # because validation is scoped to provider == "aks".

    def test_aws_provider_behavior_unchanged(self):
        env = os.environ.copy()
        env.pop("CL2_AZURE_CONFIG_DIR", None)
        with patch.dict(os.environ, env, clear=True):
            call_args = self._run("aws")

        volumes = call_args.args[2]
        aws_path = os.path.expanduser("~/.aws/credentials")
        self.assertIn(aws_path, volumes)
        self.assertEqual(
            volumes[aws_path], {"bind": "/root/.aws/credentials", "mode": "rw"}
        )
        self.assertNotIn(os.path.expanduser("~/.azure"), volumes)

    def test_named_worker_container_is_removed_after_completion(self):
        docker_client_cls, instance = _mock_docker_client_class()
        with patch("clusterloader2.utils.DockerClient", docker_client_cls):
            with patch.dict(
                os.environ,
                {"CL2_WORKER_CONTAINER_NAME": "cl2-run-mesh-1"},
                clear=True,
            ):
                run_cl2_command(
                    kubeconfig="/kube/config",
                    cl2_image="test-image",
                    cl2_config_dir="/cl2/config",
                    cl2_report_dir="/cl2/report",
                    provider="gce",
                )

        self.assertEqual(
            instance.run_container.call_args.kwargs["name"],
            "cl2-run-mesh-1",
        )
        instance.run_container.return_value.remove.assert_called_once_with(
            force=True
        )


if __name__ == "__main__":
    unittest.main()
