"""Tests for KWOK node functionality."""  # pylint: disable=too-many-lines
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, wait
from threading import Barrier, Event, Lock, get_ident
from unittest.mock import MagicMock, call, patch

import yaml
from kubernetes import client

# Mock kubernetes config before importing
with patch('kubernetes.config.load_kube_config'):
    from clients.kubernetes_client import AuthSynchronizedApiClient, KubernetesClient
    from kwok.kwok import Node, NodeCreatePacer, main


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

    def test_build_controller_deployment_with_custom_resources(self):
        """Test custom controller resources are preserved in the deployment."""
        custom_node = Node(
            controller_cpu_request="250m",
            controller_memory_request="512Mi",
            controller_cpu_limit="750m",
            controller_memory_limit="1Gi",
            k8s_client=self.mock_k8s_client,
        )

        deployment = custom_node._build_controller_deployment(
            make_base_controller_deployment(),
            controller_index=0,
        )
        controller_container = deployment.spec.template.spec.containers[0]

        self.assertEqual(
            client.ApiClient().sanitize_for_serialization(
                controller_container.resources
            ),
            {
                "limits": {"cpu": "750m", "memory": "1Gi"},
                "requests": {"cpu": "250m", "memory": "512Mi"},
            },
        )

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
            self.node.validate(node_validate_success_threshold=1.0)
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
            self.node.validate(node_validate_success_threshold=1.0)
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
            self.node.validate(node_validate_success_threshold=1.0)

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
            self.node.validate(node_validate_success_threshold=1.0)

    def test_validate_partial_threshold_passes(self):
        """Test that validation succeeds when failing nodes are within the allowed threshold."""
        mock_deployment = MagicMock()
        mock_deployment.status.available_replicas = 1
        self.mock_k8s_client.get_deployment.return_value = mock_deployment

        # node_count=2, threshold=0.5 → only 1 of 2 must pass; one node is not ready
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

        try:
            self.node.validate(node_validate_success_threshold=0.5)
        except RuntimeError as e:
            self.fail(f"Validation failed unexpectedly with threshold=0.5: {e}")

    def test_validate_partial_threshold_fails(self):
        """Test that validation fails when too many nodes fail the threshold."""
        mock_deployment = MagicMock()
        mock_deployment.status.available_replicas = 1
        self.mock_k8s_client.get_deployment.return_value = mock_deployment

        # node_count=2, threshold=0.9 → ceil(2*0.9)=2 must pass; one node is not ready
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

        with self.assertRaises(RuntimeError) as context:
            self.node.validate(node_validate_success_threshold=0.9)
        self.assertIn("1/2 nodes passed", str(context.exception))

    def test_validate_invalid_threshold(self):
        """Test that an out-of-range success_threshold raises ValueError."""
        self.mock_k8s_client.get_deployment.return_value = MagicMock(
            status=MagicMock(available_replicas=1)
        )
        self.mock_k8s_client.get_nodes.return_value = [
            make_mock_node(name=f"kwok-node-{i}") for i in range(2)
        ]

        for bad_value in (0.0, -0.1, 1.1):
            with self.subTest(threshold=bad_value):
                with self.assertRaises(ValueError):
                    self.node._validate_kwok_nodes(success_threshold=bad_value)


class TestNodeCreation(unittest.TestCase):
    """Exercise scheduling through creation with only external boundaries mocked."""

    def setUp(self):
        self.k8s_client = MagicMock()
        self.k8s_client.get_config_map.return_value = None
        self.k8s_client.get_deployment.return_value = make_ready_deployment("controller")
        self.k8s_client.create_template.side_effect = self.render_template
        deployment = client.ApiClient().sanitize_for_serialization(make_base_controller_deployment())
        deployment.update(apiVersion="apps/v1", kind="Deployment")
        response = MagicMock(text=yaml.safe_dump(deployment))
        self.addCleanup(patch.stopall)
        patch("kwok.kwok.requests.get", return_value=response).start()
        self.sleep = patch("kwok.kwok.time.sleep").start()
        self.output = patch("builtins.print").start()

    @staticmethod
    def render_template(path, replacements):
        if path == "kwok/config/kwok-config.yaml":
            return make_rendered_config_map()
        return dict(replacements)

    def make_node(self, **kwargs):
        return Node(kwok_release="v0.7.0", k8s_client=self.k8s_client, **kwargs)

    def test_sequential_defaults_and_dra_order(self):
        node = self.make_node(node_count=3, enable_dra=True, node_create_qps=0.1)
        order = []
        self.k8s_client.create_node.side_effect = lambda body: order.append(body["node_name"])
        self.sleep.side_effect = lambda seconds: order.append(seconds)
        self.k8s_client.create_resource_slice.side_effect = (
            lambda body: order.append(body["resource_slice_name"])
        )
        node.create()
        self.assertEqual(node.node_create_workers, 1)
        self.assertEqual(order, [
            "kwok-node-0", 0.05, "kwok-resource-slice-0",
            "kwok-node-1", 0.05, "kwok-resource-slice-1",
            "kwok-node-2", "kwok-resource-slice-2",
        ])
        self.assertEqual(Node(k8s_client=self.k8s_client).node_create_qps, 20)

    def test_invalid_configuration(self):
        for workers in (0, -1):
            with self.subTest(workers=workers), self.assertRaisesRegex(ValueError, "greater than zero"):
                self.make_node(node_create_workers=workers)
        for qps in (0, -1, float("nan"), float("inf"), float("-inf")):
            with self.subTest(qps=qps), self.assertRaisesRegex(ValueError, "finite and greater than zero"):
                self.make_node(node_create_qps=qps)
        self.k8s_client.create_node.assert_not_called()

    def test_parallel_exact_workload_and_bounded_submission(self):
        node = self.make_node(
            node_count=6, nodes_per_controller=2, node_create_workers=3,
            node_create_qps=1000, enable_dra=True,
        )
        barrier = Barrier(3)
        lock = Lock()
        submitted = 0
        completed = []
        seen = {}
        first_node_released = Event()
        created = set()

        def create(body):
            name = body["node_name"]
            with lock:
                self.assertNotIn(name, seen)
                seen[name] = body
            barrier.wait(timeout=5)
            if name == "kwok-node-0":
                self.assertTrue(first_node_released.wait(5))
            with lock:
                created.add(name)

        def resource_slice(body):
            with lock:
                self.assertIn(body["node_name"], created)
                completed.append(body["node_name"])
                if body["node_name"] == "kwok-node-1":
                    first_node_released.set()

        original_submit = ThreadPoolExecutor.submit

        def submit(executor, *args, **kwargs):
            nonlocal submitted
            with lock:
                submitted += 1
                self.assertLessEqual(submitted - len(completed), 3)
            return original_submit(executor, *args, **kwargs)

        self.k8s_client.create_node.side_effect = create
        self.k8s_client.create_resource_slice.side_effect = resource_slice
        with patch("kwok.kwok.ThreadPoolExecutor.submit", autospec=True, side_effect=submit):
            node.create()
        self.assertEqual(submitted, 6)
        self.assertEqual(sorted(completed), [f"kwok-node-{index}" for index in range(6)])
        self.assertLess(completed.index("kwok-node-1"), completed.index("kwok-node-0"))
        self.assertEqual(seen, {
            f"kwok-node-{index}": {
                "node_name": f"kwok-node-{index}",
                "node_ip": f"10.0.0.{10 + index}",
                "node_cpu": "32", "node_memory": "256Gi", "node_pods": "110", "node_gpu": "0",
                "controller_group": str(index // 2),
            }
            for index in range(6)
        })
        self.k8s_client.apply_manifest_from_file.assert_any_call("kwok/config/device-class.yaml")
        self.assertEqual(
            self.k8s_client.apply_manifest_from_file.call_args_list.count(call("kwok/config/device-class.yaml")), 1,
        )
        self.assertEqual(self.k8s_client.create_node.call_count, 6)
        self.assertEqual(
            sorted(
                item.args[0] for item in self.output.call_args_list
                if item.args[0].startswith("Creating resource slice ")
            ),
            [
                f"Creating resource slice kwok-resource-slice-{index} for node kwok-node-{index}"
                for index in range(6)
            ],
        )
        self.sleep.assert_not_called()

    def test_retry_attempts_are_paced_without_extra_retries(self):
        clock = [0.0]
        stopped = MagicMock(spec=Event)
        stopped.is_set.return_value = False
        stopped.wait.side_effect = lambda delay: clock.__setitem__(0, clock[0] + delay)
        self.k8s_client.create_node.side_effect = [RuntimeError("busy"), RuntimeError("busy"), None]
        with patch("kwok.kwok.Event", return_value=stopped), patch(
            "kwok.kwok.time.monotonic", side_effect=lambda: clock[0],
        ):
            self.make_node(node_count=1, node_create_workers=2, node_create_qps=4).create()
        self.assertEqual(self.k8s_client.create_node.call_count, 3)
        self.assertEqual(stopped.wait.call_args_list, [call(0.25), call(0.25)])
        self.assertEqual(self.sleep.call_args_list, [call(10), call(20)])

    def test_failure_stops_waiting_workers_and_reports_identity(self):
        stopped = Event()
        first_wait = Event()
        first_started = Event()
        original_wait = stopped.wait

        def wait_for_stop(delay):
            first_wait.set()
            return original_wait(delay)

        def create(_body):
            first_started.set()
            self.assertTrue(first_wait.wait(5))

        def render(path, replacements):
            if replacements.get("node_name") == "kwok-node-1":
                self.assertTrue(first_started.wait(5))
            return self.render_template(path, replacements)

        self.k8s_client.create_template.side_effect = render
        self.k8s_client.create_node.side_effect = create
        self.k8s_client.create_resource_slice.side_effect = RuntimeError("DRA unavailable")
        # A long permit interval guarantees the other worker is waiting, not issuing a request.
        with patch("kwok.kwok.Event", return_value=stopped), patch.object(
            stopped, "wait", side_effect=wait_for_stop,
        ), self.assertRaisesRegex(RuntimeError, "kwok-node-0: DRA unavailable"):
            self.make_node(
                node_count=5, node_create_workers=2, node_create_qps=0.001, enable_dra=True,
            ).create()
        self.assertTrue(stopped.is_set())
        self.assertEqual(self.k8s_client.create_node.call_count, 1)
        self.assertEqual(self.k8s_client.create_resource_slice.call_count, 3)
        rendered_nodes = [
            item.args[1]["node_name"] for item in self.k8s_client.create_template.call_args_list
            if item.args[0] == "kwok/config/kwok-node.yaml"
        ]
        self.assertEqual(sorted(rendered_nodes), ["kwok-node-0", "kwok-node-1"])
        self.assertFalse(any("Successfully created" in str(item) for item in self.output.call_args_list))

    def test_exhausted_node_retries_reach_caller(self):
        self.k8s_client.create_node.side_effect = [RuntimeError("API unavailable")] * 3
        with self.assertRaisesRegex(RuntimeError, "kwok-node-0: API unavailable"):
            self.make_node(node_count=1, node_create_workers=2, node_create_qps=1000).create()
        self.assertEqual(self.k8s_client.create_node.call_count, 3)
        self.assertFalse(any("Successfully created" in str(item) for item in self.output.call_args_list))

    def test_failure_waits_for_in_flight_requests(self):
        stopped = Event()
        both_started = Barrier(2)
        attempts = 0

        def create(body):
            nonlocal attempts
            if body["node_name"] == "kwok-node-0":
                attempts += 1
                if attempts == 1:
                    both_started.wait(timeout=5)
                raise RuntimeError("node failure")
            both_started.wait(timeout=5)
            self.assertTrue(stopped.wait(5))

        self.k8s_client.create_node.side_effect = create
        with patch("kwok.kwok.Event", return_value=stopped), self.assertRaisesRegex(
            RuntimeError, "kwok-node-0: node failure",
        ):
            self.make_node(node_count=5, node_create_workers=2, node_create_qps=1000).create()
        names = [item.args[0]["node_name"] for item in self.k8s_client.create_node.call_args_list]
        self.assertEqual(sorted(names), ["kwok-node-0"] * 3 + ["kwok-node-1"])
        self.assertTrue(any("Created 1/5 virtual nodes; pending-tasks=0" in str(item)
                            for item in self.output.call_args_list))

    def test_progress_distinguishes_node_success_from_dra_failure(self):
        self.k8s_client.create_resource_slice.side_effect = RuntimeError("DRA unavailable")
        with self.assertRaisesRegex(RuntimeError, "kwok-node-0: DRA unavailable"):
            self.make_node(node_count=1, node_create_workers=2, enable_dra=True).create()
        self.assertEqual(self.k8s_client.create_node.call_count, 1)
        self.assertEqual(self.k8s_client.create_resource_slice.call_count, 3)
        messages = [str(item.args[0]) for item in self.output.call_args_list]
        self.assertTrue(any("Created 1/1 virtual nodes" in message for message in messages))
        self.assertFalse(any("node-plus-resource-slice" in message for message in messages))
        self.assertFalse(any("Successfully created" in message for message in messages))

    def test_progress_reports_while_requests_are_in_flight(self):
        clock = [0.0]
        request_started = Event()
        release_request = Event()

        def create(_body):
            request_started.set()
            self.assertTrue(release_request.wait(5))

        def wait_for_tasks(futures, **kwargs):
            self.assertTrue(request_started.wait(5))
            if clock[0] == 0:
                clock[0] = 10.0
                return set(), set(futures)
            release_request.set()
            return wait(futures, **kwargs)

        self.k8s_client.create_node.side_effect = create
        with patch("kwok.kwok.wait", side_effect=wait_for_tasks), patch(
            "kwok.kwok.time.monotonic", side_effect=lambda: clock[0],
        ):
            self.make_node(node_count=1, node_create_workers=2).create()
        self.output.assert_any_call(
            "Created 0/1 virtual nodes; pending-tasks=1; elapsed=10.0s; completed-rate=0.0 nodes/s",
            flush=True,
        )
        self.output.assert_any_call(
            "Created 1/1 virtual nodes; pending-tasks=0; elapsed=10.0s; completed-rate=0.1 nodes/s",
            flush=True,
        )

    def test_validate_accepts_creation_options_without_changing_validation(self):
        self.k8s_client.get_config_map.return_value = MagicMock()
        self.k8s_client.get_nodes.return_value = [
            make_mock_node("kwok-node-0", allocatable={"cpu": "32"}, capacity={"cpu": "32"}),
        ]
        with patch("sys.argv", [
            "kwok", "--action", "validate", "--node-create-workers", "8",
            "--node-create-qps", "20", "--log-level", "WARNING",
        ]), patch.multiple(
            Node.k8s_client,
            get_config_map=self.k8s_client.get_config_map,
            get_deployment=self.k8s_client.get_deployment,
            get_nodes=self.k8s_client.get_nodes,
            create_node=self.k8s_client.create_node,
        ):
            main()
        self.k8s_client.create_node.assert_not_called()
        self.k8s_client.get_config_map.assert_called_once_with("kwok", "kube-system")
        self.k8s_client.get_deployment.assert_called_once_with("kwok-controller-0", "kube-system")
        self.k8s_client.get_nodes.assert_called_once_with()

    def test_cli_rejects_invalid_creation_options(self):
        for option, value, error in [
            ("--node-create-workers", "0", ValueError),
            ("--node-create-workers", "-2", ValueError),
            ("--node-create-workers", "1.5", SystemExit),
            ("--node-create-qps", "0", ValueError),
            ("--node-create-qps", "-1", ValueError),
            ("--node-create-qps", "nan", ValueError),
            ("--node-create-qps", "inf", ValueError),
            ("--node-create-qps", "-inf", ValueError),
            ("--node-create-qps", "invalid", SystemExit),
        ]:
            with self.subTest(option=option, value=value), patch(
                "sys.argv", ["kwok", "--action", "create", f"{option}={value}"],
            ), self.assertRaises(error):
                main()
        self.k8s_client.create_node.assert_not_called()


class TestKwokEntryPoint(unittest.TestCase):
    def test_help_runs_as_script_and_module(self):
        module_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory() as directory:
            kubeconfig_path = os.path.join(directory, "config")
            with open(kubeconfig_path, "w", encoding="utf-8") as kubeconfig_file:
                yaml.safe_dump({
                    "apiVersion": "v1",
                    "kind": "Config",
                    "clusters": [{"name": "test", "cluster": {"server": "https://127.0.0.1:9"}}],
                    "contexts": [{"name": "test", "context": {"cluster": "test", "user": "test"}}],
                    "current-context": "test",
                    "users": [{"name": "test", "user": {}}],
                }, kubeconfig_file)
            environment = {
                **os.environ,
                "KUBECONFIG": kubeconfig_path,
                "PYTHONPATH": f":{module_directory}",
            }
            for arguments in (["kwok/kwok.py"], ["-m", "kwok.kwok"]):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [sys.executable, *arguments, "--help"],
                        cwd=module_directory,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--node-create-workers", result.stdout)
                    self.assertIn("--node-create-qps", result.stdout)


class TestNodeCreatePacer(unittest.TestCase):
    def test_shared_budget_no_catch_up_and_cancellation(self):
        clock = [0.0]
        stopped = MagicMock(spec=Event)
        stopped.is_set.return_value = False
        stopped.wait.side_effect = lambda delay: clock.__setitem__(0, clock[0] + delay)
        barrier = Barrier(4)
        with patch("kwok.kwok.time.monotonic", side_effect=lambda: clock[0]):
            pacer = NodeCreatePacer(4, stopped)

            def acquire():
                barrier.wait(timeout=5)
                return pacer.acquire()

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(acquire) for _ in range(4)]
                self.assertEqual([future.result() for future in futures], [True] * 4)
            self.assertEqual(stopped.wait.call_args_list, [call(0.25)] * 3)
            clock[0] = 10
            self.assertTrue(pacer.acquire())
            self.assertTrue(pacer.acquire())
            self.assertEqual(clock[0], 10.25)
            stopped.is_set.return_value = True
            self.assertFalse(pacer.acquire())
            self.assertEqual(stopped.wait.call_count, 4)


class TestNodeCreationClient(unittest.TestCase):
    def setUp(self):
        with patch("kubernetes.config.load_kube_config"):
            self.k8s_client = KubernetesClient()
        self.api_client = self.k8s_client.api.api_client
        self.configuration = self.api_client.configuration
        self.configuration.api_key = {"authorization": "static-token"}
        self.configuration.refresh_api_key_hook = None
        self.addCleanup(self.api_client.close)
        self.addCleanup(self.api_client.rest_client.pool_manager.clear)

    @staticmethod
    def node_template(index):
        return yaml.safe_dump({"kind": "Node", "metadata": {"name": f"kwok-node-{index}"}})

    @staticmethod
    def node_response(body):
        return MagicMock(data=json.dumps(body), status=201)

    def test_shared_authentication_is_serialized_while_requests_overlap(self):
        second_attempted_auth = Event()
        requests_started = Barrier(2)
        refresh_lock = Lock()
        attempts_lock = Lock()
        attempts = 0
        tokens = []
        auth_threads = set()

        def enter_auth():
            nonlocal attempts
            with attempts_lock:
                attempts += 1
                if attempts == 2:
                    second_attempted_auth.set()
            self.assertTrue(refresh_lock.acquire(timeout=5))  # pylint: disable=consider-using-with
            with attempts_lock:
                auth_threads.add(get_ident())

        def exit_auth(*_args):
            with attempts_lock:
                auth_threads.remove(get_ident())
            refresh_lock.release()

        observed_lock = MagicMock()
        observed_lock.__enter__.side_effect = enter_auth
        observed_lock.__exit__.side_effect = exit_auth
        self.api_client.auth_lock = observed_lock

        def refresh(configuration):
            self.assertTrue(refresh_lock.locked())
            tokens.append(f"token-{len(tokens) + 1}")
            configuration.api_key["authorization"] = tokens[-1]
            configuration.refresh_api_key_hook = refresh
            self.assertTrue(second_attempted_auth.wait(5))

        initial_refresh = MagicMock(side_effect=refresh)
        self.configuration.refresh_api_key_hook = initial_refresh

        def request(_method, _url, **kwargs):
            with attempts_lock:
                self.assertNotIn(get_ident(), auth_threads)
            token = kwargs["headers"]["authorization"]
            requests_started.wait(timeout=5)
            self.assertEqual(kwargs["headers"]["authorization"], token)
            return self.node_response(kwargs["body"])

        with patch.object(self.api_client, "request", side_effect=request) as requests:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(self.k8s_client.create_node, self.node_template(index))
                    for index in range(2)
                ]
                self.assertEqual([future.result(timeout=10) for future in futures],
                                 ["kwok-node-0", "kwok-node-1"])
        self.assertEqual(tokens, ["token-1", "token-2"])
        self.assertEqual(attempts, 2)
        initial_refresh.assert_called_once_with(self.configuration)
        self.assertIs(self.configuration.refresh_api_key_hook, refresh)
        self.assertEqual(sorted(
            item.kwargs["headers"]["authorization"] for item in requests.call_args_list
        ), ["token-1", "token-2"])

    def test_refresh_failure_releases_authentication_lock(self):
        refresh = MagicMock(side_effect=RuntimeError("refresh failed"))
        self.configuration.refresh_api_key_hook = refresh
        with self.assertRaisesRegex(RuntimeError, "refresh failed"):
            self.k8s_client.create_node(self.node_template(0))
        self.assertFalse(self.api_client.auth_lock.locked())
        self.configuration.refresh_api_key_hook = None
        with patch.object(self.api_client, "request", return_value=self.node_response({
            "metadata": {"name": "kwok-node-1"},
        })) as request:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.k8s_client.create_node, self.node_template(1))
                self.assertEqual(future.result(timeout=5), "kwok-node-1")
        self.assertEqual(request.call_args.kwargs["headers"]["authorization"], "static-token")

    def test_dra_uses_shared_api_client_with_static_credentials(self):
        body = {"metadata": {"name": "slice"}}
        with patch.object(self.api_client, "request", return_value=self.node_response(body)) as request:
            self.assertEqual(self.k8s_client.create_resource_slice(
                "kind: ResourceSlice\napiVersion: resource.k8s.io/v1beta1\nmetadata:\n  name: slice",
            ), "slice")
        self.assertEqual(request.call_args.kwargs["headers"]["authorization"], "static-token")
        self.assertEqual(request.call_args.args,
                         ("POST", self.configuration.host + "/apis/resource.k8s.io/v1beta1/resourceslices"))

    def test_context_switch_reinitializes_synchronized_core_client(self):
        self.assertIsInstance(self.api_client, AuthSynchronizedApiClient)
        self.assertFalse(self.api_client.auth_lock.locked())
        with patch("kubernetes.config.load_kube_config") as load_config:
            self.k8s_client.set_context("other-context")
        replacement = self.k8s_client.api.api_client
        self.addCleanup(replacement.close)
        self.addCleanup(replacement.rest_client.pool_manager.clear)
        self.assertIsInstance(replacement, AuthSynchronizedApiClient)
        self.assertIsNot(replacement, self.api_client)
        self.assertIs(replacement.auth_lock, self.api_client.auth_lock)
        load_config.assert_called_once_with(config_file=None, context="other-context")


class TestKwokPipeline(unittest.TestCase):
    def test_all_tiers_use_parallel_creation_and_strict_validation(self):
        pipeline_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "..", "kcl", "ccp_team",
            "hyperscale_apiserver_executing_seats", "pipeline.yaml",
        )
        with open(pipeline_path, encoding="utf-8") as pipeline_file:
            stages = yaml.safe_load(pipeline_file)["stages"]
        self.assertEqual([stage["stage"] for stage in stages], ["H2", "H4", "H8"])
        for stage in stages:
            with self.subTest(stage=stage["stage"]):
                steps = {step["displayName"]: step for step in stage["jobs"][0]["steps"]}
                create = steps["Create KWOK Nodes"]
                validate = steps["Validate KWOK Nodes"]
                self.assertTrue(create["continueOnError"])
                self.assertNotIn("continueOnError", validate)
                for step, action in [(create, "create"), (validate, "validate")]:
                    arguments = shlex.split(step["script"])
                    for option, expected in {
                        "--action": action,
                        "--node-count": "18000" if stage["stage"] == "H8" else "15000",
                        "--validate-success-threshold": "0.9",
                        "--node-create-workers": "8",
                        "--node-create-qps": "20",
                    }.items():
                        with self.subTest(action=action, option=option):
                            self.assertEqual(arguments.count(option), 1)
                            index = arguments.index(option)
                            self.assertEqual(arguments[index + 1:index + 2], [expected])


if __name__ == "__main__":
    unittest.main()
