#!/usr/bin/env python3
"""
Test script for k8s_cost_collector.py

This script performs basic tests to ensure the cost collector works correctly.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add the parent directory to the Python path to import modules
sys.path.append(str(Path(__file__).parent.parent))

from cost_analysis.k8s_cost_collector import OpenCostKubernetesCollector


class TestOpenCostKubernetesCollector(unittest.TestCase):
    """Test cases for OpenCostKubernetesCollector."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_context = "test-context"
        
    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    def test_collector_initialization(self, mock_k8s_client):
        """Test that the collector initializes correctly."""
        collector = OpenCostKubernetesCollector(cluster_context=self.test_context)
        
        # Verify that KubernetesClient was instantiated
        mock_k8s_client.assert_called_once()
        
        # Verify that set_context was called with the correct context
        collector.k8s_client.set_context.assert_called_once_with(self.test_context)
        
        self.assertEqual(collector.cluster_context, self.test_context)
    
    def test_find_free_port(self):
        """Test that find_free_port returns a valid port number."""
        collector = OpenCostKubernetesCollector()
        port = collector._find_free_port()
        
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertLess(port, 65536)
    
    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    def test_deploy_opencost_service_success(self, mock_k8s_client):
        """Test successful deployment of OpenCost service."""
        collector = OpenCostKubernetesCollector()
        
        # Mock successful apply_manifest_from_file
        collector.k8s_client.apply_manifest_from_file.return_value = Mock()
        
        # Create a temporary manifest file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""
apiVersion: v1
kind: Service
metadata:
  name: opencost-service
  namespace: kube-system
spec:
  selector:
    app: cost-analysis-agent
  ports:
    - name: opencost-service
      protocol: TCP
      port: 9003
      targetPort: 9003
  type: ClusterIP
""")
            manifest_path = f.name
        
        try:
            result = collector.deploy_opencost_service(manifest_path)
            
            self.assertTrue(result)
            collector.k8s_client.apply_manifest_from_file.assert_called_once_with(manifest_path=manifest_path)
        finally:
            os.unlink(manifest_path)
    
    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    def test_deploy_opencost_service_failure(self, mock_k8s_client):
        """Test failed deployment of OpenCost service."""
        collector = OpenCostKubernetesCollector()
        
        # Mock failed apply_manifest_from_file
        collector.k8s_client.apply_manifest_from_file.side_effect = Exception("Deployment failed")
        
        # Create a temporary manifest file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content")
            manifest_path = f.name
        
        try:
            result = collector.deploy_opencost_service(manifest_path)
            
            self.assertFalse(result)
        finally:
            os.unlink(manifest_path)
    
    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    def test_wait_for_service_ready_success(self, mock_k8s_client):
        """Test waiting for service to become ready."""
        collector = OpenCostKubernetesCollector()
        
        # Mock successful service read
        mock_service = Mock()
        mock_service.spec.cluster_ip = "10.0.0.1"
        collector.k8s_client.api.read_namespaced_service.return_value = mock_service
        
        result = collector.wait_for_service_ready(timeout=1)
        
        self.assertTrue(result)
        collector.k8s_client.api.read_namespaced_service.assert_called_with(
            name="opencost-service", 
            namespace="kube-system"
        )
    
    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    def test_wait_for_service_ready_timeout(self, mock_k8s_client):
        """Test timeout when waiting for service to become ready."""
        collector = OpenCostKubernetesCollector()
        
        # Mock service that never becomes ready
        mock_service = Mock()
        mock_service.spec.cluster_ip = None
        collector.k8s_client.api.read_namespaced_service.return_value = mock_service
        
        result = collector.wait_for_service_ready(timeout=1)
        
        self.assertFalse(result)

    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    @patch('cost_analysis.k8s_cost_collector.subprocess.Popen')
    def test_start_port_forward_success(self, mock_popen, mock_k8s_client):
        """Test successful port forwarding setup."""
        collector = OpenCostKubernetesCollector()
        
        # Mock subprocess
        mock_process = Mock()
        mock_popen.return_value = mock_process
        
        # Mock requests for health check
        with patch('cost_analysis.k8s_cost_collector.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            result = collector.start_port_forward()
            
            self.assertIsInstance(result, int)
            self.assertGreater(result, 0)
            self.assertLess(result, 65536)
    
    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    @patch('cost_analysis.k8s_cost_collector.subprocess.Popen')
    def test_start_port_forward_failure(self, mock_popen, mock_k8s_client):
        """Test port forwarding failure."""
        collector = OpenCostKubernetesCollector()
        
        # Mock subprocess failure
        mock_popen.side_effect = Exception("Failed to start process")
        
        result = collector.start_port_forward()
        
        self.assertIsNone(result)
    
    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    @patch('cost_analysis.k8s_cost_collector.OpenCostLiveExporter')
    def test_collect_cost_data_success(self, mock_exporter_class, mock_k8s_client):
        """Test successful cost data collection."""
        collector = OpenCostKubernetesCollector()
        
        # Mock exporter
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = "allocation.json"
        mock_exporter.export_assets_live_data.return_value = "assets.json"
        
        # Create temporary files
        with tempfile.TemporaryDirectory() as temp_dir:
            allocation_file = os.path.join(temp_dir, "allocation.json")
            assets_file = os.path.join(temp_dir, "assets.json")
            
            # Create the files
            with open(allocation_file, 'w', encoding='utf-8') as f:
                f.write('{"test": "allocation"}')
            with open(assets_file, 'w', encoding='utf-8') as f:
                f.write('{"test": "assets"}')
            
            result = collector.collect_cost_data(
                window="1h",
                aggregate="container", 
                scenario_name="test",
                run_id="123",
                metadata={"test": "value"},
                allocation_output=allocation_file,
                assets_output=assets_file,
                local_port=9003
            )
            
            self.assertTrue(result)
    
    @patch('cost_analysis.k8s_cost_collector.KubernetesClient')
    @patch('cost_analysis.k8s_cost_collector.OpenCostLiveExporter')
    def test_collect_cost_data_failure(self, mock_exporter_class, mock_k8s_client):
        """Test cost data collection failure."""
        collector = OpenCostKubernetesCollector()
        
        # Mock exporter failure
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.side_effect = Exception("Export failed")
        
        result = collector.collect_cost_data(
            window="1h",
            aggregate="container",
            scenario_name="test", 
            run_id="123",
            metadata={},
            allocation_output="allocation.json",
            assets_output="assets.json",
            local_port=9003
        )
        
        self.assertFalse(result)


def run_tests():
    """Run all tests."""
    unittest.main(verbosity=2)


if __name__ == "__main__":
    run_tests()
