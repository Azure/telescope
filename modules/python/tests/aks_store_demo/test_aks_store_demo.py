"""Unit tests for AKS Store Demo module."""
# pylint: disable=missing-class-docstring
from dataclasses import dataclass
import unittest
from unittest.mock import Mock, patch, call

import pytest

from aks_store_demo.aks_store_demo import AKSStoreDemo, SingleClusterDemo, main
from clients.kubernetes_client import KubernetesClient


class TestAKSStoreDemo(unittest.TestCase):
    """Test cases for the abstract AKSStoreDemo base class."""

    def test_abstract_class_cannot_be_instantiated(self):
        """Test that AKSStoreDemo abstract class cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AKSStoreDemo()  # pylint: disable=abstract-class-instantiated

    def test_post_init_creates_kubernetes_client(self):
        """Test that __post_init__ creates a KubernetesClient when none provided."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        with patch('aks_store_demo.aks_store_demo.KubernetesClient') as mock_k8s_client:
            demo = ConcreteDemo()

            # Should create a new KubernetesClient
            mock_k8s_client.assert_called_once()
            assert demo.k8s_client is not None

    def test_post_init_uses_provided_kubernetes_client(self):
        """Test that __post_init__ uses provided KubernetesClient."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)

        with patch('aks_store_demo.aks_store_demo.KubernetesClient') as mock_k8s_client:
            demo = ConcreteDemo(k8s_client=mock_client)

            # Should not create a new KubernetesClient
            mock_k8s_client.assert_not_called()
            assert demo.k8s_client is mock_client

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_set_context_with_context(self, mock_execute):
        """Test setting Kubernetes context when cluster_context is provided."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, cluster_context="test-context")

        demo.set_context()

        mock_execute.assert_called_once_with(
            mock_client.set_context,
            "test-context"
        )

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_set_context_without_context(self, mock_execute):
        """Test that set_context does nothing when no cluster_context is provided."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, cluster_context="")

        demo.set_context()

        mock_execute.assert_not_called()

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_ensure_namespace_success(self, mock_execute):
        """Test successful namespace creation."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        demo.ensure_namespace()

        mock_execute.assert_called_once_with(
            mock_client.create_namespace,
            "test-namespace"
        )

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    @patch('aks_store_demo.aks_store_demo.logger')
    def test_ensure_namespace_exception(self, mock_logger, mock_execute):
        """Test namespace creation with exception handling."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        mock_execute.side_effect = Exception("Namespace error")

        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        demo.ensure_namespace()

        mock_logger.warning.assert_called_once_with("Namespace operation: Namespace error")

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_apply_manifest_basic(self, mock_execute):
        """Test basic manifest application without wait conditions."""
  
        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        demo.apply_manifest("/path/to/manifest.yaml")

        mock_execute.assert_called_once_with(
            mock_client.apply_manifest_from_file,
            manifest_path="/path/to/manifest.yaml",
            default_namespace="test-namespace"
        )

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_apply_manifest_with_wait_condition(self, mock_execute):
        """Test manifest application with wait conditions."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        # Mock successful apply and wait
        mock_execute.side_effect = [None, True]  # apply_manifest, then wait_for_condition

        demo.apply_manifest(
            "/path/to/manifest.yaml",
            wait_condition="available",
            wait_resource="deployment/test-deployment",
            timeout="600s"
        )

        expected_calls = [
            call(
                mock_client.apply_manifest_from_file,
                manifest_path="/path/to/manifest.yaml",
                default_namespace="test-namespace"
            ),
            call(
                mock_client.wait_for_condition,
                resource_type="deployment",
                resource_name="test-deployment",
                wait_condition_type="available",
                namespace="test-namespace",
                timeout_seconds=600
            )
        ]

        assert mock_execute.call_args_list == expected_calls

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_apply_manifest_with_resource_type_only(self, mock_execute):
        """Test manifest application with resource type only (no specific name)."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        # Mock successful apply and wait
        mock_execute.side_effect = [None, True]

        demo.apply_manifest(
            "/path/to/manifest.yaml",
            wait_condition="available",
            wait_resource="deployment",
            timeout="300s"
        )

        expected_calls = [
            call(
                mock_client.apply_manifest_from_file,
                manifest_path="/path/to/manifest.yaml",
                default_namespace="test-namespace"
            ),
            call(
                mock_client.wait_for_condition,
                resource_type="deployment",
                resource_name=None,
                wait_condition_type="available",
                namespace="test-namespace",
                timeout_seconds=300
            )
        ]

        assert mock_execute.call_args_list == expected_calls

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    @patch('aks_store_demo.aks_store_demo.logger')
    def test_apply_manifest_wait_timeout(self, mock_logger, mock_execute):
        """Test manifest application with wait timeout."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        # Mock successful apply but failed wait
        mock_execute.side_effect = [None, False]

        demo.apply_manifest(
            "/path/to/manifest.yaml",
            wait_condition="available",
            wait_resource="deployment/test-deployment"
        )

        mock_logger.warning.assert_called_once_with(
            "Timeout waiting for deployment/test-deployment with condition available"
        )

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_apply_manifest_exception(self, mock_execute):
        """Test manifest application with exception."""

        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        mock_execute.side_effect = Exception("Apply failed")

        with pytest.raises(RuntimeError, match="Failed to apply manifest /path/to/manifest.yaml: Apply failed"):
            demo.apply_manifest("/path/to/manifest.yaml")


class TestSingleClusterDemo:
    """Test cases for the SingleClusterDemo implementation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_client = Mock(spec=KubernetesClient)  # pylint: disable=attribute-defined-outside-init
        self.demo = SingleClusterDemo(  # pylint: disable=attribute-defined-outside-init
            k8s_client=self.mock_client,
            manifests_path="/test/manifests",
            namespace="test-namespace"
        )

    def test_get_manifest_files(self):
        """Test that get_manifest_files returns correct configuration."""
        manifests = self.demo.get_manifest_files()

        expected = [
            {
                "file": "/test/manifests/aks-store-all-in-one.yaml",
                "wait_condition_type": "available",
                "wait_resource": "deployment",
                "timeout": "1200s"
            },
            {
                "file": "/test/manifests/aks-store-virtual-worker.yaml",
                "wait_condition_type": "available",
                "wait_resource": "deployment/virtual-worker",
                "timeout": "120s"
            },
            {
                "file": "/test/manifests/aks-store-virtual-customer.yaml",
                "wait_condition_type": "available",
                "wait_resource": "deployment/virtual-customer",
                "timeout": "120s"
            }
        ]

        assert manifests == expected

    @patch('aks_store_demo.aks_store_demo.os.path.exists')
    @patch.object(SingleClusterDemo, 'set_context')
    @patch.object(SingleClusterDemo, 'ensure_namespace')
    @patch.object(SingleClusterDemo, 'apply_manifest')
    def test_deploy_all_manifests_exist(self, mock_apply, mock_ensure_ns, mock_set_context, mock_exists):
        """Test successful deployment when all manifest files exist."""
        mock_exists.return_value = True

        self.demo.deploy()

        mock_set_context.assert_called_once()
        mock_ensure_ns.assert_called_once()

        assert mock_apply.call_count == 3

        expected_calls = [
            call(
                manifest_file="/test/manifests/aks-store-all-in-one.yaml",
                wait_condition="available",
                wait_resource="deployment",
                timeout="1200s"
            ),
            call(
                manifest_file="/test/manifests/aks-store-virtual-worker.yaml",
                wait_condition="available",
                wait_resource="deployment/virtual-worker",
                timeout="120s"
            ),
            call(
                manifest_file="/test/manifests/aks-store-virtual-customer.yaml",
                wait_condition="available",
                wait_resource="deployment/virtual-customer",
                timeout="120s"
            )
        ]

        assert mock_apply.call_args_list == expected_calls

    @patch('aks_store_demo.aks_store_demo.os.path.exists')
    @patch.object(SingleClusterDemo, 'set_context')
    @patch.object(SingleClusterDemo, 'ensure_namespace')
    @patch.object(SingleClusterDemo, 'apply_manifest')
    @patch('aks_store_demo.aks_store_demo.logger')
    def test_deploy_missing_manifest_files(self, mock_logger, mock_apply, mock_ensure_ns,  # pylint: disable=too-many-arguments,too-many-positional-arguments
                                         mock_set_context, mock_exists):
        """Test deployment with missing manifest files."""
        # First file exists, second doesn't, third exists
        mock_exists.side_effect = [True, False, True]

        self.demo.deploy()

        mock_set_context.assert_called_once()
        mock_ensure_ns.assert_called_once()

        # Should only apply 2 manifests (skip the missing one)
        assert mock_apply.call_count == 2

        # Should log warning for missing file
        mock_logger.warning.assert_called_once_with(
            "Manifest file not found: /test/manifests/aks-store-virtual-worker.yaml"
        )

    @patch.object(SingleClusterDemo, 'set_context')
    @patch.object(SingleClusterDemo, 'ensure_namespace')
    def test_deploy_exception_handling(self, mock_ensure_ns, _mock_set_context):
        """Test deployment exception handling."""
        mock_ensure_ns.side_effect = Exception("Namespace creation failed")

        with pytest.raises(RuntimeError, match="Failed to deploy AKS Store Demo: Namespace creation failed"):
            self.demo.deploy()

    @patch('aks_store_demo.aks_store_demo.os.path.exists')
    @patch.object(SingleClusterDemo, 'set_context')
    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_cleanup_all_manifests_exist(self, mock_execute, mock_set_context, mock_exists):
        """Test successful cleanup when all manifest files exist."""
        mock_exists.return_value = True

        self.demo.cleanup()

        mock_set_context.assert_called_once()

        # Should call delete_manifest_from_file 3 times (in reverse order)
        assert mock_execute.call_count == 3

        expected_calls = [
            call(
                self.mock_client.delete_manifest_from_file,
                manifest_path="/test/manifests/aks-store-virtual-customer.yaml",
                default_namespace="test-namespace",
                ignore_not_found=True
            ),
            call(
                self.mock_client.delete_manifest_from_file,
                manifest_path="/test/manifests/aks-store-virtual-worker.yaml",
                default_namespace="test-namespace",
                ignore_not_found=True
            ),
            call(
                self.mock_client.delete_manifest_from_file,
                manifest_path="/test/manifests/aks-store-all-in-one.yaml",
                default_namespace="test-namespace",
                ignore_not_found=True
            )
        ]

        assert mock_execute.call_args_list == expected_calls

    @patch('aks_store_demo.aks_store_demo.os.path.exists')
    @patch.object(SingleClusterDemo, 'set_context')
    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    @patch('aks_store_demo.aks_store_demo.logger')
    def test_cleanup_missing_manifest_files(self, mock_logger, mock_execute,
                                          mock_set_context, mock_exists):  # pylint: disable=too-many-arguments
        """Test cleanup with missing manifest files."""
        # First file missing, second exists, third missing
        mock_exists.side_effect = [False, True, False]

        self.demo.cleanup()

        mock_set_context.assert_called_once()

        # Should only delete 1 manifest (the one that exists)
        assert mock_execute.call_count == 1

        # Should log warnings for missing files
        assert mock_logger.warning.call_count == 2
        mock_logger.warning.assert_any_call(
            "Manifest file not found for cleanup: /test/manifests/aks-store-virtual-customer.yaml"
        )
        mock_logger.warning.assert_any_call(
            "Manifest file not found for cleanup: /test/manifests/aks-store-all-in-one.yaml"
        )

    @patch('aks_store_demo.aks_store_demo.os.path.exists')
    @patch.object(SingleClusterDemo, 'set_context')
    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    @patch('aks_store_demo.aks_store_demo.logger')
    def test_cleanup_delete_exception(self, mock_logger, mock_execute,
                                    mock_set_context, mock_exists):  # pylint: disable=too-many-arguments
        """Test cleanup with delete exception handling."""
        mock_exists.return_value = True
        # First delete succeeds, second fails, third succeeds
        mock_execute.side_effect = [None, Exception("Delete failed"), None]

        self.demo.cleanup()

        mock_set_context.assert_called_once()

        # Should attempt all 3 deletes
        assert mock_execute.call_count == 3

        # Should log warning for failed delete
        mock_logger.warning.assert_called_once_with(
            "Failed to cleanup manifest /test/manifests/aks-store-virtual-worker.yaml: Delete failed"
        )

    @patch.object(SingleClusterDemo, 'set_context')
    def test_cleanup_exception_handling(self, mock_set_context):
        """Test cleanup exception handling."""
        mock_set_context.side_effect = Exception("Context setting failed")

        with pytest.raises(RuntimeError, match="Failed to cleanup AKS Store Demo: Context setting failed"):
            self.demo.cleanup()


class TestMainFunction:
    """Test cases for the main function and argument parsing."""

    @patch('aks_store_demo.aks_store_demo.SingleClusterDemo')
    @patch('sys.argv', ['aks_store_demo.py', '--manifests-path', '/test/path', '--action', 'deploy'])
    def test_main_deploy_action(self, mock_demo_class):
        """Test main function with deploy action."""
        mock_demo = Mock()
        mock_demo_class.return_value = mock_demo

        main()

        mock_demo_class.assert_called_once_with(
            cluster_context="",
            namespace="default",
            manifests_path="/test/path",
            action="deploy"
        )
        mock_demo.deploy.assert_called_once()
        mock_demo.cleanup.assert_not_called()

    @patch('aks_store_demo.aks_store_demo.SingleClusterDemo')
    @patch('sys.argv', ['aks_store_demo.py', '--manifests-path', '/test/path', '--action', 'cleanup'])
    def test_main_cleanup_action(self, mock_demo_class):
        """Test main function with cleanup action."""
        mock_demo = Mock()
        mock_demo_class.return_value = mock_demo

        main()

        mock_demo_class.assert_called_once_with(
            cluster_context="",
            namespace="default",
            manifests_path="/test/path",
            action="cleanup"
        )
        mock_demo.cleanup.assert_called_once()
        mock_demo.deploy.assert_not_called()

    @patch('aks_store_demo.aks_store_demo.SingleClusterDemo')
    @patch('sys.argv', [
        'aks_store_demo.py',
        '--cluster-context', 'test-context',
        '--namespace', 'test-namespace',
        '--manifests-path', '/custom/path',
        '--action', 'deploy'
    ])
    def test_main_with_all_arguments(self, mock_demo_class):
        """Test main function with all arguments provided."""
        mock_demo = Mock()
        mock_demo_class.return_value = mock_demo

        main()

        mock_demo_class.assert_called_once_with(
            cluster_context="test-context",
            namespace="test-namespace",
            manifests_path="/custom/path",
            action="deploy"
        )
        mock_demo.deploy.assert_called_once()

    @patch('sys.argv', ['aks_store_demo.py', '--manifests-path', '/test/path'])
    def test_main_missing_required_action(self):
        """Test main function fails with missing required action argument."""
        with pytest.raises(SystemExit):
            main()

    @patch('sys.argv', ['aks_store_demo.py', '--action', 'deploy'])
    def test_main_missing_required_manifests_path(self):
        """Test main function fails with missing required manifests-path argument."""
        with pytest.raises(SystemExit):
            main()

    @patch('sys.argv', ['aks_store_demo.py', '--manifests-path', '/test/path', '--action', 'invalid'])
    def test_main_invalid_action(self):
        """Test main function fails with invalid action."""
        with pytest.raises(SystemExit):
            main()
