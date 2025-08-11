"""Unit tests for AKS Store Demo module."""
# pylint: disable=missing-class-docstring
from dataclasses import dataclass
import unittest
from unittest.mock import Mock, patch, call

# Mock kubernetes config before importing
with patch('kubernetes.config.load_kube_config'):
    from aks_store_demo.aks_store_demo import AKSStoreDemo, AllInOneAKSStoreDemo, main
    from clients.kubernetes_client import KubernetesClient


class TestAKSStoreDemo(unittest.TestCase):
    """Test cases for the abstract AKSStoreDemo base class."""

    def test_abstract_class_cannot_be_instantiated(self):
        """Test that AKSStoreDemo abstract class cannot be instantiated directly."""
        with self.assertRaises(TypeError):
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
    def test_delete_manifest_from_url_success(self, mock_execute):
        """Test successful deletion of manifest from URL."""
        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        # Call the method
        demo.delete_manifest_from_url("https://example.com/manifest.yaml")

        # Verify delete_manifest_from_url was called via execute_with_retries
        mock_execute.assert_called_once_with(
            mock_client.delete_manifest_from_url,
            manifest_url="https://example.com/manifest.yaml",
            ignore_not_found=True,
            namespace="test-namespace"
        )

    @patch('aks_store_demo.aks_store_demo.execute_with_retries')
    def test_apply_manifest_success(self, mock_execute):
        """Test successful application of manifest from URL."""
        @dataclass
        class ConcreteDemo(AKSStoreDemo):
            def deploy(self):
                pass
            def cleanup(self):
                pass

        mock_client = Mock(spec=KubernetesClient)
        demo = ConcreteDemo(k8s_client=mock_client, namespace="test-namespace")

        # Call the method
        demo.apply_manifest(
            "https://example.com/manifest.yaml",
            wait_condition_type="available",
            resource_type="deployment",
            resource_name="test-deployment",
            timeout=600
        )

        # Verify apply_manifest_from_url was called
        self.assertEqual(mock_execute.call_count, 2)  # apply + wait calls

        # Check the first call (apply)
        first_call = mock_execute.call_args_list[0]
        self.assertEqual(first_call[0][0], mock_client.apply_manifest_from_url)
        self.assertEqual(first_call[1]['manifest_url'], "https://example.com/manifest.yaml")
        self.assertEqual(first_call[1]['namespace'], "test-namespace")

        # Check the second call (wait_for_condition)
        second_call = mock_execute.call_args_list[1]
        self.assertEqual(second_call[0][0], mock_client.wait_for_condition)
        self.assertEqual(second_call[1]['resource_type'], "deployment")
        self.assertEqual(second_call[1]['resource_name'], "test-deployment")
        self.assertEqual(second_call[1]['wait_condition_type'], "available")
        self.assertEqual(second_call[1]['namespace'], "test-namespace")
        self.assertEqual(second_call[1]['timeout_seconds'], 600)


class TestAllInOneAKSStoreDemo(unittest.TestCase):
    """Test cases for the AllInOneAKSStoreDemo implementation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_client = Mock(spec=KubernetesClient)
        self.demo = AllInOneAKSStoreDemo(
            k8s_client=self.mock_client,
            namespace="test-namespace"
        )

    def test_get_manifest_urls(self):
        """Test that get_manifest_urls returns correct configuration."""
        manifests = self.demo.get_manifest_urls()

        expected = [
            {
                "url": "https://raw.githubusercontent.com/Azure-Samples/aks-store-demo/2.0.0/aks-store-all-in-one.yaml",
                "wait_condition_type": "available",
                "resource_type": "deployment",
                "resource_name": None,
                "timeout": 1200
            }
        ]

        assert manifests == expected

    @patch('aks_store_demo.aks_store_demo.KubernetesClient')
    def test_get_manifest_urls_with_custom_tag(self, mock_k8s_client): #pylint: disable=unused-argument
        """Test that get_manifest_urls uses custom tag correctly."""
        demo_with_custom_tag = AllInOneAKSStoreDemo(tag="1.5.0")
        manifests = demo_with_custom_tag.get_manifest_urls()

        expected = [
            {
                "url": "https://raw.githubusercontent.com/Azure-Samples/aks-store-demo/1.5.0/aks-store-all-in-one.yaml",
                "wait_condition_type": "available",
                "resource_type": "deployment",
                "resource_name": None,
                "timeout": 1200
            }
        ]

        assert manifests == expected

    @patch.object(AllInOneAKSStoreDemo, 'set_context')
    @patch.object(AllInOneAKSStoreDemo, 'ensure_namespace')
    @patch.object(AllInOneAKSStoreDemo, 'apply_manifest')
    def test_deploy_success(self, mock_apply, mock_ensure_ns, mock_set_context):
        """Test successful deployment using URL-based manifests."""
        self.demo.deploy()

        mock_set_context.assert_called_once()
        mock_ensure_ns.assert_called_once()

        # Should apply 1 manifest URL
        assert mock_apply.call_count == 1

        expected_call = call(
            manifest_url="https://raw.githubusercontent.com/Azure-Samples/aks-store-demo/2.0.0/aks-store-all-in-one.yaml",
            wait_condition_type="available",
            resource_type="deployment",
            resource_name=None,
            timeout=1200
        )

        assert mock_apply.call_args_list == [expected_call]

    @patch.object(AllInOneAKSStoreDemo, 'set_context')
    @patch.object(AllInOneAKSStoreDemo, 'ensure_namespace')
    def test_deploy_exception_handling(self, mock_ensure_ns, _mock_set_context):
        """Test deployment exception handling."""
        mock_ensure_ns.side_effect = Exception("Namespace creation failed")

        with self.assertRaises(RuntimeError):
            self.demo.deploy()

    @patch.object(AllInOneAKSStoreDemo, 'set_context')
    @patch.object(AllInOneAKSStoreDemo, 'delete_manifest_from_url')
    def test_cleanup_success(self, mock_delete_url, mock_set_context):
        """Test successful cleanup using URL-based manifests."""
        self.demo.cleanup()

        mock_set_context.assert_called_once()

        # Should call delete_manifest_from_url once for the single manifest URL
        assert mock_delete_url.call_count == 1

        expected_call = call("https://raw.githubusercontent.com/Azure-Samples/aks-store-demo/2.0.0/aks-store-all-in-one.yaml")
        assert mock_delete_url.call_args_list == [expected_call]

    @patch.object(AllInOneAKSStoreDemo, 'set_context')
    def test_cleanup_exception_handling(self, mock_set_context):
        """Test cleanup exception handling."""
        mock_set_context.side_effect = Exception("Context setting failed")

        with self.assertRaises(RuntimeError):
            self.demo.cleanup()


class TestMainFunction(unittest.TestCase):
    """Test cases for the main function and argument parsing."""

    @patch('aks_store_demo.aks_store_demo.AllInOneAKSStoreDemo')
    @patch('sys.argv', ['aks_store_demo.py', '--action', 'deploy'])
    def test_main_deploy_action(self, mock_demo_class):
        """Test main function with deploy action."""
        mock_demo = Mock()
        mock_demo_class.return_value = mock_demo

        main()

        mock_demo_class.assert_called_once_with(
            cluster_context="",
            namespace="aks-store-demo",
            action="deploy",
            tag="2.0.0"
        )
        mock_demo.deploy.assert_called_once()
        mock_demo.cleanup.assert_not_called()

    @patch('aks_store_demo.aks_store_demo.AllInOneAKSStoreDemo')
    @patch('sys.argv', ['aks_store_demo.py', '--action', 'cleanup'])
    def test_main_cleanup_action(self, mock_demo_class):
        """Test main function with cleanup action."""
        mock_demo = Mock()
        mock_demo_class.return_value = mock_demo

        main()

        mock_demo_class.assert_called_once_with(
            cluster_context="",
            namespace="aks-store-demo",
            action="cleanup",
            tag="2.0.0"
        )
        mock_demo.cleanup.assert_called_once()
        mock_demo.deploy.assert_not_called()

    @patch('aks_store_demo.aks_store_demo.AllInOneAKSStoreDemo')
    @patch('sys.argv', [
        'aks_store_demo.py',
        '--cluster-context', 'test-context',
        '--namespace', 'test-namespace',
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
            action="deploy",
            tag="2.0.0"
        )
        mock_demo.deploy.assert_called_once()

    @patch('aks_store_demo.aks_store_demo.AllInOneAKSStoreDemo')
    @patch('sys.argv', [
        'aks_store_demo.py',
        '--cluster-context', 'test-context',
        '--namespace', 'test-namespace',
        '--action', 'deploy',
        '--tag', '1.0.0'
    ])
    def test_main_with_custom_tag(self, mock_demo_class):
        """Test main function with custom tag argument."""
        mock_demo = Mock()
        mock_demo_class.return_value = mock_demo

        main()

        mock_demo_class.assert_called_once_with(
            cluster_context="test-context",
            namespace="test-namespace",
            action="deploy",
            tag="1.0.0"
        )
        mock_demo.deploy.assert_called_once()

    @patch('sys.argv', ['aks_store_demo.py'])
    def test_main_missing_required_action(self):
        """Test main function fails with missing required action argument."""
        with self.assertRaises(SystemExit):
            main()

    @patch('sys.argv', ['aks_store_demo.py', '--action', 'invalid'])
    def test_main_invalid_action(self):
        """Test main function fails with invalid action."""
        with self.assertRaises(SystemExit):
            main()
