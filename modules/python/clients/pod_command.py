from typing import Optional
from clients.kubernetes_client import KubernetesClient
from utils.retries import execute_with_retries
from utils.logger_config import get_logger, setup_logging


setup_logging()
logger = get_logger(__name__)


class PodRoleCommand:
    def __init__(
        self,
        client_label_selector: str,
        server_label_selector: str,
        client_container: str,
        server_container: str,
        cluster_cli_context: str,
        cluster_srv_context: str,
        validate_command: Optional[str] = "",
        service_name: Optional[str] = "",
        namespace="default",
    ):
        self._client_label_selector = client_label_selector
        self._server_label_selector = server_label_selector
        self._client_container = client_container
        self._server_container = server_container
        self._validate_command = validate_command
        self._service_name = service_name
        self.cluster_cli_context = cluster_cli_context
        self.cluster_srv_context = cluster_srv_context
        self.namespace = namespace
        self.k8s_client = KubernetesClient()
        self.pod_role = {}
        self.service_external_ip = None

    @property
    def client_label_selector(self):
        return self._client_label_selector

    @property
    def server_label_selector(self):
        return self._server_label_selector

    @property
    def client_container(self):
        return self._client_container

    @property
    def server_container(self):
        return self._server_container

    @property
    def validate_command(self):
        return self._validate_command

    @property
    def service_name(self):
        return self._service_name

    def set_context_by_role(self, role: str):
        label_selector = ""
        if role == "server":
            self.k8s_client.set_context(self.cluster_srv_context)
            label_selector = self.server_label_selector
        elif role == "client":
            self.k8s_client.set_context(self.cluster_cli_context)
            label_selector = self.client_label_selector
        else:
            raise ValueError(f"Unsupported role: {role}")
        return label_selector

    def get_pod_by_role(self, role: str):
        if role in self.pod_role:
            return self.pod_role.get(role)

        label_selector = self.set_context_by_role(role)
        pod = self.k8s_client.get_pod_name_and_ip(
            label_selector=label_selector, namespace=self.namespace
        )
        self.pod_role[role] = pod
        return pod

    def get_service_external_ip(self):
        if not self.service_name:
            raise ValueError(
                "Service name must be provided to get the external IP.")
        if not self.service_external_ip:
            self.set_context_by_role("server")
            self.service_external_ip = self.k8s_client.get_service_external_ip(
                service_name=self.service_name, namespace=self.namespace
            )

        return self.service_external_ip

    def run_command_for_role(self, role: str, command: str, result_file: str):
        pod = self.get_pod_by_role(role=role)
        if not pod:
            raise ValueError(f"No pod found for role: {role}")
        logger.info(
            f"namespace: {self.namespace}, client_pod: {pod['name']}, command: {command}")

        if role == "client":
            container_name = self.client_container
            context_name = self.cluster_cli_context
        elif role == "server":
            container_name = self.server_container
            context_name = self.cluster_srv_context
        else:
            raise ValueError(f"Unsupported role: {role}")

        self.k8s_client.set_context(context_name)

        return execute_with_retries(
            self.k8s_client.run_pod_exec_command,
            pod_name=pod["name"],
            command=command,
            container_name=container_name,
            dest_path=result_file,
            namespace=self.namespace,
        )

    def validate(self):
        self.run_command_for_role(
            role="client", command=self.validate_command or "", result_file="")
        self.run_command_for_role(
            role="server", command=self.validate_command or "", result_file="")

    def collect(self, result_dir: str):
        logger.info(f"Switching context to {self.cluster_cli_context}")
        self.k8s_client.set_context(self.cluster_cli_context)
        self.k8s_client.collect_pod_and_node_info(
            namespace=self.namespace,
            label_selector=self.client_label_selector,
            result_dir=result_dir,
            role="client",
        )
        logger.info(f"Switching context to {self.cluster_srv_context}")
        self.k8s_client.set_context(self.cluster_srv_context)
        self.k8s_client.collect_pod_and_node_info(
            namespace=self.namespace,
            label_selector=self.server_label_selector,
            result_dir=result_dir,
            role="server",
        )
