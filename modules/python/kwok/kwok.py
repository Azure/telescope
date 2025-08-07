"""KWOK (Kubernetes WithOut Kubelet) - Virtual Node/Pod Simulator."""
import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from clients.kubernetes_client import KubernetesClient
from utils.retries import execute_with_retries


@dataclass
class KWOK(ABC):
    """Abstract base class for KWOK (Kubernetes WithOut Kubelet) components."""
    kwok_repo: str = "kubernetes-sigs/kwok"
    kwok_release: str = None
    enable_metrics: bool = False
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
        # Replace KWOK configuration configmap
        execute_with_retries(
            self.k8s_client.delete_manifest_from_file,
            "kwok/config/kwok-config.yaml"
        )
        execute_with_retries(
            self.k8s_client.apply_manifest_from_file,
            "kwok/config/kwok-config.yaml"
        )

        # Patch kwok-controller deployment with node selector and toleration
        node_selector = {"user": "true"}
        tolerations = [{
            "key": "kwok",
            "value": "true",
            "effect": "NoSchedule"
        }]
        execute_with_retries(
            self.k8s_client.patch_deployment,
            "kwok-controller",
            "kube-system",
            node_selector,
            tolerations
        )

        if enable_metrics:
            metrics_usage_url = (f"https://github.com/{self.kwok_repo}/releases/"
                               f"download/{kwok_release}/metrics-usage.yaml")
            execute_with_retries(
                self.k8s_client.apply_manifest_from_url,
                metrics_usage_url
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
    node_count: int = 1
    node_cpu: str = "32"
    node_memory: str = "256Gi"
    node_pods: str = "110"
    node_gpu: str = "0"
    enable_dra: bool = False

    def create(self):
        try:
            self.kwok_release = self.kwok_release or self.fetch_latest_release()
            print(f"Using KWOK_RELEASE={self.kwok_release}")

            self.apply_kwok_manifests(self.kwok_release, self.enable_metrics)

            # Apply DRA manifests once if enabled
            if self.enable_dra:
                execute_with_retries(
                    self.k8s_client.apply_manifest_from_file,
                    "kwok/config/device-class.yaml"
                )

            for i in range(self.node_count):
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

    def validate(self):
        ready_nodes = execute_with_retries(
            self.k8s_client.get_nodes
        )
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
        type=bool,
        default=False,
        help="Enable Dynamic Resource Allocation (DRA).",
    )
    parser.add_argument(
        "--action",
        choices=["create", "validate", "tear_down"],
        required=True,
        help="Action to perform: create, validate, or tear_down.",
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
    )
    if args.action == "create":
        node.create()
    elif args.action == "validate":
        node.validate()
    elif args.action == "tear_down":
        node.tear_down()


if __name__ == "__main__":
    main()
