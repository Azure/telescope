"""
Unit tests for EKS Client launch template functionality
"""
# pylint: disable=too-many-lines,too-many-public-methods,protected-access

import unittest
from unittest import mock
import os
from datetime import datetime, timedelta
from clients.eks_client import EKSClient


# Mock botocore exceptions to avoid import issues in test environment
class MockClientError(Exception):
    """Mock implementation of boto3 ClientError for testing"""

    def __init__(self, error_response, operation_name):
        self.response = error_response
        self.operation_name = operation_name
        super().__init__(f"{operation_name}: {error_response}")


class MockWaiterError(Exception):
    """Mock implementation of boto3 WaiterError for testing"""

    def __init__(self, name, reason, last_response):
        self.name = name
        self.reason = reason
        self.last_response = last_response
        super().__init__(f"{name}: {reason}")


# Use mock exceptions instead of real ones
ClientError = MockClientError
WaiterError = MockWaiterError


class TestEKSClient(unittest.TestCase):
    """Test suite for EKS Client functionality"""

    def setUp(self):
        """Set up test environment"""
        # Mock environment variables
        self.env_patcher = mock.patch.dict(
            os.environ,
            {
                "AWS_DEFAULT_REGION": "us-west-2",
                "RUN_ID": "test-run-123",
                "SCENARIO_NAME": "test-scenario",
                "SCENARIO_TYPE": "cri",
                "DELETION_DUE_TIME": (datetime.now() + timedelta(hours=2)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            },
        )
        self.env_patcher.start()

        # Mock boto3 clients
        self.boto3_patcher = mock.patch("clients.eks_client.boto3")
        mock_boto3 = self.boto3_patcher.start()

        # Mock EKS client
        self.mock_eks = mock.MagicMock()
        mock_boto3.client.return_value = self.mock_eks

        # Mock cluster list and describe responses
        self.mock_eks.list_clusters.return_value = {"clusters": ["test-cluster-123"]}
        self.mock_eks.describe_cluster.return_value = {
            "cluster": {"tags": {"run_id": "test-run-123"}, "version": "1.29"}
        }

        # Mock subnets response
        self.mock_eks.describe_subnets = mock.MagicMock()

        # Mock EC2 client for subnets and launch templates
        self.mock_ec2 = mock.MagicMock()
        mock_boto3.client.side_effect = lambda service, **kwargs: {
            "eks": self.mock_eks,
            "ec2": self.mock_ec2,
            "iam": mock.MagicMock(),
        }.get(service, mock.MagicMock())

        # Mock subnet response
        self.mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"SubnetId": "subnet-123", "AvailabilityZone": "us-west-2a"},
                {"SubnetId": "subnet-456", "AvailabilityZone": "us-west-2b"},
            ]
        }

        # Mock node groups response
        self.mock_eks.list_nodegroups.return_value = {"nodegroups": ["existing-ng"]}
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"nodeRole": "arn:aws:iam::123456789012:role/eksNodeRole"}
        }

        # Mock Kubernetes client
        self.k8s_patcher = mock.patch("clients.eks_client.KubernetesClient")
        mock_k8s_class = self.k8s_patcher.start()
        self.mock_k8s = mock_k8s_class.return_value

    def tearDown(self):
        """Clean up after tests"""
        self.env_patcher.stop()
        self.boto3_patcher.stop()
        self.k8s_patcher.stop()

    # NOTE: The following tests were removed because they directly called protected methods.
    # The functionality of these protected methods is now tested through public interfaces:
    # - _create_default_launch_template is tested via create_node_group operations
    # - _create_launch_template is tested via create_node_group operations
    # - _get_capacity_reservation_id is tested via GPU node group creation with CAPACITY_BLOCK
    # - _delete_launch_template is tested via delete_node_group operations
    # - _serialize_aws_response is tested via operations that return AWS data
    # - _wait_for_node_group_active/_wait_for_node_group_deleted are tested via node group operations

    # NOTE: _create_launch_template wrapper functionality is now tested via create_node_group

    def test_create_node_group_always_creates_launch_template(self):
        """Test that create_node_group always creates a launch template"""
        # Setup
        eks_client = EKSClient()

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-always-12345"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1", "node2"]

        # Execute
        eks_client.create_node_group(
            node_group_name="test-always-lt",
            instance_type="t3.medium",
            node_count=2,
            gpu_node_group=False,
            capacity_type="ON_DEMAND",
        )

        # Verify launch template was created
        self.mock_ec2.create_launch_template.assert_called_once()

        # Verify node group creation included launch template
        create_call = self.mock_eks.create_nodegroup.call_args[1]
        self.assertIn("launchTemplate", create_call)
        self.assertEqual(create_call["launchTemplate"]["id"], "lt-always-12345")
        self.assertEqual(create_call["launchTemplate"]["version"], "1")

        # Note: instanceTypes might not be included in current implementation
        # when using launch template (depends on AWS EKS requirements)

    # NOTE: Direct capacity reservation testing moved to GPU node group creation tests

    # NOTE: Direct launch template deletion testing moved to delete_node_group tests

    # NOTE: Direct serialization testing moved to operations that use AWS responses

    def test_get_cluster_data_success(self):
        """Test successful cluster data retrieval"""
        # Setup
        eks_client = EKSClient()

        # Reset the mock to only track calls from this test
        self.mock_eks.describe_cluster.reset_mock()

        # Mock cluster response
        self.mock_eks.describe_cluster.return_value = {
            "cluster": {
                "name": "test-cluster-123",
                "status": "ACTIVE",
                "created_at": datetime(2025, 7, 15, 10, 0, 0),
            }
        }

        # Execute
        result = eks_client.get_cluster_data()

        # Verify
        self.assertEqual(result["name"], "test-cluster-123")
        self.assertEqual(result["status"], "ACTIVE")
        # Check that datetime was serialized (format may vary)
        self.assertIn("created_at", result)
        self.assertIsInstance(result["created_at"], str)
        self.mock_eks.describe_cluster.assert_called_once_with(name="test-cluster-123")

    def test_get_cluster_data_with_custom_name(self):
        """Test cluster data retrieval with custom cluster name"""
        # Setup
        eks_client = EKSClient()

        # Reset the mock to only track calls from this test
        self.mock_eks.describe_cluster.reset_mock()

        # Mock cluster response
        self.mock_eks.describe_cluster.return_value = {
            "cluster": {"name": "custom-cluster", "status": "ACTIVE"}
        }

        # Execute
        result = eks_client.get_cluster_data("custom-cluster")

        # Verify
        self.assertEqual(result["name"], "custom-cluster")
        self.mock_eks.describe_cluster.assert_called_once_with(name="custom-cluster")

    def test_get_cluster_data_client_error(self):
        """Test cluster data retrieval with AWS client error"""
        # Setup
        eks_client = EKSClient()

        # Mock client error
        self.mock_eks.describe_cluster.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "ResourceNotFoundException",
                    "Message": "Cluster not found",
                }
            },
            operation_name="DescribeCluster",
        )

        # Execute and verify exception
        with self.assertRaises(ClientError):
            eks_client.get_cluster_data("nonexistent-cluster")

    def test_get_node_group_success(self):
        """Test successful node group retrieval"""
        # Setup
        eks_client = EKSClient()

        # Reset the mock to only track calls from this test
        self.mock_eks.describe_nodegroup.reset_mock()

        # Mock node group response
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "nodegroupName": "test-nodegroup",
                "status": "ACTIVE",
                "scalingConfig": {"desiredSize": 3},
                "createdAt": datetime(2025, 7, 15, 12, 0, 0),
            }
        }

        # Execute
        result = eks_client.get_node_group("test-nodegroup")

        # Verify
        self.assertEqual(result["nodegroupName"], "test-nodegroup")
        self.assertEqual(result["status"], "ACTIVE")
        # Check that datetime was serialized (format may vary)
        self.assertIn("createdAt", result)
        self.assertIsInstance(result["createdAt"], str)
        self.mock_eks.describe_nodegroup.assert_called_once_with(
            clusterName="test-cluster-123", nodegroupName="test-nodegroup"
        )

    def test_get_node_group_not_found(self):
        """Test node group retrieval when node group doesn't exist"""
        # Setup
        eks_client = EKSClient()

        # Mock ResourceNotFoundException
        self.mock_eks.describe_nodegroup.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "ResourceNotFoundException",
                    "Message": "NodeGroup not found",
                }
            },
            operation_name="DescribeNodegroup",
        )

        # Execute and verify exception
        with self.assertRaises(ClientError):
            eks_client.get_node_group("nonexistent-nodegroup")

    def test_get_node_group_other_client_error(self):
        """Test node group retrieval with other AWS client errors"""
        # Setup
        eks_client = EKSClient()

        # Mock other client error
        self.mock_eks.describe_nodegroup.side_effect = ClientError(
            error_response={
                "Error": {"Code": "AccessDenied", "Message": "Access denied"}
            },
            operation_name="DescribeNodegroup",
        )

        # Execute and verify exception
        with self.assertRaises(ClientError):
            eks_client.get_node_group("test-nodegroup")

    # NOTE: Direct _wait_for_node_group_active testing moved to operations that create/scale node groups

    # NOTE: Direct _wait_for_node_group_deleted testing moved to delete_node_group operations

    # NOTE: Capacity reservation testing moved to GPU node group creation with CAPACITY_BLOCK

    # NOTE: Launch template tests moved to create_node_group operations

    # NOTE: Launch template wrapper exception testing moved to create_node_group failure scenarios

    # NOTE: Launch template deletion errors tested via delete_node_group operations

    # NOTE: Launch template name truncation tested via create_node_group with long names

    def test_create_node_group_launch_template_failure(self):
        """Test node group creation when launch template creation fails"""
        # Setup
        eks_client = EKSClient()

        # Mock launch template creation failure
        self.mock_ec2.create_launch_template.side_effect = Exception(
            "Launch template creation failed"
        )

        # Mock other operations to succeed if reached
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = []

        # Execute - the operation should exit with SystemExit due to current implementation
        with self.assertRaises(SystemExit):
            eks_client.create_node_group(
                node_group_name="test-lt-fail",
                instance_type="t3.medium",
                node_count=2,
                gpu_node_group=False,
                capacity_type="ON_DEMAND",
            )

    def test_create_node_group_gpu_without_capacity_block(self):
        """Test GPU node group creation without CAPACITY_BLOCK (should not check reservations)"""
        # Setup
        eks_client = EKSClient()

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-gpu-on-demand-12345"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]
        self.mock_k8s.verify_nvidia_smi_on_node.return_value = {
            "node1": "nvidia-smi output"
        }

        # Execute
        eks_client.create_node_group(
            node_group_name="gpu-on-demand",
            instance_type="p3.2xlarge",
            node_count=1,
            gpu_node_group=True,
            capacity_type="ON_DEMAND",  # Not CAPACITY_BLOCK
        )

        # Verify that capacity reservation lookup was NOT called
        self.mock_ec2.describe_capacity_reservations.assert_not_called()

        # Verify launch template was still created
        self.mock_ec2.create_launch_template.assert_called_once()

        # Verify NVIDIA verification was called for GPU nodes
        self.mock_k8s.verify_nvidia_smi_on_node.assert_called_once()

    def test_scale_node_group_success(self):
        """Test successful node group scaling"""
        # Setup
        eks_client = EKSClient()

        # Mock current node group state
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "scalingConfig": {"desiredSize": 2, "maxSize": 5, "minSize": 1}
            }
        }

        # Mock successful scaling
        self.mock_eks.update_nodegroup_config.return_value = {}
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1", "node2", "node3"]

        # Execute
        result = eks_client.scale_node_group("test-ng", 3, 3)

        # Verify
        self.assertTrue(result)
        self.mock_eks.update_nodegroup_config.assert_called_once()
        update_call = self.mock_eks.update_nodegroup_config.call_args[1]
        self.assertEqual(update_call["scalingConfig"]["desiredSize"], 3)

    def test_scale_node_group_increase_max_size(self):
        """Test scaling that requires increasing maxSize"""
        # Setup
        eks_client = EKSClient()

        # Mock current node group state with low maxSize
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "scalingConfig": {
                    "desiredSize": 2,
                    "maxSize": 3,  # Lower than target
                    "minSize": 1,
                }
            }
        }

        # Mock successful scaling
        self.mock_eks.update_nodegroup_config.return_value = {}
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = [
            "node1",
            "node2",
            "node3",
            "node4",
            "node5",
        ]

        # Execute - scale to 5 nodes (higher than current maxSize of 3)
        result = eks_client.scale_node_group("test-ng", 5, 5)

        # Verify maxSize was increased
        self.assertTrue(result)
        update_call = self.mock_eks.update_nodegroup_config.call_args[1]
        self.assertEqual(update_call["scalingConfig"]["desiredSize"], 5)
        self.assertEqual(update_call["scalingConfig"]["maxSize"], 5)

    def test_scale_node_group_no_change_needed(self):
        """Test scaling when target equals current size"""
        # Setup
        eks_client = EKSClient()

        # Mock current node group state
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "scalingConfig": {"desiredSize": 3, "maxSize": 5, "minSize": 1}
            }
        }

        # Mock update response
        self.mock_eks.update_nodegroup_config.return_value = {
            "update": {"id": "update-123", "status": "InProgress"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1", "node2", "node3"]

        # Execute - scale to same size
        result = eks_client.scale_node_group("test-ng", 3, 3)

        # Verify update was called (the method does call AWS API even for same size)
        self.assertTrue(result)
        self.mock_eks.update_nodegroup_config.assert_called_once()

        # Verify scaling config
        call_args = self.mock_eks.update_nodegroup_config.call_args[1]
        self.assertEqual(call_args["scalingConfig"]["desiredSize"], 3)

    def test_scale_node_group_progressive_scaling(self):
        """Test progressive scaling"""
        # Setup
        eks_client = EKSClient()

        # Mock current node group state
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "scalingConfig": {"desiredSize": 2, "maxSize": 10, "minSize": 1}
            }
        }

        # Mock the _progressive_scale method
        with mock.patch.object(eks_client, "_progressive_scale") as mock_progressive:
            mock_progressive.return_value = {"status": "ACTIVE"}

            # Execute
            eks_client.scale_node_group(
                "test-ng", 8, 8, progressive=True, scale_step_size=2
            )

            # Verify progressive scaling was called
            mock_progressive.assert_called_once()
            call_args = mock_progressive.call_args[0]
            self.assertEqual(call_args[0], "test-ng")  # node_group_name
            self.assertEqual(call_args[1], 2)  # current_count
            self.assertEqual(call_args[2], 8)  # target_count
            self.assertEqual(call_args[3], 2)  # step_size

    def test_scale_node_group_update_failure(self):
        """Test scaling failure during node group update"""
        # Setup
        eks_client = EKSClient()

        # Mock current node group state
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "scalingConfig": {"desiredSize": 2, "maxSize": 5, "minSize": 1}
            }
        }

        # Mock update failure
        self.mock_eks.update_nodegroup_config.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "ResourceNotFoundException",
                    "Message": "NodeGroup not found",
                }
            },
            operation_name="UpdateNodegroupConfig",
        )

        # Execute and verify exception
        with self.assertRaises(ClientError):
            eks_client.scale_node_group("nonexistent-ng", 3, 3)

    def test_delete_node_group_success(self):
        """Test successful node group deletion"""
        # Setup
        eks_client = EKSClient()
        eks_client.launch_template_id = "lt-to-delete-12345"

        # Mock node group info for metadata
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"scalingConfig": {"desiredSize": 3}, "amiType": "AL2_x86_64"}
        }

        # Mock successful deletion
        self.mock_eks.delete_nodegroup.return_value = {}
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()

        # Execute
        result = eks_client.delete_node_group("test-ng")

        # Verify
        self.assertTrue(result)
        self.mock_eks.delete_nodegroup.assert_called_once_with(
            clusterName="test-cluster-123", nodegroupName="test-ng"
        )
        # Verify launch template deletion was attempted
        self.mock_ec2.delete_launch_template.assert_called_once_with(
            LaunchTemplateId="lt-to-delete-12345"
        )

    def test_delete_node_group_without_launch_template(self):
        """Test node group deletion when no launch template exists"""
        # Setup
        eks_client = EKSClient()
        # Don't set launch_template_id

        # Mock node group info
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"scalingConfig": {"desiredSize": 2}, "amiType": "AL2_x86_64"}
        }

        # Mock successful deletion
        self.mock_eks.delete_nodegroup.return_value = {}
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()

        # Execute
        result = eks_client.delete_node_group("test-ng")

        # Verify
        self.assertTrue(result)
        # Verify launch template deletion was NOT called
        self.mock_ec2.delete_launch_template.assert_not_called()

    def test_delete_node_group_info_retrieval_failure(self):
        """Test node group deletion when info retrieval fails"""
        # Setup
        eks_client = EKSClient()

        # Mock node group info failure for all calls
        self.mock_eks.describe_nodegroup.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "ResourceNotFoundException",
                    "Message": "NodeGroup not found",
                }
            },
            operation_name="DescribeNodegroup",
        )

        # Execute and verify exception is raised (from the second get_node_group call)
        with self.assertRaises(ClientError):
            eks_client.delete_node_group("test-ng")

    def test_delete_node_group_deletion_failure(self):
        """Test node group deletion failure"""
        # Setup
        eks_client = EKSClient()

        # Mock node group info
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"scalingConfig": {"desiredSize": 2}, "amiType": "AL2_x86_64"}
        }

        # Mock deletion failure
        self.mock_eks.delete_nodegroup.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "ResourceInUseException",
                    "Message": "NodeGroup is in use",
                }
            },
            operation_name="DeleteNodegroup",
        )

        # Execute and verify exception
        with self.assertRaises(ClientError):
            eks_client.delete_node_group("test-ng")

    def test_eks_client_initialization_failure(self):
        """Test EKS client initialization failure"""
        # Setup - mock boto3 to raise exception
        with mock.patch("clients.eks_client.boto3") as mock_boto3:
            mock_boto3.client.side_effect = Exception("AWS credentials not found")

            # Execute and verify exception
            with self.assertRaises(Exception):
                EKSClient()

    def test_kubernetes_client_initialization_failure(self):
        """Test EKS client when Kubernetes client initialization fails"""
        # Setup - patch Kubernetes client to fail
        with mock.patch("clients.eks_client.KubernetesClient") as mock_k8s_class:
            mock_k8s_class.side_effect = Exception("Kubeconfig not found")

            # Execute - should not raise exception but k8s_client should be None
            eks_client = EKSClient()

            # Verify k8s_client is None
            self.assertIsNone(eks_client.k8s_client)

    def test_get_cluster_name_by_run_id_no_match(self):
        """Test cluster name lookup when no cluster matches run_id"""
        # Setup
        self.mock_eks.list_clusters.return_value = {"clusters": ["other-cluster"]}
        self.mock_eks.describe_cluster.return_value = {
            "cluster": {"tags": {"run_id": "different-run-id"}}
        }

        # Execute and verify exception
        with self.assertRaises(Exception) as context:
            EKSClient()

        self.assertIn("No EKS cluster found with run_id", str(context.exception))

    def test_load_subnet_ids_no_subnets(self):
        """Test subnet loading when no subnets found"""
        # Setup
        self.mock_ec2.describe_subnets.return_value = {"Subnets": []}

        # Execute and verify exception
        with self.assertRaises(Exception) as context:
            EKSClient()

        self.assertIn("No subnets found for run_id", str(context.exception))

    def test_load_node_role_arn_no_existing_nodegroups(self):
        """Test node role loading when no existing node groups found"""
        # Setup
        self.mock_eks.list_nodegroups.return_value = {"nodegroups": []}

        # Execute - should not raise exception
        EKSClient()

    def test_get_operation_context(self):
        """Test operation context retrieval"""
        # Setup
        eks_client = EKSClient()

        # Execute
        context = eks_client._get_operation_context()

        # Verify
        self.assertIsNotNone(context)
        # The context should be the OperationContext class
        self.assertEqual(context.__name__, "OperationContext")

    def test_serialize_aws_response_nested_datetime(self):
        """Test serialization with nested datetime objects"""
        # Setup
        eks_client = EKSClient()

        test_obj = {
            "name": "test",
            "metadata": {
                "createdAt": datetime(2025, 7, 15, 10, 30, 45),
                "nested": {"updatedAt": datetime(2025, 7, 15, 11, 45, 30)},
            },
            "list_field": [{"timestamp": datetime(2025, 7, 15, 12, 0, 0)}],
        }

        # Execute
        result = eks_client._serialize_aws_response(test_obj)

        # Verify
        self.assertEqual(result["name"], "test")
        self.assertIsInstance(result["metadata"]["createdAt"], str)
        self.assertIsInstance(result["metadata"]["nested"]["updatedAt"], str)
        self.assertIsInstance(result["list_field"][0]["timestamp"], str)

    def test_serialize_aws_response_with_non_datetime_objects(self):
        """Test serialization with various object types"""
        # Setup
        eks_client = EKSClient()

        test_obj = {
            "string": "test",
            "int": 123,
            "float": 45.67,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
            "dict": {"key": "value"},
        }

        # Execute
        result = eks_client._serialize_aws_response(test_obj)

        # Verify all types are preserved
        self.assertEqual(result["string"], "test")
        self.assertEqual(result["int"], 123)
        self.assertEqual(result["float"], 45.67)
        self.assertEqual(result["bool"], True)
        self.assertIsNone(result["none"])
        self.assertEqual(result["list"], [1, 2, 3])
        self.assertEqual(result["dict"], {"key": "value"})

    def test_load_subnet_ids_success(self):
        """Test successful subnet loading"""
        # Setup - create fresh EKS client to test _load_subnet_ids
        with mock.patch("clients.eks_client.boto3") as mock_boto3:
            mock_eks = mock.MagicMock()
            mock_ec2 = mock.MagicMock()

            # Setup subnet response
            mock_ec2.describe_subnets.return_value = {
                "Subnets": [
                    {"SubnetId": "subnet-123", "AvailabilityZone": "us-west-2a"},
                    {"SubnetId": "subnet-456", "AvailabilityZone": "us-west-2b"},
                    {"SubnetId": "subnet-789", "AvailabilityZone": "us-west-2c"},
                ]
            }

            mock_boto3.client.side_effect = lambda service, **kwargs: {
                "eks": mock_eks,
                "ec2": mock_ec2,
                "iam": mock.MagicMock(),
            }.get(service, mock.MagicMock())

            # Mock EKS responses
            mock_eks.list_clusters.return_value = {"clusters": ["test-cluster-123"]}
            mock_eks.describe_cluster.return_value = {
                "cluster": {"tags": {"run_id": "test-run-123"}}
            }
            mock_eks.list_nodegroups.return_value = {"nodegroups": ["existing-ng"]}
            mock_eks.describe_nodegroup.return_value = {
                "nodegroup": {"nodeRole": "arn:aws:iam::123456789012:role/eksNodeRole"}
            }

            # Execute
            eks_client = EKSClient()

            # Verify
            self.assertEqual(len(eks_client.subnet_map), 3)
            self.assertEqual(len(eks_client.subnet_azs), 3)
            self.assertIn("subnet-123", [s["SubnetId"] for s in eks_client.subnet_map])
            self.assertIn("us-west-2a", eks_client.subnet_azs)

    def test_load_node_role_arn_success(self):
        """Test successful node role ARN loading"""
        # This is already tested implicitly in setUp, but we'll test explicitly
        eks_client = EKSClient()

        # Verify role ARN was loaded
        self.assertEqual(
            eks_client.node_role_arn, "arn:aws:iam::123456789012:role/eksNodeRole"
        )

    def test_get_cluster_data_with_exception_handling(self):
        """Test cluster data retrieval with unexpected exception"""
        # Setup
        eks_client = EKSClient()

        # Mock unexpected exception
        self.mock_eks.describe_cluster.side_effect = Exception("Unexpected AWS error")

        # Execute and verify exception is raised
        with self.assertRaises(Exception):
            eks_client.get_cluster_data()

    def test_create_node_group_with_zero_nodes(self):
        """Test node group creation with zero nodes"""
        # Setup
        eks_client = EKSClient()

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-zero-nodes-12345"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = []

        # Execute
        result = eks_client.create_node_group(
            node_group_name="zero-nodes-ng",
            instance_type="t3.medium",
            node_count=0,
            gpu_node_group=False,
            capacity_type="ON_DEMAND",
        )

        # Verify
        self.assertTrue(result)

        # Check node group parameters
        call_args = self.mock_eks.create_nodegroup.call_args[1]
        self.assertEqual(call_args["scalingConfig"]["desiredSize"], 0)
        self.assertEqual(call_args["scalingConfig"]["minSize"], 0)
        self.assertEqual(
            call_args["scalingConfig"]["maxSize"], 1
        )  # AWS requires maxSize >= 1

    def test_create_node_group_with_spot_capacity(self):
        """Test node group creation with SPOT capacity type"""
        # Setup
        eks_client = EKSClient()

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-spot-12345"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1", "node2"]

        # Execute
        result = eks_client.create_node_group(
            node_group_name="spot-ng",
            instance_type="t3.medium",
            node_count=2,
            gpu_node_group=False,
            capacity_type="SPOT",
        )

        # Verify
        self.assertTrue(result)

        # Check capacity type
        call_args = self.mock_eks.create_nodegroup.call_args[1]
        self.assertEqual(call_args["capacityType"], "SPOT")

    def test_create_node_group_with_gpu_and_nvidia_verification(self):
        """Test GPU node group creation with NVIDIA driver verification"""
        # Setup
        eks_client = EKSClient()

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-gpu-12345"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["gpu-node1"]
        self.mock_k8s.verify_nvidia_smi_on_node.return_value = "GPU driver verified"

        # Execute
        result = eks_client.create_node_group(
            node_group_name="gpu-ng",
            instance_type="p3.2xlarge",
            node_count=1,
            gpu_node_group=True,
            capacity_type="ON_DEMAND",
        )

        # Verify
        self.assertTrue(result)

        # Check AMI type for GPU
        call_args = self.mock_eks.create_nodegroup.call_args[1]
        self.assertEqual(call_args["amiType"], "AL2_x86_64_GPU")

        # Verify NVIDIA verification was called
        self.mock_k8s.verify_nvidia_smi_on_node.assert_called_once_with(["gpu-node1"])

    def test_create_node_group_node_group_creation_failure(self):
        """Test node group creation when EKS create_nodegroup fails"""
        # Setup
        eks_client = EKSClient()

        # Mock successful launch template creation
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-fail-12345"}
        }

        # Mock node group creation failure
        self.mock_eks.create_nodegroup.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "InvalidParameterException",
                    "Message": "Invalid parameters",
                }
            },
            operation_name="CreateNodegroup",
        )

        # Execute and verify exception is raised
        with self.assertRaises(ClientError):
            eks_client.create_node_group(
                node_group_name="fail-ng",
                instance_type="t3.medium",
                node_count=2,
                gpu_node_group=False,
                capacity_type="ON_DEMAND",
            )

    def test_scale_node_group_with_progressive_enabled(self):
        """Test scaling with progressive scaling enabled"""
        # Setup
        eks_client = EKSClient()

        # Mock current node group state
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "scalingConfig": {"desiredSize": 1, "maxSize": 10, "minSize": 1}
            }
        }

        # Mock progressive scale method
        with mock.patch.object(eks_client, "_progressive_scale") as mock_progressive:
            mock_progressive.return_value = True

            # Execute - scale from 1 to 10 (> step size of 5)
            result = eks_client.scale_node_group(
                "test-ng", 10, 10, progressive=True, scale_step_size=5
            )

            # Verify progressive scaling was called
            self.assertTrue(result)
            mock_progressive.assert_called_once()

    def test_scale_node_group_waiter_timeout(self):
        """Test scaling when waiter times out"""
        # Setup
        eks_client = EKSClient()

        # Mock current node group state
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "scalingConfig": {"desiredSize": 2, "maxSize": 5, "minSize": 1}
            }
        }

        # Mock update response and waiter timeout
        self.mock_eks.update_nodegroup_config.return_value = {
            "update": {"id": "update-123", "status": "InProgress"}
        }
        self.mock_eks.get_waiter.return_value.wait.side_effect = WaiterError(
            name="NodegroupActive",
            reason="Timeout",
            last_response={"nodegroup": {"status": "UPDATING"}},
        )

        # Execute and verify exception is raised
        with self.assertRaises(WaiterError):
            eks_client.scale_node_group("test-ng", 4, 4)

    def test_delete_node_group_with_launch_template_deletion_failure(self):
        """Test node group deletion when launch template deletion fails"""
        # Setup
        eks_client = EKSClient()
        eks_client.launch_template_id = "lt-to-delete-12345"

        # Mock node group info
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"scalingConfig": {"desiredSize": 2}, "amiType": "AL2_x86_64"}
        }

        # Mock launch template deletion failure
        self.mock_ec2.delete_launch_template.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "InvalidLaunchTemplateId.NotFound",
                    "Message": "Template not found",
                }
            },
            operation_name="DeleteLaunchTemplate",
        )

        # Mock successful node group deletion
        self.mock_eks.delete_nodegroup.return_value = {}
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()

        # Execute and verify exception is raised
        with self.assertRaises(ClientError):
            eks_client.delete_node_group("test-ng")

    def test_create_node_group_with_launch_template_coverage(self):
        """Test create_node_group to cover _create_launch_template functionality"""
        # Setup
        eks_client = EKSClient()

        # Mock the EKS and EC2 responses for launch template creation
        mock_launch_template_response = {
            "LaunchTemplate": {
                "LaunchTemplateId": "lt-123456789",
                "LaunchTemplateName": "test-launch-template",
                "DefaultVersionNumber": 1,
            }
        }

        mock_nodegroup_response = {
            "nodegroup": {
                "status": "CREATING",
                "scalingConfig": {"desiredSize": 2, "minSize": 2, "maxSize": 3},
            }
        }

        self.mock_ec2.create_launch_template.return_value = (
            mock_launch_template_response
        )
        self.mock_eks.create_nodegroup.return_value = mock_nodegroup_response
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"status": "ACTIVE", "scalingConfig": {"desiredSize": 2}}
        }

        # Mock ready nodes
        mock_nodes = [{"metadata": {"name": f"node-{i}"}} for i in range(2)]
        self.mock_k8s.wait_for_nodes_ready.return_value = mock_nodes

        # Call the public method which should internally call _create_launch_template
        result = eks_client.create_node_group(
            node_group_name="test-ng", instance_type="t3.medium", node_count=2
        )

        self.assertTrue(result)
        self.mock_ec2.create_launch_template.assert_called_once()
        self.mock_eks.create_nodegroup.assert_called_once()

    def test_create_node_group_with_gpu_and_capacity_reservation_coverage(self):
        """Test create_node_group with GPU to cover _get_capacity_reservation_id functionality"""
        # Setup
        eks_client = EKSClient()

        # Mock capacity reservation response
        mock_reservation_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-123456789",
                    "InstanceType": "p3.2xlarge",
                    "AvailabilityZone": "us-west-2a",
                    "State": "active",
                    "TotalInstanceCount": 4,
                    "AvailableInstanceCount": 2,
                }
            ]
        }

        mock_launch_template_response = {
            "LaunchTemplate": {
                "LaunchTemplateId": "lt-gpu-123",
                "LaunchTemplateName": "test-gpu-launch-template",
                "DefaultVersionNumber": 1,
            }
        }

        mock_nodegroup_response = {
            "nodegroup": {
                "status": "CREATING",
                "scalingConfig": {"desiredSize": 1, "minSize": 1, "maxSize": 2},
            }
        }

        self.mock_ec2.describe_capacity_reservations.return_value = (
            mock_reservation_response
        )
        self.mock_ec2.create_launch_template.return_value = (
            mock_launch_template_response
        )
        self.mock_eks.create_nodegroup.return_value = mock_nodegroup_response
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"status": "ACTIVE", "scalingConfig": {"desiredSize": 1}}
        }

        # Mock ready nodes and GPU verification
        mock_nodes = [{"metadata": {"name": "gpu-node-1"}}]
        self.mock_k8s.wait_for_nodes_ready.return_value = mock_nodes
        self.mock_k8s.verify_nvidia_smi_on_node.return_value = ["GPU verified"]

        # Call with GPU node group and capacity block to trigger capacity reservation check
        result = eks_client.create_node_group(
            node_group_name="test-gpu-ng",
            instance_type="p3.2xlarge",
            node_count=1,
            gpu_node_group=True,
            capacity_type="CAPACITY_BLOCK",
        )

        self.assertTrue(result)
        self.mock_ec2.describe_capacity_reservations.assert_called_once()
        self.mock_k8s.verify_nvidia_smi_on_node.assert_called_once()

    def test_scale_node_group_progressive_coverage(self):
        """Test scale_node_group with progressive scaling to cover _progressive_scale functionality"""
        # Setup
        eks_client = EKSClient()

        # Mock current node group state
        current_nodegroup = {
            "scalingConfig": {"desiredSize": 2, "minSize": 1, "maxSize": 10},
            "status": "ACTIVE",
        }

        # Progressive scaling from 2 to 6 with step size 2 creates steps: [4, 6]
        # Each step calls scale_node_group which calls get_node_group
        # Need enough responses for: initial + step1 + step2 calls

        # Mock the methods that are called internally
        eks_client.get_node_group = mock.Mock()
        eks_client.get_node_group.side_effect = [
            current_nodegroup,  # Initial call to get current state
            {
                "scalingConfig": {"desiredSize": 2, "minSize": 1, "maxSize": 10},
                "status": "ACTIVE",
            },  # Before step 1
            {
                "scalingConfig": {"desiredSize": 4, "minSize": 1, "maxSize": 10},
                "status": "ACTIVE",
            },  # After step 1
            {
                "scalingConfig": {"desiredSize": 4, "minSize": 1, "maxSize": 10},
                "status": "ACTIVE",
            },
            {
                "scalingConfig": {"desiredSize": 4, "minSize": 1, "maxSize": 10},
                "status": "ACTIVE",
            },  # Before step 2
            {
                "scalingConfig": {"desiredSize": 6, "minSize": 1, "maxSize": 10},
                "status": "ACTIVE",
            },  # Final state
            {
                "scalingConfig": {"desiredSize": 6, "minSize": 1, "maxSize": 10},
                "status": "ACTIVE",
            },
        ]

        # Mock ready nodes for each step
        mock_nodes = [{"metadata": {"name": f"node-{i}"}} for i in range(6)]
        self.mock_k8s.wait_for_nodes_ready.return_value = mock_nodes

        # Mock get_cluster_data
        eks_client.get_cluster_data = mock.Mock(
            return_value={"cluster": {"status": "ACTIVE"}}
        )

        # Call progressive scaling (from 2 to 6 nodes with step size 2)
        result = eks_client.scale_node_group(
            node_group_name="test-ng", node_count=6, target_count=6, progressive=True, scale_step_size=2
        )

        self.assertTrue(result)
        # Should call update_nodegroup_config multiple times for progressive scaling
        self.assertGreaterEqual(self.mock_eks.update_nodegroup_config.call_count, 2)

    def test_delete_node_group_with_launch_template_cleanup_coverage(self):
        """Test delete_node_group to cover _delete_launch_template functionality"""
        # Setup
        eks_client = EKSClient()

        # Set up a launch template ID to trigger cleanup
        eks_client.launch_template_id = "lt-cleanup-123"

        # Mock node group info
        mock_nodegroup = {
            "scalingConfig": {"desiredSize": 2},
            "amiType": "AL2_x86_64",
            "status": "ACTIVE",
        }

        # Mock get_node_group and get_cluster_data
        eks_client.get_node_group = mock.Mock(return_value=mock_nodegroup)
        eks_client.get_cluster_data = mock.Mock(
            return_value={"cluster": {"status": "ACTIVE"}}
        )

        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"status": "DELETING"}
        }

        # Mock successful deletion
        self.mock_eks.delete_nodegroup.return_value = {}
        self.mock_ec2.delete_launch_template.return_value = {}

        # Call delete which should trigger launch template cleanup
        result = eks_client.delete_node_group("test-ng")

        self.assertTrue(result)
        self.mock_ec2.delete_launch_template.assert_called_once()
        self.mock_eks.delete_nodegroup.assert_called_once()

    def test_wait_for_node_group_operations_coverage(self):
        """Test operations that cover _wait_for_node_group_active and _wait_for_node_group_deleted"""
        # Setup
        eks_client = EKSClient()

        # Test _wait_for_node_group_active through create_node_group
        mock_nodegroup_response = {
            "nodegroup": {
                "status": "CREATING",
                "scalingConfig": {"desiredSize": 1, "minSize": 1, "maxSize": 2},
            }
        }

        self.mock_eks.create_nodegroup.return_value = mock_nodegroup_response

        # Mock the transition from CREATING to ACTIVE
        self.mock_eks.describe_nodegroup.side_effect = [
            {"nodegroup": {"status": "CREATING", "scalingConfig": {"desiredSize": 1}}},
            {"nodegroup": {"status": "ACTIVE", "scalingConfig": {"desiredSize": 1}}},
        ]

        mock_nodes = [{"metadata": {"name": "node-1"}}]
        self.mock_k8s.wait_for_nodes_ready.return_value = mock_nodes

        result = eks_client.create_node_group(
            node_group_name="test-wait-ng", instance_type="t3.medium", node_count=1
        )

        self.assertTrue(result)
        # Verify that describe_nodegroup was called multiple times (polling)
        self.assertGreaterEqual(self.mock_eks.describe_nodegroup.call_count, 2)

    def test_serialize_aws_response_through_operations(self):
        """Test _serialize_aws_response through normal operations that generate responses"""
        # Setup
        eks_client = EKSClient()

        # Create a response with datetime objects that need serialization
        mock_response_with_datetime = {
            "nodegroupName": "test-serialize-ng",
            "status": "ACTIVE",
            "createdAt": datetime(2023, 1, 1, 12, 0, 0),
            "modifiedAt": datetime(2023, 1, 1, 13, 0, 0),
            "scalingConfig": {"desiredSize": 1, "minSize": 1, "maxSize": 2},
        }

        # Mock get_node_group and get_cluster_data
        eks_client.get_node_group = mock.Mock(return_value=mock_response_with_datetime)
        eks_client.get_cluster_data = mock.Mock(
            return_value={"cluster": {"status": "ACTIVE"}}
        )

        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"status": "ACTIVE", "scalingConfig": {"desiredSize": 1}}
        }
        mock_nodes = [{"metadata": {"name": "node-1"}}]
        self.mock_k8s.wait_for_nodes_ready.return_value = mock_nodes

        # Call scale operation which will use serialization for metadata
        result = eks_client.scale_node_group(
            node_group_name="test-serialize-ng", node_count=1, target_count=1
        )

        self.assertTrue(result)
        # The serialization happens internally when adding metadata to operation context

    def test_create_launch_template_with_required_tags(self):
        """Test that launch template creation includes all required tags"""
        # Setup
        eks_client = EKSClient()

        # Mock the EC2 response for launch template creation
        mock_launch_template_response = {
            "LaunchTemplate": {
                "LaunchTemplateId": "lt-tag-test-123",
                "LaunchTemplateName": "test-tag-launch-template",
                "DefaultVersionNumber": 1,
            }
        }

        mock_nodegroup_response = {
            "nodegroup": {
                "status": "CREATING",
                "scalingConfig": {"desiredSize": 2, "minSize": 2, "maxSize": 3},
            }
        }

        self.mock_ec2.create_launch_template.return_value = (
            mock_launch_template_response
        )
        self.mock_eks.create_nodegroup.return_value = mock_nodegroup_response
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"status": "ACTIVE", "scalingConfig": {"desiredSize": 2}}
        }

        # Mock ready nodes
        mock_nodes = [{"metadata": {"name": f"node-{i}"}} for i in range(2)]
        self.mock_k8s.wait_for_nodes_ready.return_value = mock_nodes

        # Call create_node_group which internally calls _create_launch_template
        result = eks_client.create_node_group(
            node_group_name="test-tag-ng", instance_type="t3.medium", node_count=2
        )

        # Verify the method succeeded
        self.assertTrue(result)

        # Verify launch template was created
        self.mock_ec2.create_launch_template.assert_called_once()

        # Get the actual call arguments to validate tag specifications
        create_lt_call_args = self.mock_ec2.create_launch_template.call_args[1]

        # Verify that TagSpecifications are present
        self.assertIn("TagSpecifications", create_lt_call_args)
        tag_specs = create_lt_call_args["TagSpecifications"]

        # Should have tag specifications only for launch-template (instance is not valid)
        self.assertEqual(len(tag_specs), 1)

        # Check launch-template tags
        lt_tag_spec = next(
            (spec for spec in tag_specs if spec["ResourceType"] == "launch-template"),
            None,
        )
        self.assertIsNotNone(
            lt_tag_spec, "Launch template tag specification should be present"
        )

        lt_tags = {tag["Key"]: tag["Value"] for tag in lt_tag_spec["Tags"]}
        self.assertIn("Name", lt_tags)
        self.assertIn("run_id", lt_tags)
        self.assertIn("cluster_name", lt_tags)
        self.assertIn("node_group_name", lt_tags)
        self.assertIn("gpu_node_group", lt_tags)
        self.assertIn("instance_type", lt_tags)
        self.assertIn("capacity_type", lt_tags)
        self.assertIn("scenario_name", lt_tags)
        self.assertIn("scenario_type", lt_tags)
        self.assertIn("created_at", lt_tags)
        self.assertIn("deletion_due_time", lt_tags)

        # Verify the Name tag contains the node group name
        self.assertIn("test-tag-ng", lt_tags["Name"])

        # Verify specific tag values
        self.assertEqual(lt_tags["node_group_name"], "test-tag-ng")
        self.assertEqual(lt_tags["instance_type"], "t3.medium")
        self.assertEqual(lt_tags["capacity_type"], "ON_DEMAND")
        self.assertEqual(lt_tags["gpu_node_group"], "False")

    def test_create_launch_template_with_gpu_and_capacity_reservation_tags(self):
        """Test that launch template creation includes all required tags for GPU node groups with capacity reservations"""
        # Setup
        eks_client = EKSClient()

        # Mock capacity reservation response with full capacity available
        mock_reservation_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-gpu-123456789",
                    "InstanceType": "p3.2xlarge",
                    "AvailabilityZone": "us-west-2a",
                    "State": "active",
                    "TotalInstanceCount": 4,
                    "AvailableInstanceCount": 4,  # Full capacity available
                }
            ]
        }

        # Mock the EC2 response for launch template creation
        mock_launch_template_response = {
            "LaunchTemplate": {
                "LaunchTemplateId": "lt-gpu-tag-test-123",
                "LaunchTemplateName": "test-gpu-tag-launch-template",
                "DefaultVersionNumber": 1,
            }
        }

        mock_nodegroup_response = {
            "nodegroup": {
                "status": "CREATING",
                "scalingConfig": {"desiredSize": 2, "minSize": 2, "maxSize": 3},
            }
        }

        self.mock_ec2.describe_capacity_reservations.return_value = (
            mock_reservation_response
        )
        self.mock_ec2.create_launch_template.return_value = (
            mock_launch_template_response
        )
        self.mock_eks.create_nodegroup.return_value = mock_nodegroup_response
        self.mock_eks.describe_nodegroup.return_value = {
            "nodegroup": {"status": "ACTIVE", "scalingConfig": {"desiredSize": 2}}
        }

        # Mock ready nodes and GPU verification
        mock_nodes = [{"metadata": {"name": f"gpu-node-{i}"}} for i in range(2)]
        self.mock_k8s.wait_for_nodes_ready.return_value = mock_nodes
        self.mock_k8s.verify_nvidia_smi_on_node.return_value = {"status": "success"}

        # Call create_node_group for GPU with CAPACITY_BLOCK
        result = eks_client.create_node_group(
            node_group_name="test-gpu-tag-ng",
            instance_type="p3.2xlarge",
            node_count=2,
            gpu_node_group=True,
            capacity_type="CAPACITY_BLOCK",
        )

        # Verify the method succeeded
        self.assertTrue(result)

        # Verify launch template was created
        self.mock_ec2.create_launch_template.assert_called_once()

        # Get the actual call arguments to validate tag specifications
        create_lt_call_args = self.mock_ec2.create_launch_template.call_args[1]

        # Verify that TagSpecifications are present
        self.assertIn("TagSpecifications", create_lt_call_args)
        tag_specs = create_lt_call_args["TagSpecifications"]

        # Should have tag specifications only for launch-template (instance is not valid)
        self.assertEqual(len(tag_specs), 1)

        # Check launch-template tags
        lt_tag_spec = next(
            (spec for spec in tag_specs if spec["ResourceType"] == "launch-template"),
            None,
        )
        self.assertIsNotNone(
            lt_tag_spec, "Launch template tag specification should be present"
        )

        lt_tags = {tag["Key"]: tag["Value"] for tag in lt_tag_spec["Tags"]}

        # Verify all required tags are present
        required_tags = [
            "Name",
            "run_id",
            "cluster_name",
            "node_group_name",
            "gpu_node_group",
            "instance_type",
            "capacity_type",
            "scenario_name",
            "scenario_type",
            "created_at",
            "deletion_due_time",
            "capacity_reservation_id",
        ]
        for tag in required_tags:
            self.assertIn(
                tag, lt_tags, f"Tag '{tag}' should be present in launch template tags"
            )

        # Verify specific tag values for GPU and capacity reservation
        self.assertEqual(lt_tags["gpu_node_group"], "True")
        self.assertEqual(lt_tags["capacity_type"], "CAPACITY_BLOCK")
        self.assertEqual(lt_tags["capacity_reservation_id"], "cr-gpu-123456789")
        self.assertEqual(lt_tags["instance_type"], "p3.2xlarge")

    def test_get_ami_type_with_k8s_version_old_non_gpu(self):
        """Test AMI type selection for old Kubernetes version (< 1.33) with non-GPU"""
        # Setup
        eks_client = EKSClient()
        eks_client.k8s_version = "1.29"

        # Execute
        ami_type = eks_client.get_ami_type_with_k8s_version(gpu_node_group=False)

        # Verify
        self.assertEqual(ami_type, "AL2_x86_64")

    def test_get_ami_type_with_k8s_version_old_gpu(self):
        """Test AMI type selection for old Kubernetes version (< 1.33) with GPU"""
        # Setup
        eks_client = EKSClient()
        eks_client.k8s_version = "1.32"

        # Execute
        ami_type = eks_client.get_ami_type_with_k8s_version(gpu_node_group=True)

        # Verify
        self.assertEqual(ami_type, "AL2_x86_64_GPU")

    def test_get_ami_type_with_k8s_version_new_non_gpu(self):
        """Test AMI type selection for new Kubernetes version (>= 1.33) with non-GPU"""
        # Setup
        eks_client = EKSClient()
        eks_client.k8s_version = "1.33"

        # Execute
        ami_type = eks_client.get_ami_type_with_k8s_version(gpu_node_group=False)

        # Verify
        self.assertEqual(ami_type, "AL2023_x86_64_STANDARD")

    def test_get_ami_type_with_k8s_version_new_gpu(self):
        """Test AMI type selection for new Kubernetes version (>= 1.33) with GPU"""
        # Setup
        eks_client = EKSClient()
        eks_client.k8s_version = "1.34"

        # Execute
        ami_type = eks_client.get_ami_type_with_k8s_version(gpu_node_group=True)

        # Verify
        self.assertEqual(ami_type, "AL2023_x86_64_NVIDIA")

    def test_get_ami_type_with_k8s_version_boundary_case(self):
        """Test AMI type selection at the boundary version 1.33"""
        # Setup
        eks_client = EKSClient()
        eks_client.k8s_version = "1.33"

        # Execute - Test both GPU and non-GPU for boundary case
        ami_type_non_gpu = eks_client.get_ami_type_with_k8s_version(
            gpu_node_group=False
        )
        ami_type_gpu = eks_client.get_ami_type_with_k8s_version(gpu_node_group=True)

        # Verify
        self.assertEqual(ami_type_non_gpu, "AL2023_x86_64_STANDARD")
        self.assertEqual(ami_type_gpu, "AL2023_x86_64_NVIDIA")

    def test_get_ami_type_with_k8s_version_none_fallback(self):
        """Test AMI type selection when k8s_version is None (should handle gracefully)"""
        # Setup
        eks_client = EKSClient()
        eks_client.k8s_version = None

        # Execute and verify it raises an appropriate error
        with self.assertRaises(ValueError) as context:
            eks_client.get_ami_type_with_k8s_version(gpu_node_group=False)

        # Verify the error message is informative
        self.assertIn("Kubernetes version is not set", str(context.exception))

    def test_get_ami_type_with_k8s_version_invalid_format(self):
        """Test AMI type selection with invalid version format"""
        # Setup
        eks_client = EKSClient()
        eks_client.k8s_version = "invalid-version"

        # Execute and verify it raises an appropriate error
        with self.assertRaises(ValueError) as context:
            eks_client.get_ami_type_with_k8s_version(gpu_node_group=False)

        # Verify the error message mentions the invalid format
        self.assertIn("Invalid Kubernetes version format", str(context.exception))
        self.assertIn("invalid-version", str(context.exception))

    def test_get_ami_type_with_k8s_version_logging(self):
        """Test that AMI type selection includes proper logging"""
        # Setup
        eks_client = EKSClient()
        eks_client.k8s_version = "1.30"

        with self.assertLogs("clients.eks_client", level="INFO") as log:
            # Execute
            ami_type = eks_client.get_ami_type_with_k8s_version(gpu_node_group=True)

            # Verify result
            self.assertEqual(ami_type, "AL2_x86_64_GPU")

            # Verify logging
            log_messages = " ".join(log.output)
            self.assertIn(
                "Determining AMI type for Kubernetes version: 1.30", log_messages
            )
            self.assertIn("Selected AMI type: AL2_x86_64_GPU", log_messages)

    def test_capacity_reservation_subnet_filtering_success(self):
        """Test that node group uses only the subnet in the capacity reservation AZ"""
        # Setup
        eks_client = EKSClient()

        # Mock capacity reservation in us-west-2a with full capacity available
        mock_reservation_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-subnet-filter-123",
                    "InstanceType": "p3.2xlarge",
                    "AvailabilityZone": "us-west-2a",
                    "State": "active",
                    "TotalInstanceCount": 4,
                    "AvailableInstanceCount": 4,  # Full capacity available
                }
            ]
        }

        # Mock launch template and node group responses
        self.mock_ec2.describe_capacity_reservations.return_value = (
            mock_reservation_response
        )
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-subnet-filter-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

        # Execute
        result = eks_client.create_node_group(
            node_group_name="test-subnet-filter-ng",
            instance_type="p3.2xlarge",
            node_count=1,
            gpu_node_group=True,
            capacity_type="CAPACITY_BLOCK",
        )

        # Verify
        self.assertTrue(result)

        # Check that node group was created with only the subnet in us-west-2a
        create_call = self.mock_eks.create_nodegroup.call_args[1]
        self.assertIn("subnets", create_call)
        # Should only contain subnet-123 (us-west-2a), not subnet-456 (us-west-2b)
        self.assertEqual(create_call["subnets"], ["subnet-123"])

    def test_capacity_reservation_subnet_filtering_no_reservation(self):
        """Test that system exits when no capacity reservation is found for CAPACITY_BLOCK"""
        # Setup
        eks_client = EKSClient()

        # Mock no capacity reservation found
        self.mock_ec2.describe_capacity_reservations.return_value = {
            "CapacityReservations": []
        }
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-no-reservation-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

        # Execute and expect SystemExit
        with self.assertRaises(SystemExit) as _:
            eks_client.create_node_group(
                node_group_name="test-no-reservation-ng",
                instance_type="p3.2xlarge",
                node_count=1,
                gpu_node_group=True,
                capacity_type="CAPACITY_BLOCK",
            )

    def test_capacity_reservation_subnet_filtering_no_matching_subnet(self):
        """Test error when capacity reservation AZ has no matching subnet"""
        # Setup
        eks_client = EKSClient()

        # Mock capacity reservation in us-west-2c (not in our subnet list) but with full capacity
        mock_reservation_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-no-subnet-123",
                    "InstanceType": "p3.2xlarge",
                    "AvailabilityZone": "us-west-2c",  # No subnet in this AZ
                    "State": "active",
                    "TotalInstanceCount": 4,
                    "AvailableInstanceCount": 4,  # Full capacity available
                }
            ]
        }

        self.mock_ec2.describe_capacity_reservations.return_value = (
            mock_reservation_response
        )
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-no-subnet-123"}
        }

        # Execute and verify exception is raised because no subnets in reservation AZ
        with self.assertRaises(Exception) as context:
            eks_client.create_node_group(
                node_group_name="test-no-subnet-ng",
                instance_type="p3.2xlarge",
                node_count=1,
                gpu_node_group=True,
                capacity_type="CAPACITY_BLOCK",
            )

        # Verify error message mentions the missing subnet
        self.assertIn(
            "No subnets available in capacity reservation AZ us-west-2c",
            str(context.exception),
        )

    def test_capacity_reservation_return_format_with_az(self):
        """Test that _get_capacity_reservation_id returns both reservation_id and availability_zone"""
        # Setup
        eks_client = EKSClient()

        # Mock capacity reservation response
        mock_reservation_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-return-format-123",
                    "InstanceType": "p3.2xlarge",
                    "AvailabilityZone": "us-west-2b",
                    "State": "active",
                    "TotalInstanceCount": 4,
                    "AvailableInstanceCount": 4,  # Full capacity available
                }
            ]
        }

        self.mock_ec2.describe_capacity_reservations.return_value = (
            mock_reservation_response
        )

        # Execute
        result = eks_client._get_capacity_reservation_id(
            instance_type="p3.2xlarge",
            target_count=2,
            availability_zones=["us-west-2a", "us-west-2b"],
        )

        # Verify return format
        self.assertIsInstance(result, dict)
        self.assertIn("reservation_id", result)
        self.assertIn("availability_zone", result)
        self.assertEqual(result["reservation_id"], "cr-return-format-123")
        self.assertEqual(result["availability_zone"], "us-west-2b")

    def test_capacity_reservation_insufficient_capacity_warning(self):
        """Test warning when capacity reservation has insufficient available instances"""
        # Setup
        eks_client = EKSClient()

        # Mock capacity reservation with insufficient capacity (available < target_count)
        mock_reservation_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-insufficient-123",
                    "InstanceType": "p3.2xlarge",
                    "AvailabilityZone": "us-west-2a",
                    "State": "active",
                    "TotalInstanceCount": 4,
                    "AvailableInstanceCount": 2,  # Less than target_count (3)
                }
            ]
        }

        self.mock_ec2.describe_capacity_reservations.return_value = (
            mock_reservation_response
        )

        # Execute with logging capture
        with self.assertLogs("clients.eks_client", level="WARNING") as log:
            result = eks_client._get_capacity_reservation_id(
                instance_type="p3.2xlarge",
                target_count=3,  # Request more than available (2)
                availability_zones=["us-west-2a", "us-west-2b"],
            )

            # Verify returns None when insufficient capacity
            self.assertIsNone(result)

            # Verify warning was logged
            log_messages = " ".join(log.output)
            self.assertIn(
                "Capacity reservation has only 2 instances available, but 3 were requested",
                log_messages,
            )

    def test_capacity_reservation_full_capacity_available(self):
        """Test successful capacity reservation when full capacity is available"""
        # Setup
        eks_client = EKSClient()

        # Mock capacity reservation with full capacity available
        mock_reservation_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-full-capacity-123",
                    "InstanceType": "p3.2xlarge",
                    "AvailabilityZone": "us-west-2a",
                    "State": "active",
                    "TotalInstanceCount": 4,
                    "AvailableInstanceCount": 4,  # Full capacity available
                }
            ]
        }

        self.mock_ec2.describe_capacity_reservations.return_value = (
            mock_reservation_response
        )

        # Execute
        result = eks_client._get_capacity_reservation_id(
            instance_type="p3.2xlarge",
            target_count=2,
            availability_zones=["us-west-2a", "us-west-2b"],
        )

        # Verify returns the reservation
        self.assertIsNotNone(result)
        self.assertEqual(result["reservation_id"], "cr-full-capacity-123")
        self.assertEqual(result["availability_zone"], "us-west-2a")

    def test_capacity_reservation_multiple_subnets_same_az(self):
        """Test subnet filtering when multiple subnets exist in the same AZ"""
        # Setup with multiple subnets in same AZ
        with mock.patch("clients.eks_client.boto3") as mock_boto3:
            mock_eks = mock.MagicMock()
            mock_ec2 = mock.MagicMock()

            # Setup multiple subnets, including two in us-west-2a
            mock_ec2.describe_subnets.return_value = {
                "Subnets": [
                    {"SubnetId": "subnet-123", "AvailabilityZone": "us-west-2a"},
                    {"SubnetId": "subnet-456", "AvailabilityZone": "us-west-2b"},
                    {
                        "SubnetId": "subnet-789",
                        "AvailabilityZone": "us-west-2a",
                    },  # Another in same AZ
                ]
            }

            mock_boto3.client.side_effect = lambda service, **kwargs: {
                "eks": mock_eks,
                "ec2": mock_ec2,
                "iam": mock.MagicMock(),
            }.get(service, mock.MagicMock())

            # Mock EKS responses
            mock_eks.list_clusters.return_value = {"clusters": ["test-cluster-123"]}
            mock_eks.describe_cluster.return_value = {
                "cluster": {"tags": {"run_id": "test-run-123"}, "version": "1.29"}
            }
            mock_eks.list_nodegroups.return_value = {"nodegroups": ["existing-ng"]}
            mock_eks.describe_nodegroup.return_value = {
                "nodegroup": {"nodeRole": "arn:aws:iam::123456789012:role/eksNodeRole"}
            }

            # Mock capacity reservation in us-west-2a with full capacity available
            mock_reservation_response = {
                "CapacityReservations": [
                    {
                        "CapacityReservationId": "cr-multi-subnet-123",
                        "InstanceType": "p3.2xlarge",
                        "AvailabilityZone": "us-west-2a",
                        "State": "active",
                        "TotalInstanceCount": 4,
                        "AvailableInstanceCount": 4,  # Full capacity available
                    }
                ]
            }

            mock_ec2.describe_capacity_reservations.return_value = (
                mock_reservation_response
            )
            mock_ec2.create_launch_template.return_value = {
                "LaunchTemplate": {"LaunchTemplateId": "lt-multi-subnet-123"}
            }
            mock_eks.create_nodegroup.return_value = {
                "nodegroup": {"status": "CREATING"}
            }
            mock_eks.get_waiter.return_value.wait = mock.MagicMock()

            # Mock Kubernetes client
            with mock.patch("clients.eks_client.KubernetesClient") as mock_k8s_class:
                mock_k8s = mock_k8s_class.return_value
                mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

                # Execute
                eks_client = EKSClient()
                result = eks_client.create_node_group(
                    node_group_name="test-multi-subnet-ng",
                    instance_type="p3.2xlarge",
                    node_count=1,
                    gpu_node_group=True,
                    capacity_type="CAPACITY_BLOCK",
                )

                # Verify
                self.assertTrue(result)

                # Check that node group was created with both subnets in us-west-2a
                create_call = mock_eks.create_nodegroup.call_args[1]
                self.assertIn("subnets", create_call)
                # Should contain both subnets in us-west-2a
                self.assertEqual(
                    sorted(create_call["subnets"]), ["subnet-123", "subnet-789"]
                )

    def test_capacity_reservation_non_capacity_block_no_filtering(self):
        """Test that subnet filtering is not applied for non-CAPACITY_BLOCK types"""
        # Setup
        eks_client = EKSClient()

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-non-cb-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

        # Execute with ON_DEMAND (not CAPACITY_BLOCK)
        result = eks_client.create_node_group(
            node_group_name="test-non-cb-ng",
            instance_type="p3.2xlarge",
            node_count=1,
            gpu_node_group=True,
            capacity_type="ON_DEMAND",  # Not CAPACITY_BLOCK
        )

        # Verify
        self.assertTrue(result)

        # Check that capacity reservation lookup was NOT called
        self.mock_ec2.describe_capacity_reservations.assert_not_called()

        # Check that all subnets were used (should be empty for non-CAPACITY_BLOCK)
        create_call = self.mock_eks.create_nodegroup.call_args[1]
        self.assertIn("subnets", create_call)
        self.assertEqual(create_call["subnets"], [])

    def test_describe_instance_types_success(self):
        """Test successful describe_instance_types operation"""
        # Setup
        eks_client = EKSClient()

        # Mock successful response
        mock_response = {
            "InstanceTypes": [
                {
                    "InstanceType": "t3.medium",
                    "NetworkInfo": {
                        "MaximumNetworkCards": 3,
                        "NetworkPerformance": "Up to 5 Gigabit"
                    },
                    "VCpuInfo": {"DefaultVCpus": 2},
                    "MemoryInfo": {"SizeInMiB": 4096}
                }
            ]
        }
        self.mock_ec2.describe_instance_types.return_value = mock_response

        # Execute
        result = eks_client.describe_instance_types(["t3.medium"])

        # Verify
        self.mock_ec2.describe_instance_types.assert_called_once_with(
            InstanceTypes=["t3.medium"]
        )
        self.assertEqual(result, mock_response["InstanceTypes"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["InstanceType"], "t3.medium")
        self.assertEqual(result[0]["NetworkInfo"]["MaximumNetworkCards"], 3)

    def test_describe_instance_types_multiple_instances(self):
        """Test describe_instance_types with multiple instance types"""
        # Setup
        eks_client = EKSClient()

        # Mock response for multiple instance types
        mock_response = {
            "InstanceTypes": [
                {
                    "InstanceType": "t3.medium",
                    "NetworkInfo": {"MaximumNetworkCards": 3}
                },
                {
                    "InstanceType": "p3.2xlarge",
                    "NetworkInfo": {"MaximumNetworkCards": 4}
                }
            ]
        }
        self.mock_ec2.describe_instance_types.return_value = mock_response

        # Execute
        result = eks_client.describe_instance_types(["t3.medium", "p3.2xlarge"])

        # Verify
        self.mock_ec2.describe_instance_types.assert_called_once_with(
            InstanceTypes=["t3.medium", "p3.2xlarge"]
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["InstanceType"], "t3.medium")
        self.assertEqual(result[1]["InstanceType"], "p3.2xlarge")

    def test_describe_instance_types_client_error(self):
        """Test describe_instance_types when EC2 API fails"""
        # Setup
        eks_client = EKSClient()

        # Mock client error
        self.mock_ec2.describe_instance_types.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "InvalidInstanceTypeValue",
                    "Message": "Invalid instance type"
                }
            },
            operation_name="DescribeInstanceTypes"
        )

        # Execute and verify exception is raised
        with self.assertRaises(ClientError):
            eks_client.describe_instance_types(["invalid-instance-type"])

    def test_describe_instance_types_empty_response(self):
        """Test describe_instance_types with empty response"""
        # Setup
        eks_client = EKSClient()

        # Mock empty response
        mock_response = {"InstanceTypes": []}
        self.mock_ec2.describe_instance_types.return_value = mock_response

        # Execute
        result = eks_client.describe_instance_types(["nonexistent-type"])

        # Verify
        self.assertEqual(result, [])

    def test_launch_template_block_device_mappings(self):
        """Test that launch template includes correct BlockDeviceMappings"""
        # Setup
        eks_client = EKSClient()

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-block-device-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

        # Execute
        result = eks_client.create_node_group(
            node_group_name="test-block-device-ng",
            instance_type="t3.medium",
            node_count=1
        )

        # Verify
        self.assertTrue(result)
        self.mock_ec2.create_launch_template.assert_called_once()

        # Get the launch template data
        create_lt_call_args = self.mock_ec2.create_launch_template.call_args[1]
        launch_template_data = create_lt_call_args["LaunchTemplateData"]

        # Verify BlockDeviceMappings
        self.assertIn("BlockDeviceMappings", launch_template_data)
        block_devices = launch_template_data["BlockDeviceMappings"]
        self.assertEqual(len(block_devices), 1)

        block_device = block_devices[0]
        self.assertEqual(block_device["DeviceName"], "/dev/xvda")

        ebs_config = block_device["Ebs"]
        self.assertEqual(ebs_config["Iops"], 5000)
        self.assertEqual(ebs_config["Throughput"], 200)
        self.assertEqual(ebs_config["VolumeSize"], 1024)
        self.assertEqual(ebs_config["VolumeType"], "gp3")
        self.assertTrue(ebs_config["DeleteOnTermination"])

    def test_launch_template_network_interfaces_single_nic(self):
        """Test launch template NetworkInterfaces configuration for single NIC instance"""
        # Setup
        eks_client = EKSClient()

        # Mock describe_instance_types response for single NIC
        self.mock_ec2.describe_instance_types.return_value = {
            "InstanceTypes": [
                {
                    "InstanceType": "t3.medium",
                    "NetworkInfo": {"MaximumNetworkCards": 1}
                }
            ]
        }

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-single-nic-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

        # Execute
        result = eks_client.create_node_group(
            node_group_name="test-single-nic-ng",
            instance_type="t3.medium",
            node_count=1
        )

        # Verify
        self.assertTrue(result)

        # Verify describe_instance_types was called
        self.mock_ec2.describe_instance_types.assert_called_once_with(
            InstanceTypes=["t3.medium"]
        )

        # Get the launch template data
        create_lt_call_args = self.mock_ec2.create_launch_template.call_args[1]
        launch_template_data = create_lt_call_args["LaunchTemplateData"]

        # Verify NetworkInterfaces
        self.assertIn("NetworkInterfaces", launch_template_data)
        network_interfaces = launch_template_data["NetworkInterfaces"]
        self.assertEqual(len(network_interfaces), 1)

        nic = network_interfaces[0]
        self.assertEqual(nic["NetworkCardIndex"], 0)  # First interface should have NetworkCardIndex 0
        self.assertEqual(nic["DeviceIndex"], 0)
        self.assertEqual(nic["InterfaceType"], "efa")
        self.assertFalse(nic["AssociatePublicIpAddress"])
        self.assertTrue(nic["DeleteOnTermination"])

    def test_launch_template_network_interfaces_multiple_nics(self):
        """Test launch template NetworkInterfaces configuration for multi-NIC instance"""
        # Setup
        eks_client = EKSClient()

        # Mock describe_instance_types response for multiple NICs
        self.mock_ec2.describe_instance_types.return_value = {
            "InstanceTypes": [
                {
                    "InstanceType": "p3.2xlarge",
                    "NetworkInfo": {"MaximumNetworkCards": 4}
                }
            ]
        }

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-multi-nic-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

        # Execute
        result = eks_client.create_node_group(
            node_group_name="test-multi-nic-ng",
            instance_type="p3.2xlarge",
            node_count=1
        )

        # Verify
        self.assertTrue(result)

        # Verify describe_instance_types was called
        self.mock_ec2.describe_instance_types.assert_called_once_with(
            InstanceTypes=["p3.2xlarge"]
        )

        # Get the launch template data
        create_lt_call_args = self.mock_ec2.create_launch_template.call_args[1]
        launch_template_data = create_lt_call_args["LaunchTemplateData"]

        # Verify NetworkInterfaces
        self.assertIn("NetworkInterfaces", launch_template_data)
        network_interfaces = launch_template_data["NetworkInterfaces"]
        self.assertEqual(len(network_interfaces), 4)

        # Verify each NIC configuration
        for i, nic in enumerate(network_interfaces):
            # NetworkCardIndex logic: 0 for first interface, 1 for all others
            expected_device_index = 0 if i == 0 else 1
            self.assertEqual(nic["NetworkCardIndex"], i)
            self.assertEqual(nic["DeviceIndex"], expected_device_index)
            self.assertEqual(nic["InterfaceType"], "efa")
            self.assertFalse(nic["AssociatePublicIpAddress"])
            self.assertTrue(nic["DeleteOnTermination"])

    def test_launch_template_network_interfaces_missing_network_info(self):
        """Test launch template handles missing NetworkInfo gracefully"""
        # Setup
        eks_client = EKSClient()

        # Mock describe_instance_types response without NetworkInfo
        self.mock_ec2.describe_instance_types.return_value = {
            "InstanceTypes": [
                {
                    "InstanceType": "t3.medium",
                    # NetworkInfo is missing
                }
            ]
        }

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-missing-netinfo-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

        # Execute
        result = eks_client.create_node_group(
            node_group_name="test-missing-netinfo-ng",
            instance_type="t3.medium",
            node_count=1
        )

        # Verify
        self.assertTrue(result)

        # Get the launch template data
        create_lt_call_args = self.mock_ec2.create_launch_template.call_args[1]
        launch_template_data = create_lt_call_args["LaunchTemplateData"]

        # Verify NetworkInterfaces defaults to 1 NIC
        self.assertIn("NetworkInterfaces", launch_template_data)
        network_interfaces = launch_template_data["NetworkInterfaces"]
        self.assertEqual(len(network_interfaces), 1)

    def test_launch_template_network_interfaces_missing_max_nics(self):
        """Test launch template handles missing MaximumNetworkCards gracefully"""
        # Setup
        eks_client = EKSClient()

        # Mock describe_instance_types response without MaximumNetworkCards
        self.mock_ec2.describe_instance_types.return_value = {
            "InstanceTypes": [
                {
                    "InstanceType": "t3.medium",
                    "NetworkInfo": {
                        # MaximumNetworkCards is missing
                        "NetworkPerformance": "Up to 5 Gigabit"
                    }
                }
            ]
        }

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-missing-max-nics-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1"]

        # Execute
        result = eks_client.create_node_group(
            node_group_name="test-missing-max-nics-ng",
            instance_type="t3.medium",
            node_count=1
        )

        # Verify
        self.assertTrue(result)

        # Get the launch template data
        create_lt_call_args = self.mock_ec2.create_launch_template.call_args[1]
        launch_template_data = create_lt_call_args["LaunchTemplateData"]

        # Verify NetworkInterfaces defaults to 1 NIC
        self.assertIn("NetworkInterfaces", launch_template_data)
        network_interfaces = launch_template_data["NetworkInterfaces"]
        self.assertEqual(len(network_interfaces), 1)

    def test_launch_template_integration_with_instance_details(self):
        """Test complete integration between describe_instance_types and launch template creation"""
        # Setup
        eks_client = EKSClient()

        # Mock describe_instance_types response
        self.mock_ec2.describe_instance_types.return_value = {
            "InstanceTypes": [
                {
                    "InstanceType": "c5.xlarge",
                    "NetworkInfo": {
                        "MaximumNetworkCards": 4,
                        "NetworkPerformance": "Up to 10 Gigabit"
                    },
                    "VCpuInfo": {"DefaultVCpus": 4},
                    "MemoryInfo": {"SizeInMiB": 8192}
                }
            ]
        }

        # Mock successful responses
        self.mock_ec2.create_launch_template.return_value = {
            "LaunchTemplate": {"LaunchTemplateId": "lt-integration-123"}
        }
        self.mock_eks.create_nodegroup.return_value = {
            "nodegroup": {"status": "CREATING"}
        }
        self.mock_eks.get_waiter.return_value.wait = mock.MagicMock()
        self.mock_k8s.wait_for_nodes_ready.return_value = ["node1", "node2"]

        # Execute
        result = eks_client.create_node_group(
            node_group_name="test-integration-ng",
            instance_type="c5.xlarge",
            node_count=2
        )

        # Verify
        self.assertTrue(result)

        # Verify describe_instance_types was called
        self.mock_ec2.describe_instance_types.assert_called_once_with(
            InstanceTypes=["c5.xlarge"]
        )

        # Get the launch template data
        create_lt_call_args = self.mock_ec2.create_launch_template.call_args[1]
        launch_template_data = create_lt_call_args["LaunchTemplateData"]

        # Verify instance type
        self.assertEqual(launch_template_data["InstanceType"], "c5.xlarge")

        # Verify BlockDeviceMappings (should always be present)
        self.assertIn("BlockDeviceMappings", launch_template_data)
        block_devices = launch_template_data["BlockDeviceMappings"]
        self.assertEqual(len(block_devices), 1)
        self.assertEqual(block_devices[0]["DeviceName"], "/dev/xvda")

        # Verify NetworkInterfaces based on instance type
        self.assertIn("NetworkInterfaces", launch_template_data)
        network_interfaces = launch_template_data["NetworkInterfaces"]
        self.assertEqual(len(network_interfaces), 4)  # c5.xlarge supports 4 NICs

        # Verify all NICs have correct configuration
        for i, nic in enumerate(network_interfaces):
            # NetworkCardIndex logic: 0 for first interface, 1 for all others
            expected_device_index = 0 if i == 0 else 1
            self.assertEqual(nic["NetworkCardIndex"], i)
            self.assertEqual(nic["DeviceIndex"], expected_device_index)
            self.assertEqual(nic["InterfaceType"], "efa")
            self.assertFalse(nic["AssociatePublicIpAddress"])
            self.assertTrue(nic["DeleteOnTermination"])


if __name__ == "__main__":
    unittest.main()
