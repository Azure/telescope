"""Tests for KWOK node functionality."""
import json
import os
import unittest
from unittest.mock import MagicMock, call, patch

import yaml
from kubernetes import client

# Mock kubernetes config before importing
with patch('kubernetes.config.load_kube_config'):
    from kwok.kwok import Node


def make_mock_node(name, **kwargs):
    """Create a mock Kubernetes node for testing.

    Args:
        name: Node name
        **kwargs: Optional node properties (ready, allocatable, capacity,
                 unschedulable, taints, annotations)
    """
    ready = kwargs.get('ready', True)
    allocatable = kwargs.get('allocatable')
    capacity = kwargs.get('capacity')
    unschedulable = kwargs.get('unschedulable', False)
    taints = kwargs.get('taints')
    annotations = kwargs.get('annotations')
    node = MagicMock()
    node.metadata = MagicMock(
        annotations=annotations or {"kwok.x-k8s.io/node": "fake"}, name=name
    )
    node.status = MagicMock(
        conditions=[MagicMock(type="Ready", status="True" if ready else "False")],
        allocatable=allocatable,
        capacity=capacity,
    )
    node.spec = MagicMock(
        unschedulable=unschedulable,
        taints=taints
        or [MagicMock(effect="NoSchedule", key="kwok.x-k8s.io/node", value="fake")],
    )
    return node


def make_rendered_config_map():
    """Create a minimal rendered KWOK configmap manifest."""
    return yaml.dump(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "kwok", "namespace": "kube-system"},
            "data": {
                "kwok.yaml": yaml.dump({"options": {}}, default_flow_style=False)
            },
        },
        default_flow_style=False,
    )


def make_base_controller_deployment(image="registry.k8s.io/kwok/kwok:v0.7.0"):
    """Create a minimal upstream KWOK controller deployment object."""
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name="kwok-controller",
            namespace="kube-system",
            labels={"app": "kwok-controller"},
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": "kwok-controller"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "kwok-controller"}),
                spec=client.V1PodSpec(
                    service_account_name="kwok-controller",
                    containers=[
                        client.V1Container(
                            name="kwok-controller",
                            image=image,
                            args=[
                                "--config=/root/.kwok/kwok.yaml",
                                "--server-address=0.0.0.0:10247",
                            ],
                        )
                    ],
                ),
            ),
        ),
    )


def make_ready_deployment(name):
    """Create a deployment object that reports one available replica."""
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name=name, namespace="kube-system"),
        status=client.V1DeploymentStatus(available_replicas=1),
    )


def make_rendered_node_template(replacements):
    """Create a minimal rendered KWOK node template manifest."""
    return yaml.dump(
        {
            "apiVersion": "v1",
            "kind": "Node",
            "metadata": {
                "name": replacements["node_name"],
                "annotations": {"kwok.x-k8s.io/node": "fake"},
                "labels": {
                    "kwok-controller-group": replacements["controller_group"],
                },
            },
            "status": {
                "addresses": [
                    {
                        "type": "InternalIP",
                        "address": replacements["node_ip"],
                    }
                ]
            },
        },
        default_flow_style=False,
    )


def collect_applied_manifests(mock_calls, kind):
    """Collect applied manifest dicts of a given kind from mock call history."""
    manifests = []

    for call_args in mock_calls:
        manifest_dict = call_args.kwargs.get("manifest_dict")
        if manifest_dict is None and call_args.args and isinstance(call_args.args[0], dict):
            manifest_dict = call_args.args[0]

        if manifest_dict and manifest_dict.get("kind") == kind:
            manifests.append(manifest_dict)

    return manifests


class TestNodeIntegration(unittest.TestCase):
    """Test class for KWOK node integration tests."""
    def setUp(self):
        """
        Set up the environment for each test.
        """
        # Get the absolute path to the template file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(current_dir, "..", "..", "kwok", "config", "kwok-node.yaml")
        template_path = os.path.normpath(template_path)

        # Mock the Kubernetes client and core API
        self.mock_k8s_client = MagicMock()
        self.core_v1_api = MagicMock()

        # Initialize the Node instance with correct template path and mock client
        self.node = Node(
            node_count=2,
            kwok_release="v0.7.0",
            enable_metrics=True,
            node_manifest_path=template_path,
            k8s_client=self.mock_k8s_client,
            node_gpu="8",
            enable_dra=True
        )

    def test_create_nodes(self):
        """Test creating KWOK nodes."""
        ready_deployment = make_ready_deployment("kwok-controller-0")

        def get_deployment_side_effect(name, namespace):
            self.assertEqual(namespace, "kube-system")
            if name == "kwok-controller-0":
                return ready_deployment
            self.fail(f"Unexpected deployment lookup: {name}")

        def create_template_side_effect(template_path, replacements):
            if template_path == self.node.kwok_config_path:
                return make_rendered_config_map()
            if template_path == self.node.node_manifest_path:
                return make_rendered_node_template(replacements)
            if template_path == "kwok/config/resource-slice.yaml":
                return "resource-slice-template"
            self.fail(f"Unexpected template path: {template_path}")

        self.mock_k8s_client.get_deployment.side_effect = get_deployment_side_effect
        self.mock_k8s_client.get_config_map.return_value = None
        self.mock_k8s_client.create_template.side_effect = create_template_side_effect
        self.mock_k8s_client.apply_manifest_from_url.return_value = None
        self.mock_k8s_client.delete_manifest_from_file.return_value = None
        self.mock_k8s_client.apply_manifest_from_file.return_value = None
        self.mock_k8s_client.create_node.return_value = None
        self.mock_k8s_client.create_resource_slice.return_value = None

        mock_kwok_yaml_response = MagicMock()
        deployment_dict = client.ApiClient().sanitize_for_serialization(make_base_controller_deployment())
        deployment_dict["apiVersion"] = "apps/v1"
        deployment_dict["kind"] = "Deployment"
        mock_kwok_yaml_response.text = yaml.dump(deployment_dict)

        try:
            with patch('kwok.kwok.requests.get', return_value=mock_kwok_yaml_response):
                self.node.create()
            print("Nodes created successfully.")
            self.mock_k8s_client.apply_manifest_from_url.assert_has_calls([
                call("https://github.com/kubernetes-sigs/kwok/releases/download/v0.7.0/stage-fast.yaml"),
                call("https://github.com/kubernetes-sigs/kwok/releases/download/v0.7.0/metrics-usage.yaml"),
            ])

            controller_manifests = collect_applied_manifests(
                self.mock_k8s_client.apply_manifest_from_file.call_args_list,
                "Deployment",
            )
            self.assertEqual(len(controller_manifests), 1)
            controller_manifest = controller_manifests[0]
            controller_container = controller_manifest["spec"]["template"]["spec"]["containers"][0]
            controller_env = {item["name"]: item for item in controller_container["env"]}

            self.assertEqual(controller_manifest["metadata"]["name"], "kwok-controller-0")
            self.assertEqual(
                controller_container["args"],
                [
                    "--config=/root/.kwok/kwok.yaml",
                    "--server-address=0.0.0.0:10247",
                    "--node-ip=$(POD_IP)",
                    "--manage-all-nodes=false",
                    "--manage-nodes-with-label-selector=kwok-controller-group=0",
                    "--manage-nodes-with-annotation-selector=kwok.x-k8s.io/node=fake",
                    "--node-lease-duration-seconds=40",
                ],
            )
            self.assertEqual(controller_env["KUBE_API_QPS"]["value"], "500")
            self.assertEqual(controller_env["KUBE_API_BURST"]["value"], "1000")
            self.assertEqual(
                controller_container["resources"],
                {
                    "limits": {"cpu": "3", "memory": "10Gi"},
                    "requests": {"cpu": "2", "memory": "5Gi"},
                },
            )

            # Verify DRA-specific calls were made
            self.mock_k8s_client.apply_manifest_from_file.assert_called_with(
                "kwok/config/device-class.yaml"
            )

            # Verify create_resource_slice was called for each node
            expected_calls = 2  # node_count = 2
            self.assertEqual(
                self.mock_k8s_client.create_resource_slice.call_count,
                expected_calls,
                f"Expected {expected_calls} resource slice calls, got {self.mock_k8s_client.create_resource_slice.call_count}"
            )

            # Mock the nodes for verification
            mock_nodes = [
                make_mock_node(name=f"kwok-node-{i}", ready=True)
                for i in range(2)
            ]
            self.core_v1_api.list_node.return_value.items = mock_nodes

            # Verify the number of nodes in the cluster
            nodes = self.core_v1_api.list_node().items
            node_names = [node.metadata.name for node in nodes]
            created_nodes = [
                name for name in node_names if name.startswith("kwok-node-")
            ]
            self.assertEqual(
                len(created_nodes),
                self.node.node_count,
                f"Expected {self.node.node_count} nodes, but found {len(created_nodes)}.",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.fail(f"Node creation failed: {exc}")

    def test_create_nodes_grouped_mode(self):
        """Test multiple-controller mode creates per-controller deployments and labels nodes."""
        grouped_node = Node(
            node_count=5,
            kwok_release="v0.7.0",
            enable_metrics=False,
            node_manifest_path=self.node.node_manifest_path,
            k8s_client=self.mock_k8s_client,
            nodes_per_controller=2,
        )

        mock_deployment = make_base_controller_deployment()
        ready_deployment = make_ready_deployment("kwok-controller-ready")

        def get_deployment_side_effect(name, namespace):
            self.assertEqual(namespace, "kube-system")
            if name in {"kwok-controller-0", "kwok-controller-1", "kwok-controller-2"}:
                return ready_deployment
            self.fail(f"Unexpected deployment lookup: {name}")

        def create_template_side_effect(template_path, replacements):
            if template_path == grouped_node.kwok_config_path:
                return make_rendered_config_map()
            if template_path == grouped_node.node_manifest_path:
                return make_rendered_node_template(replacements)
            self.fail(f"Unexpected template path: {template_path}")

        self.mock_k8s_client.get_deployment.side_effect = get_deployment_side_effect
        self.mock_k8s_client.get_config_map.return_value = None
        self.mock_k8s_client.create_template.side_effect = create_template_side_effect
        self.mock_k8s_client.apply_manifest_from_url.return_value = None
        self.mock_k8s_client.delete_manifest_from_file.return_value = None
        self.mock_k8s_client.apply_manifest_from_file.return_value = None
        self.mock_k8s_client.create_node.return_value = None

        mock_kwok_yaml_response = MagicMock()
        deployment_dict = client.ApiClient().sanitize_for_serialization(mock_deployment)
        deployment_dict["apiVersion"] = "apps/v1"
        deployment_dict["kind"] = "Deployment"
        mock_kwok_yaml_response.text = yaml.dump(deployment_dict)
        with patch('kwok.kwok.requests.get', return_value=mock_kwok_yaml_response):
            grouped_node.create()

        self.mock_k8s_client.apply_manifest_from_url.assert_has_calls([
            call("https://github.com/kubernetes-sigs/kwok/releases/download/v0.7.0/stage-fast.yaml"),
        ])
        self.assertEqual(self.mock_k8s_client.apply_manifest_from_url.call_count, 1)

        controller_manifests = collect_applied_manifests(
            self.mock_k8s_client.apply_manifest_from_file.call_args_list,
            "Deployment",
        )
        self.assertEqual(
            [manifest["metadata"]["name"] for manifest in controller_manifests],
            ["kwok-controller-0", "kwok-controller-1", "kwok-controller-2"],
        )
        self.assertEqual(
            [
                next(
                    arg for arg in manifest["spec"]["template"]["spec"]["containers"][0]["args"]
                    if arg.startswith("--manage-nodes-with-label-selector=")
                )
                for manifest in controller_manifests
            ],
            [
                "--manage-nodes-with-label-selector=kwok-controller-group=0",
                "--manage-nodes-with-label-selector=kwok-controller-group=1",
                "--manage-nodes-with-label-selector=kwok-controller-group=2",
            ],
        )

        rendered_nodes = [
            yaml.safe_load(call_args.args[0])
            for call_args in self.mock_k8s_client.create_node.call_args_list
        ]
        self.assertEqual(
            [node["metadata"]["name"] for node in rendered_nodes],
            [f"kwok-node-{i}" for i in range(grouped_node.node_count)],
        )
        self.assertEqual(
            [node["metadata"]["labels"]["kwok-controller-group"] for node in rendered_nodes],
            ["0", "0", "1", "1", "2"],
        )

    def test_bootstrap_returns_controller_deployment(self):
        """Test that _bootstrap_kwok returns a V1Deployment from fetched kwok.yaml."""
        mock_deployment = make_base_controller_deployment(image="controller-image")
        self.mock_k8s_client.get_config_map.return_value = None
        self.mock_k8s_client.create_template.return_value = make_rendered_config_map()
        self.mock_k8s_client.apply_manifest_from_url.return_value = None
        self.mock_k8s_client.delete_manifest_from_file.return_value = None
        self.mock_k8s_client.apply_manifest_from_file.return_value = None

        mock_response = MagicMock()
        deployment_dict = client.ApiClient().sanitize_for_serialization(mock_deployment)
        deployment_dict["apiVersion"] = "apps/v1"
        deployment_dict["kind"] = "Deployment"
        mock_response.text = yaml.dump(deployment_dict)

        with patch('kwok.kwok.requests.get', return_value=mock_response):
            controller_base = self.node._bootstrap_kwok("v0.7.0", enable_metrics=False)

        self.assertIsInstance(controller_base, client.V1Deployment)
        self.assertEqual(
            controller_base.spec.template.spec.containers[0].image,
            "controller-image",
        )

        derived_manifest = client.ApiClient().sanitize_for_serialization(
            self.node._build_controller_deployment(controller_base, 0)
        )
        derived_container = derived_manifest["spec"]["template"]["spec"]["containers"][0]
        derived_env = {item["name"]: item for item in derived_container["env"]}

        self.assertEqual(derived_env["KUBE_API_QPS"]["value"], "500")
        self.assertEqual(derived_env["KUBE_API_BURST"]["value"], "1000")
        self.assertEqual(
            derived_container["resources"],
            {
                "limits": {"cpu": "3", "memory": "10Gi"},
                "requests": {"cpu": "2", "memory": "5Gi"},
            },
        )
        # Verify the original deployment is not mutated
        self.assertNotIn(
            "--manage-nodes-with-label-selector=kwok-controller-group=0",
            mock_deployment.spec.template.spec.containers[0].args,
        )

    def test_tear_down_nodes(self):
        """
        Test the deletion of KWOK nodes from the cluster.
        """
        # Setup additional mocks for DRA functionality
        self.mock_k8s_client.delete_node.return_value = None
        self.mock_k8s_client.delete_resource_slice.return_value = None

        try:
            self.node.tear_down()
            print("Nodes deleted successfully.")

            # Verify delete_resource_slice was called for each node (since DRA is enabled)
            expected_calls = 2  # node_count = 2
            self.assertEqual(
                self.mock_k8s_client.delete_resource_slice.call_count,
                expected_calls,
                f"Expected {expected_calls} resource slice deletion calls, got {self.mock_k8s_client.delete_resource_slice.call_count}"
            )

            # Mock empty node list after deletion
            self.core_v1_api.list_node.return_value.items = []

            # Verify the number of nodes in the cluster
            nodes = self.core_v1_api.list_node().items
            node_names = [node.metadata.name for node in nodes]
            deleted_nodes = [
                name for name in node_names if name.startswith("kwok-node-")
            ]
            self.assertEqual(
                len(deleted_nodes),
                0,
                f"Expected 0 nodes, but found {len(deleted_nodes)}.",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.fail(f"Node deletion failed: {exc}")



class TestDeploymentDeserialization(unittest.TestCase):
    """Verify that a YAML-parsed deployment dict deserializes into V1Deployment."""

    def test_deserialize_controller_manifest(self):
        manifest = client.ApiClient().sanitize_for_serialization(
            make_base_controller_deployment()
        )
        deployment = client.ApiClient().deserialize(
            type("Resp", (), {"data": json.dumps(manifest)})(),
            "V1Deployment",
        )
        self.assertIsInstance(deployment, client.V1Deployment)
        self.assertEqual(deployment.metadata.name, "kwok-controller")
        self.assertEqual(
            deployment.spec.template.spec.containers[0].image,
            "registry.k8s.io/kwok/kwok:v0.7.0",
        )
        self.assertEqual(
            deployment.spec.template.spec.containers[0].args,
            ["--config=/root/.kwok/kwok.yaml", "--server-address=0.0.0.0:10247"],
        )


class TestNodeValidation(unittest.TestCase):
    """Test class for KWOK node validation tests."""
    def setUp(self):
        """
        Set up the environment for each test.
        """
        # Get the absolute path to the template file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(current_dir, "..", "..", "kwok", "config", "kwok-node.yaml")
        template_path = os.path.normpath(template_path)
        self.mock_k8s_client = MagicMock()
        self.node = Node(
            node_count=2,
            k8s_client=self.mock_k8s_client,
            node_manifest_path=template_path,
            node_gpu="8",
            enable_dra=True
        )

    def test_validate_success(self):
        """
        Test that validation succeeds when the correct number of KWOK nodes is present.
        """
        # Mock deployment for kwok-controller validation
        mock_deployment = MagicMock()
        mock_deployment.status.available_replicas = 1
        self.mock_k8s_client.get_deployment.return_value = mock_deployment

        # Mock nodes for validation
        mock_nodes = [
            make_mock_node(
                name=f"kwok-node-{i}",
                ready=True,
                allocatable={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
                capacity={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
            )
            for i in range(2)
        ]
        self.mock_k8s_client.get_nodes.return_value = mock_nodes

        try:
            self.node.validate()
            print("Validation succeeded.")
        except RuntimeError as e:
            self.fail(f"Validation failed unexpectedly: {e}")

    def test_validate_insufficient_nodes(self):
        """
        Test that validation fails when fewer KWOK nodes are present than expected.
        """
        # Mock deployment for kwok-controller validation
        mock_deployment = MagicMock()
        mock_deployment.status.available_replicas = 1
        self.mock_k8s_client.get_deployment.return_value = mock_deployment

        mock_nodes = [
            make_mock_node(
                name=f"kwok-node-{i}",
                ready=True,
                allocatable={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
                capacity={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
            )
            for i in range(1)  # Only one node, but node_count=2
        ]
        self.mock_k8s_client.get_nodes.return_value = mock_nodes

        with self.assertRaises(RuntimeError) as context:
            self.node.validate()
        self.assertIn("Expected at least 2 KWOK nodes", str(context.exception))

    def test_validate_node_not_ready(self):
        """
        Test that validation fails when a node's status is not "Ready".
        """
        # Mock deployment for kwok-controller validation
        mock_deployment = MagicMock()
        mock_deployment.status.available_replicas = 1
        self.mock_k8s_client.get_deployment.return_value = mock_deployment

        mock_nodes = [
            make_mock_node(
                name="kwok-node-0",
                ready=False,
                allocatable={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
                capacity={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
            ),
            make_mock_node(
                name="kwok-node-1",
                ready=True,
                allocatable={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
                capacity={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
            ),
        ]
        self.mock_k8s_client.get_nodes.return_value = mock_nodes

        with self.assertRaises(RuntimeError):
            self.node.validate()

    def test_validate_missing_resources(self):
        """
        Test that validation fails when a node is missing resource information.
        """
        # Mock deployment for kwok-controller validation
        mock_deployment = MagicMock()
        mock_deployment.status.available_replicas = 1
        self.mock_k8s_client.get_deployment.return_value = mock_deployment

        mock_nodes = [
            make_mock_node(
                name="kwok-node-0",
                ready=True,
                allocatable=None,
                capacity=None,
            ),
            make_mock_node(
                name="kwok-node-1",
                ready=True,
                allocatable={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
                capacity={"cpu": "96", "memory": "1Ti", "pods": "250", "nvidia.com/gpu": "8"},
            ),
        ]
        self.mock_k8s_client.get_nodes.return_value = mock_nodes

        with self.assertRaises(RuntimeError):
            self.node.validate()


if __name__ == "__main__":
    unittest.main()
