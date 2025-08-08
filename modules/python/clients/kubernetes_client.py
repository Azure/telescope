"""Kubernetes client for managing cluster operations and resources."""  # pylint: disable=too-many-lines
import time
from typing import Optional
import os
import uuid
import glob
import yaml
import requests

from kubernetes import client, config
from kubernetes.stream import stream
from utils.logger_config import get_logger, setup_logging
from utils.common import save_info_to_file
from utils.constants import UrlConstants

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
    """Client for managing Kubernetes cluster operations and resources."""
    def __init__(self, config_file=None):
        self.config_file = config_file
        config.load_kube_config(config_file=config_file)
        self._setup_clients()

    def _setup_clients(self):
        """
        Initialize or reinitialize all Kubernetes API clients.
        This method is used by both __init__ and set_context to create client instances.
        """
        self.api = client.CoreV1Api()
        self.app = client.AppsV1Api()
        self.storage = client.StorageV1Api()
        self.batch = client.BatchV1Api()

    def get_app_client(self):
        """Get the AppsV1Api client."""
        return self.app

    def get_api_client(self):
        """Get the CoreV1Api client."""
        return self.api

    def describe_node(self, node_name):
        """Get detailed information about a specific node."""
        return self.api.read_node(node_name)

    def get_nodes(self, label_selector=None, field_selector=None):
        """Get a list of nodes matching the given selectors."""
        return self.api.list_node(label_selector=label_selector,
                                 field_selector=field_selector).items

    def get_ready_nodes(self, label_selector=None, field_selector=None):
        """
        Get a list of nodes that are ready to be scheduled. Should apply all conditions:
        - 'Ready' condition status is True
        - 'NetworkUnavailable' condition status is not present or is False
        - Spec unschedulable is False
        - Spec taints do not have any builtin taints keys with effect 'NoSchedule' or 'NoExecute'
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
            logger.info("Node NOT Ready: '%s' is not schedulable. "
                       "status_conditions: %s. unschedulable: %s",
                       node.metadata.name, status_conditions, node.spec.unschedulable)

        return is_schedulable

    def _is_node_untainted(self, node):
        if not node.spec.taints:
            return True

        for taint in node.spec.taints:
            if (taint.key in builtin_taints_keys and
                taint.effect in ("NoSchedule", "NoExecute")):
                logger.info("Node NOT Ready: '%s' has taint '%s' with effect '%s'",
                           node.metadata.name, taint.key, taint.effect)
                return False

        return True

    def _is_ready_pod(self, pod):
        """Check if a pod is in Ready state."""
        for condition in pod.status.conditions:
            if condition.type == "Ready" and condition.status == "True":
                return True

        return False

    def get_pods_by_namespace(self, namespace, label_selector=None, field_selector=None):
        """Get pods in a specific namespace matching the given selectors."""
        return self.api.list_namespaced_pod(namespace=namespace,
                                           label_selector=label_selector,
                                           field_selector=field_selector).items

    def get_ready_pods_by_namespace(self, namespace=None, label_selector=None, field_selector=None):
        """Get pods that are running and ready in a specific namespace."""
        pods = self.get_pods_by_namespace(namespace=namespace,
                                         label_selector=label_selector,
                                         field_selector=field_selector)
        return [pod for pod in pods if pod.status.phase == "Running" and self._is_ready_pod(pod)]

    def get_persistent_volume_claims_by_namespace(self, namespace):
        """Get all persistent volume claims in a namespace."""
        return self.api.list_namespaced_persistent_volume_claim(namespace=namespace).items

    def get_bound_persistent_volume_claims_by_namespace(self, namespace):
        """Get all bound persistent volume claims in a namespace."""
        claims = self.get_persistent_volume_claims_by_namespace(namespace=namespace)
        return [claim for claim in claims if claim.status.phase == "Bound"]

    def delete_persistent_volume_claim_by_namespace(self, namespace):
        """Delete all persistent volume claims in a namespace."""
        pvcs = self.get_persistent_volume_claims_by_namespace(namespace=namespace)
        for pvc in pvcs:
            try:
                self.api.delete_namespaced_persistent_volume_claim(
                    pvc.metadata.name, namespace, body=client.V1DeleteOptions())
            except client.rest.ApiException as e:
                logger.error("Error deleting PVC '%s': %s", pvc.metadata.name, e)

    def get_volume_attachments(self):
        """Get all volume attachments in the cluster."""
        return self.storage.list_volume_attachment().items

    def get_attached_volume_attachments(self):
        """Get all attached volume attachments in the cluster."""
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

    def create_node(self, template):
        """
        Create a Node in the Kubernetes cluster using the provided YAML template.

        :param template: YAML template for the Node.
        :param namespace: Namespace where the Node will be created (not applicable for Node, but kept for consistency).
        :return: Name of the created Node.
        """
        try:
            node_obj = yaml.safe_load(template)
            if node_obj["kind"] != "Node":
                raise ValueError("The provided YAML template does not define a Node resource.")

            response = self.api.create_node(body=node_obj)
            return response.metadata.name
        except yaml.YAMLError as e:
            raise Exception(f"Error parsing Node template: {str(e)}") from e
        except client.rest.ApiException as e:
            if e.status == 409:  # Node already exists
                self.api.replace_node(name=node_obj["metadata"]["name"], body=node_obj)
                return node_obj["metadata"]["name"]
            raise Exception(f"Error creating Node: {str(e)}") from e

    def delete_node(self, node_name):
        """
        Delete a Kubernetes Node resource by name.

        :param node_name: Name of the Node to delete.
        :return: None
        """
        try:
            self.api.delete_node(name=node_name, body=client.V1DeleteOptions())
            logger.info(f"Node '{node_name}' deleted successfully.")
        except client.rest.ApiException as e:
            if e.status == 404:  # Node not found
                logger.info(f"Node '{node_name}' not found.")
            else:
                raise Exception(f"Error deleting Node '{node_name}': {str(e)}") from e

    def wait_for_nodes_ready(self, node_count, operation_timeout_in_minutes, label_selector=None):
        """
        Waits for a specific number of nodes with a given label to be ready within a specified timeout.
        Raises an exception if the expected number of nodes are not ready within the timeout.

        :param node_label: The label to filter nodes.
        :param node_count: The expected number of nodes to be ready.
        :param operation_timeout_in_minutes: The timeout in minutes to wait for the nodes to be ready.
        :return: None
        """
        ready_nodes = []
        ready_node_count = 0
        timeout = time.time() + (operation_timeout_in_minutes * 60)
        logger.info(f"Validating {node_count} nodes with label {label_selector} are ready.")
        while time.time() < timeout:
            ready_nodes = self.get_ready_nodes(label_selector=label_selector)
            ready_node_count = len(ready_nodes)
            logger.info(f"Currently {ready_node_count} nodes are ready.")
            if ready_node_count == node_count:
                return ready_nodes
            logger.info(f"Waiting for {node_count} nodes to be ready.")
            time.sleep(10)
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
        raise Exception(f"Only {len(pods)} pods are ready, expected {pod_count} pods!")

    def wait_for_labeled_pods_ready(self, label_selector: str, namespace: str = "default", timeout_in_minutes: int = 5) -> None:
        """
        Wait for all pods with specific label to be ready

        Args:
            selector: Label selector for the pods
            namespace: Namespace where pods exist
            timeout: Timeout string (e.g., "300s", "5m")
        """
        pods = self.get_pods_by_namespace(
            namespace=namespace, label_selector=label_selector
        )
        pod_count = len(pods)
        if pod_count == 0:
            raise Exception(f"No pods found with selector '{label_selector}' in namespace '{namespace}'")
        self.wait_for_pods_ready(
            pod_count=pod_count,
            operation_timeout_in_minutes=timeout_in_minutes,
            namespace=namespace,
            label_selector=label_selector,
        )

    def wait_for_pods_completed(self, label_selector, namespace="default", timeout=300):
        """
        Waits for pods with a specific label to complete successfully their execution within a specified timeout.
        Raises an exception if the pods do not complete within the timeout.

        :param label_selector: The label selector to filter pods.
        :param namespace: The namespace where the pod is located (default: "default").
        :param timeout: The timeout in seconds to wait for the pod to complete (default: 300 seconds).
        :return: None
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            logger.info(
                f"Waiting for pods with label '{label_selector}' in namespace '{namespace}' to complete..."
            )
            pods = self.get_pods_by_namespace(
                namespace=namespace, label_selector=label_selector
            )
            if not pods:
                raise Exception(f"No pods found with label '{label_selector}' in namespace '{namespace}'.")
            all_completed = True
            for pod in pods:
                logger.info(f"Pod '{pod.metadata.name}' status: {pod.status.phase}")
                if pod.status.phase != "Succeeded":
                    all_completed = False
                    break
            if all_completed:
                logger.info(
                    f"All pods with label '{label_selector}' in namespace '{namespace}' have completed successfully."
                )
                return pods
            sleep_time = 10
            logger.info(f"Waiting for {sleep_time} seconds before checking pod status again.")
            time.sleep(sleep_time)
        raise Exception(
            f"Pods with label '{label_selector}' in namespace '{namespace}' did not complete within {timeout} seconds."
        )

    def wait_for_job_completed(self, job_name, namespace="default", timeout=300):
        """
        Waits for a specific job to complete its execution within a specified timeout.
        Raises an exception if the job does not complete within the timeout.

        :param job_name: The name of the job to wait for.
        :param namespace: The namespace where the job is located (default: "default").
        :param timeout: The timeout in seconds to wait for the job to complete (default: 300 seconds).
        :return: None
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                job = self.batch.read_namespaced_job(name=job_name, namespace=namespace)
                if job.status.succeeded is not None and job.status.succeeded > 0:
                    logger.info(
                        f"Job '{job_name}' in namespace '{namespace}' has completed successfully."
                    )
                    return job.metadata.name
                if job.status.failed is not None and job.status.failed > 0:
                    raise Exception(
                        f"Job '{job_name}' in namespace '{namespace}' has failed."
                    )
                logger.info(
                    f"Job '{job_name}' in namespace '{namespace}' is still running with status:\n{job.status}"
                )
            except client.rest.ApiException as e:
                if e.status == 404:
                    raise Exception(
                        f"Job '{job_name}' not found in namespace '{namespace}'."
                    ) from e
                raise e
            sleep_time = 30
            logger.info(
                f"Waiting {sleep_time} seconds before checking job status again."
            )
            time.sleep(sleep_time)
        raise Exception(
            f"Job '{job_name}' in namespace '{namespace}' did not complete within {timeout} seconds."
        )

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
                tail_lines=tail_lines,
                _preload_content=False  # Avoid breaking data format
            ).data
        except client.rest.ApiException as e:
            raise Exception(f"Error getting logs for pod '{pod_name}' in namespace '{namespace}': {str(e)}") from e

    def run_pod_exec_command(self, pod_name: str, command: str, container_name: str = "", dest_path: str = "", namespace: str = "default") -> str:
        """
        Executes a command in a specified container within a Kubernetes pod and optionally saves the output to a file.
        Args:
            pod_name (str): The name of the pod where the command will be executed.
            container_name (str): The name of the container within the pod where the command will be executed.
            command (str): The command to be executed in the container.
            dest_path (str, optional): The file path where the command output will be saved. Defaults to "".
            namespace (str, optional): The Kubernetes namespace where the pod is located. Defaults to "default".
        Returns:
            str: The combined standard output of the executed command.
        Raises:
            Exception: If an error occurs while executing the command in the pod.
        """
        commands = ['/bin/sh', '-c', command]
        logger.info(
            f"Executing command in pod '{pod_name}' in namespace '{namespace}': {' '.join(commands)}"
        )
        # Build kwargs conditionally
        stream_kwargs = {
            "name": pod_name,
            "namespace": namespace,
            "command": commands,
            "stderr": True,
            "stdin": False,
            "stdout": True,
            "tty": False,
            "_preload_content": False,
        }

        # Only include container if container_name is provided
        if container_name:
            stream_kwargs["container"] = container_name

        resp = stream(self.api.connect_get_namespaced_pod_exec, **stream_kwargs)

        res = []
        file = None
        if dest_path:
            file = open(dest_path, 'wb')  # pylint: disable=consider-using-with
        try:
            while resp.is_open():
                resp.update(timeout=1)
                if resp.peek_stdout():
                    stdout = resp.read_stdout()
                    res.append(stdout)
                    clean_stdout = stdout.rstrip('\n\r')
                    logger.info("STDOUT: %s", clean_stdout)
                    if file:
                        file.write(stdout.encode('utf-8'))
                        logger.info("Saved response to file: %s", dest_path)
                if resp.peek_stderr():
                    error_msg = resp.read_stderr()
                    raise Exception(f"Error occurred while executing command in pod: {error_msg}")
        finally:
            resp.close()
            if file is not None:
                file.close()
        return ''.join(res)

    def get_daemonsets_pods_allocated_resources(self, namespace, node_name):
        """Get CPU and memory resources allocated by DaemonSet pods on a specific node."""
        pods = self.get_pods_by_namespace(namespace=namespace, field_selector=f"spec.nodeName={node_name}")
        cpu_request = 0
        memory_request = 0
        for pod in pods:
            for container in pod.spec.containers:
                if container.resources.requests:
                    logger.info("Pod %s has container %s with resources %s",
                               pod.metadata.name, container.name, container.resources.requests)
                    cpu_request += int(container.resources.requests.get("cpu", "0m").replace("m", ""))
                    memory_request += int(container.resources.requests.get("memory", "0Mi").replace("Mi", ""))
        return cpu_request, memory_request * 1024 # Convert to KiB

    def get_daemonsets_pods_count(self, namespace, node_name):
        """
        Get the count of DaemonSet pods running on a specific node.
        Args:
            namespace (str): The namespace where the DaemonSet is located.
            node_name (str): The name of the node where the pods are running.
        Returns:
            int: The count of DaemonSet pods running on a specific node.
        """
        pods = self.get_pods_by_namespace(namespace=namespace, field_selector=f"spec.nodeName={node_name}")
        return len(pods)

    def set_context(self, context_name):
        """
        Switch to the specified Kubernetes context and reinitialize all API clients.
        Args:
            context_name (str): Name of the Kubernetes context to switch to
        Returns:
            None
        Raises:
            Exception: If the context switch fails
        """
        try:
            config.load_kube_config(
                config_file=self.config_file, context=context_name)
            self._setup_clients()
            logger.info(f"Successfully switched to context: {context_name}")
        except Exception as e:
            raise Exception(f"Failed to switch to context {context_name}: {e}") from e

    def get_pods_name_and_ip(self, label_selector="", namespace="default"):
        """
        Retrieve the name and IP address of all pods matching the given label selector and namespace.

        Args:
            label_selector (str, optional): The label selector to filter pods. Defaults to an empty string.
            namespace (str, optional): The namespace to search for pods. Defaults to "default".

        Returns:
            list: A list of dictionaries containing the name and IP address of each matching pod.
        """
        pods = self.get_pods_by_namespace(
            namespace=namespace, label_selector=label_selector)
        return [{"name": pod.metadata.name, "ip": pod.status.pod_ip, "node_ip": pod.status.host_ip} for pod in pods]

    def get_pod_name_and_ip(self, label_selector="", namespace="default"):
        """
        Retrieve the name and IP address of the first pod matching the given label selector and namespace.

        Args:
            label_selector (str, optional): The label selector to filter pods. Defaults to an empty string.
            namespace (str, optional): The namespace to search for pods. Defaults to "default".

        Returns:
            tuple: A tuple containing the name and IP address of the first matching pod.

        Raises:
            Exception: If no pods are found matching the given label selector and namespace.
        """
        pods = self.get_pods_name_and_ip(
            namespace=namespace, label_selector=label_selector)
        logger.info(pods)
        if not pods:
            raise Exception(
                f"No pod found with label: {label_selector} and namespace: {namespace}")
        return pods[0]

    def get_service_external_ip(self, service_name, namespace="default"):
        """
        Get the external IP address of a service.
        """
        service = self.api.read_namespaced_service(service_name, namespace)
        if service.status.load_balancer.ingress:
            return service.status.load_balancer.ingress[0].ip

        return None

    def get_pod_details(self, namespace="default", label_selector=""):
        """
        Get detailed info about pods in a namespace
        """

        pods = self.get_pods_by_namespace(
            namespace=namespace, label_selector=label_selector)

        pod_details = []
        for pod in pods:

            pod_details.append({
                "name": pod.metadata.name,
                "labels": pod.metadata.labels,
                "node_name": pod.spec.node_name,
                "ip": pod.status.pod_ip,
                "status": pod.status.phase,
                "spec": pod.spec.to_dict(),
            })

        return pod_details

    def get_node_details(self, node_name):
        """
        Get detailed info about a node
        """
        node = self.api.read_node(node_name)
        if not node:
            raise Exception(f"Node '{node_name}' not found.")
        labels = node.metadata.labels

        node_details = {
            "name": node.metadata.name,
            "labels": labels,
            "region": labels.get("topology.kubernetes.io/region", "Unknown"),
            "zone": labels.get("topology.kubernetes.io/zone", "Unknown"),
            "instance_type": labels.get("node.kubernetes.io/instance-type", "Unknown"),
            "allocatable": node.status.allocatable,
            "capacity": node.status.capacity,
            "node_info": node.status.node_info.to_dict(),
        }
        return node_details

    def collect_pod_and_node_info(self, namespace="default", label_selector="", result_dir="", role=""):
        """
        Collect information about all pods and their respective nodes.
        The result will have pod information under 'pod' key and node information under 'node' key
        to prevent any naming conflicts.
        """
        pods = self.get_pod_details(
            namespace=namespace, label_selector=label_selector)

        logger.info(
            f"Inside collect_pod_and_node_info, The pods details are: {pods}")

        node_cache = {}
        pods_and_nodes = []

        for pod in pods:
            node_name = pod["node_name"]
            logger.info(
                f"Inside collect_pod_and_node_info, The node_name details are: {node_name}")

            if node_name not in node_cache:
                node_cache[node_name] = self.get_node_details(
                    node_name=node_name)
            node_info = node_cache[node_name]
            logger.info(
                f"Inside collect_pod_and_node_info, The node_info details are: {node_info}")

            pod_and_node_info = {
                "pod": pod,
                "node": node_info
            }
            logger.info(
                f"Inside collect_pod_and_node_info, The pod_and_node_info details are: {pod_and_node_info}")
            pods_and_nodes.append(pod_and_node_info)

        # Save results
        file_name = os.path.join(result_dir, f"{role}_pod_node_info.json")
        logger.info(
            f"Inside collect_pod_and_node_info, The file_name details are: {file_name}")
        save_info_to_file(pods_and_nodes, file_name)

    def verify_nvidia_smi_on_node(self, nodes, namespace="default"):
        """
        Create a pod on the specific node and run nvidia-smi to verify GPU access
        Args:
            nodes: List of nodes to verify
            namespace: Namespace to create the pod in (default: "default")
        Returns:
            True if nvidia-smi command succeeds, False otherwise
        """
        try:
            all_pod_logs = {}
            for node in nodes:
                pod_name = f"gpu-verify-{uuid.uuid4()}"
                node_name = node.metadata.name
                logger.info(f"Verifying NVIDIA drivers on node {node_name}")
                logger.info(f"Node allocatable resources: {node.status.allocatable}")

                # Get GPU count for this node
                gpu_count = int(node.status.allocatable.get("nvidia.com/gpu", "1"))

                logger.info(f"Node {node_name} has {gpu_count} GPUs, requesting all for validation")

                # Create pod spec with node selector
                pod = client.V1Pod(
                    metadata=client.V1ObjectMeta(name=pod_name),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="nvidia-test",
                                image="nvidia/cuda:12.2.0-base-ubuntu20.04",
                                command=["/bin/bash", "-c", "nvidia-smi"],
                                resources=client.V1ResourceRequirements(
                                    limits={"nvidia.com/gpu": str(gpu_count)}
                                ),
                            )
                        ],
                        node_selector={"kubernetes.io/hostname": node_name},
                        restart_policy="Never",
                        tolerations=[
                            client.V1Toleration(
                                key="nvidia.com/gpu",
                                operator="Exists",
                                effect="NoSchedule",
                            )
                        ],
                    ),
                )

                # Create the pod
                logger.info(f"Creating test pod {pod_name} on node {node_name}")
                self.api.create_namespaced_pod(namespace=namespace, body=pod)

                # Wait for pod to complete
                timeout = time.time() + 120  # 2 minutes timeout
                while time.time() < timeout:
                    pod_status = self.api.read_namespaced_pod(
                        name=pod_name, namespace=namespace
                    )
                    if pod_status.status.phase in ["Succeeded", "Failed"]:
                        break
                    time.sleep(2)

                # Get pod logs
                pod_logs = self.get_pod_logs(pod_name=pod_name, namespace=namespace)
                if isinstance(pod_logs, bytes):
                    pod_logs_str = pod_logs.decode('utf-8')
                else:
                    pod_logs_str = str(pod_logs)

                logger.info(f"nvidia-smi output: {pod_logs_str}")

                # Check if output contains expected NVIDIA information
                if "NVIDIA-SMI" in pod_logs_str and "GPU" in pod_logs_str:
                    logger.info(f"NVIDIA drivers verified on node {node_name}")
                    verification_successful = True
                else:
                    logger.warning(
                        f"nvidia-smi output does not contain expected NVIDIA information on node {node_name}"
                    )
                    verification_successful = False
                all_pod_logs[node_name] = {
                    "pod_name": pod_name,
                    "logs": pod_logs_str,
                    "device_status": verification_successful,
                }
                # Clean up the test pod
                try:
                    logger.info(f"Deleting test pod {pod_name}")
                    self.api.delete_namespaced_pod(
                        name=pod_name,
                        namespace=namespace,
                        body=client.V1DeleteOptions(),
                    )
                except Exception as e:
                    logger.warning(f"Error deleting test pod {pod_name}: {str(e)}")

            return all_pod_logs

        except Exception as e:
            logger.error(
                f"Error verifying NVIDIA drivers: {str(e)}"
            )
            return False

    def apply_manifest_from_url(self, manifest_url, namespace: Optional[str] = None):
        """
        Apply a Kubernetes manifest from a URL using Kubernetes Python client API.

        :param manifest_url: URL of the manifest to apply
        :param namespace: Optional namespace to override the manifest namespace
        :return: None
        """
        try:
            # Fetch the manifest content from the URL
            response = requests.get(manifest_url, timeout=30)
            response.raise_for_status()

            # Parse YAML content (can contain multiple documents)
            manifests = list(yaml.safe_load_all(response.text))

            for manifest in manifests:
                if not manifest:  # Skip empty documents
                    continue

                self._apply_single_manifest(manifest, namespace=namespace)

            logger.info("Successfully applied manifest from %s", manifest_url)
        except Exception as e:
            raise Exception(f"Error applying manifest from {manifest_url}: {str(e)}") from e

    def delete_manifest_from_url(self, manifest_url, ignore_not_found: bool = True, namespace: Optional[str] = None):
        """
        Delete a Kubernetes manifest from a URL using Kubernetes Python client API.
        Equivalent to 'kubectl delete -f <url>'

        :param manifest_url: URL of the manifest to delete
        :param ignore_not_found: If True, don't raise error if resource doesn't exist (equivalent to --ignore-not-found)
        :param namespace: Optional namespace to override the manifest namespace
        :return: None
        """
        try:
            # Fetch the manifest content from the URL
            response = requests.get(manifest_url, timeout=30)
            response.raise_for_status()

            # Parse YAML content (can contain multiple documents)
            manifests = list(yaml.safe_load_all(response.text))

            # Delete manifests in reverse order (to handle dependencies)
            manifests.reverse()

            for manifest in manifests:
                if not manifest:  # Skip empty documents
                    continue

                self._delete_single_manifest(manifest, ignore_not_found=ignore_not_found, namespace=namespace)

            logger.info("Successfully deleted manifest from %s", manifest_url)
        except Exception as e:
            raise Exception(f"Error deleting manifest from {manifest_url}: {str(e)}") from e

    def _load_manifests_from_sources(self, manifest_path: str = None, manifest_dict: dict = None):
        """
        Load manifests from various sources (file, directory, or dictionary).

        :param manifest_path: Path to YAML manifest file or folder containing manifest files
        :param manifest_dict: Dictionary containing the manifest
        :return: Tuple of (manifests_list, sources_list)
        """
        manifests = []
        sources = []

        # Load manifests from file or directory
        if manifest_path:
            if os.path.isfile(manifest_path):
                # Single file
                with open(manifest_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    # Handle multiple documents in a single YAML file
                    yaml_docs = list(yaml.safe_load_all(content))
                    manifests.extend([doc for doc in yaml_docs if doc])  # Filter out None/empty docs
                sources.append(f"file: {manifest_path}")
            elif os.path.isdir(manifest_path):
                # Directory containing manifest files
                yaml_files = []
                for ext in ['*.yaml', '*.yml']:
                    # Use recursive search which will include all files
                    yaml_files.extend(glob.glob(os.path.join(manifest_path, '**', ext), recursive=True))

                # Remove duplicates and sort files to ensure consistent ordering
                yaml_files = sorted(list(set(yaml_files)))

                if not yaml_files:
                    raise ValueError(f"No YAML files found in directory: {manifest_path}")

                for yaml_file in yaml_files:
                    with open(yaml_file, 'r', encoding='utf-8') as file:
                        content = file.read()
                        # Handle multiple documents in each YAML file
                        yaml_docs = list(yaml.safe_load_all(content))
                        manifests.extend([doc for doc in yaml_docs if doc])  # Filter out None/empty docs

                sources.append(f"directory: {manifest_path} ({len(yaml_files)} files)")
            else:
                raise FileNotFoundError(f"Path does not exist: {manifest_path}")

        # Load manifest from dictionary
        if manifest_dict:
            manifests.append(manifest_dict)
            sources.append("dictionary")

        if not manifests:
            raise ValueError("At least one of manifest_path or manifest_dict must be provided")

        return manifests, sources

    def apply_manifest_from_file(self, manifest_path: str = None, manifest_dict: dict = None, namespace: Optional[str] = None):
        """
        Apply Kubernetes manifest(s) from file path, folder path, or dictionary.

        :param manifest_path: Path to YAML manifest file or folder containing manifest files
        :param manifest_dict: Dictionary containing the manifest
        :param namespace: Optional namespace to override the manifest namespace
        :return: None
        """
        try:
            # Load manifests from various sources
            manifests_to_apply, applied_sources = self._load_manifests_from_sources(manifest_path, manifest_dict)

            # Apply all manifests
            namespace_info = f" in namespace '{namespace}'" if namespace else ""
            logger.info(f"Applying {len(manifests_to_apply)} manifest(s) from: {', '.join(applied_sources)}{namespace_info}")

            for i, manifest in enumerate(manifests_to_apply):
                if not manifest:  # Skip empty documents
                    continue

                logger.info(f"Applying manifest {i+1}/{len(manifests_to_apply)}: {manifest.get('kind', 'Unknown')}/{manifest.get('metadata', {}).get('name', 'Unknown')}")
                self._apply_single_manifest(manifest=manifest, namespace=namespace)

            logger.info(f"Successfully applied {len(manifests_to_apply)} manifest(s)")

        except Exception as e:
            logger.error(f"Error applying manifest(s): {str(e)}")
            raise e

    def delete_manifest_from_file(self, manifest_path: str = None, manifest_dict: dict = None, ignore_not_found: bool = True, namespace: Optional[str] = None):
        """
        Delete Kubernetes manifest(s) from file path, folder path, or dictionary.
        Equivalent to 'kubectl delete -f <file/folder>'

        :param manifest_path: Path to YAML manifest file or folder containing manifest files
        :param manifest_dict: Dictionary containing the manifest
        :param ignore_not_found: If True, don't raise error if resource doesn't exist (equivalent to --ignore-not-found)
        :param namespace: Optional namespace to override the manifest namespace
        :return: None
        """
        try:
            # Load manifests from various sources
            manifests_to_delete, deleted_sources = self._load_manifests_from_sources(manifest_path, manifest_dict)

            # Delete all manifests in reverse order (to handle dependencies)
            manifests_to_delete.reverse()
            namespace_info = f" in namespace '{namespace}'" if namespace else ""
            logger.info(f"Deleting {len(manifests_to_delete)} manifest(s) from: {', '.join(deleted_sources)}{namespace_info}")

            for i, manifest in enumerate(manifests_to_delete):
                if not manifest:  # Skip empty documents
                    continue

                logger.info(f"Deleting manifest {i+1}/{len(manifests_to_delete)}: {manifest.get('kind', 'Unknown')}/{manifest.get('metadata', {}).get('name', 'Unknown')}")
                self._delete_single_manifest(manifest=manifest, ignore_not_found=ignore_not_found, namespace=namespace)

            logger.info(f"Successfully deleted {len(manifests_to_delete)} manifest(s)")

        except Exception as e:
            logger.error(f"Error deleting manifest(s): {str(e)}")
            raise e

    def wait_for_condition(self, resource_type: str, wait_condition_type: str, namespace: str = "default",
                          timeout_seconds: int = 300, resource_name: str = None, wait_all: bool = False):
        """
        Wait for a Kubernetes resource to meet a specific condition.
        Equivalent to 'kubectl wait --for=condition=<wait_condition_type> <resource> --timeout=<timeout> -n <namespace>'

        :param resource_type: Type of resource (e.g., 'deployment', 'pod', 'service')
        :param wait_condition_type: Condition type to wait for (e.g., 'available', 'ready', 'progressing')
        :param namespace: Namespace where the resource is located
        :param timeout_seconds: Maximum time to wait in seconds
        :param resource_name: Name of specific resource (None to wait for all)
        :param wait_all: If True, wait for all resources of the type (equivalent to --all flag)
        :return: True if condition is met, False if timeout
        :raises ValueError: If wait_condition_type is invalid
        """
        # Define valid condition types for different resource types
        valid_conditions = {
            'deployment': ['available', 'progressing', 'replicafailure', 'ready'],
            'deployments': ['available', 'progressing', 'replicafailure', 'ready'],
            # Add more resource types as needed
        }

        # Validate wait_condition_type format and type
        if not wait_condition_type or not isinstance(wait_condition_type, str):
            raise ValueError("wait_condition_type must be a non-empty string")

        wait_condition_lower = wait_condition_type.lower().strip()
        resource_type_lower = resource_type.lower()

        # Check if resource type is supported
        if resource_type_lower not in valid_conditions:
            raise ValueError(f"Resource type '{resource_type}' is not supported for condition checking")

        # Check if condition type is valid for this resource type
        if wait_condition_lower not in valid_conditions[resource_type_lower]:
            valid_conditions_str = ', '.join(valid_conditions[resource_type_lower])
            raise ValueError(f"Invalid condition '{wait_condition_type}' for resource type '{resource_type}'. Valid conditions: {valid_conditions_str}")

        try:
            start_time = time.time()
            timeout = start_time + timeout_seconds

            # If no specific resource name and wait_all is False, wait for all resources
            if not resource_name and not wait_all:
                wait_all = True

            # Build resource description for logging
            resource_desc = f"{resource_type}"
            if resource_name:
                resource_desc = f"{resource_type}/{resource_name}"

            logger.info(f"Waiting for {resource_desc} with condition '{wait_condition_type}' in namespace '{namespace}' (timeout: {timeout_seconds}s)")

            while time.time() < timeout:
                try:
                    if self._check_resource_condition(resource_type, resource_name, wait_condition_lower, namespace, wait_all):
                        elapsed_time = time.time() - start_time
                        logger.info(f"Condition '{wait_condition_type}' met for {resource_desc} after {elapsed_time:.2f} seconds")
                        return True

                    time.sleep(5)  # Check every 5 seconds

                except Exception as e:
                    logger.warning(f"Error checking condition for {resource_desc}: {str(e)}")
                    time.sleep(5)

            # Timeout reached
            elapsed_time = time.time() - start_time
            logger.error(f"Timeout waiting for condition '{wait_condition_type}' on {resource_desc} after {elapsed_time:.2f} seconds")
            return False

        except Exception as e:
            logger.error(f"Error waiting for condition: {str(e)}")
            raise e

    def _check_resource_condition(self, resource_type: str, resource_name: str, condition_type: str,
                                 namespace: str, wait_all: bool) -> bool:
        """
        Check if a specific resource condition is met.

        :param resource_type: Type of resource (e.g., 'deployment', 'pod', 'service')
        :param resource_name: Name of specific resource (None if checking all)
        :param condition_type: Condition type to check (e.g., 'available', 'ready', 'progressing')
        :param namespace: Namespace of the resource
        :param wait_all: Whether to check all resources of the type
        :return: True if condition is met
        """
        try:
            resource_type_lower = resource_type.lower()

            if resource_type_lower in ['deployment', 'deployments']:
                return self._check_deployment_condition(resource_name, condition_type, namespace, wait_all)

            logger.warning(f"Unsupported resource type for condition checking: {resource_type}")
            return False

        except Exception as e:
            logger.error(f"Error checking resource condition: {str(e)}")
            return False

    def _check_deployment_condition(self, resource_name: str, condition_type: str, namespace: str, wait_all: bool) -> bool:
        """Check deployment condition (e.g., 'available', 'progressing')."""
        try:
            if wait_all or not resource_name:
                # Check all deployments in namespace
                deployments = self.app.list_namespaced_deployment(namespace=namespace).items
            else:
                # Check specific deployment
                deployment = self.app.read_namespaced_deployment(name=resource_name, namespace=namespace)
                deployments = [deployment]

            for deployment in deployments:
                if not self._is_deployment_condition_met(deployment, condition_type):
                    return False

            return True

        except client.rest.ApiException as e:
            if e.status == 404:
                logger.debug("Deployment not found, waiting...")
                return False
            raise e

    def _is_deployment_condition_met(self, deployment, condition_type: str) -> bool:
        """Check if a deployment meets the specified condition."""
        if not deployment.status or not deployment.status.conditions:
            return False

        condition_type_lower = condition_type.lower()

        for condition in deployment.status.conditions:
            if condition.type.lower() == condition_type_lower and condition.status == "True":
                return True

        # Special case for 'ready' - check if all replicas are ready
        if condition_type_lower == 'ready':
            return (deployment.status.ready_replicas == deployment.status.replicas and
                    deployment.status.replicas > 0)

        return False

    def _apply_single_manifest(self, manifest, namespace=None):
        """
        Apply a single Kubernetes manifest using the appropriate API client.

        :param manifest: Dictionary representing a Kubernetes resource
        :param namespace: Optional namespace to override the manifest namespace
        :return: None
        """
        try:
            kind = manifest.get("kind")
            # Use provided namespace or fall back to manifest namespace
            namespace = namespace or manifest.get("metadata", {}).get("namespace")
            name = manifest.get("metadata", {}).get("name")
            logger.info("Applying manifest %s %s in namespace %s", kind, name, namespace)

            if kind == "Deployment":
                if namespace:
                    self.app.create_namespaced_deployment(namespace=namespace, body=manifest)
                else:
                    raise ValueError("Deployment requires a namespace")
            elif kind == "DaemonSet":
                if namespace:
                    self.app.create_namespaced_daemon_set(namespace=namespace, body=manifest)
                else:
                    raise ValueError("DaemonSet requires a namespace")
            elif kind == "StatefulSet":
                if namespace:
                    self.app.create_namespaced_stateful_set(namespace=namespace, body=manifest)
                else:
                    raise ValueError("StatefulSet requires a namespace")
            elif kind == "Service":
                if namespace:
                    self.api.create_namespaced_service(namespace=namespace, body=manifest)
                else:
                    raise ValueError("Service requires a namespace")
            elif kind == "ConfigMap":
                if namespace:
                    self.api.create_namespaced_config_map(namespace=namespace, body=manifest)
                else:
                    raise ValueError("ConfigMap requires a namespace")
            elif kind == "Secret":
                if namespace:
                    self.api.create_namespaced_secret(namespace=namespace, body=manifest)
                else:
                    raise ValueError("Secret requires a namespace")
            elif kind == "ServiceAccount":
                if namespace:
                    self.api.create_namespaced_service_account(namespace=namespace, body=manifest)
                else:
                    raise ValueError("ServiceAccount requires a namespace")
            elif kind == "ClusterRole":
                # ClusterRole is cluster-scoped
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.create_cluster_role(body=manifest)
            elif kind == "ClusterRoleBinding":
                # ClusterRoleBinding is cluster-scoped
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.create_cluster_role_binding(body=manifest)
            elif kind == "Role":
                if namespace:
                    rbac_api = client.RbacAuthorizationV1Api()
                    rbac_api.create_namespaced_role(namespace=namespace, body=manifest)
                else:
                    raise ValueError("Role requires a namespace")
            elif kind == "RoleBinding":
                if namespace:
                    rbac_api = client.RbacAuthorizationV1Api()
                    rbac_api.create_namespaced_role_binding(namespace=namespace, body=manifest)
                else:
                    raise ValueError("RoleBinding requires a namespace")
            elif kind == "Namespace":
                # Namespace is cluster-scoped
                self.api.create_namespace(body=manifest)
            elif kind == "CustomResourceDefinition":
                # CustomResourceDefinition is cluster-scoped
                apiextensions_api = client.ApiextensionsV1Api()
                apiextensions_api.create_custom_resource_definition(body=manifest)
            elif kind == "FlowSchema":
                # FlowSchema is cluster-scoped (part of flow control API)
                flowcontrol_api = client.FlowcontrolApiserverV1Api()
                flowcontrol_api.create_flow_schema(body=manifest)
            elif kind == "Stage":
                # Stage is a custom resource from KWOK, handle as custom resource
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.create_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="stages",  # KWOK Stage resources use "stages" as plural
                    body=manifest
                )
            elif kind == "MPIJob":
                # MPIJob is a custom resource from Kubeflow MPI Operator
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                if namespace:
                    custom_api.create_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=namespace,
                        plural="mpijobs",
                        body=manifest
                    )
                else:
                    raise ValueError("MPIJob requires a namespace")
            elif kind == "NodeFeatureRule":
                # NodeFeatureRule is a custom resource from Node Feature Discovery (NFD)
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                # NodeFeatureRule is cluster-scoped
                custom_api.create_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="nodefeaturerules",
                    body=manifest
                )
            elif kind == "NicClusterPolicy":
                # NicClusterPolicy is a custom resource from NVIDIA Network Operator
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                # NicClusterPolicy is cluster-scoped
                custom_api.create_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="nicclusterpolicies",
                    body=manifest
                )
            else:
                logger.warning("Unsupported resource kind: %s. Skipping...", kind)

        except client.rest.ApiException as e:
            if e.status == 409:  # Resource already exists
                resource_name = manifest.get('metadata', {}).get('name')
                logger.info("Resource %s/%s already exists, skipping creation",
                           kind, resource_name)
            else:
                raise Exception(f"Error creating {kind}: {str(e)}") from e

    def _delete_single_manifest(self, manifest, ignore_not_found: bool = True, namespace: Optional[str] = None):
        """
        Delete a single Kubernetes manifest using the appropriate API client.

        :param manifest: Dictionary representing a Kubernetes resource
        :param ignore_not_found: If True, don't raise error if resource doesn't exist
        :param namespace: Optional namespace to override the manifest namespace
        :return: None
        """
        try:
            kind = manifest.get("kind")
            # Use provided namespace or fall back to manifest namespace
            namespace = namespace or manifest.get("metadata", {}).get("namespace")
            resource_name = manifest.get("metadata", {}).get("name")

            if not resource_name:
                logger.warning(f"Resource name not found in manifest for {kind}, skipping deletion")
                return

            delete_options = client.V1DeleteOptions(
                propagation_policy="Foreground"  # Wait for dependent resources to be deleted
            )

            if kind == "Deployment":
                if namespace:
                    self.app.delete_namespaced_deployment(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("Deployment requires a namespace")
            elif kind == "DaemonSet":
                if namespace:
                    self.app.delete_namespaced_daemon_set(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("DaemonSet requires a namespace")
            elif kind == "StatefulSet":
                if namespace:
                    self.app.delete_namespaced_stateful_set(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("StatefulSet requires a namespace")
            elif kind == "Service":
                if namespace:
                    self.api.delete_namespaced_service(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("Service requires a namespace")
            elif kind == "ConfigMap":
                if namespace:
                    self.api.delete_namespaced_config_map(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("ConfigMap requires a namespace")
            elif kind == "Secret":
                if namespace:
                    self.api.delete_namespaced_secret(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("Secret requires a namespace")
            elif kind == "ServiceAccount":
                if namespace:
                    self.api.delete_namespaced_service_account(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("ServiceAccount requires a namespace")
            elif kind == "ClusterRole":
                # ClusterRole is cluster-scoped
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.delete_cluster_role(name=resource_name, body=delete_options)
            elif kind == "ClusterRoleBinding":
                # ClusterRoleBinding is cluster-scoped
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.delete_cluster_role_binding(name=resource_name, body=delete_options)
            elif kind == "Role":
                if namespace:
                    rbac_api = client.RbacAuthorizationV1Api()
                    rbac_api.delete_namespaced_role(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("Role requires a namespace")
            elif kind == "RoleBinding":
                if namespace:
                    rbac_api = client.RbacAuthorizationV1Api()
                    rbac_api.delete_namespaced_role_binding(name=resource_name, namespace=namespace, body=delete_options)
                else:
                    raise ValueError("RoleBinding requires a namespace")
            elif kind == "Namespace":
                # Namespace is cluster-scoped
                self.api.delete_namespace(name=resource_name, body=delete_options)
            elif kind == "CustomResourceDefinition":
                # CustomResourceDefinition is cluster-scoped
                apiextensions_api = client.ApiextensionsV1Api()
                apiextensions_api.delete_custom_resource_definition(name=resource_name, body=delete_options)
            elif kind == "FlowSchema":
                # FlowSchema is cluster-scoped (part of flow control API)
                flowcontrol_api = client.FlowcontrolApiserverV1Api()
                flowcontrol_api.delete_flow_schema(name=resource_name, body=delete_options)
            elif kind == "Stage":
                # Stage is a custom resource from KWOK, handle as custom resource
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.delete_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="stages",  # KWOK Stage resources use "stages" as plural
                    name=resource_name,
                    body=delete_options
                )
            elif kind == "MPIJob":
                # MPIJob is a custom resource from Kubeflow MPI Operator
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                if namespace:
                    custom_api.delete_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=namespace,
                        plural="mpijobs",
                        name=resource_name,
                        body=delete_options
                    )
                else:
                    raise ValueError("MPIJob requires a namespace")
            elif kind == "NodeFeatureRule":
                # NodeFeatureRule is a custom resource from Node Feature Discovery (NFD)
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                # NodeFeatureRule is cluster-scoped
                custom_api.delete_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="nodefeaturerules",
                    name=resource_name,
                    body=delete_options
                )
            elif kind == "NicClusterPolicy":
                # NicClusterPolicy is a custom resource from NVIDIA Network Operator
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                # NicClusterPolicy is cluster-scoped
                custom_api.delete_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="nicclusterpolicies",
                    name=resource_name,
                    body=delete_options
                )
            else:
                logger.warning("Unsupported resource kind for deletion: %s. Skipping...", kind)

            logger.info(f"Successfully deleted {kind}/{resource_name}")

        except client.rest.ApiException as e:
            if e.status == 404 and ignore_not_found:  # Resource not found
                resource_name = manifest.get('metadata', {}).get('name')
                logger.info("Resource %s/%s not found, skipping deletion",
                           kind, resource_name)
            else:
                raise Exception(f"Error deleting {kind}/{resource_name}: {str(e)}") from e
        except Exception as e:
            resource_name = manifest.get('metadata', {}).get('name')
            raise Exception(f"Error deleting {kind}/{resource_name}: {str(e)}") from e

    def install_gpu_device_plugin(self, namespace="kube-system"):
        """
        Install the NVIDIA GPU device plugin in the specified namespace.
        This will create a DaemonSet that deploys the NVIDIA device plugin on all nodes.
        """
        try:
            # Load the DaemonSet YAML from the official NVIDIA repository
            logger.info("Installing NVIDIA GPU device plugin...")
            response = requests.get(UrlConstants.NVIDIA_GPU_DEVICE_PLUGIN_YAML, timeout=30)
            response.raise_for_status()  # Raise an error for bad responses
            daemonset_yaml = yaml.safe_load(response.text)

            # Create the DaemonSet in the specified namespace
            self.app.create_namespaced_daemon_set(
                body=daemonset_yaml, namespace=namespace
            )
            logger.info("NVIDIA GPU device plugin installed successfully.")
        except Exception as e:
            logger.error(f"Error installing NVIDIA GPU device plugin: {str(e)}")
            raise e

    # verify device plugin and return logs for success and error case
    def verify_gpu_device_plugin(self, namespace="kube-system", timeout=100):
        """
        Verify if the NVIDIA GPU device plugin is running correctly.
        This checks if the DaemonSet is available and all pods are running.
        """
        logger.info("Verifying NVIDIA GPU device plugin...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                daemonset = self.app.read_namespaced_daemon_set(
                    name="nvidia-device-plugin-daemonset", namespace=namespace
                )
                desired = daemonset.status.desired_number_scheduled
                ready = daemonset.status.number_ready
                logger.info(f"DaemonSet status: Desired={desired}, Ready={ready}")
                if desired == ready:
                    logger.info("NVIDIA GPU device plugin is running correctly.")
                    return True
            except client.rest.ApiException as e:
                logger.error(f"Error verifying NVIDIA GPU device plugin: {str(e)}")
                raise e
            time.sleep(1)
        logger.error("NVIDIA GPU device plugin verification timed out.")
        return False

    def patch_deployment(self, name, namespace, node_selector=None, tolerations=None):
        """
        Patch a deployment with node selector and tolerations.

        :param name: Name of the deployment to patch
        :param namespace: Namespace of the deployment
        :param node_selector: Dictionary of node selector labels (e.g., {"kwok": "true"})
        :param tolerations: List of toleration dictionaries
        :return: None
        """
        try:
            # Construct the patch body
            patch_body = {
                "spec": {
                    "template": {
                        "spec": {}
                    }
                }
            }

            # Add node selector if provided
            if node_selector:
                patch_body["spec"]["template"]["spec"]["nodeSelector"] = node_selector

            # Add tolerations if provided
            if tolerations:
                patch_body["spec"]["template"]["spec"]["tolerations"] = tolerations

            logger.info(f"Patching deployment {name} in namespace {namespace}")
            logger.info(f"Patch body: {patch_body}")

            # Patch the deployment
            self.app.patch_namespaced_deployment(
                name=name,
                namespace=namespace,
                body=patch_body
            )
            logger.info(f"Successfully patched deployment {name}")

        except client.rest.ApiException as e:
            logger.error(f"Error patching deployment {name}: {str(e)}")
            raise Exception(f"Error patching deployment {name}: {str(e)}") from e
        except Exception as e:
            logger.error(f"Unexpected error patching deployment {name}: {str(e)}")
            raise Exception(f"Unexpected error patching deployment {name}: {str(e)}") from e
