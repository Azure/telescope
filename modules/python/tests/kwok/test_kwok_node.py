import unittest
from unittest.mock import MagicMock

from kubernetes import client, config

from kwok.kwok import Node


def make_mock_node(
    name,
    ready=True,
    allocatable=None,
    capacity=None,
    unschedulable=False,
    taints=None,
    annotations=None,
):
    node = MagicMock()
    node.metadata = MagicMock(
        annotations=annotations or {"kwok.x-k8s.io/node": "fake"},
        name=name
    )
    node.status = MagicMock(
        conditions=[MagicMock(type="Ready", status="True" if ready else "False")],
        allocatable=allocatable,
        capacity=capacity,
    )
    node.spec = MagicMock(
        unschedulable=unschedulable,
        taints=taints or [
            MagicMock(
                effect="NoSchedule",
                key="kwok.x-k8s.io/node",
                value="fake"
            )
        ]
    )
    return node


class TestNodeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Set up a Kubernetes cluster before running the tests.
        """
        # Load the Kubernetes configuration (assumes a cluster is already running)
        try:
            config.load_kube_config()
            cls.core_v1_api = client.CoreV1Api()
            print("Kubernetes cluster is accessible.")
        except Exception as e:
            raise RuntimeError(f"Failed to access Kubernetes cluster: {e}") from e

    def setUp(self):
        """
        Set up the environment for each test.
        """
        # Initialize the Node instance
        self.node = Node(node_count=2)

    def test_create_nodes(self):
        try:
            self.node.create()
            print("Nodes created successfully.")

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
        except Exception as e:
            self.fail(f"Node creation failed: {e}")

    def test_tear_down_nodes(self):
        """
        Test the deletion of KWOK nodes from the cluster.
        """
        try:
            self.node.tear_down()
            print("Nodes deleted successfully.")

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
        except Exception as e:
            self.fail(f"Node deletion failed: {e}")

    class TestNodeValidation(unittest.TestCase):
        def setUp(self):
            """
            Set up the environment for each test.
            """
            self.mock_k8s_client = MagicMock()
            self.node = Node(node_count=2, k8s_client=self.mock_k8s_client)

        def test_validate_success(self):
            """
            Test that validation succeeds when the correct number of KWOK nodes is present.
            """
            mock_nodes = [
                make_mock_node(
                    name=f"kwok-node-{i}",
                    ready=True,
                    allocatable={"cpu": "2", "memory": "4Gi"},
                    capacity={"cpu": "2", "memory": "4Gi"},
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
            mock_nodes = [
                make_mock_node(
                    name=f"kwok-node-{i}",
                    ready=True,
                    allocatable={"cpu": "2", "memory": "4Gi"},
                    capacity={"cpu": "2", "memory": "4Gi"},
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
            mock_nodes = [
                make_mock_node(
                    name="kwok-node-0",
                    ready=False,
                    allocatable={"cpu": "2", "memory": "4Gi"},
                    capacity={"cpu": "2", "memory": "4Gi"},
                ),
                make_mock_node(
                    name="kwok-node-1",
                    ready=True,
                    allocatable={"cpu": "2", "memory": "4Gi"},
                    capacity={"cpu": "2", "memory": "4Gi"},
                ),
            ]
            self.mock_k8s_client.get_nodes.return_value = mock_nodes

            with self.assertRaises(RuntimeError):
                self.node.validate()

        def test_validate_missing_resources(self):
            """
            Test that validation fails when a node is missing resource information.
            """
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
                    allocatable={"cpu": "2", "memory": "4Gi"},
                    capacity={"cpu": "2", "memory": "4Gi"},
                ),
            ]
            self.mock_k8s_client.get_nodes.return_value = mock_nodes

            with self.assertRaises(RuntimeError):
                self.node.validate()


if __name__ == "__main__":
    unittest.main()
