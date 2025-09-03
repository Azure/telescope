# pylint: disable=protected-access
import unittest
from unittest import mock
import os
import docker

from clusterloader2.utils.cl2_command import Cl2Command


class DummyContainer:
    def __init__(self, logs_iter=None, wait_result=None):
        self._logs_iter = logs_iter or []
        self._wait_result = wait_result or {"StatusCode": 0}

    def logs(self, stream=True):
        # mimic generator when stream=True
        yield from self._logs_iter

    def wait(self):
        return self._wait_result


class DummyDockerClient:
    def __init__(self, container=None, raise_on_run=None):
        self._container = container
        self._raise_on_run = raise_on_run

    def run_container(self, image, command, volumes, detach=True):
        if self._raise_on_run:
            raise self._raise_on_run
        return self._container


class TestCl2Command(unittest.TestCase):
    def test_build_command_basic_and_flags(self):
        params = Cl2Command.Params(
            provider="gcp",
            enable_exec_service=False,
            enable_prometheus=False,
            scrape_containerd=False,
            overrides=False,
        )
        cmd = Cl2Command(params)
        built = cmd._build_command()
        self.assertIn("--provider=gcp", built)
        self.assertIn("--enable-exec-service=False", built)
        self.assertIn("--enable-prometheus-server=False", built)
        self.assertNotIn("--prometheus-scrape-containerd", built)

    def test_build_command_with_containerd_and_overrides(self):
        params = Cl2Command.Params(
            provider="aws",
            enable_exec_service=True,
            enable_prometheus=True,
            scrape_containerd=True,
            overrides=True,
            cl2_config_file="custom.yaml",
            tear_down_prometheus=False,
            scrape_ksm=True,
            scrape_metrics_server=True,
        )
        cmd = Cl2Command(params)
        built = cmd._build_command()
        self.assertIn("--provider=aws", built)
        self.assertIn("--enable-exec-service=True", built)
        self.assertIn("--enable-prometheus-server=True", built)
        self.assertIn("--prometheus-scrape-containerd=True", built)
        self.assertIn("--testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml", built)
        self.assertIn("--testconfig /root/perf-tests/clusterloader2/config/custom.yaml", built)
        self.assertIn("--tear-down-prometheus-server=False", built)
        self.assertIn("--prometheus-scrape-kube-state-metrics=True", built)
        self.assertIn("--prometheus-scrape-metrics-server=True", built)

    def test_build_volumes_includes_aws_credentials_for_aws_provider(self):
        params = Cl2Command.Params(
            kubeconfig="/tmp/kc",
            cl2_config_dir="/tmp/config",
            cl2_report_dir="/tmp/results",
            provider="aws",
        )
        cmd = Cl2Command(params)
        vols = cmd._build_volumes()
        self.assertIn(params.kubeconfig, vols)
        self.assertIn(params.cl2_config_dir, vols)
        self.assertIn(params.cl2_report_dir, vols)
        aws_path = os.path.expanduser("~/.aws/credentials")
        self.assertIn(aws_path, vols)
        self.assertEqual(vols[params.kubeconfig]["bind"], '/root/.kube/config')

    def test_run_container_handles_container_error_and_logs(self):
        params = Cl2Command.Params(cl2_image="img")
        # Construct a docker.errors.ContainerError with a stderr bytes payload
        err = docker.errors.ContainerError(container=None, exit_status=1, command=None, image=None, stderr=b"error-msg")
        dummy_client = DummyDockerClient(raise_on_run=err)
        cmd = Cl2Command(params, docker_client=dummy_client)

        with mock.patch('clusterloader2.utils.cl2_command.logger') as mock_logger:
            container = cmd._run_container("cmd", {})
            self.assertIsNone(container)
            # error should be logged (stderr decoded)
            mock_logger.error.assert_called()

    def test_stream_logs_and_handle_result(self):
        params = Cl2Command.Params()
        # prepare dummy container that yields logs and returns non-zero exit code
        logs_iter = [b"line1\n", b"\n", b"line2\n"]
        container = DummyContainer(logs_iter=logs_iter, wait_result={"StatusCode": 1})
        cmd = Cl2Command(params)

        with mock.patch('clusterloader2.utils.cl2_command.logger') as mock_logger:
            # stream logs should call logger.info for non-empty lines
            cmd._stream_logs(container)
            # should have been called at least twice: line1 and line2
            self.assertTrue(mock_logger.info.call_count >= 2)

            # handle_result should log an error for non-zero exit codes
            cmd._handle_result(container)
            mock_logger.error.assert_called()


if __name__ == '__main__':
    unittest.main()
