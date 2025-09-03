from dataclasses import dataclass

import os
import docker

from clients.docker_client import DockerClient
from utils.logger_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


class Cl2Command:
    @dataclass
    class Params:
        kubeconfig: str = ""
        cl2_image: str = ""
        cl2_config_dir: str = ""
        cl2_report_dir: str = ""
        provider: str = ""
        cl2_config_file: str = "config.yaml"
        overrides: bool = False
        enable_prometheus: bool = False
        tear_down_prometheus: bool = True
        enable_exec_service: bool = False
        scrape_kubelets: bool = False
        scrape_containerd: bool = False
        scrape_ksm: bool = False
        scrape_metrics_server: bool = False

    def __init__(
        self,
        cl2_params: Params,
        docker_client: DockerClient = None,
    ):
        self.cl2_params = cl2_params
        self.docker_client = docker_client if docker_client is not None else DockerClient()

    def _build_command(self):
        p = self.cl2_params
        command = f"--provider={p.provider} --v=2 "
        command += f"--enable-exec-service={p.enable_exec_service} "
        command += f"--enable-prometheus-server={p.enable_prometheus} "
        command += f"--prometheus-scrape-kubelets={p.scrape_kubelets} "
        command += "--kubeconfig /root/.kube/config "
        command += f"--testconfig /root/perf-tests/clusterloader2/config/{p.cl2_config_file} "
        command += "--report-dir /root/perf-tests/clusterloader2/results "
        command += f"--tear-down-prometheus-server={p.tear_down_prometheus} "
        command += f"--prometheus-scrape-kube-state-metrics={p.scrape_ksm} "
        command += f"--prometheus-scrape-metrics-server={p.scrape_metrics_server}"
        if p.scrape_containerd:
            command += f" --prometheus-scrape-containerd={p.scrape_containerd}"
        if p.overrides:
            command += " --testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml"
        return command

    def _build_volumes(self):
        p = self.cl2_params
        volumes = {
            p.kubeconfig: {'bind': '/root/.kube/config', 'mode': 'rw'},
            p.cl2_config_dir: {'bind': '/root/perf-tests/clusterloader2/config', 'mode': 'rw'},
            p.cl2_report_dir: {'bind': '/root/perf-tests/clusterloader2/results', 'mode': 'rw'}
        }
        if p.provider == "aws":
            aws_path = os.path.expanduser("~/.aws/credentials")
            volumes[aws_path] = {'bind': '/root/.aws/credentials', 'mode': 'rw'}
        return volumes

    def _run_container(self, command, volumes):
        logger.info(f"Running clusterloader2 with command: {command} and volumes: {volumes}")
        try:
            container = self.docker_client.run_container(
                self.cl2_params.cl2_image,
                command,
                volumes,
                detach=True
            )
            return container
        except docker.errors.ContainerError as e:
            logger.error(
                f"Container exited with a non-zero status code: {e.exit_status}\n{e.stderr.decode('utf-8')}")
            return None

    def _stream_logs(self, container):
        if container is None:
            return
        for log in container.logs(stream=True):
            log_line = log.decode('utf-8').rstrip('\n')
            if log_line:
                logger.info(log_line)

    def _handle_result(self, container):
        if container is None:
            return
        result = container.wait()
        exit_code = result['StatusCode']
        if exit_code != 0:
            logger.error(
                f"clusterloader2 exited with a non-zero status code {exit_code}. "
                "Make sure to check the logs to confirm whether the error is expected!")

    def execute(self):
        command = self._build_command()
        volumes = self._build_volumes()
        container = self._run_container(command, volumes)
        self._stream_logs(container)
        self._handle_result(container)
