import time
import os
import yaml
from kubernetes import client, config
from kubernetes.stream import stream
from utils.logger_config import get_logger, setup_logging

# https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/#taint-based-evictions
# https://kubernetes.io/docs/reference/labels-annotations-taints/
builtin_taints_keys = [
	"node.kubernetes.io/not-ready",
	"node.kubernetes.io/unreachable",
	"node.kubernetes.io/pid-pressure",
	"node.kubernetes.io/out-of-disk",
	"node.kubernetes.io/memory-pressure",
	"node.kubernetes.io/disk-pressure",
	"node.kubernetes.io/network-unavailable",
	"node.kubernetes.io/unschedulable",
	"node.cloudprovider.kubernetes.io/uninitialized",
	"node.cloudprovider.kubernetes.io/shutdown",
]

# Configure logging
setup_logging()
logger = get_logger(__name__)

class KubernetesClient:
    def __init__(self, kubeconfig=None):
        config.load_kube_config(kubeconfig)
        self.api = client.CoreV1Api()
        self.app = client.AppsV1Api()
        self.storage = client.StorageV1Api()

    def get_app_client(self):
        return self.app

    def describe_node(self, node_name):
        return self.api.read_node(node_name)

    def get_nodes(self, label_selector=None, field_selector=None):
        return self.api.list_node(label_selector=label_selector, field_selector=field_selector).items

    def get_ready_nodes(self, label_selector=None, field_selector=None):
        """
        Get a list of nodes that are ready to be scheduled. Should apply all those conditions:
        - 'Ready' condition status is True
        - 'NetworkUnavailable' condition status is not present or is False
        - Spec unschedulable is False
        - Spec taints do not have any of the builtin taints keys with effect 'NoSchedule' or 'NoExecute'
        """
        nodes = self.get_nodes(label_selector=label_selector, field_selector=field_selector)
        return [
            node for node in nodes
            if self._is_node_schedulable(node) and self._is_node_untainted(node)
        ]

    def _is_node_schedulable(self, node):
        status_conditions = {cond.type: cond.status for cond in node.status.conditions}
        is_schedulable = (
            status_conditions.get("Ready") == "True"
            and status_conditions.get("NetworkUnavailable") != "True"
            and node.spec.unschedulable is not True
        )
        if not is_schedulable:
            logger.info(f"Node NOT Ready: '{node.metadata.name}' is not schedulable. status_conditions: {status_conditions}. unschedulable: {node.spec.unschedulable}")

        return is_schedulable

    def _is_node_untainted(self, node):
        if not node.spec.taints:
            return True

        for taint in node.spec.taints:
            if taint.key in builtin_taints_keys and taint.effect in ("NoSchedule", "NoExecute"):
                logger.info(f"Node NOT Ready: '{node.metadata.name}' has taint '{taint.key}' with effect '{taint.effect}'")
                return False

        return True

    def _is_ready_pod(self, pod):
        if pod.status.phase != "Running":
            return False

        for condition in pod.status.conditions:
            if condition.type == "Ready" and condition.status == "True":
                return True

        return False

    def get_pods_by_namespace(self, namespace, label_selector=None, field_selector=None):
        return self.api.list_namespaced_pod(namespace=namespace, label_selector=label_selector, field_selector=field_selector).items

    def get_ready_pods_by_namespace(self, namespace=None, label_selector=None, field_selector=None):
        pods = self.get_pods_by_namespace(namespace=namespace, label_selector=label_selector, field_selector=field_selector)
        return [pod for pod in pods if pod.status.phase == "Running" and self._is_ready_pod(pod)]

    def get_persistent_volume_claims_by_namespace(self, namespace):
        return self.api.list_namespaced_persistent_volume_claim(namespace=namespace).items

    def get_bound_persistent_volume_claims_by_namespace(self, namespace):
        claims = self.get_persistent_volume_claims_by_namespace(namespace=namespace)
        return [claim for claim in claims if claim.status.phase == "Bound"]

    def delete_persistent_volume_claim_by_namespace(self, namespace):
        pvcs = self.get_persistent_volume_claims_by_namespace(namespace=namespace)
        for pvc in pvcs:
            try:
                self.api.delete_namespaced_persistent_volume_claim(pvc.metadata.name, namespace, body=client.V1DeleteOptions())
            except client.rest.ApiException as e:
                logger.error(f"Error deleting PVC '{pvc.metadata.name}': {e}")

    def get_volume_attachments(self):
        return self.storage.list_volume_attachment().items

    def get_attached_volume_attachments(self):
        volume_attachments = self.get_volume_attachments()
        return [attachment for attachment in volume_attachments if attachment.status.attached]

    def create_namespace(self, namespace):
        """
        Returns the namespace object if it exists, otherwise creates it.
        """
        try:
            namespace = self.api.read_namespace(namespace)
            logger.info(f"Namespace '{namespace.metadata.name}' already exists.")
            return namespace
        except client.rest.ApiException as e:
            if e.status == 404:
                body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
                return self.api.create_namespace(body)
            raise e

    def delete_namespace(self, namespace):
        return self.api.delete_namespace(namespace)

    # TODO: Explore https://kustomize.io for templating
    def create_template(self, template_path: str, replacements: dict) -> str:
        """
        Generate a Kubernetes resource template by replacing placeholders with actual values.

        :param template_path: Path to the YAML template file.
        :param replacements: Dictionary of placeholders and their corresponding values.
        :return: Processed YAML content as a string.
        """
        if not os.path.isfile(template_path):
            raise FileNotFoundError(f"Template file not found: {template_path}")

        try:
            with open(template_path, "r", encoding="utf-8") as file:
                template = file.read()

            for key, value in replacements.items():
                template = template.replace(f"{{{{{key}}}}}", str(value))
                logger.info(f"Final template: \n{template}")

            return template
        except Exception as e:
            raise Exception(f"Error processing template file {template_path}: {str(e)}") from e

    def create_deployment(self, template, namespace="default"):
        """
        Create a Deployment in the specified namespace using the provided YAML template.

        :param template: YAML template for the Deployment.
        :param namespace: Namespace where the Deployment will be created.
        :return: Name of the created Deployment.
        """
        try:
            deployment_obj = yaml.safe_load(template)
            response = self.app.create_namespaced_deployment(
                body=deployment_obj,
                namespace=namespace
            )
            return response.metadata.name
        except yaml.YAMLError as e:
            raise Exception(f"Error parsing deployment template: {str(e)}") from e
        except Exception as e:
            raise Exception(f"Error creating deployment {template}: {str(e)}") from e

    def wait_for_nodes_ready(self, node_count, operation_timeout_in_minutes, label_selector=None):
        """
        Waits for a specific number of nodes with a given label to be ready within a specified timeout.
        Raises an exception if the expected number of nodes are not ready within the timeout.

        :param node_label: The label to filter nodes.
        :param node_count: The expected number of nodes to be ready.
        :param operation_timeout_in_minutes: The timeout in minutes to wait for the nodes to be ready.
        :return: None
        """
        ready_node_count = 0
        timeout = time.time() + (operation_timeout_in_minutes * 60)
        logger.info(f"Validating {node_count} nodes with label {label_selector} are ready.")
        while time.time() < timeout:
            ready_nodes = self.get_ready_nodes(label_selector=label_selector)
            ready_node_count = len(ready_nodes)
            logger.info(f"Currently {ready_node_count} nodes are ready.")
            if ready_node_count == node_count:
                break
            logger.info(f"Waiting for {node_count} nodes to be ready.")
            time.sleep(10)
        if ready_node_count != node_count:
            raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")

    def wait_for_pods_ready(self, pod_count, operation_timeout_in_minutes, namespace="default", label_selector=None):
        """
        Waits for a specific number of pods with a given label to be ready within a specified timeout.
        Raises an exception if the expected number of pods are not ready within the timeout.

        :param label_selector: The label to filter pods.
        :param pod_count: The expected number of pods to be ready.
        :param operation_timeout_in_minutes: The timeout in minutes to wait for the pods to be ready.
        :param namespace: The namespace to filter pods.
        :return: None
        """
        pods = []
        timeout = time.time() + (operation_timeout_in_minutes * 60)
        logger.info(f"Validating {pod_count} pods with label {label_selector} are ready.")
        while time.time() < timeout:
            pods = self.get_ready_pods_by_namespace(namespace=namespace, label_selector=label_selector)
            if len(pods) == pod_count:
                return pods
            logger.info(f"Waiting for {pod_count} pods to be ready.")
            time.sleep(10)
        if len(pods) != pod_count:
            raise Exception(f"Only {len(pods)} pods are ready, expected {pod_count} pods!")
        return pods

    def get_pod_logs(self, pod_name, namespace="default", container=None, tail_lines=None):
        """
        Get logs from a specific pod in the given namespace.

        :param pod_name: Name of the pod
        :param namespace: Namespace where the pod is located (default: "default")
        :param container: Container name if pod has multiple containers (optional)
        :param tail_lines: Number of lines to return from the end of the logs (optional)
        :return: String containing the pod logs
        """
        try:
            return self.api.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines
            )
        except client.rest.ApiException as e:
            raise Exception(f"Error getting logs for pod '{pod_name}' in namespace '{namespace}': {str(e)}") from e

    def run_pod_exec_command(self, pod_name: str, container_name: str, command: str, dest_path: str = None, namespace: str = "default") -> str:
        """
        Executes a command in a specified container within a Kubernetes pod and optionally saves the output to a file.
        Args:
            pod_name (str): The name of the pod where the command will be executed.
            container_name (str): The name of the container within the pod where the command will be executed.
            command (str): The command to be executed in the container.
            dest_path (str, optional): The file path where the command output will be saved. Defaults to None.
            namespace (str, optional): The Kubernetes namespace where the pod is located. Defaults to "default".
        Returns:
            str: The combined standard output of the executed command.
        Raises:
            Exception: If an error occurs while executing the command in the pod.
        """
        commands = ['/bin/sh', '-c', command]
        resp = stream(self.api.connect_get_namespaced_pod_exec,
                      name=pod_name,
                      namespace=namespace,
                      command=commands,
                      container=container_name,
                      stderr=True, stdin=False,
                      stdout=True, tty=False,
                      _preload_content=False)

        res = []
        file = open(dest_path, 'wb') if dest_path else None # pylint: disable=consider-using-with
        try:
            while resp.is_open():
                resp.update(timeout=1)
                if resp.peek_stdout():
                    stdout = resp.read_stdout()
                    res.append(stdout)
                    logger.info(f"STDOUT: {stdout}")
                    if file:
                        file.write(stdout.encode('utf-8'))
                        logger.info(f"Saved response to file: {dest_path}")
                if resp.peek_stderr():
                    error_msg = resp.read_stderr()
                    raise Exception(f"Error occurred while executing command in pod: {error_msg}")
        finally:
            resp.close()
            if file is not None:
                file.close()
        return ''.join(res)
