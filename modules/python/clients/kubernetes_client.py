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

    def wait_for_pods_ready(self, operation_timeout_in_minutes, namespace="default", pod_count=None, label_selector=None):
        """
        Waits for a specific number of pods with a given label to be ready within a specified timeout.
        Raises an exception if the expected number of pods are not ready within the timeout.

        :param label_selector: The label to filter pods.
        :param operation_timeout_in_minutes: The timeout in minutes to wait for the pods to be ready.
        :param pod_count: The expected number of pods to be ready. If not provided, it will dynamically fetch the count of pods with the specified label on each iteration.
        :param namespace: The namespace to filter pods.
        :return: List of ready pods
        """
        pods = []
        timeout = time.time() + (operation_timeout_in_minutes * 60)

        # If pod_count is provided, use it for logging
        if pod_count is not None:
            logger.info(f"Validating {pod_count} pods with label {label_selector} are ready.")
        else:
            logger.info(f"Validating all pods with label {label_selector} are ready (dynamic count).")

        while time.time() < timeout:
            # Get current expected pod count
            current_pod_count = pod_count
            if current_pod_count is None:
                labelled_pods = self.get_pods_by_namespace(
                    namespace=namespace, label_selector=label_selector
                )
                current_pod_count = len(labelled_pods)
                if current_pod_count == 0:
                    raise Exception(f"No pods found with selector '{label_selector}' in namespace '{namespace}'")

            pods = self.get_ready_pods_by_namespace(namespace=namespace, label_selector=label_selector)
            if len(pods) == current_pod_count:
                return pods
            logger.info(f"Waiting for {current_pod_count} pods to be ready. Currently {len(pods)} pods are ready.")
            time.sleep(10)

        # Final count for error message
        final_expected_count = pod_count
        if final_expected_count is None:
            labelled_pods = self.get_pods_by_namespace(
                namespace=namespace, label_selector=label_selector
            )
            final_expected_count = len(labelled_pods)

        raise Exception(f"Only {len(pods)} pods are ready, expected {final_expected_count} pods!")

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

    def wait_for_pods_completed(self, label_selector, namespace="default", timeout=300, pod_count=None):
        """
        Waits for pods with a specific label to complete successfully their execution within a specified timeout.
        Raises an exception if the pods do not complete within the timeout.

        :param label_selector: The label selector to filter pods.
        :param namespace: The namespace where the pod is located (default: "default").
        :param timeout: The timeout in seconds to wait for the pod to complete (default: 300 seconds).
        :return: None
        """
        # If pod_count is provided, use it for logging
        if pod_count is not None:
            logger.info(f"Waiting for {pod_count} pod(s) with label {label_selector}in namespace '{namespace}' to complete")
        else:
            logger.info(f"Waiting for pods with label '{label_selector}' in namespace '{namespace}' to complete")
        start_time = time.time()
        while time.time() - start_time < timeout:
            pods = self.get_pods_by_namespace(
                    namespace=namespace, label_selector=label_selector
                )
            if not pods:
                raise Exception(f"No pods found with selector '{label_selector}' in namespace '{namespace}'")
            current_pod_count = pod_count
            if current_pod_count is None:
                current_pod_count = len(pods)
            completed_pods = []
            for pod in pods:
                logger.info(f"Pod '{pod.metadata.name}' status: {pod.status.phase}")
                if pod.status.phase == "Succeeded":
                    completed_pods.append(pod)
                if len(completed_pods) == current_pod_count:
                    return completed_pods
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

    def _format_k8s_timestamp(self, ts):
        """Format a Kubernetes datetime object to ISO 8601 string."""
        if ts is None:
            return None
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _get_condition_transition_time(self, conditions, condition_type):
        """Get lastTransitionTime for a specific condition type from a list of conditions."""
        if not conditions:
            return None
        for cond in conditions:
            if cond.type == condition_type:
                return self._format_k8s_timestamp(cond.last_transition_time)
        return None

    def collect_node_startup_timestamps(self, nodes):
        """
        Collect per-node startup timestamps from Kubernetes node objects.

        For each node, extracts:
          - node_name: the node's name
          - node_registered: node.metadata.creationTimestamp (T1) — when kubelet registers the node object
          - node_ready: Ready condition lastTransitionTime (T4)
          - node_network_unavailable_cleared: NetworkUnavailable condition lastTransitionTime

        Args:
            nodes: List of V1Node objects (e.g. from wait_for_nodes_ready)

        Returns:
            List of dicts with per-node timestamp data
        """
        results = []
        for node in nodes:
            node_name = node.metadata.name
            created = self._format_k8s_timestamp(node.metadata.creation_timestamp)
            ready_time = self._get_condition_transition_time(
                node.status.conditions, "Ready")
            network_unavailable_time = self._get_condition_transition_time(
                node.status.conditions, "NetworkUnavailable")

            entry = {
                "node_name": node_name,
                "node_registered": created,
                "node_ready": ready_time,
                "node_network_unavailable_cleared": network_unavailable_time,
            }
            logger.info("Node startup timestamps for '%s': %s", node_name, entry)
            results.append(entry)
        return results

    def collect_cni_pod_timestamps(self, node_names, cni_daemonset_label, namespace="kube-system"):
        """
        Collect CNI agent pod timestamps for specific nodes.

        For each node, finds the CNI daemonset pod and extracts:
          - cni_container_started: first container's state.running.startedAt (T2)
          - cni_pod_ready: Ready condition lastTransitionTime (T3)
          - init_containers: list of init container timing dicts
          - containers: list of main container timing dicts
          - image_pull_events: list of image pull timing dicts from pod events

        Args:
            node_names: List of node name strings
            cni_daemonset_label: Label selector for the CNI daemonset pods
                                 (e.g. "k8s-app=cilium" or "k8s-app=azure-cni")
            namespace: Namespace where CNI pods run (default: kube-system)

        Returns:
            Dict mapping node_name -> CNI timestamp dict
        """
        results = {}
        for node_name in node_names:
            pods = self.get_pods_by_namespace(
                namespace=namespace,
                label_selector=cni_daemonset_label,
                field_selector=f"spec.nodeName={node_name}",
            )
            if not pods:
                logger.warning("No CNI pod found on node '%s' with label '%s'",
                               node_name, cni_daemonset_label)
                results[node_name] = {
                    "cni_container_started": None,
                    "cni_pod_ready": None,
                    "init_containers": [],
                    "containers": [],
                    "image_pull_events": [],
                }
                continue

            pod = pods[0]
            # T2: first container started time
            container_started = None
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    if cs.state and cs.state.running and cs.state.running.started_at:
                        container_started = self._format_k8s_timestamp(
                            cs.state.running.started_at)
                        break

            # T3: pod Ready condition transition time
            cni_ready = self._get_condition_transition_time(
                pod.status.conditions, "Ready")

            # Collect init container timestamps
            init_containers = self._collect_init_container_timestamps(pod)

            # Collect main container timestamps
            containers = self._collect_container_timestamps(pod)

            # Collect image pull events
            image_pull_events = self._collect_image_pull_events(
                pod.metadata.name, namespace)

            entry = {
                "cni_container_started": container_started,
                "cni_pod_ready": cni_ready,
                "init_containers": init_containers,
                "containers": containers,
                "image_pull_events": image_pull_events,
            }
            logger.info("CNI pod timestamps for node '%s': %s", node_name, entry)
            results[node_name] = entry

        return results

    def _collect_init_container_timestamps(self, pod):
        """
        Collect start/finish timestamps for each init container in a pod.

        Returns:
            List of dicts with name, image, started_at, finished_at, duration_seconds
        """
        init_containers = []
        if not pod.status.init_container_statuses:
            return init_containers

        for cs in pod.status.init_container_statuses:
            entry = {
                "name": cs.name,
                "image": cs.image,
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
            }
            # Terminated init containers have start and finish times
            if cs.state and cs.state.terminated:
                started = cs.state.terminated.started_at
                finished = cs.state.terminated.finished_at
                entry["started_at"] = self._format_k8s_timestamp(started)
                entry["finished_at"] = self._format_k8s_timestamp(finished)
                if started and finished:
                    entry["duration_seconds"] = (finished - started).total_seconds()
            # Last state may also have terminated info
            elif cs.last_state and cs.last_state.terminated:
                started = cs.last_state.terminated.started_at
                finished = cs.last_state.terminated.finished_at
                entry["started_at"] = self._format_k8s_timestamp(started)
                entry["finished_at"] = self._format_k8s_timestamp(finished)
                if started and finished:
                    entry["duration_seconds"] = (finished - started).total_seconds()

            init_containers.append(entry)

        return init_containers

    def _collect_container_timestamps(self, pod):
        """
        Collect start timestamps for each main container in a pod.

        Returns:
            List of dicts with name, image, started_at
        """
        containers = []
        if not pod.status.container_statuses:
            return containers

        for cs in pod.status.container_statuses:
            entry = {
                "name": cs.name,
                "image": cs.image,
                "started_at": None,
                "ready": cs.ready,
            }
            if cs.state and cs.state.running and cs.state.running.started_at:
                entry["started_at"] = self._format_k8s_timestamp(
                    cs.state.running.started_at)
            containers.append(entry)

        return containers

    def _collect_image_pull_events(self, pod_name, namespace):
        """
        Collect image pull events (Pulling, Pulled) for a pod.

        Returns:
            List of dicts with image, pulling_at, pulled_at, duration_seconds, message
        """
        image_pulls = []
        try:
            events = self.api.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod_name},involvedObject.kind=Pod"
            )

            # Group events by image
            pull_map = {}  # image -> {pulling_at, pulled_at}
            for event in events.items:
                if event.reason == "Pulling":
                    # Extract image name from message: 'Pulling image "..."'
                    image = self._extract_image_from_event_message(event.message)
                    if image:
                        if image not in pull_map:
                            pull_map[image] = {"pulling_at": None, "pulled_at": None, "message": None}
                        ts = (event.event_time or event.first_timestamp
                              or event.metadata.creation_timestamp)
                        pull_map[image]["pulling_at"] = self._format_k8s_timestamp(ts)
                elif event.reason == "Pulled":
                    image = self._extract_image_from_event_message(event.message)
                    if image:
                        if image not in pull_map:
                            pull_map[image] = {"pulling_at": None, "pulled_at": None, "message": None}
                        ts = (event.event_time or event.first_timestamp
                              or event.metadata.creation_timestamp)
                        pull_map[image]["pulled_at"] = self._format_k8s_timestamp(ts)
                        pull_map[image]["message"] = event.message

            # Convert to list with duration
            for image, times in pull_map.items():
                entry = {
                    "image": image,
                    "pulling_at": times["pulling_at"],
                    "pulled_at": times["pulled_at"],
                    "duration_seconds": None,
                    "message": times["message"],
                }
                if times["pulling_at"] and times["pulled_at"]:
                    try:
                        from datetime import datetime
                        start = datetime.fromisoformat(
                            times["pulling_at"].replace("Z", "+00:00"))
                        end = datetime.fromisoformat(
                            times["pulled_at"].replace("Z", "+00:00"))
                        entry["duration_seconds"] = (end - start).total_seconds()
                    except Exception:
                        pass
                image_pulls.append(entry)

        except Exception as e:
            logger.warning("Failed to collect image pull events for pod '%s': %s",
                          pod_name, e)

        return image_pulls

    def _extract_image_from_event_message(self, message):
        """Extract image name from a Pulling/Pulled event message."""
        if not message:
            return None
        # Messages are like: 'Pulling image "mcr.microsoft.com/..."'
        # or 'Successfully pulled image "mcr.microsoft.com/..." in 3.5s'
        start = message.find('"')
        if start == -1:
            return None
        end = message.find('"', start + 1)
        if end == -1:
            return None
        return message[start + 1:end]

    def deploy_probe_pod(self, node_pool_name, namespace="default",
                         pod_name="latency-probe", image="mcr.microsoft.com/oss/kubernetes/pause:3.9"):
        """
        Deploy a probe pod with anti-affinity against existing nodes in the pool.

        The pod uses a nodeSelector for the target pool and a podAntiAffinity against
        itself on the existing node, ensuring it stays Pending until a new node is added.

        Args:
            node_pool_name: The node pool to target (agentpool label)
            namespace: Namespace for the probe pod (default: "default")
            pod_name: Name of the probe pod
            image: Container image to use

        Returns:
            The created pod name
        """
        # Get ALL existing nodes in the pool (not just ready ones) to build anti-affinity
        existing_nodes = self.get_nodes(label_selector=f"agentpool={node_pool_name}")
        existing_node_names = [n.metadata.name for n in existing_nodes]

        logger.info("Deploying probe pod '%s' with anti-affinity against nodes: %s",
                    pod_name, existing_node_names)

        # Build nodeAffinity to NOT schedule on existing nodes
        affinity = None
        if existing_node_names:
            affinity = client.V1Affinity(
                node_affinity=client.V1NodeAffinity(
                    required_during_scheduling_ignored_during_execution=client.V1NodeSelector(
                        node_selector_terms=[
                            client.V1NodeSelectorTerm(
                                match_expressions=[
                                    client.V1NodeSelectorRequirement(
                                        key="kubernetes.io/hostname",
                                        operator="NotIn",
                                        values=existing_node_names,
                                    ),
                                    client.V1NodeSelectorRequirement(
                                        key="agentpool",
                                        operator="In",
                                        values=[node_pool_name],
                                    ),
                                ]
                            )
                        ]
                    )
                )
            )

        pod_manifest = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels={"app": "latency-probe"},
            ),
            spec=client.V1PodSpec(
                node_selector={"agentpool": node_pool_name},
                affinity=affinity,
                containers=[
                    client.V1Container(
                        name="probe",
                        image=image,
                        resources=client.V1ResourceRequirements(
                            requests={"cpu": "100m", "memory": "64Mi"},
                        ),
                    )
                ],
            ),
        )

        try:
            self.api.create_namespaced_pod(namespace=namespace, body=pod_manifest)
            logger.info("Probe pod '%s' created in namespace '%s'", pod_name, namespace)
        except client.rest.ApiException as e:
            if e.status == 409:
                # Pod already exists, delete and recreate
                logger.info("Probe pod '%s' already exists, recreating", pod_name)
                self.api.delete_namespaced_pod(name=pod_name, namespace=namespace)
                time.sleep(2)
                self.api.create_namespaced_pod(namespace=namespace, body=pod_manifest)
            else:
                raise

        return pod_name

    def wait_for_probe_pod_running(self, pod_name="latency-probe", namespace="default",
                                   operation_timeout_in_minutes=10):
        """
        Wait for the probe pod to transition to Running phase with Ready condition.

        Args:
            pod_name: Name of the probe pod
            namespace: Namespace of the probe pod
            operation_timeout_in_minutes: Timeout in minutes

        Returns:
            The pod object once it's Running and Ready
        """
        timeout = time.time() + (operation_timeout_in_minutes * 60)
        logger.info("Waiting for probe pod '%s' to become Running...", pod_name)

        while time.time() < timeout:
            pod = self.api.read_namespaced_pod(name=pod_name, namespace=namespace)
            phase = pod.status.phase if pod.status else None

            if phase == "Running":
                # Check Ready condition
                if pod.status.conditions:
                    for cond in pod.status.conditions:
                        if cond.type == "Ready" and cond.status == "True":
                            logger.info("Probe pod '%s' is Running and Ready", pod_name)
                            return pod

            logger.info("Probe pod '%s' phase: %s, waiting...", pod_name, phase)
            time.sleep(2)

        # Log diagnostic info before raising
        try:
            pod = self.api.read_namespaced_pod(name=pod_name, namespace=namespace)
            logger.warning("Probe pod '%s' final state - phase: %s, node: %s, conditions: %s",
                          pod_name, pod.status.phase, pod.spec.node_name,
                          [(c.type, c.status, c.reason, c.message) for c in (pod.status.conditions or [])])
            # Get scheduler events for the pod
            events = self.api.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod_name},involvedObject.kind=Pod"
            )
            for event in events.items:
                logger.warning("Probe pod event: %s - %s: %s",
                              event.reason, event.source.component if event.source else "unknown",
                              event.message)
        except Exception as diag_err:
            logger.warning("Failed to collect probe pod diagnostics: %s", diag_err)

        raise Exception(
            f"Probe pod '{pod_name}' did not become Running within {operation_timeout_in_minutes} minutes"
        )

    def delete_probe_pod(self, pod_name="latency-probe", namespace="default"):
        """Delete the probe pod used for latency measurement."""
        try:
            self.api.delete_namespaced_pod(name=pod_name, namespace=namespace)
            logger.info("Probe pod '%s' deleted", pod_name)
        except client.rest.ApiException as e:
            if e.status == 404:
                logger.info("Probe pod '%s' not found (already deleted)", pod_name)
            else:
                raise

    def collect_autoscale_latency(self, node_pool_name, cni_daemonset_label=None,
                                  cni_blocking_taint=None, namespace="default",
                                  pod_name="latency-probe",
                                  operation_timeout_in_minutes=15):
        """
        Measure node and pod startup latency via cluster autoscaler.

        Deploys a probe pod that cannot schedule on existing nodes, forcing the
        cluster autoscaler to scale up. Uses a node watch to capture intermediate
        state transitions (taints clearing, conditions changing) in real time,
        then collects final timestamps once the pod is Running.

        Timestamps collected:
          - pod_created: probe pod creationTimestamp (trigger moment)
          - triggered_scale_up: TriggeredScaleUp event timestamp from cluster autoscaler
          - node_registered: new node's creationTimestamp (T1)
          - node_ready: new node's Ready condition lastTransitionTime (T4)
          - node_network_unavailable_cleared: NetworkUnavailable condition lastTransitionTime
          - not_ready_taint_cleared: wall-clock time when not-ready taint was removed
          - cni_taint_cleared: wall-clock time when CNI blocking taint was removed
          - cni_container_started: CNI pod container startedAt (T2)
          - cni_pod_ready: CNI pod Ready condition lastTransitionTime (T3)
          - pod_scheduled: probe pod PodScheduled condition lastTransitionTime
          - container_started: probe pod container startedAt (T5)
          - pod_ready: probe pod Ready condition lastTransitionTime

        Args:
            node_pool_name: The node pool to target (agentpool label)
            cni_daemonset_label: Label selector for CNI pods (e.g. "k8s-app=cilium")
            cni_blocking_taint: CNI-specific taint key that blocks scheduling
                                (e.g. "node.cilium.io/agent-not-ready")
            namespace: Namespace for the probe pod
            pod_name: Name of the probe pod
            operation_timeout_in_minutes: Timeout for the entire operation

        Returns:
            Dict with all timestamps, intermediate states, and computed latency metrics
        """
        from kubernetes import watch

        try:
            # Snapshot existing nodes before scale-up
            existing_nodes = {n.metadata.name for n in
                              self.get_nodes(label_selector=f"agentpool={node_pool_name}")}

            # Deploy probe pod — this triggers the autoscaler
            self.deploy_probe_pod(node_pool_name=node_pool_name,
                                  namespace=namespace, pod_name=pod_name)

            # Get pod_created timestamp
            pod = self.api.read_namespaced_pod(name=pod_name, namespace=namespace)
            pod_created = self._format_k8s_timestamp(pod.metadata.creation_timestamp)
            logger.info("Probe pod '%s' created at %s, waiting for autoscaler to scale up...",
                       pod_name, pod_created)

            # Watch for new node in a background thread so it runs concurrently
            # with the pod scheduling. This avoids blocking if the watch doesn't
            # terminate promptly (e.g. Kubenet NetworkUnavailable delay).
            import threading
            stop_event = threading.Event()

            # Shared result dict — the watch writes events here in real-time,
            # so they're available even if the watch thread is still blocked on
            # I/O when join() times out.
            intermediate_states = {
                "events": [],
                "node_registered_at": None,
                "not_ready_taint_observed": None,
                "not_ready_taint_cleared": None,
                "network_unavailable_taint_observed": None,
                "network_unavailable_taint_cleared": None,
                "cni_taint_observed": None,
                "cni_taint_cleared": None,
                "node_ready_at": None,
            }

            def _run_watch():
                self._watch_node_transitions(
                    existing_nodes=existing_nodes,
                    node_pool_name=node_pool_name,
                    cni_blocking_taint=cni_blocking_taint,
                    timeout_minutes=operation_timeout_in_minutes,
                    stop_event=stop_event,
                    result=intermediate_states,
                )

            watch_thread = threading.Thread(target=_run_watch, daemon=True)
            watch_thread.start()

            # Wait for the probe pod to become Running
            pod = self.wait_for_probe_pod_running(
                pod_name=pod_name, namespace=namespace,
                operation_timeout_in_minutes=operation_timeout_in_minutes)

            # Signal watch to stop and wait for it to finish
            stop_event.set()
            watch_thread.join(timeout=15)

            # Collect TriggeredScaleUp event timestamp from pod events
            triggered_scale_up = self._get_triggered_scale_up_timestamp(
                pod_name=pod_name, namespace=namespace)

            # Fallback: if no TriggeredScaleUp found (e.g. BYOCNI), use the
            # first FailedScheduling event as a proxy for when autoscaler saw the pod
            if triggered_scale_up is None:
                triggered_scale_up = self._get_first_scheduling_event_timestamp(
                    pod_name=pod_name, namespace=namespace)

            # Identify the new node (the one the pod was scheduled on)
            new_node_name = pod.spec.node_name
            logger.info("Probe pod scheduled on node '%s'", new_node_name)

            # Collect node timestamps
            new_node = self.api.read_node(name=new_node_name)
            node_registered = self._format_k8s_timestamp(new_node.metadata.creation_timestamp)
            node_ready = self._get_condition_transition_time(
                new_node.status.conditions, "Ready")
            node_network_unavailable_cleared = self._get_condition_transition_time(
                new_node.status.conditions, "NetworkUnavailable")

            # Collect CNI timestamps if applicable
            cni_container_started = None
            cni_pod_ready = None
            cni_init_containers = []
            cni_containers = []
            cni_image_pull_events = []
            if cni_daemonset_label:
                cni_timestamps = self.collect_cni_pod_timestamps(
                    [new_node_name], cni_daemonset_label)
                cni_info = cni_timestamps.get(new_node_name, {})
                cni_container_started = cni_info.get("cni_container_started")
                cni_pod_ready = cni_info.get("cni_pod_ready")
                cni_init_containers = cni_info.get("init_containers", [])
                cni_containers = cni_info.get("containers", [])
                cni_image_pull_events = cni_info.get("image_pull_events", [])

            # Collect pod timestamps
            pod_scheduled = self._get_condition_transition_time(
                pod.status.conditions, "PodScheduled")
            pod_initialized = self._get_condition_transition_time(
                pod.status.conditions, "Initialized")
            containers_ready = self._get_condition_transition_time(
                pod.status.conditions, "ContainersReady")
            pod_ready = self._get_condition_transition_time(
                pod.status.conditions, "Ready")

            container_started = None
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    if cs.state and cs.state.running and cs.state.running.started_at:
                        container_started = self._format_k8s_timestamp(cs.state.running.started_at)
                        break

            # Build result
            timestamps = {
                "node_name": new_node_name,
                "pod_name": pod_name,
                "pod_created": pod_created,
                "triggered_scale_up": triggered_scale_up,
                "node_registered": node_registered,
                "node_ready": node_ready,
                "node_network_unavailable_cleared": node_network_unavailable_cleared,
                "not_ready_taint_observed": intermediate_states.get("not_ready_taint_observed"),
                "not_ready_taint_cleared": intermediate_states.get("not_ready_taint_cleared"),
                "network_unavailable_taint_observed": intermediate_states.get("network_unavailable_taint_observed"),
                "network_unavailable_taint_cleared": intermediate_states.get("network_unavailable_taint_cleared"),
                "cni_taint_observed": intermediate_states.get("cni_taint_observed"),
                "cni_taint_cleared": intermediate_states.get("cni_taint_cleared"),
                "cni_container_started": cni_container_started,
                "cni_pod_ready": cni_pod_ready,
                "cni_init_containers": cni_init_containers,
                "cni_containers": cni_containers,
                "cni_image_pull_events": cni_image_pull_events,
                "pod_scheduled": pod_scheduled,
                "pod_initialized": pod_initialized,
                "container_started": container_started,
                "containers_ready": containers_ready,
                "pod_ready": pod_ready,
                "intermediate_states": intermediate_states.get("events", []),
            }

            # Compute latencies
            timestamps["latencies"] = self._compute_autoscale_latencies(timestamps)

            logger.info("Autoscale latency results: %s", timestamps)
            return timestamps

        finally:
            # Always clean up the probe pod
            try:
                self.delete_probe_pod(pod_name=pod_name, namespace=namespace)
            except Exception:
                pass

    def _watch_node_transitions(self, existing_nodes, node_pool_name,
                                cni_blocking_taint=None, timeout_minutes=15,
                                stop_event=None, result=None):
        """
        Watch for a new node in the pool and capture intermediate state transitions.

        Tracks:
          - Node appearance (registration)
          - not-ready taint cleared (node.kubernetes.io/not-ready:NoSchedule removed)
          - CNI blocking taint cleared (e.g. node.cilium.io/agent-not-ready removed)
          - Node Ready condition transition (first time only)

        Args:
            existing_nodes: Set of node names that existed before scale-up
            node_pool_name: Label value to filter nodes
            cni_blocking_taint: Optional CNI-specific taint key to track
            timeout_minutes: Watch timeout
            stop_event: Optional threading.Event to signal early termination
            result: Optional shared dict to write events into (for thread-safe access)

        Returns:
            Dict with taint-clearing timestamps and event log
        """
        from kubernetes import watch
        from datetime import datetime, timezone

        if result is None:
            result = {
                "events": [],
                "node_registered_at": None,
                "not_ready_taint_observed": None,
                "not_ready_taint_cleared": None,
                "network_unavailable_taint_observed": None,
                "network_unavailable_taint_cleared": None,
                "cni_taint_observed": None,
                "cni_taint_cleared": None,
                "node_ready_at": None,
            }

        deadline = time.time() + (timeout_minutes * 60)
        new_node_name = None
        saw_not_ready_taint = False
        saw_network_unavailable_taint = False
        saw_cni_taint = False
        node_ready_recorded = False

        w = watch.Watch()
        try:
            for event in w.stream(
                self.api.list_node,
                label_selector=f"agentpool={node_pool_name}",
                timeout_seconds=int(timeout_minutes * 60),
            ):
                if time.time() > deadline:
                    break
                if stop_event and stop_event.is_set():
                    logger.info("Watch: stop signal received, terminating")
                    break

                node = event["object"]
                node_name = node.metadata.name

                # Only track the new node
                if node_name in existing_nodes:
                    continue

                now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                # First time we see the new node
                if new_node_name is None:
                    new_node_name = node_name
                    result["node_registered_at"] = now_iso
                    result["events"].append({
                        "event": "node_registered",
                        "node": node_name,
                        "observed_at": now_iso,
                        "creation_timestamp": self._format_k8s_timestamp(
                            node.metadata.creation_timestamp),
                    })
                    logger.info("Watch: new node '%s' registered", node_name)

                # Track taints using (key, effect) pairs for precision
                current_taints = {
                    (t.key, t.effect) for t in (node.spec.taints or [])
                }

                # Track not-ready taint (NoSchedule effect is the scheduling gate)
                not_ready_key = "node.kubernetes.io/not-ready"
                not_ready_noschedule = (not_ready_key, "NoSchedule")
                if not_ready_noschedule in current_taints:
                    if not saw_not_ready_taint:
                        saw_not_ready_taint = True
                        result["not_ready_taint_observed"] = now_iso
                        result["events"].append({
                            "event": "not_ready_taint_observed",
                            "node": node_name,
                            "observed_at": now_iso,
                        })
                        logger.info("Watch: not-ready taint observed on '%s'", node_name)
                elif saw_not_ready_taint and result["not_ready_taint_cleared"] is None:
                    result["not_ready_taint_cleared"] = now_iso
                    result["events"].append({
                        "event": "not_ready_taint_cleared",
                        "node": node_name,
                        "observed_at": now_iso,
                    })
                    logger.info("Watch: not-ready taint cleared on '%s'", node_name)

                # Track network-unavailable taint (blocks scheduling in kubenet)
                net_unavail_key = "node.kubernetes.io/network-unavailable"
                net_unavail_noschedule = (net_unavail_key, "NoSchedule")
                if net_unavail_noschedule in current_taints:
                    if not saw_network_unavailable_taint:
                        saw_network_unavailable_taint = True
                        result["network_unavailable_taint_observed"] = now_iso
                        result["events"].append({
                            "event": "network_unavailable_taint_observed",
                            "node": node_name,
                            "observed_at": now_iso,
                        })
                        logger.info("Watch: network-unavailable taint observed on '%s'", node_name)
                elif saw_network_unavailable_taint and result["network_unavailable_taint_cleared"] is None:
                    result["network_unavailable_taint_cleared"] = now_iso
                    result["events"].append({
                        "event": "network_unavailable_taint_cleared",
                        "node": node_name,
                        "observed_at": now_iso,
                    })
                    logger.info("Watch: network-unavailable taint cleared on '%s'", node_name)

                # Track CNI-specific taint (any effect)
                if cni_blocking_taint:
                    cni_taint_present = any(
                        t.key == cni_blocking_taint
                        for t in (node.spec.taints or [])
                    )
                    if cni_taint_present:
                        if not saw_cni_taint:
                            saw_cni_taint = True
                            result["cni_taint_observed"] = now_iso
                            result["events"].append({
                                "event": "cni_taint_observed",
                                "node": node_name,
                                "taint": cni_blocking_taint,
                                "observed_at": now_iso,
                            })
                            logger.info("Watch: CNI taint '%s' observed on '%s'",
                                       cni_blocking_taint, node_name)
                    elif saw_cni_taint and result["cni_taint_cleared"] is None:
                        result["cni_taint_cleared"] = now_iso
                        result["events"].append({
                            "event": "cni_taint_cleared",
                            "node": node_name,
                            "taint": cni_blocking_taint,
                            "observed_at": now_iso,
                        })
                        logger.info("Watch: CNI taint '%s' cleared on '%s'",
                                   cni_blocking_taint, node_name)

                # Track Ready condition — only record the first transition
                if not node_ready_recorded:
                    for cond in (node.status.conditions or []):
                        if cond.type == "Ready":
                            if cond.status == "True":
                                node_ready_recorded = True
                                result["node_ready_at"] = now_iso
                                result["events"].append({
                                    "event": "node_ready",
                                    "node": node_name,
                                    "observed_at": now_iso,
                                    "last_transition_time": self._format_k8s_timestamp(
                                        cond.last_transition_time),
                                })
                                logger.info("Watch: node '%s' is Ready", node_name)
                            break

        except Exception as e:
            logger.warning("Node watch ended: %s", e)
        finally:
            w.stop()

        return result

    def _get_triggered_scale_up_timestamp(self, pod_name, namespace="default",
                                            max_retries=5, retry_interval=3):
        """
        Get the timestamp of the TriggeredScaleUp event for the probe pod.

        The cluster autoscaler posts this event on unschedulable pods when it
        decides to scale up a node group. In some K8s versions or cluster
        configurations (e.g., BYOCNI), the event may use the events.k8s.io/v1
        API with eventTime instead of firstTimestamp, or may take longer to appear.

        Args:
            pod_name: Name of the probe pod
            namespace: Pod namespace
            max_retries: Number of retry attempts
            retry_interval: Seconds between retries

        Returns:
            ISO 8601 timestamp string, or None if not found
        """
        scale_up_reasons = {"TriggeredScaleUp", "ScaleUp", "ScaledUpGroup"}

        for attempt in range(max_retries):
            try:
                # Try core/v1 Events API
                events = self.api.list_namespaced_event(
                    namespace=namespace,
                    field_selector=f"involvedObject.name={pod_name},involvedObject.kind=Pod"
                )
                for event in events.items:
                    if event.reason in scale_up_reasons:
                        # Prefer event_time (events.k8s.io/v1), then first_timestamp, then creation_timestamp
                        ts = (event.event_time or event.first_timestamp
                              or event.metadata.creation_timestamp)
                        if ts:
                            return self._format_k8s_timestamp(ts)

                # Try events.k8s.io/v1 API as fallback (newer clusters may only have events here)
                try:
                    from kubernetes.client import EventsV1Api
                    events_v1 = EventsV1Api(self.api.api_client)
                    event_list = events_v1.list_namespaced_event(
                        namespace=namespace,
                        field_selector=f"regarding.name={pod_name},regarding.kind=Pod"
                    )
                    for event in event_list.items:
                        if event.reason in scale_up_reasons:
                            ts = (event.event_time or event.metadata.creation_timestamp)
                            if ts:
                                return self._format_k8s_timestamp(ts)
                except Exception as e:
                    logger.debug("EventsV1Api lookup failed (expected on older clusters): %s", e)

                if attempt < max_retries - 1:
                    logger.debug("TriggeredScaleUp event not found (attempt %d/%d), retrying...",
                                attempt + 1, max_retries)
                    time.sleep(retry_interval)
            except Exception as e:
                logger.warning("Failed to get TriggeredScaleUp event (attempt %d): %s",
                              attempt + 1, e)
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)

        logger.warning("No TriggeredScaleUp event found for pod '%s' after %d attempts",
                      pod_name, max_retries)
        return None

    def _get_first_scheduling_event_timestamp(self, pod_name, namespace="default"):
        """
        Get the timestamp of the first FailedScheduling event for the probe pod.

        Used as a fallback for TriggeredScaleUp when the autoscaler doesn't post
        that event (e.g. BYOCNI clusters). The first FailedScheduling event marks
        when the scheduler first evaluated the pod and found it unschedulable,
        which closely approximates when the autoscaler would have noticed it.

        Returns:
            ISO 8601 timestamp string, or None if not found
        """
        try:
            events = self.api.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod_name},involvedObject.kind=Pod"
            )
            earliest_ts = None
            for event in events.items:
                if event.reason == "FailedScheduling":
                    ts = (event.event_time or event.first_timestamp
                          or event.metadata.creation_timestamp)
                    if ts:
                        formatted = self._format_k8s_timestamp(ts)
                        if earliest_ts is None or formatted < earliest_ts:
                            earliest_ts = formatted
            if earliest_ts:
                logger.info("Using first FailedScheduling event as T0 fallback: %s", earliest_ts)
                return earliest_ts
            logger.warning("No FailedScheduling event found for pod '%s'", pod_name)
            return None
        except Exception as e:
            logger.warning("Failed to get FailedScheduling event: %s", e)
            return None

    def _compute_autoscale_latencies(self, timestamps):
        """Compute latency KPIs for autoscaler-triggered scaling."""
        latencies = {}

        def _diff_seconds(end_key, start_key):
            end_val = timestamps.get(end_key)
            start_val = timestamps.get(start_key)
            if not end_val or not start_val:
                return None
            try:
                from datetime import datetime
                end_dt = datetime.fromisoformat(end_val.replace("Z", "+00:00"))
                start_dt = datetime.fromisoformat(start_val.replace("Z", "+00:00"))
                return (end_dt - start_dt).total_seconds()
            except Exception:
                return None

        # Autoscaler reaction: time from pod created to scale-up triggered
        latencies["autoscaler_reaction_seconds"] = _diff_seconds(
            "triggered_scale_up", "pod_created")
        # Cloud provisioning: time from scale-up triggered to node registered
        latencies["cloud_provisioning_seconds"] = _diff_seconds(
            "node_registered", "triggered_scale_up")
        # Node init: time from node registered to node Ready
        latencies["node_init_seconds"] = _diff_seconds(
            "node_ready", "node_registered")
        # Total node startup: max(node_ready, cni_pod_ready) - node_registered
        node_ready_secs = _diff_seconds("node_ready", "node_registered")
        cni_ready_secs = _diff_seconds("cni_pod_ready", "node_registered")
        if node_ready_secs is not None and cni_ready_secs is not None:
            latencies["total_node_startup_seconds"] = max(node_ready_secs, cni_ready_secs)
        else:
            latencies["total_node_startup_seconds"] = (
                node_ready_secs if node_ready_secs is not None else cni_ready_secs
            )
        # Node workload-ready: time from node_registered until all scheduling
        # gates clear (max of node_ready, network_unavailable_cleared, cni_pod_ready)
        workload_ready_candidates = [
            node_ready_secs,
            _diff_seconds("node_network_unavailable_cleared", "node_registered"),
            cni_ready_secs,
        ]
        valid_candidates = [c for c in workload_ready_candidates if c is not None]
        latencies["node_workload_ready_seconds"] = (
            max(valid_candidates) if valid_candidates else None
        )
        # CNI init: time for CNI pod to become Ready
        latencies["cni_init_seconds"] = _diff_seconds(
            "cni_pod_ready", "cni_container_started")
        # CNI-induced delay: extra time CNI adds after node Ready
        cni_delay = _diff_seconds("cni_pod_ready", "node_ready")
        if cni_delay is not None:
            latencies["cni_induced_delay_seconds"] = max(0, cni_delay)
        else:
            latencies["cni_induced_delay_seconds"] = None
        # Taint clearing: time from node registered to not-ready taint cleared
        latencies["not_ready_taint_seconds"] = _diff_seconds(
            "not_ready_taint_cleared", "node_registered")
        # CNI taint clearing: time from node registered to CNI taint cleared
        latencies["cni_taint_seconds"] = _diff_seconds(
            "cni_taint_cleared", "node_registered")

        # --- Intermediate segment durations (for dashboard charts) ---
        # How long the not-ready taint was actively present on the node
        latencies["not_ready_taint_active_seconds"] = _diff_seconds(
            "not_ready_taint_cleared", "not_ready_taint_observed")
        # How long the CNI-specific taint was actively present on the node
        latencies["cni_taint_active_seconds"] = _diff_seconds(
            "cni_taint_cleared", "cni_taint_observed")
        # Time from node registration until not-ready taint first appeared
        latencies["registration_to_not_ready_taint_seconds"] = _diff_seconds(
            "not_ready_taint_observed", "node_registered")
        # Time from node registration until CNI taint first appeared
        latencies["registration_to_cni_taint_seconds"] = _diff_seconds(
            "cni_taint_observed", "node_registered")
        # Time from node Ready to CNI taint cleared (positive = CNI was bottleneck)
        latencies["node_ready_to_cni_clear_seconds"] = _diff_seconds(
            "cni_taint_cleared", "node_ready")
        # Network-unavailable taint active duration (kubenet route provisioning)
        latencies["network_unavailable_taint_active_seconds"] = _diff_seconds(
            "network_unavailable_taint_cleared", "network_unavailable_taint_observed")
        # Time from node registered to network-unavailable taint cleared
        latencies["network_unavailable_taint_seconds"] = _diff_seconds(
            "network_unavailable_taint_cleared", "node_registered")
        # Pod scheduling: time from last scheduling gate cleared to pod scheduled
        # The last gate is max(not_ready_taint_cleared, network_unavailable_taint_cleared, cni_taint_cleared)
        latencies["pod_scheduling_seconds"] = _diff_seconds(
            "pod_scheduled", "node_ready")
        # Network unavailable condition clearing: time from node_registered
        latencies["network_unavailable_seconds"] = _diff_seconds(
            "node_network_unavailable_cleared", "node_registered")
        # Pod init: time from pod Scheduled to container started
        latencies["pod_init_seconds"] = _diff_seconds(
            "container_started", "pod_scheduled")
        # Pod ready: time from container started to pod Ready
        latencies["pod_ready_seconds"] = _diff_seconds(
            "pod_ready", "container_started")
        # Total end-to-end: pod_ready - pod_created (user-facing SLA)
        latencies["total_e2e_seconds"] = _diff_seconds(
            "pod_ready", "pod_created")
        # Node-to-pod (IaaS-free): container_started - node_registered
        # Comparable to SRodi's time_to_runnable_s — isolates K8s/CNI latency
        latencies["node_to_pod_seconds"] = _diff_seconds(
            "container_started", "node_registered")

        return latencies

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
                node = self.describe_node(node_name)

                # Check if the node has GPUs allocated values
                start_time = time.time()
                while "nvidia.com/gpu" not in node.status.allocatable and time.time() < start_time + 600:
                    node = self.describe_node(node_name)
                    logger.info(f"Node allocatable resources: {node.status.allocatable}")
                    logger.info(f"Waiting for GPUs to be allocated on node {node_name}...")
                    time.sleep(1)
                gpu_count = int(node.status.allocatable.get("nvidia.com/gpu", "0"))

                logger.info(f"Node {node_name} has {gpu_count} GPUs, requesting all for validation")

                # Skip nodes with no GPUs
                if gpu_count == 0:
                    logger.warning(f"Skipping node {node_name} as it has no GPUs")
                    continue

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

            # Validate and expand manifests (handles List kind and non-dict manifests)
            expanded_manifests = self._expand_and_validate_manifests(manifests)

            for manifest in expanded_manifests:
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

            # Validate and expand manifests (handles List kind and non-dict manifests)
            expanded_manifests = self._expand_and_validate_manifests(manifests)

            # Delete manifests in reverse order (to handle dependencies)
            expanded_manifests.reverse()

            for manifest in expanded_manifests:
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

            # Validate and expand manifests (handles List kind and non-dict manifests)
            manifests_to_apply = self._expand_and_validate_manifests(manifests_to_apply)

            # Apply all manifests
            namespace_info = f" in namespace '{namespace}'" if namespace else ""
            logger.info(f"Applying {len(manifests_to_apply)} manifest(s) from: {', '.join(applied_sources)}{namespace_info}")

            for i, manifest in enumerate(manifests_to_apply):
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

            # Validate and expand manifests (handles List kind and non-dict manifests)
            manifests_to_delete = self._expand_and_validate_manifests(manifests_to_delete)

            # Delete all manifests in reverse order (to handle dependencies)
            manifests_to_delete.reverse()
            namespace_info = f" in namespace '{namespace}'" if namespace else ""
            logger.info(f"Deleting {len(manifests_to_delete)} manifest(s) from: {', '.join(deleted_sources)}{namespace_info}")

            for i, manifest in enumerate(manifests_to_delete):
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

    def _expand_and_validate_manifests(self, manifests):
        """
        Validate and expand manifests, handling List kind and non-dict manifests.

        :param manifests: List of manifests (can be dicts, lists, or scalars)
        :return: List of valid manifest dictionaries
        """
        expanded = []
        for manifest in manifests:
            # Skip None or empty manifests
            if not manifest:
                continue

            # Validate that manifest is a dictionary
            if not isinstance(manifest, dict):
                logger.warning(
                    "Skipping non-dictionary manifest (type: %s). "
                    "YAML documents must be mappings (dictionaries), not lists or scalars.",
                    type(manifest).__name__
                )
                continue

            # Handle kind: List manifests by expanding their items
            kind = manifest.get("kind")
            if kind == "List":
                items = manifest.get("items", [])
                if not isinstance(items, list):
                    logger.warning(
                        "Skipping List manifest with invalid 'items' field (expected list, got %s)",
                        type(items).__name__
                    )
                    continue
                logger.info("Expanding List manifest containing %d items", len(items))
                # Recursively expand in case items contain more Lists
                expanded.extend(self._expand_and_validate_manifests(items))
            else:
                expanded.append(manifest)

        return expanded

    def _apply_single_manifest(self, manifest, namespace=None):
        """
        Apply a single Kubernetes manifest using the appropriate API client.

        :param manifest: Dictionary representing a Kubernetes resource
        :param namespace: Optional namespace to override the manifest namespace.
                         Defaults to 'default' for namespaced resources if not specified.
        :return: None
        """
        try:
            kind = manifest.get("kind")
            # Use provided namespace or fall back to manifest namespace, then to "default"
            namespace = namespace or manifest.get("metadata", {}).get("namespace") or "default"
            name = manifest.get("metadata", {}).get("name")
            logger.info("Applying manifest %s %s in namespace %s", kind, name, namespace)

            if kind == "Deployment":
                self.app.create_namespaced_deployment(namespace=namespace, body=manifest)
            elif kind == "DaemonSet":
                self.app.create_namespaced_daemon_set(namespace=namespace, body=manifest)
            elif kind == "StatefulSet":
                self.app.create_namespaced_stateful_set(namespace=namespace, body=manifest)
            elif kind == "Service":
                self.api.create_namespaced_service(namespace=namespace, body=manifest)
            elif kind == "ConfigMap":
                self.api.create_namespaced_config_map(namespace=namespace, body=manifest)
            elif kind == "Secret":
                self.api.create_namespaced_secret(namespace=namespace, body=manifest)
            elif kind == "ServiceAccount":
                self.api.create_namespaced_service_account(namespace=namespace, body=manifest)
            elif kind == "ClusterRole":
                # ClusterRole is cluster-scoped
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.create_cluster_role(body=manifest)
            elif kind == "ClusterRoleBinding":
                # ClusterRoleBinding is cluster-scoped
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.create_cluster_role_binding(body=manifest)
            elif kind == "Role":
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.create_namespaced_role(namespace=namespace, body=manifest)
            elif kind == "RoleBinding":
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.create_namespaced_role_binding(namespace=namespace, body=manifest)
            elif kind == "Namespace":
                # Namespace is cluster-scoped
                self.api.create_namespace(body=manifest)
            elif kind == "CustomResourceDefinition":
                # CustomResourceDefinition is cluster-scoped
                apiextensions_api = client.ApiextensionsV1Api()
                apiextensions_api.create_custom_resource_definition(body=manifest)
            elif kind == "FlowSchema":
                # FlowSchema is cluster-scoped (part of flow control API)
                # Skip FlowSchemas that reference 'exempt' PriorityLevelConfiguration
                # as they are protected and cannot be created/updated
                priority_level_ref = manifest.get("spec", {}).get("priorityLevelConfiguration", {}).get("name")
                if priority_level_ref == "exempt":
                    logger.warning(
                        "Skipping FlowSchema %s that references exempt PriorityLevelConfiguration",
                        name
                    )
                    return
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
                custom_api.create_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural="mpijobs",
                    body=manifest
                )
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
            elif kind == "ResourceSlice":
                # ResourceSlice is a cluster-scoped resource for Dynamic Resource Allocation (DRA)
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.create_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="resourceslices",
                    body=manifest
                )
            elif kind == "DeviceClass":
                # DeviceClass is a cluster-scoped resource for Dynamic Resource Allocation (DRA)
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.create_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="deviceclasses",
                    body=manifest
                )
            else:
                logger.warning("Unsupported resource kind: %s. Skipping...", kind)

        except client.rest.ApiException as e:
            if e.status == 409:  # Resource already exists, update it instead
                resource_name = manifest.get('metadata', {}).get('name')
                logger.info("Resource %s/%s already exists, updating it",
                           kind, resource_name)
                self._update_single_manifest(manifest, namespace)
            else:
                raise Exception(f"Error creating {kind}: {str(e)}") from e

    def _update_single_manifest(self, manifest, namespace=None):
        """
        Update an existing Kubernetes manifest using the appropriate API client.
        Uses strategic merge patch to update the resource.

        :param manifest: Dictionary representing a Kubernetes resource
        :param namespace: Optional namespace to override the manifest namespace
        :return: None
        """
        try:
            kind = manifest.get("kind")
            # Use provided namespace or fall back to manifest namespace
            namespace = namespace or manifest.get("metadata", {}).get("namespace")
            name = manifest.get("metadata", {}).get("name")
            logger.info("Updating manifest %s %s in namespace %s", kind, name, namespace)

            if kind == "Deployment":
                if namespace:
                    self.app.patch_namespaced_deployment(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("Deployment requires a namespace")
            elif kind == "DaemonSet":
                if namespace:
                    self.app.patch_namespaced_daemon_set(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("DaemonSet requires a namespace")
            elif kind == "StatefulSet":
                if namespace:
                    self.app.patch_namespaced_stateful_set(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("StatefulSet requires a namespace")
            elif kind == "Service":
                if namespace:
                    self.api.patch_namespaced_service(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("Service requires a namespace")
            elif kind == "ConfigMap":
                if namespace:
                    self.api.patch_namespaced_config_map(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("ConfigMap requires a namespace")
            elif kind == "Secret":
                if namespace:
                    self.api.patch_namespaced_secret(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("Secret requires a namespace")
            elif kind == "ServiceAccount":
                if namespace:
                    self.api.patch_namespaced_service_account(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("ServiceAccount requires a namespace")
            elif kind == "ClusterRole":
                # ClusterRole is cluster-scoped
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.patch_cluster_role(name=name, body=manifest)
            elif kind == "ClusterRoleBinding":
                # ClusterRoleBinding is cluster-scoped
                rbac_api = client.RbacAuthorizationV1Api()
                rbac_api.patch_cluster_role_binding(name=name, body=manifest)
            elif kind == "Role":
                if namespace:
                    rbac_api = client.RbacAuthorizationV1Api()
                    rbac_api.patch_namespaced_role(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("Role requires a namespace")
            elif kind == "RoleBinding":
                if namespace:
                    rbac_api = client.RbacAuthorizationV1Api()
                    rbac_api.patch_namespaced_role_binding(name=name, namespace=namespace, body=manifest)
                else:
                    raise ValueError("RoleBinding requires a namespace")
            elif kind == "Namespace":
                # Namespace is cluster-scoped
                self.api.patch_namespace(name=name, body=manifest)
            elif kind == "CustomResourceDefinition":
                # CustomResourceDefinition is cluster-scoped
                apiextensions_api = client.ApiextensionsV1Api()
                apiextensions_api.patch_custom_resource_definition(name=name, body=manifest)
            elif kind == "FlowSchema":
                # FlowSchema is cluster-scoped (part of flow control API)
                # Skip FlowSchemas that reference 'exempt' PriorityLevelConfiguration
                priority_level_ref = manifest.get("spec", {}).get("priorityLevelConfiguration", {}).get("name")
                if priority_level_ref == "exempt":
                    logger.warning(
                        "Skipping update of FlowSchema %s that references exempt PriorityLevelConfiguration",
                        name
                    )
                    return
                flowcontrol_api = client.FlowcontrolApiserverV1Api()
                flowcontrol_api.patch_flow_schema(name=name, body=manifest)
            elif kind == "Stage":
                # Stage is a custom resource from KWOK, handle as custom resource
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.patch_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="stages",
                    name=name,
                    body=manifest
                )
            elif kind == "MPIJob":
                # MPIJob is a custom resource from Kubeflow MPI Operator
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                if namespace:
                    custom_api.patch_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=namespace,
                        plural="mpijobs",
                        name=name,
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
                custom_api.patch_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="nodefeaturerules",
                    name=name,
                    body=manifest
                )
            elif kind == "NicClusterPolicy":
                # NicClusterPolicy is a custom resource from NVIDIA Network Operator
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                # NicClusterPolicy is cluster-scoped
                custom_api.patch_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="nicclusterpolicies",
                    name=name,
                    body=manifest
                )
            elif kind == "ResourceSlice":
                # ResourceSlice is a cluster-scoped resource for Dynamic Resource Allocation (DRA)
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.patch_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="resourceslices",
                    name=name,
                    body=manifest
                )
            elif kind == "DeviceClass":
                # DeviceClass is a cluster-scoped resource for Dynamic Resource Allocation (DRA)
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.patch_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="deviceclasses",
                    name=name,
                    body=manifest
                )
            else:
                logger.warning("Unsupported resource kind for update: %s. Skipping...", kind)

        except Exception as e:
            raise Exception(f"Error updating {kind}: {str(e)}") from e

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
                # Skip FlowSchemas that reference 'exempt' PriorityLevelConfiguration
                # as they are protected and cannot be deleted
                priority_level_ref = manifest.get("spec", {}).get("priorityLevelConfiguration", {}).get("name")
                if priority_level_ref == "exempt":
                    logger.warning(
                        "Skipping deletion of FlowSchema %s that references exempt PriorityLevelConfiguration",
                        resource_name
                    )
                    return
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
            elif kind == "ResourceSlice":
                # ResourceSlice is a cluster-scoped resource for Dynamic Resource Allocation (DRA)
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.delete_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="resourceslices",
                    name=resource_name,
                    body=delete_options
                )
            elif kind == "DeviceClass":
                # DeviceClass is a cluster-scoped resource for Dynamic Resource Allocation (DRA)
                api_version = manifest.get("apiVersion", "")
                group, version = api_version.split("/") if "/" in api_version else ("", api_version)
                custom_api = client.CustomObjectsApi()
                custom_api.delete_cluster_custom_object(
                    group=group,
                    version=version,
                    plural="deviceclasses",
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

    def create_resource_slice(self, template):
        """
        Create a ResourceSlice in the Kubernetes cluster using the provided YAML template.
        ResourceSlice is a cluster-scoped resource for Dynamic Resource Allocation (DRA).

        :param template: YAML template for the ResourceSlice.
        :return: Name of the created ResourceSlice.
        """
        try:
            resource_slice_obj = yaml.safe_load(template)
            if resource_slice_obj["kind"] != "ResourceSlice":
                raise ValueError("The provided YAML template does not define a ResourceSlice resource.")

            api_version = resource_slice_obj.get("apiVersion", "")
            group, version = api_version.split("/") if "/" in api_version else ("", api_version)
            custom_api = client.CustomObjectsApi()

            response = custom_api.create_cluster_custom_object(
                group=group,
                version=version,
                plural="resourceslices",
                body=resource_slice_obj
            )
            return response['metadata']['name']
        except yaml.YAMLError as e:
            raise Exception(f"Error parsing ResourceSlice template: {str(e)}") from e
        except client.rest.ApiException as e:
            if e.status == 409:  # ResourceSlice already exists
                resource_name = resource_slice_obj["metadata"]["name"]
                logger.info(f"ResourceSlice '{resource_name}' already exists.")
                return resource_name
            raise Exception(f"Error creating ResourceSlice: {str(e)}") from e

    def delete_resource_slice(self, resource_slice_name):
        """
        Delete a ResourceSlice by name.
        ResourceSlice is a cluster-scoped resource for Dynamic Resource Allocation (DRA).

        :param resource_slice_name: Name of the ResourceSlice to delete.
        :return: None
        """
        try:
            custom_api = client.CustomObjectsApi()
            delete_options = client.V1DeleteOptions()

            custom_api.delete_cluster_custom_object(
                group="resource.k8s.io",
                version="v1beta2",
                plural="resourceslices",
                name=resource_slice_name,
                body=delete_options
            )
            logger.info(f"ResourceSlice '{resource_slice_name}' deleted successfully.")
        except client.rest.ApiException as e:
            if e.status == 404:  # ResourceSlice not found
                logger.info(f"ResourceSlice '{resource_slice_name}' not found.")
            else:
                raise Exception(f"Error deleting ResourceSlice '{resource_slice_name}': {str(e)}") from e

    def install_gpu_device_plugin(self, namespace="kube-system"):
        """
        Install the NVIDIA GPU device plugin in the specified namespace.
        This will create a DaemonSet that deploys the NVIDIA device plugin on all nodes.
        """
        try:
            # Load the DaemonSet YAML from the official NVIDIA repository
            logger.info("Installing NVIDIA GPU device plugin...")
            self.apply_manifest_from_url(UrlConstants.NVIDIA_GPU_DEVICE_PLUGIN_YAML, namespace=namespace)
            logger.info("NVIDIA GPU device plugin installed successfully.")
        except Exception as e:
            logger.error(f"Error installing NVIDIA GPU device plugin: {str(e)}")
            raise e

    def uninstall_gpu_device_plugin(self, namespace="kube-system"):
        """
        Uninstall the NVIDIA GPU device plugin in the specified namespace.
        """
        try:
            logger.info("Uninstalling NVIDIA GPU device plugin...")
            self.app.delete_namespaced_daemon_set(
                name="nvidia-device-plugin-daemonset", namespace=namespace
            )
            logger.info("NVIDIA GPU device plugin uninstalled successfully.")
        except Exception as e:
            logger.error(f"Error uninstalling NVIDIA GPU device plugin: {str(e)}")
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

    def get_deployment(self, name, namespace):
        """
        Get a deployment by name from the specified namespace.

        :param name: Name of the deployment to retrieve
        :param namespace: Namespace where the deployment is located
        :return: Deployment object if found, None if not found
        """
        try:
            deployment = self.app.read_namespaced_deployment(name=name, namespace=namespace)
            logger.info(f"Retrieved deployment '{name}' from namespace '{namespace}'")
            return deployment
        except client.rest.ApiException as e:
            if e.status == 404:
                logger.info(f"Deployment '{name}' not found in namespace '{namespace}'")
                return None
            logger.error(f"Error getting deployment '{name}' from namespace '{namespace}': {str(e)}")
            raise Exception(f"Error getting deployment '{name}' from namespace '{namespace}': {str(e)}") from e
        except Exception as e:
            logger.error(f"Unexpected error getting deployment '{name}' from namespace '{namespace}': {str(e)}")
            raise Exception(f"Unexpected error getting deployment '{name}' from namespace '{namespace}': {str(e)}") from e

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

    def get_config_map(self, name, namespace):
        """
        Get a ConfigMap by name from the specified namespace.

        :param name: Name of the ConfigMap to retrieve
        :param namespace: Namespace where the ConfigMap is located
        :return: ConfigMap object if found, None if not found
        """
        try:
            config_map = self.api.read_namespaced_config_map(name=name, namespace=namespace)
            return config_map
        except client.rest.ApiException as e:
            if e.status == 404:
                logger.info(f"ConfigMap '{name}' not found in namespace '{namespace}'")
                return None
            logger.error(f"Error getting ConfigMap '{name}' from namespace '{namespace}': {str(e)}")
            raise Exception(f"Error getting ConfigMap '{name}' from namespace '{namespace}': {str(e)}") from e
        except Exception as e:
            logger.error(f"Unexpected error getting ConfigMap '{name}' from namespace '{namespace}': {str(e)}")
            raise Exception(f"Unexpected error getting ConfigMap '{name}' from namespace '{namespace}': {str(e)}") from e

    def patch_deployment_resources(self, name, namespace, container_name, cpu_limit=None, memory_limit=None, cpu_request=None, memory_request=None):
        """
        Patch a deployment's container resource limits and requests.

        :param name: Name of the deployment to patch
        :param namespace: Namespace of the deployment
        :param container_name: Name of the container to patch
        :param cpu_limit: CPU limit (e.g., "8", "500m")
        :param memory_limit: Memory limit (e.g., "4Gi", "512Mi")
        :param cpu_request: CPU request (e.g., "100m", "1")
        :param memory_request: Memory request (e.g., "128Mi", "1Gi")
        :return: None
        """
        try:
            # Get the current deployment
            deployment = self.get_deployment(name, namespace)
            if not deployment:
                raise Exception(f"Deployment '{name}' not found in namespace '{namespace}'")

            # Find the container to patch
            containers = deployment.spec.template.spec.containers
            target_container_index = None
            for i, container in enumerate(containers):
                if container.name == container_name:
                    target_container_index = i
                    break

            if target_container_index is None:
                raise Exception(f"Container '{container_name}' not found in deployment '{name}'")

            # Build resource patch
            resources = {}
            if cpu_limit or memory_limit:
                limits = {}
                if cpu_limit:
                    limits["cpu"] = cpu_limit
                if memory_limit:
                    limits["memory"] = memory_limit
                resources["limits"] = limits

            if cpu_request or memory_request:
                reqs = {}
                if cpu_request:
                    reqs["cpu"] = cpu_request
                if memory_request:
                    reqs["memory"] = memory_request
                resources["requests"] = reqs

            if not resources:
                logger.warning("No resource limits or requests specified for patching")
                return

            # Construct the patch body
            patch_body = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": container_name,
                                    "resources": resources
                                }
                            ]
                        }
                    }
                }
            }

            logger.info(f"Patching deployment '{name}' container '{container_name}' resources in namespace '{namespace}'")
            logger.info(f"Resource patch: {resources}")

            # Apply the patch using strategic merge
            self.app.patch_namespaced_deployment(
                name=name,
                namespace=namespace,
                body=patch_body
            )
            logger.info(f"Successfully patched deployment '{name}' container '{container_name}' resources")

        except Exception as e:
            logger.error(f"Error patching deployment '{name}' container '{container_name}' resources: {str(e)}")
            raise Exception(f"Error patching deployment '{name}' container '{container_name}' resources: {str(e)}") from e
