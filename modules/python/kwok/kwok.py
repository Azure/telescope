from abc import ABC, abstractmethod
from dataclasses import dataclass

import os
import tempfile
import urllib.request
import yaml

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
        self.apply_yaml_file(kwok_yaml_url)
        self.apply_yaml_file(stage_fast_yaml_url)
        # TODO: exchange subprocess with k8s_client, will be done in another PR since change is quiet big
        if enable_metrics:
            metrics_usage_url = f"https://github.com/{self.kwok_repo}/releases/download/{kwok_release}/metrics-usage.yaml"
            self.apply_yaml_file(metrics_usage_url)
    def apply_yaml_file(self, yaml_file_path):
        """
        Apply all resources in a YAML file (local path or URL) using the K8s client.
        """
        tmp = None
        # Download if it's a URL
        if yaml_file_path.startswith("http://") or yaml_file_path.startswith("https://"):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".yaml")
            urllib.request.urlretrieve(yaml_file_path, tmp.name)
            yaml_file_path = tmp.name

        plural_map = {
            "ClusterAttach": "clusterattaches",
            "ClusterExec": "clusterexecs",
            "ClusterLogs": "clusterlogs"
        }

        kind_method_map = {
            "Deployment": self.k8s_client.create_deployment,
            "Service": self.k8s_client.create_service,
            "ConfigMap": self.k8s_client.create_config_map,
            "ServiceAccount": self.k8s_client.create_service_account,
            "ClusterRole": self.k8s_client.create_cluster_role,
            "ClusterRoleBinding": self.k8s_client.create_cluster_role_binding,
            "CustomResourceDefinition": self.k8s_client.create_crd,
            "Attach": self.k8s_client.create_attach,
            "Stage": self.k8s_client.create_stage,
            "Metric": self.k8s_client.create_metric,
            "FlowSchema": self.k8s_client.create_flow_schema,
        }

        try:
            with open(yaml_file_path) as f:
                docs = list(yaml.safe_load_all(f))

            for doc in docs:
                if not doc or "kind" not in doc:
                    continue
                kind = doc["kind"]
                # Convert the doc back to YAML string for your create_* methods
                template = yaml.dump(doc)
                namespace = doc.get("metadata", {}).get("namespace", "default")

                try:
                    if kind in kind_method_map:
                        if kind in ["ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition", "FlowSchema"]:
                            kind_method_map[kind](template)
                        else:
                            kind_method_map[kind](template, namespace)
                    elif kind in plural_map:
                        self.k8s_client.create_cluster_resource(template, plural_map[kind])
                    else:
                        print(f"Skipping unsupported kind: {kind}")
                except Exception as e:
                    print(f"Failed to apply {kind}: {e}")
        finally:
            if tmp:
                os.unlink(tmp.name)
   
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
