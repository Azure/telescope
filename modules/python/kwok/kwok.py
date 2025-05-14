import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests


from clients.kubernetes_client import KubernetesClient


@dataclass
class KWOK(ABC):
    kwok_repo: str = "kubernetes-sigs/kwok"
    kwok_release: str = None
    enable_metrics: bool = False
    k8s_client: KubernetesClient = KubernetesClient()

    def fetch_latest_release(self):
        response = requests.get(
            f"https://api.github.com/repos/{self.kwok_repo}/releases/latest", timeout=10
        )
        response.raise_for_status()
        return response.json().get("tag_name")

    # Setting up the KWOK environment and simulating the pod/node emulation
    # If `enable_metrics` is True, it also applies an additional metrics usage YAML file
    # to simulate resource usage for nodes, pods, and containers.
    def apply_kwok_manifests(self, kwok_release, enable_metrics):
        kwok_yaml_url = f"https://github.com/{self.kwok_repo}/releases/download/{kwok_release}/kwok.yaml"
        stage_fast_yaml_url = f"https://github.com/{self.kwok_repo}/releases/download/{kwok_release}/stage-fast.yaml"
        subprocess.run(["kubectl", "apply", "-f", kwok_yaml_url], check=True)
        subprocess.run(["kubectl", "apply", "-f", stage_fast_yaml_url], check=True)
        # TODO: exchange subprocess with k8s_client, will be done in another PR since change is quiet big
        if enable_metrics:
            metrics_usage_url = f"https://github.com/{self.kwok_repo}/releases/download/{kwok_release}/metrics-usage.yaml"
            subprocess.run(["kubectl", "apply", "-f", metrics_usage_url], check=True)

    @abstractmethod
    def create(self):
        pass

    @abstractmethod
    def validate(self):
        pass

    @abstractmethod
    def tear_down(self):
        pass


@dataclass
class Node(KWOK):
    node_manifest_path: str = "kwok/config/kwok-node.yaml"
    node_count: int = 1

    def create(self):
        try:
            self.kwok_release = self.kwok_release or self.fetch_latest_release()
            print(f"Using KWOK_RELEASE={self.kwok_release}")

            self.apply_kwok_manifests(self.kwok_release, self.enable_metrics)

            for i in range(self.node_count):
                replacements = {"node_name": f"kwok-node-{i}"}
                kwok_template = self.k8s_client.create_template(
                    self.node_manifest_path, replacements
                )
                self.k8s_client.create_node(kwok_template)

            print(f"Successfully created {self.node_count} virtual nodes.")
        except Exception as e:
            raise RuntimeError(f"Failed to create nodes: {e}") from e

    def validate(self):
        ready_nodes = self.k8s_client.get_nodes()
        kwok_nodes = [
            node
            for node in ready_nodes
            if node.metadata.annotations
            and node.metadata.annotations.get("kwok.x-k8s.io/node") == "fake"
        ]

        if len(kwok_nodes) < self.node_count:
            raise RuntimeError(
                f"Validation failed: Expected at least {self.node_count} KWOK nodes, but found {len(kwok_nodes)}."
            )

        for node in kwok_nodes:
            try:
                self._validate_node_status(node)
                self._validate_node_resources(node)
            except Exception as e:
                raise RuntimeError(
                    f"Validation failed for node {node.metadata.name}: {e}"
                ) from e

        print(f"Validation completed for {self.node_count} KWOK nodes.")

    def tear_down(self):
        for i in range(self.node_count):
            node_name = f"kwok-node-{i}"
            print(f"Deleting node: {node_name}")
            self.k8s_client.delete_node(node_name)
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
                f"Node {node.metadata.name} is NOT Ready."
                f"Condition: {ready_condition.status if ready_condition else 'No Ready condition found'}"
            )

    def _validate_node_resources(self, node):
        allocatable = (
            node.status.allocatable if node.status and node.status.allocatable else {}
        )
        capacity = node.status.capacity if node.status and node.status.capacity else {}

        if not allocatable or not capacity:
            raise RuntimeError(
                f"Node {node.metadata.name} is missing resource information (allocatable or capacity)."
            )
        print(f"Node {node.metadata.name} Allocatable: {allocatable}")
        print(f"Node {node.metadata.name} Capacity: {capacity}")


# TODO: Implement the logic for KWOK pods
@dataclass
class Pod(KWOK):
    def create(self):
        pass

    def validate(self):
        pass

    def tear_down(self):
        pass


# TODO: Implement an argument parser so that KWOK can be invoked in the topology.
