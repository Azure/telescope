"""KWOK (Kubernetes WithOut Kubelet) - Virtual Node/Pod Simulator."""
import argparse
import time
import math
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass

import json

import requests
import yaml
from kubernetes import client

from clients.kubernetes_client import KubernetesClient
from utils.logger_config import setup_logging
from utils.retries import execute_with_retries


NODE_CREATE_INTERVAL_SECONDS = 0.05
CONTROLLER_READY_TIMEOUT_SECONDS = 900
CONTROLLER_READY_POLL_INTERVAL_SECONDS = 5
NODE_LEASE_PARALLELISM = 200
POD_PLAY_STAGE_PARALLELISM = 100
NODE_PLAY_STAGE_PARALLELISM = 200
DEFAULT_NODE_SELECTOR = ""
DEFAULT_TOLERATION = "kwok=true"
DEFAULT_CIDR = "10.0.0.0/8" # About 17 million addresses
DEFAULT_NODE_IP = "10.0.0.1"
DEFAULT_KUBE_CONNECTION_QPS = None
DEFAULT_KUBE_CONNECTION_BURST = None


@dataclass
class KWOK(ABC):
    """Abstract base class for KWOK (Kubernetes WithOut Kubelet) components."""
    kwok_repo: str = "kubernetes-sigs/kwok"
    kwok_release: str = None
    enable_metrics: bool = False
    kwok_config_path: str = "kwok/config/kwok-config.yaml"
    node_selector: str = DEFAULT_NODE_SELECTOR
    toleration: str = DEFAULT_TOLERATION
    node_lease_parallelism: int = NODE_LEASE_PARALLELISM
    pod_play_stage_parallelism: int = POD_PLAY_STAGE_PARALLELISM
    node_play_stage_parallelism: int = NODE_PLAY_STAGE_PARALLELISM
    cidr: str = DEFAULT_CIDR
    node_ip: str = DEFAULT_NODE_IP
    node_lease_duration_seconds: int = 40
    kube_connection_qps: float = DEFAULT_KUBE_CONNECTION_QPS
    kube_connection_burst: int = DEFAULT_KUBE_CONNECTION_BURST
    k8s_client: KubernetesClient = KubernetesClient()

    @staticmethod
    def _controller_name(controller_index):
        """Build a deterministic controller deployment name."""
        return f"kwok-controller-{controller_index}"

    def fetch_latest_release(self):
        """Fetch the latest KWOK release version from GitHub."""
        response = requests.get(
            f"https://api.github.com/repos/{self.kwok_repo}/releases/latest", timeout=10
        )
        response.raise_for_status()
        return response.json().get("tag_name")

    def _bootstrap_kwok(self, kwok_release, enable_metrics):
        """Apply the shared KWOK bootstrap manifests and replace the configmap.

        Returns the upstream kwok-controller Deployment as a V1Deployment
        for the caller to use as a template for per-shard controllers.
        """
        kwok_yaml_url = (f"https://github.com/{self.kwok_repo}/releases/"
                         f"download/{kwok_release}/kwok.yaml")
        stage_fast_yaml_url = (f"https://github.com/{self.kwok_repo}/releases/"
                              f"download/{kwok_release}/stage-fast.yaml")

        # Fetch kwok.yaml and apply everything except the Deployment.
        response = execute_with_retries(requests.get, kwok_yaml_url, timeout=30)
        response.raise_for_status()
        controller_manifest = None
        for doc in yaml.safe_load_all(response.text):
            if not doc:
                continue
            if doc.get("kind") == "Deployment":
                controller_manifest = doc
            else:
                execute_with_retries(
                    self.k8s_client.apply_manifest_from_file,
                    manifest_dict=doc,
                )

        if controller_manifest is None:
            raise RuntimeError("Controller Deployment not found in kwok.yaml.")

        controller_deployment = client.ApiClient().deserialize(
            type("Resp", (), {"data": json.dumps(controller_manifest)})(),
            "V1Deployment",
        )

        execute_with_retries(
            self.k8s_client.apply_manifest_from_url,
            stage_fast_yaml_url
        )
        self._replace_config_map()
        if enable_metrics:
            metrics_usage_url = (f"https://github.com/{self.kwok_repo}/releases/"
                               f"download/{kwok_release}/metrics-usage.yaml")
            execute_with_retries(
                self.k8s_client.apply_manifest_from_url,
                metrics_usage_url
            )

        return controller_deployment

    @staticmethod
    def _upsert_container_arg(container, arg_name, arg_value):
        """Set or append a controller arg in --name=value form."""
        args = list(container.args or [])
        rendered_arg = f"{arg_name}={arg_value}"

        for index, existing_arg in enumerate(args):
            if existing_arg.startswith(f"{arg_name}="):
                args[index] = rendered_arg
                container.args = args
                return

        args.append(rendered_arg)
        container.args = args

    @staticmethod
    def _upsert_env_var(container, env_var):
        """Set or append a controller env var by name."""
        env = list(container.env or [])

        for index, existing_env_var in enumerate(env):
            if existing_env_var.name == env_var.name:
                env[index] = env_var
                container.env = env
                return

        env.append(env_var)
        container.env = env

    @staticmethod
    def _parse_key_value(setting, field_name):
        """Parse a key=value string into its components."""
        if setting.count("=") != 1:
            raise ValueError(f"Invalid {field_name}={setting!r}. Expected format 'key=value'.")

        key, value = setting.split("=", 1)
        if not key or not value:
            raise ValueError(f"Invalid {field_name}={setting!r}. Expected format 'key=value'.")

        return key, value


    def _build_controller_deployment(self, base_deployment, controller_index):
        """Clone the upstream controller deployment and patch shard-specific fields."""
        deployment = deepcopy(base_deployment)
        deployment_name = self._controller_name(controller_index)
        controller_selector = f"kwok-controller-group={controller_index}"

        deployment.metadata.name = deployment_name
        deployment.metadata.resource_version = None
        deployment.metadata.uid = None
        deployment.metadata.creation_timestamp = None
        deployment.metadata.generation = None
        deployment.metadata.managed_fields = None

        deployment_labels = dict(deployment.metadata.labels or {})
        deployment_labels["app"] = deployment_name
        deployment.metadata.labels = deployment_labels

        deployment.spec.replicas = 1
        match_labels = dict(deployment.spec.selector.match_labels or {})
        match_labels["app"] = deployment_name
        deployment.spec.selector.match_labels = match_labels

        template_metadata = deployment.spec.template.metadata or client.V1ObjectMeta()
        template_labels = dict(template_metadata.labels or {})
        template_labels.update(match_labels)
        template_metadata.labels = template_labels
        deployment.spec.template.metadata = template_metadata

        controller_container = deployment.spec.template.spec.containers[0]
        self._upsert_container_arg(controller_container, "--node-ip", "$(POD_IP)")
        self._upsert_container_arg(controller_container, "--manage-all-nodes", "false")
        self._upsert_container_arg(
            controller_container,
            "--manage-nodes-with-label-selector",
            controller_selector,
        )
        self._upsert_container_arg(
            controller_container,
            "--manage-nodes-with-annotation-selector",
            "kwok.x-k8s.io/node=fake",
        )
        self._upsert_container_arg(
            controller_container,
            "--node-lease-duration-seconds",
            str(self.node_lease_duration_seconds),
        )
        self._upsert_env_var(
            controller_container,
            client.V1EnvVar(
                name="POD_IP",
                value_from=client.V1EnvVarSource(
                    field_ref=client.V1ObjectFieldSelector(field_path="status.podIP")
                ),
            ),
        )
        self._upsert_env_var(
            controller_container,
            client.V1EnvVar(name="KUBE_API_QPS", value="500"),
        )
        self._upsert_env_var(
            controller_container,
            client.V1EnvVar(name="KUBE_API_BURST", value="1000"),
        )
        controller_container.resources = client.V1ResourceRequirements(
            limits={"cpu": "3", "memory": "10Gi"},
            requests={"cpu": "2", "memory": "5Gi"},
        )

        pod_spec = deployment.spec.template.spec
        selector_setting = (self.node_selector or "").strip()
        if selector_setting:
            node_selector_key, node_selector_value = self._parse_key_value(
                selector_setting,
                "node_selector",
            )
        toleration_key, toleration_value = self._parse_key_value(
            self.toleration,
            "toleration",
        )
        if selector_setting:
            node_selector = dict(pod_spec.node_selector or {})
            node_selector[node_selector_key] = node_selector_value
            pod_spec.node_selector = node_selector
        pod_spec.tolerations = [
            client.V1Toleration(
                key=toleration_key,
                value=toleration_value,
                effect="NoSchedule",
            )
        ]

        return deployment

    def _create_controller_deployment(self, controller_index, base_deployment):
        """Create a kwok-controller deployment scoped to a controller shard."""
        deployment = self._build_controller_deployment(base_deployment, controller_index)
        deployment_name = deployment.metadata.name
        manifest_dict = client.ApiClient().sanitize_for_serialization(deployment)
        manifest_dict["apiVersion"] = manifest_dict.get("apiVersion", "apps/v1")
        manifest_dict["kind"] = manifest_dict.get("kind", "Deployment")

        print(f"Creating Deployment '{deployment_name}'")
        execute_with_retries(
            self.k8s_client.apply_manifest_from_file,
            manifest_dict=manifest_dict,
        )

    def _replace_config_map(self):
        """Replace KWOK configuration configmap."""
        replacements = {
            "node_lease_parallelism": str(self.node_lease_parallelism),
            "pod_play_stage_parallelism": str(self.pod_play_stage_parallelism),
            "node_play_stage_parallelism": str(self.node_play_stage_parallelism),
            "cidr": self.cidr,
            "node_lease_duration_seconds": str(self.node_lease_duration_seconds),
        }
        rendered = self.k8s_client.create_template(
            self.kwok_config_path, replacements)
        rendered_manifest = yaml.safe_load(rendered)

        # Add optional fields only when explicitly set
        kwok_yaml = yaml.safe_load(rendered_manifest["data"]["kwok.yaml"])
        if self.node_ip is not None:
            kwok_yaml["options"]["nodeIP"] = self.node_ip
        if self.kube_connection_qps is not None:
            kwok_yaml["options"]["kubeConnectionQPS"] = self.kube_connection_qps
        if self.kube_connection_burst is not None:
            kwok_yaml["options"]["kubeConnectionBurst"] = self.kube_connection_burst
        rendered_manifest["data"]["kwok.yaml"] = yaml.dump(kwok_yaml, default_flow_style=False)

        # Delete the configmap if it exists, then verify deletion
        execute_with_retries(
            self.k8s_client.delete_manifest_from_file,
            self.kwok_config_path,
        )
        execute_with_retries(self._assert_config_map_absent)
        # Re-apply the configmap manifest with rendered values
        execute_with_retries(
            self.k8s_client.apply_manifest_from_file,
            manifest_dict=rendered_manifest
        )

    def _assert_config_map_absent(self):
        """Assert that the KWOK configmap is absent from kube-system namespace."""
        config_map = self.k8s_client.get_config_map("kwok", "kube-system")
        if config_map:
            raise RuntimeError("KWOK configmap still exists in kube-system namespace.")

    @abstractmethod
    def create(self):
        """Create KWOK resources."""

    @abstractmethod
    def validate(self):
        """Validate KWOK resources are working correctly."""

    @abstractmethod
    def tear_down(self):
        """Clean up and remove KWOK resources."""


@dataclass
class Node(KWOK):
    """KWOK Node implementation for creating and managing virtual Kubernetes nodes."""
    node_manifest_path: str = "kwok/config/kwok-node.yaml"
    node_count: int = 1
    node_cpu: str = "32"
    node_memory: str = "256Gi"
    node_pods: str = "110"
    node_gpu: str = "0"
    enable_dra: bool = False
    nodes_per_controller: int = 100

    def _controller_count(self):
        """Calculate how many controller deployments are needed."""
        if self.nodes_per_controller < 1:
            raise ValueError(
                f"Invalid nodes_per_controller={self.nodes_per_controller}. "
                "nodes_per_controller must be at least 1."
            )
        return max(1, (self.node_count + self.nodes_per_controller - 1) // self.nodes_per_controller)

    def create(self):
        try:
            self.kwok_release = self.kwok_release or self.fetch_latest_release()
            print(f"Using KWOK_RELEASE={self.kwok_release}")

            controller_deployment_base = self._bootstrap_kwok(self.kwok_release, self.enable_metrics)

            controller_count = self._controller_count()
            print(f"Using {controller_count} controller(s) for {self.node_count} nodes, "
                  f"{self.nodes_per_controller} nodes each")
            for controller_index in range(controller_count):
                self._create_controller_deployment(controller_index, controller_deployment_base)
            self._wait_for_controllers_ready()

            # Apply DRA manifests once if enabled
            if self.enable_dra:
                execute_with_retries(
                    self.k8s_client.apply_manifest_from_file,
                    "kwok/config/device-class.yaml"
                )

            for i in range(self.node_count):
                controller_index = i // self.nodes_per_controller
                node_name = f"kwok-node-{i}"
                replacements = {
                    "node_name": node_name,
                    "node_ip": self._generate_node_ip(i),
                    "node_cpu": self.node_cpu,
                    "node_memory": self.node_memory,
                    "node_pods": self.node_pods,
                    "node_gpu": self.node_gpu,
                    "controller_group": str(controller_index),
                }
                kwok_template = self.k8s_client.create_template(
                    self.node_manifest_path, replacements
                )

                execute_with_retries(
                    self.k8s_client.create_node,
                    kwok_template,
                )

                if NODE_CREATE_INTERVAL_SECONDS > 0 and i < self.node_count - 1:
                    time.sleep(NODE_CREATE_INTERVAL_SECONDS)

                # Apply resource slice for each node if DRA is enabled
                if self.enable_dra:
                    resource_slice_name = f"kwok-resource-slice-{i}"
                    print(f"Creating resource slice {resource_slice_name} for node {node_name}")

                    replacements = {
                        "resource_slice_name": resource_slice_name,
                        "node_name": node_name
                    }

                    resource_slice_template = self.k8s_client.create_template(
                        "kwok/config/resource-slice.yaml", replacements
                    )

                    execute_with_retries(
                        self.k8s_client.create_resource_slice,
                        resource_slice_template
                    )

            print(f"Successfully created {self.node_count} virtual nodes.")
        except Exception as e:
            raise RuntimeError(f"Failed to create nodes: {e}") from e

    def _wait_for_controllers_ready(self):
        """Wait until expected kwok-controller deployment(s) are available."""
        controller_names = [self._controller_name(i) for i in range(self._controller_count())]

        deadline = time.time() + CONTROLLER_READY_TIMEOUT_SECONDS
        last_not_ready = []

        while time.time() < deadline:
            not_ready = []
            for name in controller_names:
                deployment = self.k8s_client.get_deployment(name, "kube-system")
                if not deployment:
                    not_ready.append(f"{name}:not-found")
                    continue

                available_replicas = deployment.status.available_replicas or 0
                if available_replicas < 1:
                    not_ready.append(f"{name}:available={available_replicas}")

            if not not_ready:
                print(f"All {len(controller_names)} KWOK controller deployment(s) are ready.")
                return

            if not_ready != last_not_ready:
                print(f"Waiting for KWOK controller readiness: {', '.join(not_ready)}")
                last_not_ready = not_ready

            time.sleep(CONTROLLER_READY_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            "Timed out waiting for KWOK controller readiness. "
            f"Last status: {', '.join(last_not_ready) if last_not_ready else 'unknown'}"
        )

    def validate(self, node_validate_success_threshold: float):
        execute_with_retries(
            self._validate_config_map,
        )

        for controller_index in range(self._controller_count()):
            execute_with_retries(
                self._validate_kwok_controller, controller_index
            )

        execute_with_retries(
            self._validate_kwok_nodes, node_validate_success_threshold
        )

    def _validate_config_map(self):
        """Validate that kwok configmap exists"""
        cm_name = "kwok"
        config_map = self.k8s_client.get_config_map(
            cm_name,
            "kube-system"
        )
        if not config_map:
            raise RuntimeError(f"{cm_name} config map not found in kube-system namespace")

    def _validate_kwok_controller(self, controller_index):
        """Validate that kwok-controller deployment is running with 1 available replica."""
        deploy_name = self._controller_name(controller_index)

        deployment = self.k8s_client.get_deployment(
            deploy_name,
            "kube-system"
        )

        if not deployment:
            raise RuntimeError(f"{deploy_name} deployment not found in kube-system namespace")

        available_replicas = deployment.status.available_replicas or 0
        if available_replicas != 1:
            raise RuntimeError(
                f"{deploy_name} deployment validation failed: "
                f"Expected 1 available replica, but found {available_replicas}"
            )

        print(f"{deploy_name} deployment is running with 1 available replica.")


    def _validate_kwok_nodes(self, success_threshold: float):
        """Validate KWOK nodes.

        Args:
            success_threshold: Fraction of nodes that must pass validation (0.0–1.0).
                               Defaults to 1.0 (100%, all nodes must pass).
        """
        if not 0.0 < success_threshold <= 1.0:
            raise ValueError(
                f"success_threshold must be between 0 (exclusive) and 1.0 (inclusive), "
                f"got {success_threshold}"
            )

        ready_nodes = self.k8s_client.get_nodes()

        kwok_nodes = [
            node
            for node in ready_nodes
            if node.metadata.annotations
            and node.metadata.annotations.get("kwok.x-k8s.io/node") == "fake"
        ]

        if len(kwok_nodes) < self.node_count:
            raise RuntimeError(
                f"Validation failed: Expected at least {self.node_count} KWOK nodes, "
                f"but found {len(kwok_nodes)}."
            )

        required_count = math.ceil(self.node_count * success_threshold)
        failure_count = 0

        for node in kwok_nodes:
            try:
                self._validate_node_status(node)
                self._validate_node_resources(node)
                self._validate_node_schedulable(node)
            except Exception as e:
                print(f"Node {node.metadata.name} failed validation: {e}")
                failure_count += 1

        passed_count = len(kwok_nodes) - failure_count
        if passed_count < required_count:
            raise RuntimeError(
                f"Validation failed: {passed_count}/{len(kwok_nodes)} nodes passed, "
                f"but {required_count} required ({success_threshold:.0%} of {self.node_count})."
            )

        print(
            f"Validation completed: {passed_count}/{len(kwok_nodes)} KWOK nodes passed "
            f"(threshold: {success_threshold:.0%})."
        )


    def _generate_node_ip(self, index, base_ip=(10, 0, 0, 10)):
        """Generate a valid IPv4 address, rolling over octets as needed."""
        a, b, c, d = base_ip
        total = d + index
        c += total // 256
        d = total % 256
        b += c // 256
        c = c % 256
        a += b // 256
        b = b % 256
        # Optionally, add a check to avoid exceeding 255.255.255.255
        if any(x > 255 for x in (a, b, c, d)):
            raise ValueError("Exceeded valid IPv4 address range.")
        return f"{a}.{b}.{c}.{d}"

    def tear_down(self):
        for i in range(self.node_count):
            node_name = f"kwok-node-{i}"
            print(f"Deleting node: {node_name}")
            execute_with_retries(
                self.k8s_client.delete_node,
                node_name
            )

            # Delete resource slice for each node if DRA was enabled
            if self.enable_dra:
                resource_slice_name = f"kwok-resource-slice-{i}"
                print(f"Deleting resource slice: {resource_slice_name}")
                try:
                    execute_with_retries(
                        self.k8s_client.delete_resource_slice,
                        resource_slice_name
                    )
                except Exception as e:
                    print(f"Warning: Could not delete resource slice {resource_slice_name}: {e}")

        print(f"Successfully deleted {self.node_count} nodes.")

        for controller_index in range(self._controller_count()):
            deploy_name = self._controller_name(controller_index)
            print(f"Deleting controller deployment: {deploy_name}")
            try:
                self.k8s_client.get_app_client().delete_namespaced_deployment(
                    name=deploy_name,
                    namespace="kube-system",
                    body=client.V1DeleteOptions(propagation_policy="Foreground"),
                )
            except Exception as e:
                print(f"Warning: Could not delete deployment {deploy_name}: {e}")
        print(f"Successfully deleted {self._controller_count()} controller deployment(s).")

    def _validate_node_status(self, node):
        conditions = (
            node.status.conditions if node.status and node.status.conditions else []
        )
        ready_condition = next((c for c in conditions if c.type == "Ready"), None)
        if ready_condition and ready_condition.status == "True":
            print(f"Node {node.metadata.name} is Ready.")
        else:
            raise RuntimeError(
                f"Node {node.metadata.name} is NOT Ready. "
                f"Condition: {ready_condition.status if ready_condition else 'No condition found'}"
            )

    def _validate_node_schedulable(self, node):
        if node.spec.unschedulable:
            raise RuntimeError(
                f"Node {node.metadata.name} is unschedulable. "
                "This may affect scheduling of pods on this node."
            )
        print(f"Node {node.metadata.name} is schedulable.")

    def _validate_node_resources(self, node):
        allocatable = (
            node.status.allocatable if node.status and node.status.allocatable else {}
        )
        capacity = node.status.capacity if node.status and node.status.capacity else {}

        if not allocatable or not capacity:
            raise RuntimeError(
                f"Node {node.metadata.name} is missing resource information "
                f"(allocatable or capacity)."
            )
        print(f"Node {node.metadata.name} Allocatable: {allocatable}")
        print(f"Node {node.metadata.name} Capacity: {capacity}")


def main():
    """Main function to handle command-line arguments and execute KWOK operations."""
    parser = argparse.ArgumentParser(
        description="KWOK: Kubernetes WithOut Kubelet - Virtual Node/Pod Simulator"
    )
    parser.add_argument(
        "--node-count",
        type=int,
        default=1,
        help="Number of virtual nodes to create",
    )
    parser.add_argument(
        "--node-manifest-path",
        type=str,
        default="kwok/config/kwok-node.yaml",
        help="Path to the node manifest YAML template.",
    )
    parser.add_argument(
        "--node-cpu",
        type=str,
        default="32",
        help="CPU capacity and allocatable for each node (default: 32).",
    )
    parser.add_argument(
        "--node-memory",
        type=str,
        default="256Gi",
        help="Memory capacity and allocatable for each node (default: 256Gi).",
    )
    parser.add_argument(
        "--node-pods",
        type=str,
        default="110",
        help="Pod capacity and allocatable for each node (default: 110).",
    )
    parser.add_argument(
        "--node-gpu",
        type=str,
        default="0",
        help="GPU (nvidia.com/gpu) capacity and allocatable for each node (default: 0).",
    )
    parser.add_argument(
        "--kwok-release",
        type=str,
        default="",
        help="KWOK release version to use (default: latest).",
    )
    parser.add_argument(
        "--enable-metrics",
        action="store_true",
        help="Enable metrics simulation by applying metrics-usage.yaml.",
    )
    parser.add_argument(
        "--enable-dra",
        action="store_true",
        help="Enable Dynamic Resource Allocation (DRA).",
    )
    parser.add_argument(
        "--nodes-per-controller",
        type=int,
        default=100,
        help="Maximum number of virtual nodes managed per controller deployment (default: 100).",
    )
    parser.add_argument(
        "--node-selector",
        type=str,
        default=DEFAULT_NODE_SELECTOR,
        help="Optional node selector for controller pod affinity in key=value form (default: empty).",
    )
    parser.add_argument(
        "--node-lease-duration-seconds",
        type=int,
        default=40,
        help="KWOK nodeLeaseDurationSeconds (default: 40).",
    )
    parser.add_argument(
        "--pod-play-stage-parallelism",
        type=int,
        default=POD_PLAY_STAGE_PARALLELISM,
        help=f"KWOK podPlayStageParallelism (default: {POD_PLAY_STAGE_PARALLELISM}).",
    )
    parser.add_argument(
        "--validate-success-threshold",
        type=float,
        default=1.0,
        help="Fraction of nodes (0.0–1.0] that must pass validation (default: 1.0).",
    )
    parser.add_argument(
        "--action",
        choices=["create", "validate", "tear_down"],
        required=True,
        help="Action to perform: create, validate, or tear_down.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Logging verbosity for KWOK and its dependencies (default: INFO).",
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    node = Node(
        node_manifest_path=args.node_manifest_path,
        node_count=args.node_count,
        node_cpu=args.node_cpu,
        node_memory=args.node_memory,
        node_pods=args.node_pods,
        node_gpu=args.node_gpu,
        kwok_release=args.kwok_release,
        enable_metrics=args.enable_metrics,
        enable_dra=args.enable_dra,
        nodes_per_controller=args.nodes_per_controller,
        node_selector=args.node_selector,
        node_lease_duration_seconds=args.node_lease_duration_seconds,
        pod_play_stage_parallelism=args.pod_play_stage_parallelism
    )
    if args.action == "create":
        node.create()
    elif args.action == "validate":
        node.validate(node_validate_success_threshold=args.validate_success_threshold)
    elif args.action == "tear_down":
        node.tear_down()


if __name__ == "__main__":
    main()
