import os
import docker

from clients.docker_client import DockerClient
from utils.logger_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

def run_cl2_command(
    kubeconfig,
    cl2_image,
    cl2_config_dir,
    cl2_report_dir,
    provider,
    cl2_config_file="config.yaml",
    overrides=False,
    enable_prometheus=False,
    tear_down_prometheus=True,
    enable_exec_service=False,
    scrape_kubelets=False,
    scrape_containerd=False,
    scrape_ksm=False,
    scrape_metrics_server=False,
):
    docker_client = DockerClient()

    command = f"""--provider={provider} --v=2
--enable-exec-service={enable_exec_service}
--enable-prometheus-server={enable_prometheus}
--prometheus-scrape-kubelets={scrape_kubelets}
--kubeconfig /root/.kube/config
--testconfig /root/perf-tests/clusterloader2/config/{cl2_config_file}
--report-dir /root/perf-tests/clusterloader2/results
--tear-down-prometheus-server={tear_down_prometheus}
--prometheus-scrape-kube-state-metrics={scrape_ksm}
--prometheus-scrape-metrics-server={scrape_metrics_server}"""

    if scrape_containerd:
        command += f" --prometheus-scrape-containerd={scrape_containerd}"

    if overrides:
        command += " --testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml"

    volumes = {
        kubeconfig: {'bind': '/root/.kube/config', 'mode': 'rw'},
        cl2_config_dir: {'bind': '/root/perf-tests/clusterloader2/config', 'mode': 'rw'},
        cl2_report_dir: {
            'bind': '/root/perf-tests/clusterloader2/results', 'mode': 'rw'}
    }

    if provider == "aws":
        aws_path = os.path.expanduser("~/.aws/credentials")
        volumes[aws_path] = {'bind': '/root/.aws/credentials', 'mode': 'rw'}

    logger.info(
        f"Running clusterloader2 with command: {command} and volumes: {volumes}")
    try:
        container = docker_client.run_container(
            cl2_image, command, volumes, detach=True)
        for log in container.logs(stream=True):
            log_line = log.decode('utf-8').rstrip('\n')
            if log_line:
                logger.info(log_line)
        result = container.wait()
        exit_code = result['StatusCode']
        if exit_code != 0:
            logger.error(
                f"clusterloader2 exited with a non-zero status code {exit_code}."
                " Make sure to check the logs to confirm whether the error is expected!"
            )
    except docker.errors.ContainerError as e:
        logger.error(
            f"Container exited with a non-zero status code: {e.exit_status}\n{e.stderr.decode('utf-8')}")
