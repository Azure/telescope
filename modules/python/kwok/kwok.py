"""KWOK (Kubernetes WithOut Kubelet) - Virtual Node/Pod Simulator."""
import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests
import yaml
import yaml

from clients.kubernetes_client import KubernetesClient
from utils.retries import execute_with_retries


@dataclass
class KWOK(ABC):
    """Abstract base class for KWOK (Kubernetes WithOut Kubelet) components."""
    kwok_repo: str = "kubernetes-sigs/kwok"
    kwok_release: str = None
    enable_metrics: bool = False
    kwok_config_path: str = "kwok/config/kwok-config.yaml"
    controller_deploy_template: str = "kwok/config/kwok-controller-group-deploy.yaml"
    node_selector_key: str = "kwok"
    node_selector_value: str = "true"
    toleration_key: str = "kwok"
    toleration_value: str = "true"
    node_lease_parallelism: int = 4
    pod_play_stage_parallelism: int = 64
    node_play_stage_parallelism: int = 4
    cidr: str = "10.0.0.1/24"
    node_ip: str = None
    node_lease_duration_seconds: int = 40
    kube_connection_qps: float = None
    kube_connection_burst: int = None
    k8s_client: KubernetesClient = KubernetesClient()

    def fetch_latest_release(self):
        """Fetch the latest KWOK release version from GitHub."""
        response = requests.get(
            f"https://api.github.com/repos/{self.kwok_repo}/releases/latest", timeout=10
        )
        response.raise_for_status()
        return response.json().get("tag_name")

    # Setting up the KWOK environment and simulating the pod/node emulation
    # If `enable_metrics` is True, it also applies an additional metrics usage YAML file
    # to simulate resource usage for nodes, pods, and containers.
    def apply_kwok_manifests(self, kwok_release, enable_metrics):
        """Apply KWOK manifests to set up the environment and enable metrics if requested."""
        kwok_yaml_url = (f"https://github.com/{self.kwok_repo}/releases/"
                         f"download/{kwok_release}/kwok.yaml")
        stage_fast_yaml_url = (f"https://github.com/{self.kwok_repo}/releases/"
                              f"download/{kwok_release}/stage-fast.yaml")
        execute_with_retries(
            self.k8s_client.apply_manifest_from_url,
            kwok_yaml_url
        )
        execute_with_retries(
            self.k8s_client.apply_manifest_from_url,
            stage_fast_yaml_url
        )
        self._replace_config_map()
        self._patch_deployment()
        if enable_metrics:
            metrics_usage_url = (f"https://github.com/{self.kwok_repo}/releases/"
                               f"download/{kwok_release}/metrics-usage.yaml")
            execute_with_retries(
                self.k8s_client.apply_manifest_from_url,
                metrics_usage_url
            )

    def setup_kwok_for_groups(self, kwok_release, enable_metrics):
        """One-time setup: apply CRDs/stages, replace configmap, extract image, delete upstream controller."""
        kwok_yaml_url = (f"https://github.com/{self.kwok_repo}/releases/"
                         f"download/{kwok_release}/kwok.yaml")
        stage_fast_yaml_url = (f"https://github.com/{self.kwok_repo}/releases/"
                              f"download/{kwok_release}/stage-fast.yaml")
        # Apply upstream CRDs and stages (idempotent)
        execute_with_retries(
            self.k8s_client.apply_manifest_from_url,
            kwok_yaml_url
        )
        execute_with_retries(
            self.k8s_client.apply_manifest_from_url,
            stage_fast_yaml_url
        )

        # Replace the upstream configmap with our custom config
        self._replace_config_map()

        # Extract image from upstream controller before deleting it
        base_deployment = self.k8s_client.get_deployment("kwok-controller", "kube-system")
        if not base_deployment:
            raise RuntimeError("Upstream kwok-controller deployment not found. "
                             "Ensure kwok.yaml was applied first.")
        controller_image = base_deployment.spec.template.spec.containers[0].image

        # Delete the upstream controller — our per-group deployments take over
        print("Deleting upstream kwok-controller deployment")
        self.k8s_client.get_app_client().delete_namespaced_deployment(
            name="kwok-controller",
            namespace="kube-system",
        )

        if enable_metrics:
            metrics_usage_url = (f"https://github.com/{self.kwok_repo}/releases/"
                               f"download/{kwok_release}/metrics-usage.yaml")
            execute_with_retries(
                self.k8s_client.apply_manifest_from_url,
                metrics_usage_url
            )

        return controller_image

    def _create_group_deployment(self, controller_index, controller_image):
        """Create a per-group kwok-controller deployment from template."""
        group_label = f"kwok-controller-group={controller_index}"
        replacements = {
            "controller_index": str(controller_index),
            "controller_image": controller_image,
            "node_label_selector": group_label,
            "node_selector_key": self.node_selector_key,
            "node_selector_value": self.node_selector_value,
            "toleration_key": self.toleration_key,
            "toleration_value": self.toleration_value,
        }
        rendered = self.k8s_client.create_template(
            self.controller_deploy_template, replacements)

        print(f"Creating Deployment 'kwok-controller-{controller_index}' "
              f"with --manage-nodes-with-label-selector={group_label}")
        execute_with_retries(
            self.k8s_client.apply_manifest_from_file,
            manifest_dict=yaml.safe_load(rendered)
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

    def _patch_deployment(self):
        """Patch kwok-controller deployment with node selector and toleration"""
        node_selector = {self.node_selector_key: self.node_selector_value}
        tolerations = [{
            "key": self.toleration_key,
            "value": self.toleration_value,
            "effect": "NoSchedule"
        }]
        execute_with_retries(
            self.k8s_client.patch_deployment,
            "kwok-controller",
            "kube-system",
            node_selector,
            tolerations
        )

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
    controller_manifest_path: str = "kwok/config/kwok-controller.yaml"
    node_count: int = 1
    node_cpu: str = "32"
    node_memory: str = "256Gi"
    node_pods: str = "110"
    node_gpu: str = "0"
    enable_dra: bool = False
    group: bool = False
    nodes_per_controller: int = 100

    def _num_groups(self):
        """Calculate the number of controller groups needed."""
        return (self.node_count + self.nodes_per_controller - 1) // self.nodes_per_controller

    def create(self):
        try:
            self.kwok_release = self.kwok_release or self.fetch_latest_release()
            print(f"Using KWOK_RELEASE={self.kwok_release}")

            if self.group:
                num_groups = self._num_groups()
                print(f"Grouped mode: {self.node_count} nodes across "
                      f"{num_groups} controller(s), {self.nodes_per_controller} nodes each")
                # One-time setup: CRDs, configmap, extract image, delete upstream
                controller_image = self.setup_kwok_for_groups(
                    self.kwok_release, self.enable_metrics)
                # Create per-group deployments
                for g in range(num_groups):
                    self._create_group_deployment(g, controller_image)
            else:
                # Legacy single-controller mode
                self.apply_kwok_manifests(self.kwok_release, self.enable_metrics)

            # Apply DRA manifests once if enabled
            if self.enable_dra:
                execute_with_retries(
                    self.k8s_client.apply_manifest_from_file,
                    "kwok/config/device-class.yaml"
                )

            for i in range(self.node_count):
                # In grouped mode, figure out which group this node belongs to
                group_index = i // self.nodes_per_controller if self.group else -1
                node_name = f"kwok-node-{i}"
                replacements = {
                    "node_name": node_name,
                    "node_ip": self._generate_node_ip(i),
                    "node_cpu": self.node_cpu,
                    "node_memory": self.node_memory,
                    "node_pods": self.node_pods,
                    "node_gpu": self.node_gpu
                }
                kwok_template = self.k8s_client.create_template(
                    self.node_manifest_path, replacements
                )

                # Add controller group label if using grouped mode
                if self.group:
                    kwok_template = self._add_group_label(kwok_template, group_index)

                execute_with_retries(
                    self.k8s_client.create_node,
                    kwok_template,
                )

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

    def _add_group_label(self, template_str, group_index):
        """Add kwok-controller-group label to a node template."""
        node_obj = yaml.safe_load(template_str)
        if "labels" not in node_obj.get("metadata", {}):
            node_obj["metadata"]["labels"] = {}
        node_obj["metadata"]["labels"]["kwok-controller-group"] = str(group_index)
        return yaml.dump(node_obj, default_flow_style=False)

    def validate(self):
        execute_with_retries(
            self._validate_config_map,
        )

        if self.group:
            for g in range(self._num_groups()):
                execute_with_retries(
                    self._validate_kwok_controller, g
                )
        else:
            execute_with_retries(
                self._validate_kwok_controller,
            )

        execute_with_retries(
            self._validate_kwok_nodes
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

    def _validate_kwok_controller(self, group_index=None):
        """Validate that kwok-controller deployment is running with 1 available replica."""
        if group_index is not None:
            deploy_name = f"kwok-controller-{group_index}"
        else:
            deploy_name = "kwok-controller"

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


    def _validate_kwok_nodes(self):
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

        for node in kwok_nodes:
            try:
                self._validate_node_status(node)
                self._validate_node_resources(node)
                self._validate_node_schedulable(node)
            except Exception as e:
                raise RuntimeError(
                    f"Validation failed for node {node.metadata.name}: {e}"
                ) from e

        print(f"Validation completed for {self.node_count} KWOK nodes.")


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

    def create_partitioned_controllers(self):
        """Create one KWOK controller Deployment per node group.

        Partitions nodes into groups of `nodes_per_group`. Each group gets its own
        kwok-controller deployment that manages only nodes labeled with its partition.
        """
        total_groups = self.node_count // self.nodes_per_group
        if self.node_count % self.nodes_per_group:
            total_groups += 1

        print(
            f"Creating {total_groups} KWOK controller deployment(s) "
            f"for {self.node_count} nodes ({self.nodes_per_group} nodes/group)."
        )

        for group_id in range(total_groups):
            manifest = self._build_controller_deployment(group_id)
            execute_with_retries(
                self.k8s_client.apply_manifest_from_file,
                manifest_path=self.controller_manifest_path,
                manifest_dict=manifest,
            )

        print(f"Successfully created {total_groups} KWOK controller deployment(s).")

    def _build_controller_deployment(self, group_id: int) -> dict:
        """Render the controller Deployment template for a single partition."""
        partition_label = f"group-{group_id}"
        replacements = {
            "controller_name": f"kwok-controller-{partition_label}",
            "partition_label": partition_label,
            "image": f"registry.k8s.io/kwok/kwok:{self.kwok_release}",
        }
        template = self.k8s_client.create_template(self.controller_manifest_path, replacements)
        return yaml.safe_load(template)

    def generate(self):
        """Print node and controller manifests to stdout without applying to the cluster."""
        self.kwok_release = self.kwok_release or self.fetch_latest_release()

        total_groups = self.node_count // self.nodes_per_group
        if self.node_count % self.nodes_per_group:
            total_groups += 1

        for group_id in range(total_groups):
            manifest = self._build_controller_deployment(group_id)
            print("---")
            print(yaml.dump(manifest, default_flow_style=False), end="")

        for i in range(self.node_count):
            node_name = f"kwok-node-{i}"
            group_id = i // self.nodes_per_group
            replacements = {
                "node_name": node_name,
                "node_ip": self._generate_node_ip(i),
                "node_cpu": self.node_cpu,
                "node_memory": self.node_memory,
                "node_pods": self.node_pods,
                "node_gpu": self.node_gpu,
            }
            node_yaml = self.k8s_client.create_template(self.node_manifest_path, replacements)
            node_dict = yaml.safe_load(node_yaml)
            node_dict.setdefault("metadata", {}).setdefault("labels", {})[
                "kwok-partition"
            ] = f"group-{group_id}"
            print("---")
            print(yaml.dump(node_dict, default_flow_style=False), end="")


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
        "--group",
        action="store_true",
        help="Enable grouped mode: automatically split nodes across multiple controllers, "
             "each managing at most --nodes-per-controller nodes.",
    )
    parser.add_argument(
        "--nodes-per-controller",
        type=int,
        default=100,
        help="Number of virtual nodes per controller group (default: 100).",
    )
    parser.add_argument(
        "--kwok-config-path",
        type=str,
        default="kwok/config/kwok-config.yaml",
        help="Path to KWOK controller configuration YAML (default: kwok/config/kwok-config.yaml).",
    )
    parser.add_argument(
        "--controller-deploy-template",
        type=str,
        default="kwok/config/kwok-controller-group-deploy.yaml",
        help="Path to per-group Deployment template (default: kwok/config/kwok-controller-group-deploy.yaml).",
    )
    parser.add_argument(
        "--node-selector-key",
        type=str,
        default="kwok",
        help="Node selector key for controller pod affinity (default: kwok).",
    )
    parser.add_argument(
        "--node-selector-value",
        type=str,
        default="true",
        help="Node selector value for controller pod affinity (default: true).",
    )
    parser.add_argument(
        "--toleration-key",
        type=str,
        default="kwok",
        help="Toleration key for controller pod scheduling (default: kwok).",
    )
    parser.add_argument(
        "--toleration-value",
        type=str,
        default="true",
        help="Toleration value for controller pod scheduling (default: true).",
    )
    parser.add_argument(
        "--node-lease-parallelism",
        type=int,
        default=4,
        help="KWOK nodeLeaseParallelism (default: 4).",
    )
    parser.add_argument(
        "--pod-play-stage-parallelism",
        type=int,
        default=64,
        help="KWOK podPlayStageParallelism (default: 64).",
    )
    parser.add_argument(
        "--node-play-stage-parallelism",
        type=int,
        default=4,
        help="KWOK nodePlayStageParallelism (default: 4).",
    )
    parser.add_argument(
        "--cidr",
        type=str,
        default="10.0.0.1/24",
        help="KWOK CIDR for simulated nodes (default: 10.0.0.1/24).",
    )
    parser.add_argument(
        "--node-ip",
        type=str,
        default=None,
        help="KWOK nodeIP for simulated nodes (default: not set).",
    )
    parser.add_argument(
        "--node-lease-duration-seconds",
        type=int,
        default=40,
        help="KWOK nodeLeaseDurationSeconds (default: 40).",
    )
    parser.add_argument(
        "--kube-connection-qps",
        type=float,
        default=None,
        help="KWOK kubeConnectionQPS (default: not set).",
    )
    parser.add_argument(
        "--kube-connection-burst",
        type=int,
        default=None,
        help="KWOK kubeConnectionBurst (default: not set).",
    )
    parser.add_argument(
        "--action",
        choices=["create", "validate", "tear_down", "generate"],
        required=True,
        help="Action to perform: create, validate, tear_down, or generate (print manifests to stdout).",
    )

    args = parser.parse_args()

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
        group=args.group,
        nodes_per_controller=args.nodes_per_controller,
        kwok_config_path=args.kwok_config_path,
        controller_deploy_template=args.controller_deploy_template,
        node_selector_key=args.node_selector_key,
        node_selector_value=args.node_selector_value,
        toleration_key=args.toleration_key,
        toleration_value=args.toleration_value,
        node_lease_parallelism=args.node_lease_parallelism,
        pod_play_stage_parallelism=args.pod_play_stage_parallelism,
        node_play_stage_parallelism=args.node_play_stage_parallelism,
        cidr=args.cidr,
        node_ip=args.node_ip,
        node_lease_duration_seconds=args.node_lease_duration_seconds,
        kube_connection_qps=args.kube_connection_qps,
        kube_connection_burst=args.kube_connection_burst,
    )
    if args.action == "create":
        node.create()
    elif args.action == "validate":
        node.validate()
    elif args.action == "tear_down":
        node.tear_down()
    elif args.action == "generate":
        node.generate()


if __name__ == "__main__":
    main()
