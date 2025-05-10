import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests
import yaml


@dataclass
class KWOK(ABC):
    kwok_repo: str = "kubernetes-sigs/kwok"
    kwok_release: str = None
    enable_metrics: bool = False

    def fetch_latest_release(self):
        response = requests.get(
            f"https://api.github.com/repos/{self.kwok_repo}/releases/latest", timeout=10
        )
        response.raise_for_status()
        return response.json().get("tag_name")

    def apply_manifest(self, manifest):
        with subprocess.Popen(
            ["kubectl", "apply", "-f", "-"], stdin=subprocess.PIPE, text=True
        ) as process:
            process.communicate(input=json.dumps(manifest))
            if process.returncode != 0:
                raise RuntimeError("Failed to apply manifest")

    # Setting up the KWOK environment and simulating the pod/node emulation
    # If `enable_metrics` is True, it also applies an additional metrics usage YAML file
    # to simulate resource usage for nodes, pods, and containers.
    def apply_kwok_manifests(self, kwok_release, enable_metrics):
        kwok_yaml_url = f"https://github.com/{self.kwok_repo}/releases/download/{kwok_release}/kwok.yaml"
        stage_fast_yaml_url = f"https://github.com/{self.kwok_repo}/releases/download/{kwok_release}/stage-fast.yaml"
        subprocess.run(["kubectl", "apply", "-f", kwok_yaml_url], check=True)
        subprocess.run(["kubectl", "apply", "-f", stage_fast_yaml_url], check=True)

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
    node_manifest_path: str = "config/kwok-node.yaml"
    node_count: int = 1

    def create(self):
        try:
            self.kwok_release = self.kwok_release or self.fetch_latest_release()
            print(f"Using KWOK_RELEASE={self.kwok_release}")

            self.apply_kwok_manifests(self.kwok_release, self.enable_metrics)

            with open(self.node_manifest_path, "r", encoding="utf-8") as file:
                base_node_manifest = yaml.safe_load(file)

            for i in range(self.node_count):
                node_manifest = base_node_manifest.copy()
                node_manifest["metadata"]["name"] = f"kwok-node-{i}"
                self.apply_manifest(node_manifest)

            print(f"Successfully created {self.node_count} virtual nodes.")
        except Exception as e:
            raise RuntimeError(f"Failed to create nodes: {e}") from e

    def validate(self):
        for i in range(self.node_count):
            node_name = f"kwok-node-{i}"
            print(f"Validating node: {node_name}")
            try:
                node_info = self._get_node_info(node_name)
                self._validate_node_status(node_name, node_info)
                self._validate_node_annotations(node_name, node_info)
                self._validate_node_resources(node_name, node_info)
            except Exception as e:
                raise RuntimeError(
                    f"Validation failed for node {node_name}: {e}"
                ) from e

        print(f"Validation completed for {self.node_count} nodes.")

    def tear_down(self):
        for i in range(self.node_count):
            node_name = f"kwok-node-{i}"
            print(f"Deleting node: {node_name}")
            try:
                subprocess.run(["kubectl", "delete", "node", node_name], check=True)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to delete node {node_name}: {e}") from e

        print(f"Successfully deleted {self.node_count} nodes.")

    def _get_node_info(self, node_name):
        result = subprocess.run(
            ["kubectl", "get", "node", node_name, "-o", "json"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        return json.loads(result.stdout)

    def _validate_node_status(self, node_name, node_info):
        conditions = node_info.get("status", {}).get("conditions", [])
        ready_condition = next((c for c in conditions if c["type"] == "Ready"), None)
        if ready_condition and ready_condition["status"] == "True":
            print(f"Node {node_name} is Ready.")
        else:
            raise RuntimeError(f"Node {node_name} is NOT Ready.")

    def _validate_node_annotations(self, node_name, node_info):
        annotations = node_info.get("metadata", {}).get("annotations", {})
        if annotations.get("kwok.x-k8s.io/node") == "fake":
            print(f"Node {node_name} is correctly annotated as a KWOK node.")
        else:
            raise RuntimeError(f"Node {node_name} is missing the KWOK annotation.")

    def _validate_node_resources(self, node_name, node_info):
        allocatable = node_info.get("status", {}).get("allocatable", {})
        capacity = node_info.get("status", {}).get("capacity", {})
        if not allocatable or not capacity:
            raise RuntimeError(
                f"Node {node_name} is missing resource information (allocatable or capacity)."
            )
        print(f"Node {node_name} Allocatable: {allocatable}")
        print(f"Node {node_name} Capacity: {capacity}")


# TODO: Implement the logic for KWOK pods
@dataclass
class Pod(KWOK):
    def create(self):
        pass

    def validate(self):
        pass

    def tear_down(self):
        pass


if __name__ == "__main__":
    # Example usage
    kwok_node = Node(node_count=2, enable_metrics=True)
    kwok_node.create()
    kwok_node.validate()
    kwok_node.tear_down()
