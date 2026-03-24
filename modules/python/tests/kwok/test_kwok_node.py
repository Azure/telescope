"""Tests for KWOK node functionality."""
import os
import unittest
from unittest.mock import MagicMock, call, patch

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

    @patch("kwok.kwok.Node.apply_kwok_manifests")
    def test_create_nodes(self, mock_apply):
        """Test creating KWOK nodes."""
        # Setup additional mocks for DRA functionality
        self.mock_k8s_client.apply_manifest_from_file.return_value = None
        self.mock_k8s_client.create_template.return_value = "mock_template"
        self.mock_k8s_client.create_node.return_value = None
        self.mock_k8s_client.create_resource_slice.return_value = None

        # Mock get_deployment so _wait_for_controllers_ready succeeds
        mock_deployment = MagicMock()
        mock_deployment.status.available_replicas = 1
        self.mock_k8s_client.get_deployment.return_value = mock_deployment

        try:
            self.node.create()
            print("Nodes created successfully.")
            # Verify mock was called with expected arguments
            mock_apply.assert_called_once_with(
                self.node.kwok_release,
                self.node.enable_metrics
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

    @patch("kwok.kwok.Node.apply_kwok_manifests")
    @patch("kwok.kwok.Node._wait_for_controllers_ready")
    @patch("kwok.kwok.Node._create_group_deployment")
    @patch("kwok.kwok.Node._add_group_label")
    @patch("kwok.kwok.Node.setup_kwok_for_groups")
    def test_create_nodes_grouped_mode(
        self,
        mock_setup_groups,
        mock_add_group_label,
        mock_create_group_deployment,
        mock_wait_for_controllers_ready,
        mock_apply,
    ):
        """Test grouped mode creates per-group controllers and labels node templates."""
        grouped_node = Node(
            node_count=5,
            kwok_release="v0.7.0",
            enable_metrics=False,
            node_manifest_path=self.node.node_manifest_path,
            k8s_client=self.mock_k8s_client,
            group=True,
            nodes_per_controller=2,
        )

        mock_setup_groups.return_value = "registry.k8s.io/kwok/kwok:v0.7.0"
        self.mock_k8s_client.create_template.side_effect = [
            f"node-template-{i}" for i in range(grouped_node.node_count)
        ]
        self.mock_k8s_client.create_node.return_value = None
        mock_add_group_label.side_effect = (
            lambda template_str, group_index: f"{template_str}|group={group_index}"
        )

        grouped_node.create()

        mock_apply.assert_not_called()
        mock_setup_groups.assert_called_once_with(
            grouped_node.kwok_release,
            grouped_node.enable_metrics,
        )
        mock_create_group_deployment.assert_has_calls([
            call(0, "registry.k8s.io/kwok/kwok:v0.7.0"),
            call(1, "registry.k8s.io/kwok/kwok:v0.7.0"),
            call(2, "registry.k8s.io/kwok/kwok:v0.7.0"),
        ])
        self.assertEqual(mock_create_group_deployment.call_count, 3)
        mock_wait_for_controllers_ready.assert_called_once_with(3)
        mock_add_group_label.assert_has_calls([
            call("node-template-0", 0),
            call("node-template-1", 0),
            call("node-template-2", 1),
            call("node-template-3", 1),
            call("node-template-4", 2),
        ])
        self.assertEqual(
            self.mock_k8s_client.create_node.call_args_list,
            [
                call("node-template-0|group=0"),
                call("node-template-1|group=0"),
                call("node-template-2|group=1"),
                call("node-template-3|group=1"),
                call("node-template-4|group=2"),
            ],
        )

    @patch("kwok.kwok.Node._replace_config_map")
    def test_setup_kwok_for_groups_deletes_upstream_with_delete_options(self, mock_replace_config_map):
        """Test grouped setup deletes the upstream controller with delete options."""
        mock_deployment = MagicMock()
        mock_deployment.spec.template.spec.containers = [MagicMock(image="controller-image")]
        self.mock_k8s_client.get_deployment.return_value = mock_deployment

        mock_app_client = MagicMock()
        self.mock_k8s_client.get_app_client.return_value = mock_app_client

        controller_image = self.node.setup_kwok_for_groups("v0.7.0", enable_metrics=False)

        self.assertEqual(controller_image, "controller-image")
        mock_replace_config_map.assert_called_once()
        mock_app_client.delete_namespaced_deployment.assert_called_once()

        _, kwargs = mock_app_client.delete_namespaced_deployment.call_args
        self.assertEqual(kwargs["name"], "kwok-controller")
        self.assertEqual(kwargs["namespace"], "kube-system")
        self.assertEqual(kwargs["body"].propagation_policy, "Foreground")

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
