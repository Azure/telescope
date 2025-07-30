#!/usr/bin/env python3
"""
Unit tests for OpenCost Live Exporter

This module provides comprehensive unit tests for the OpenCostLiveExporter class,
covering all functionality including API interactions, data export formats, and CLI operations.
"""

import json
import os
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch

import pytest
import responses

from cost_analysis.opencost_live_exporter import OpenCostLiveExporter


class TestOpenCostLiveExporter:
    """Test suite for OpenCostLiveExporter class"""

    @pytest.fixture
    def exporter(self):
        """Create an OpenCostLiveExporter instance for testing"""
        return OpenCostLiveExporter(endpoint="http://test-opencost:9003")

    @pytest.fixture
    def exporter_with_metadata(self):
        """Create an OpenCostLiveExporter instance with metadata for testing"""
        metadata = {'test_name': 'unit-test', 'environment': 'test'}
        return OpenCostLiveExporter(
            endpoint="http://test-opencost:9003",
            run_id="test-run-123",
            scenario_name="test-scenario",
            metadata=metadata
        )

    @pytest.fixture
    def sample_allocation_data(self):
        """Sample allocation data for testing"""
        return {
            "code": 200,
            "status": "success",
            "data": [
                {
                    "test-namespace/test-pod/test-container": {
                        "name": "test-namespace/test-pod/test-container",
                        "properties": {
                            "namespace": "test-namespace",
                            "pod": "test-pod",
                            "container": "test-container",
                            "node": "test-node",
                            "controller": "test-deployment",
                            "controllerKind": "Deployment"
                        },
                        "start": "2025-01-01T00:00:00Z",
                        "end": "2025-01-01T01:00:00Z",
                        "minutes": 60.0,
                        "cpuCores": 0.5,
                        "cpuCoreHours": 0.5,
                        "cpuCost": 0.024,
                        "cpuEfficiency": 0.8,
                        "ramBytes": 1073741824,
                        "ramByteHours": 1073741824.0,
                        "ramCost": 0.012,
                        "ramEfficiency": 0.75,
                        "gpuCount": 0,
                        "gpuHours": 0,
                        "gpuCost": 0,
                        "networkCost": 0.001,
                        "loadBalancerCost": 0,
                        "pvCost": 0.005,
                        "totalCost": 0.042,
                        "totalEfficiency": 0.77,
                        "externalCost": 0,
                        "sharedCost": 0
                    }
                }
            ]
        }

    @pytest.fixture
    def empty_allocation_data(self):
        """Empty allocation data for testing edge cases"""
        return {
            "code": 200,
            "status": "success",
            "data": []
        }

    @pytest.fixture
    def sample_assets_data(self):
        """Sample assets data for testing"""
        return {
            "code": 200,
            "status": "success",
            "data": {
                "azure:///subscriptions/123/resourceGroups/test-rg/providers/Microsoft.Compute/virtualMachines/test-vm": {
                    "type": "Node",
                    "properties": {
                        "category": "Compute",
                        "service": "Kubernetes",
                        "name": "test-vm",
                        "providerID": "azure:///subscriptions/123/resourceGroups/test-rg/providers/Microsoft.Compute/virtualMachines/test-vm",
                        "provider": "azure",
                        "account": "test-account",
                        "project": "test-project",
                        "region": "eastus"
                    },
                    "labels": {
                        "kubernetes.io/hostname": "test-vm",
                        "node.kubernetes.io/instance-type": "Standard_D2s_v3"
                    },
                    "start": "2025-01-01T00:00:00Z",
                    "end": "2025-01-01T01:00:00Z",
                    "minutes": 60.0,
                    "cost": 0.12,
                    "adjustment": 0.0,
                    "totalCost": 0.12,
                    "bytes": 0,
                    "breakdown": {}
                },
                "azure:///subscriptions/123/resourceGroups/test-rg/providers/Microsoft.Compute/disks/test-disk": {
                    "type": "Disk",
                    "properties": {
                        "category": "Storage",
                        "service": "Azure",
                        "name": "test-disk",
                        "providerID": "azure:///subscriptions/123/resourceGroups/test-rg/providers/Microsoft.Compute/disks/test-disk",
                        "provider": "azure",
                        "account": "test-account",
                        "project": "test-project",
                        "region": "eastus"
                    },
                    "labels": {
                        "disk.csi.azure.com/zone": "eastus-1"
                    },
                    "start": "2025-01-01T00:00:00Z",
                    "end": "2025-01-01T01:00:00Z",
                    "minutes": 60.0,
                    "cost": 0.05,
                    "adjustment": 0.0,
                    "totalCost": 0.05,
                    "bytes": 107374182400,
                    "breakdown": {
                        "storage": 0.05
                    }
                }
            }
        }

    @pytest.fixture
    def empty_assets_data(self):
        """Empty assets data for testing edge cases"""
        return {
            "code": 200,
            "status": "success",
            "data": {}
        }

    def test_init_default_endpoint(self):
        """Test initialization with default endpoint"""
        exporter = OpenCostLiveExporter()
        assert exporter.endpoint == "http://localhost:9003"
        assert exporter.session.headers['Content-Type'] == 'application/json'
        assert 'OpenCost-Live-Exporter' in exporter.session.headers['User-Agent']

    def test_init_custom_endpoint(self):
        """Test initialization with custom endpoint"""
        endpoint = "http://custom-host:8080"
        exporter = OpenCostLiveExporter(endpoint=endpoint)
        assert exporter.endpoint == endpoint

    def test_init_endpoint_with_trailing_slash(self):
        """Test initialization strips trailing slash from endpoint"""
        exporter = OpenCostLiveExporter(endpoint="http://test:9003/")
        assert exporter.endpoint == "http://test:9003"

    @responses.activate
    def test_get_allocation_data_success(self, exporter, sample_allocation_data):
        """Test successful allocation data retrieval"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/allocation",
            json=sample_allocation_data,
            status=200
        )

        result = exporter.get_allocation_data(window="1h", aggregate="container")

        assert result == sample_allocation_data
        assert len(responses.calls) == 1

        # Verify request parameters
        request = responses.calls[0].request
        assert "window=1h" in request.url
        assert "aggregate=container" in request.url
        assert "includeIdle=false" in request.url
        assert "shareIdle=false" in request.url

    @responses.activate
    def test_get_allocation_data_with_options(self, exporter, sample_allocation_data):
        """Test allocation data retrieval with all options"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/allocation",
            json=sample_allocation_data,
            status=200
        )

        result = exporter.get_allocation_data(
            window="24h",
            aggregate="namespace",
            include_idle=True,
            share_idle=True
        )

        assert result == sample_allocation_data

        # Verify all parameters are included
        request = responses.calls[0].request
        assert "window=24h" in request.url
        assert "aggregate=namespace" in request.url
        assert "includeIdle=true" in request.url
        assert "shareIdle=true" in request.url

    @responses.activate
    def test_get_allocation_data_api_error(self, exporter):
        """Test API error handling"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/allocation",
            status=500
        )

        with pytest.raises(Exception):
            exporter.get_allocation_data()

    @responses.activate
    def test_get_allocation_data_timeout(self, exporter):
        """Test timeout handling"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/allocation",
            body=responses.ConnectionError("Timeout")
        )

        with pytest.raises(Exception):
            exporter.get_allocation_data()

    def test_export_to_kusto_format_success(self, exporter, sample_allocation_data):
        """Test successful Kusto format export"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            tmp_path = tmp.name

        try:
            exporter.export_to_kusto_format(sample_allocation_data, tmp_path)

            # Verify NDJSON file was created
            assert os.path.exists(tmp_path)

            # Read NDJSON file (newline-delimited JSON)
            data = []
            with open(tmp_path, 'r', encoding='utf-8') as jsonfile:
                for line in jsonfile:
                    if line.strip():  # Skip empty lines
                        data.append(json.loads(line.strip()))

            assert len(data) == 1
            row = data[0]

            # Verify Kusto-optimized structure
            assert 'Timestamp' in row
            assert 'CollectionTime' in row
            assert 'Source' in row
            assert 'RunId' in row
            assert 'Metadata' in row
            assert row['AllocationName'] == 'test-namespace/test-pod/test-container'
            assert row['Namespace'] == 'test-namespace'
            assert row['Pod'] == 'test-pod'
            assert row['Container'] == 'test-container'
            assert row['Node'] == 'test-node'
            assert row['CpuCores'] == 0.5
            assert row['TotalCost'] == 0.042
            assert row['WindowMinutes'] == 60.0
            assert row['RunId'] == ""  # Default empty run_id
            assert row['Metadata'] == {}  # Default empty metadata as object

            # Verify properties are JSON object (not string)
            properties = row['Properties']
            assert isinstance(properties, dict)
            assert properties['namespace'] == 'test-namespace'

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_export_to_kusto_format_empty_data(self, exporter, empty_allocation_data):
        """Test Kusto format export with empty data"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            tmp_path = tmp.name

        # Remove the temp file since we don't want it to exist initially
        os.unlink(tmp_path)

        try:
            # Should not create file for empty data
            exporter.export_to_kusto_format(empty_allocation_data, tmp_path)
            # File should not be created for empty data
            assert not os.path.exists(tmp_path)

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_export_allocation_live_data_kusto(self, exporter, sample_allocation_data):
        """Test live data export to Kusto format"""
        with patch.object(exporter, 'get_allocation_data') as mock_get, \
             patch.object(exporter, 'export_to_kusto_format') as mock_export:

            mock_get.return_value = sample_allocation_data

            filename = exporter.export_allocation_live_data(
                window="2h",
                aggregate="namespace",
                filename="test_output.json"
            )

            mock_get.assert_called_once_with(
                window="2h",
                aggregate="namespace",
                validate_availability=False
            )
            mock_export.assert_called_once_with(sample_allocation_data, "test_output.json")
            assert filename == "test_output.json"

    def test_export_allocation_live_data_auto_filename(self, exporter, sample_allocation_data):
        """Test live data export with auto-generated filename"""
        with patch.object(exporter, 'get_allocation_data') as mock_get, \
             patch.object(exporter, 'export_to_kusto_format') as mock_export, \
             patch('cost_analysis.opencost_live_exporter.datetime') as mock_datetime:

            mock_get.return_value = sample_allocation_data
            mock_datetime.now.return_value.strftime.return_value = "20250117_120000"

            filename = exporter.export_allocation_live_data(
                window="1h",
                aggregate="container"
            )

            expected_filename = "opencost_live_container_1h_20250117_120000.json"
            assert filename == expected_filename
            mock_export.assert_called_once_with(sample_allocation_data, expected_filename)

    def test_init_with_metadata(self):
        """Test initialization with custom metadata"""
        metadata = {'environment': 'dev', 'team': 'platform'}
        exporter = OpenCostLiveExporter(run_id='test-123', metadata=metadata)
        assert exporter.metadata == metadata
        assert exporter.run_id == 'test-123'
        assert exporter.endpoint == "http://localhost:9003"

    def test_export_to_kusto_format_with_metadata(self, exporter_with_metadata, sample_allocation_data):
        """Test Kusto format export includes custom metadata"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            tmp_path = tmp.name

        try:
            exporter_with_metadata.export_to_kusto_format(sample_allocation_data, tmp_path)

            # Verify NDJSON file was created
            assert os.path.exists(tmp_path)

            # Read NDJSON file (newline-delimited JSON)
            data = []
            with open(tmp_path, 'r', encoding='utf-8') as jsonfile:
                for line in jsonfile:
                    if line.strip():  # Skip empty lines
                        data.append(json.loads(line.strip()))

            assert len(data) == 1
            row = data[0]

            # Verify run_id, scenario_name, and metadata are separated correctly
            assert row['RunId'] == 'test-run-123'
            assert row['ScenarioName'] == 'test-scenario'

            # Verify metadata is JSON object (not string) without run_id or scenario_name
            metadata = row['Metadata']
            assert isinstance(metadata, dict)
            assert metadata['test_name'] == 'unit-test'
            assert metadata['environment'] == 'test'
            assert 'run_id' not in metadata  # run_id should not be in metadata anymore
            assert 'scenario_name' not in metadata  # scenario_name should not be in metadata anymore

            assert row['AllocationName'] == 'test-namespace/test-pod/test-container'

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # =============================================
    # Assets API Tests
    # =============================================

    @responses.activate
    def test_get_assets_data_success(self, exporter, sample_assets_data):
        """Test successful assets data retrieval"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/assets",
            json=sample_assets_data,
            status=200
        )

        result = exporter.get_assets_data(window="1h", aggregate="type")

        assert result == sample_assets_data
        assert len(responses.calls) == 1

        # Verify correct URL and parameters
        request = responses.calls[0].request
        assert "window=1h" in request.url
        assert "aggregate=type" in request.url

    @responses.activate
    def test_get_assets_data_with_filters(self, exporter, sample_assets_data):
        """Test assets data retrieval with type filters"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/assets",
            json=sample_assets_data,
            status=200
        )

        result = exporter.get_assets_data(
            window="1h",
            aggregate="type",
            filter_types="Disk,LoadBalancer"
        )

        assert result == sample_assets_data

        # Verify correct URL and parameters
        request = responses.calls[0].request
        assert "filterTypes=Disk%2CLoadBalancer" in request.url

    @responses.activate
    def test_get_assets_data_network_error(self, exporter):
        """Test assets data retrieval with network error"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/assets",
            body=Exception("Network error")
        )

        with pytest.raises(Exception):
            exporter.get_assets_data()

    def test_export_assets_to_kusto_format_success(self, exporter, sample_assets_data):
        """Test successful assets Kusto format export"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            tmp_path = tmp.name

        try:
            exporter.export_assets_to_kusto_format(sample_assets_data, tmp_path)

            # Verify file was created and has correct content
            assert os.path.exists(tmp_path)

            # Read NDJSON file (newline-delimited JSON)
            data = []
            with open(tmp_path, 'r', encoding='utf-8') as jsonfile:
                for line in jsonfile:
                    if line.strip():  # Skip empty lines
                        data.append(json.loads(line.strip()))

            # Verify it's an array of flattened records
            assert isinstance(data, list)
            assert len(data) == 2  # VM and Disk

            # Check VM record
            vm_record = next(record for record in data if record['Type'] == 'Node')
            assert vm_record['Source'] == 'http://test-opencost:9003/assets'
            assert 'test-vm' in vm_record['AssetName']
            assert vm_record['Category'] == 'Compute'
            assert vm_record['TotalCost'] == 0.12
            assert vm_record['Name'] == 'test-vm'
            assert vm_record['RunId'] == ""  # Default empty run_id
            assert vm_record['Metadata'] == {}  # Default empty metadata as object

            # Check Disk record
            disk_record = next(record for record in data if record['Type'] == 'Disk')
            assert disk_record['Category'] == 'Storage'
            assert disk_record['TotalCost'] == 0.05
            assert disk_record['Bytes'] == 107374182400
            assert disk_record['RunId'] == ""  # Default empty run_id
            assert disk_record['Metadata'] == {}  # Default empty metadata as object

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_export_assets_live_data_kusto(self, exporter, sample_assets_data):
        """Test live assets data export to Kusto format"""
        with patch.object(exporter, 'get_assets_data') as mock_get, \
             patch.object(exporter, 'export_assets_to_kusto_format') as mock_export:

            mock_get.return_value = sample_assets_data

            filename = exporter.export_assets_live_data(
                window="30m",
                aggregate="type",
                filename="test_assets.csv"
            )

            # Verify calls
            mock_get.assert_called_once_with(window="30m", aggregate="type", filter_types=None)
            mock_export.assert_called_once_with(sample_assets_data, "test_assets.csv")
            assert filename == "test_assets.csv"

    def test_export_assets_live_data_with_filter(self, exporter, sample_assets_data):
        """Test live assets data export with type filter"""
        with patch.object(exporter, 'get_assets_data') as mock_get, \
             patch.object(exporter, 'export_assets_to_kusto_format') as mock_export:

            mock_get.return_value = sample_assets_data

            exporter.export_assets_live_data(
                window="1h",
                aggregate="type",
                filter_types="Disk,LoadBalancer"
            )

            # Verify filter was passed
            mock_get.assert_called_once_with(
                window="1h",
                aggregate="type",
                filter_types="Disk,LoadBalancer"
            )
            mock_export.assert_called_once()

    def test_export_assets_live_data_auto_filename(self, exporter, sample_assets_data):
        """Test live assets data export with auto-generated filename"""
        with patch.object(exporter, 'get_assets_data') as mock_get, \
             patch.object(exporter, 'export_assets_to_kusto_format') as mock_export, \
             patch('cost_analysis.opencost_live_exporter.datetime') as mock_datetime:

            mock_get.return_value = sample_assets_data
            mock_datetime.now.return_value.strftime.return_value = "20250117_120000"

            filename = exporter.export_assets_live_data(
                window="1h",
                aggregate="type",
                filter_types="Disk,LoadBalancer"
            )

            expected_filename = "opencost_assets_type_1h_Disk_LoadBalancer_20250117_120000.json"
            assert filename == expected_filename
            mock_export.assert_called_once_with(sample_assets_data, expected_filename)

    def test_export_assets_with_metadata(self, exporter_with_metadata, sample_assets_data):
        """Test assets export includes custom metadata"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            tmp_path = tmp.name

        try:
            exporter_with_metadata.export_assets_to_kusto_format(sample_assets_data, tmp_path)

            # Verify file was created and has correct content
            assert os.path.exists(tmp_path)

            # Read NDJSON file (newline-delimited JSON)
            data = []
            with open(tmp_path, 'r', encoding='utf-8') as jsonfile:
                for line in jsonfile:
                    if line.strip():  # Skip empty lines
                        data.append(json.loads(line.strip()))

            # Verify run_id and metadata are separated correctly in all records
            for record in data:
                assert record['RunId'] == 'test-run-123'

                # Verify metadata is JSON object (not string) without run_id
                metadata = record['Metadata']
                assert isinstance(metadata, dict)
                assert metadata['test_name'] == 'unit-test'
                assert metadata['environment'] == 'test'

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # =============================================
    # CLI Tests
    # =============================================


class TestCLI:
    """Test suite for CLI functionality"""

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_basic_usage(self, mock_exporter_class):
        """Test basic CLI usage (always exports both allocation and assets)"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = "allocation_output.json"
        mock_exporter.export_assets_live_data.return_value = "assets_output.json"

        with patch('sys.argv', ['opencost_live_exporter.py', '--window', '30m']):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify exporter was initialized correctly
        mock_exporter_class.assert_called_once_with(endpoint='http://localhost:9003', run_id="", scenario_name="", metadata={})

        # Verify both allocation and assets export were called
        mock_exporter.export_allocation_live_data.assert_called_once_with(
            window='30m',
            aggregate='container',
            filename=None,
            validate_availability=False
        )
        mock_exporter.export_assets_live_data.assert_called_once_with(
            window='30m',
            aggregate='container',
            filename=None,
            filter_types=None
        )

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_all_options(self, mock_exporter_class):
        """Test CLI with all options (always exports both allocation and assets)"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = "custom_allocation.json"
        mock_exporter.export_assets_live_data.return_value = "custom_assets.json"

        args = [
            'opencost_live_exporter.py',
            '--endpoint', 'http://custom:8080',
            '--window', '24h',
            '--aggregate', 'namespace',
            '--allocation-output', 'custom_allocation.json',
            '--assets-output', 'custom_assets.json'
        ]

        with patch('sys.argv', args):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify exporter was initialized with custom endpoint
        mock_exporter_class.assert_called_once_with(endpoint='http://custom:8080', run_id="", scenario_name="", metadata={})

        # Verify both exports were called with all parameters
        mock_exporter.export_allocation_live_data.assert_called_once_with(
            window='24h',
            aggregate='namespace',
            filename='custom_allocation.json',
            validate_availability=False
        )
        mock_exporter.export_assets_live_data.assert_called_once_with(
            window='24h',
            aggregate='namespace',
            filename='custom_assets.json',
            filter_types=None
        )

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_export_failure(self, mock_exporter_class):
        """Test CLI export failure handling"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.side_effect = Exception("Export failed")

        args = [
            'opencost_live_exporter.py',
            '--window', '1h'
        ]

        with patch('sys.argv', args), \
             patch('sys.exit') as mock_exit:
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify sys.exit was called with error code
        mock_exit.assert_called_once_with(1)

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_with_metadata(self, mock_exporter_class):
        """Test CLI with metadata"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = 'output.json'

        args = [
            'opencost_live_exporter.py',
            '--window', '1h',
            '--run-id', 'test-123',
            '--metadata', 'env=prod',
            '--metadata', 'team=platform'
        ]

        with patch('sys.argv', args):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify exporter was created with metadata
        expected_metadata = {
            'env': 'prod',
            'team': 'platform'
        }
        mock_exporter_class.assert_called_once_with(endpoint='http://localhost:9003', run_id='test-123', scenario_name="", metadata=expected_metadata)

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_with_validation_flag(self, mock_exporter_class):
        """Test CLI with validation flag enabled"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = 'allocation_validated.json'
        mock_exporter.export_assets_live_data.return_value = 'assets_validated.json'

        args = [
            'opencost_live_exporter.py',
            '--window', '2h',
            '--aggregate', 'namespace',
            '--validate-availability',
            '--run-id', 'validation-test-456'
        ]

        with patch('sys.argv', args):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify exporter was created correctly
        mock_exporter_class.assert_called_once_with(endpoint='http://localhost:9003', run_id='validation-test-456', scenario_name="", metadata={})

        # Verify allocation export was called with validation enabled
        mock_exporter.export_allocation_live_data.assert_called_once_with(
            window='2h',
            aggregate='namespace',
            filename=None,
            validate_availability=True
        )

        # Verify assets export was called (validation only applies to allocation)
        mock_exporter.export_assets_live_data.assert_called_once_with(
            window='2h',
            aggregate='namespace',
            filename=None,
            filter_types=None
        )

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_assets_basic(self, mock_exporter_class):
        """Test CLI assets functionality basic usage - now always exports both allocation and assets"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = "allocation_output.json"
        mock_exporter.export_assets_live_data.return_value = "assets_output.json"

        args = [
            'opencost_live_exporter.py',
            '--window', '1h',
            '--aggregate', 'type'
        ]

        with patch('sys.argv', args):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify exporter was initialized correctly
        mock_exporter_class.assert_called_once_with(endpoint='http://localhost:9003', run_id="", scenario_name="", metadata={})

        # Verify both allocation and assets export were called
        mock_exporter.export_allocation_live_data.assert_called_once_with(
            window='1h',
            aggregate='type',
            filename=None,
            validate_availability=False
        )
        mock_exporter.export_assets_live_data.assert_called_once_with(
            window='1h',
            aggregate='type',
            filename=None,
            filter_types=None
        )

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_assets_with_filter(self, mock_exporter_class):
        """Test CLI assets functionality with type filter - now always exports both allocation and assets"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = "allocation_output.json"
        mock_exporter.export_assets_live_data.return_value = "filtered_assets.json"

        args = [
            'opencost_live_exporter.py',
            '--window', '24h',
            '--aggregate', 'account',
            '--filter-types', 'Disk,LoadBalancer',
            '--assets-output', 'filtered_assets.json'
        ]

        with patch('sys.argv', args):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify both allocation and assets export were called
        mock_exporter.export_allocation_live_data.assert_called_once_with(
            window='24h',
            aggregate='account',
            filename=None,
            validate_availability=False
        )
        mock_exporter.export_assets_live_data.assert_called_once_with(
            window='24h',
            aggregate='account',
            filename='filtered_assets.json',
            filter_types='Disk,LoadBalancer'
        )

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_assets_with_metadata(self, mock_exporter_class):
        """Test CLI assets functionality with metadata - now always exports both allocation and assets"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = "allocation_output.json"
        mock_exporter.export_assets_live_data.return_value = "assets_with_metadata.json"

        args = [
            'opencost_live_exporter.py',
            '--window', '2h',
            '--aggregate', 'service',
            '--run-id', 'assets-test-789',
            '--metadata', 'cluster=prod-east',
            '--metadata', 'cost_center=engineering'
        ]

        with patch('sys.argv', args):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify exporter was initialized with correct metadata
        expected_metadata = {
            'cluster': 'prod-east',
            'cost_center': 'engineering'
        }
        mock_exporter_class.assert_called_once_with(endpoint='http://localhost:9003', run_id='assets-test-789', scenario_name="", metadata=expected_metadata)

        # Verify both allocation and assets export were called
        mock_exporter.export_allocation_live_data.assert_called_once_with(
            window='2h',
            aggregate='service',
            filename=None,
            validate_availability=False
        )
        mock_exporter.export_assets_live_data.assert_called_once_with(
            window='2h',
            aggregate='service',
            filename=None,
            filter_types=None
        )

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_dual_export(self, mock_exporter_class):
        """Test CLI dual export functionality (both allocation and assets)"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = "allocation_data.json"
        mock_exporter.export_assets_live_data.return_value = "assets_data.json"

        args = [
            'opencost_live_exporter.py',
            '--window', '1h',
            '--aggregate', 'namespace',
            '--allocation-output', 'allocation_output.json',
            '--assets-output', 'assets_output.json',
            '--filter-types', 'Disk,LoadBalancer'
        ]

        with patch('sys.argv', args):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify exporter was initialized
        mock_exporter_class.assert_called_once_with(endpoint='http://localhost:9003', run_id="", scenario_name="", metadata={})

        # Verify both allocation and assets exports were called
        mock_exporter.export_allocation_live_data.assert_called_once_with(
            window='1h',
            aggregate='namespace',
            filename='allocation_output.json',
            validate_availability=False
        )
        mock_exporter.export_assets_live_data.assert_called_once_with(
            window='1h',
            aggregate='namespace',
            filename='assets_output.json',
            filter_types='Disk,LoadBalancer'
        )

    @patch('cost_analysis.opencost_live_exporter.OpenCostLiveExporter')
    def test_main_dual_export_with_metadata(self, mock_exporter_class):
        """Test CLI dual export functionality with metadata"""
        mock_exporter = Mock()
        mock_exporter_class.return_value = mock_exporter
        mock_exporter.export_allocation_live_data.return_value = "allocation_meta.json"
        mock_exporter.export_assets_live_data.return_value = "assets_meta.json"

        args = [
            'opencost_live_exporter.py',
            '--window', '4h',
            '--aggregate', 'pod',
            '--assets-output', 'assets_with_meta.json',
            '--run-id', 'dual-export-test-123',
            '--metadata', 'environment=staging',
            '--metadata', 'team=platform'
        ]

        with patch('sys.argv', args):
            from cost_analysis.opencost_live_exporter import main  # pylint: disable=import-outside-toplevel
            main()

        # Verify exporter was initialized with correct metadata
        expected_metadata = {
            'environment': 'staging',
            'team': 'platform'
        }
        mock_exporter_class.assert_called_once_with(endpoint='http://localhost:9003', run_id='dual-export-test-123', scenario_name="", metadata=expected_metadata)

        # Verify both exports were called
        mock_exporter.export_allocation_live_data.assert_called_once_with(
            window='4h',
            aggregate='pod',
            filename=None,  # Auto-generated filename
            validate_availability=False
        )
        mock_exporter.export_assets_live_data.assert_called_once_with(
            window='4h',
            aggregate='pod',
            filename='assets_with_meta.json',
            filter_types=None
        )


class TestWindowFormatValidation:
    """Test cases for window format validation"""

    def test_valid_second_formats(self):
        """Test valid second formats"""
        valid_formats = ["30s", "45s", "60s", "1s", "3600s"]
        for fmt in valid_formats:
            assert OpenCostLiveExporter.validate_window_format(fmt)

    def test_valid_minute_formats(self):
        """Test valid minute formats"""
        valid_formats = ["1m", "5m", "10m", "15m", "30m", "45m", "60m"]
        for fmt in valid_formats:
            assert OpenCostLiveExporter.validate_window_format(fmt)

    def test_valid_hour_formats(self):
        """Test valid hour formats"""
        valid_formats = ["1h", "2h", "6h", "12h", "24h", "48h", "168h"]
        for fmt in valid_formats:
            assert OpenCostLiveExporter.validate_window_format(fmt)

    def test_valid_day_formats(self):
        """Test valid day formats"""
        valid_formats = ["1d", "2d", "7d", "14d", "30d", "90d", "365d"]
        for fmt in valid_formats:
            assert OpenCostLiveExporter.validate_window_format(fmt)

    def test_valid_compound_formats(self):
        """Test valid compound formats"""
        valid_formats = ["1h30m", "2d12h", "1d6h", "3h45m", "2h15m"]
        for fmt in valid_formats:
            assert OpenCostLiveExporter.validate_window_format(fmt)

    def test_valid_special_formats(self):
        """Test valid special formats"""
        valid_formats = ["today", "yesterday", "week", "month", "year"]
        for fmt in valid_formats:
            assert OpenCostLiveExporter.validate_window_format(fmt)

    def test_case_insensitive_special_formats(self):
        """Test case insensitive special formats"""
        valid_formats = ["TODAY", "Yesterday", "WEEK", "Month", "YEAR"]
        for fmt in valid_formats:
            assert OpenCostLiveExporter.validate_window_format(fmt)

    def test_invalid_window_formats(self):
        """Test invalid window formats"""
        invalid_formats = [
            "",           # Empty string
            "   ",        # Whitespace only
            "60",         # Missing unit
            "60ms",       # Invalid unit
            "1.5h",       # Decimal not supported
            "1h30",       # Missing unit for second part
            "30m1h",      # Wrong order
            "invalid",    # Invalid string
            "1y",         # Invalid unit
            "1w",         # Invalid unit
            "-1h",        # Negative value
            "0h",         # Zero value
        ]

        for fmt in invalid_formats:
            with pytest.raises(ValueError):
                OpenCostLiveExporter.validate_window_format(fmt)

    def test_invalid_types(self):
        """Test invalid input types"""
        invalid_inputs = [None, 123, [], {}]

        for inp in invalid_inputs:
            with pytest.raises(ValueError):
                OpenCostLiveExporter.validate_window_format(inp)


class TestDataAvailabilityValidation:
    """Test suite for data availability validation"""

    @pytest.fixture
    def exporter(self):
        """Create an OpenCostLiveExporter instance for testing"""
        return OpenCostLiveExporter(endpoint="http://test-opencost:9003")

    @pytest.fixture
    def sample_validation_data_success(self):
        """Sample data for successful validation testing"""
        return {
            "code": 200,
            "status": "success",
            "data": [
                {
                    "test-namespace": {
                        "name": "test-namespace",
                        "start": "2025-07-30T14:00:00Z",
                        "end": "2025-07-30T14:01:00Z",
                        "minutes": 1.0,
                        "properties": {
                            "namespace": "test-namespace"
                        },
                        "totalCost": 0.042
                    }
                }
            ]
        }

    @pytest.fixture
    def sample_validation_data_empty(self):
        """Sample empty data for validation testing"""
        return {
            "code": 200,
            "status": "success",
            "data": []
        }

    def test_parse_window_to_minutes_simple_formats(self):
        """Test parsing simple window formats to minutes"""
        assert OpenCostLiveExporter._parse_window_to_minutes("30s") == 0.5
        assert OpenCostLiveExporter._parse_window_to_minutes("5m") == 5
        assert OpenCostLiveExporter._parse_window_to_minutes("2h") == 120
        assert OpenCostLiveExporter._parse_window_to_minutes("1d") == 1440

    def test_parse_window_to_minutes_compound_formats(self):
        """Test parsing compound window formats to minutes"""
        assert OpenCostLiveExporter._parse_window_to_minutes("1h30m") == 90
        assert OpenCostLiveExporter._parse_window_to_minutes("2d12h") == 3600

    def test_parse_window_to_minutes_special_formats(self):
        """Test parsing special window formats to minutes"""
        # Test yesterday (24 hours)
        assert OpenCostLiveExporter._parse_window_to_minutes("yesterday") == 1440
        
        # Test week (7 days)
        assert OpenCostLiveExporter._parse_window_to_minutes("week") == 10080

    def test_parse_window_to_minutes_invalid(self):
        """Test parsing invalid window formats"""
        with pytest.raises(ValueError):
            OpenCostLiveExporter._parse_window_to_minutes("invalid")
        
        with pytest.raises(ValueError):
            OpenCostLiveExporter._parse_window_to_minutes("1y")

    @responses.activate
    def test_validate_data_availability_success(self, exporter, sample_validation_data_success):
        """Test successful data availability validation"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/allocation",
            json=sample_validation_data_success,
            status=200
        )
        
        # Should not raise an exception
        result = exporter.validate_data_availability(window="60m")
        assert result is True
        
        # Verify the request was made with ISO timestamp format
        request = responses.calls[0].request
        assert "window=" in request.url
        # Should contain start and end time in ISO format with Z suffix
        assert "T" in request.url  # ISO timestamp format
        assert "Z" in request.url  # UTC timezone

    @responses.activate
    def test_validate_data_availability_no_data(self, exporter, sample_validation_data_empty):
        """Test data availability validation with no data"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/allocation",
            json=sample_validation_data_empty,
            status=200
        )
        
        # Should raise ValueError due to no data
        with pytest.raises(ValueError) as exc_info:
            exporter.validate_data_availability(window="60m")
        
        assert "No allocation data available" in str(exc_info.value)

    @responses.activate
    def test_validate_data_availability_empty_window_data(self, exporter):
        """Test data availability validation with empty window data"""
        data_with_empty_windows = {
            "code": 200,
            "status": "success",
            "data": [{}]  # Empty window data
        }
        
        responses.add(
            responses.GET,
            "http://test-opencost:9003/allocation",
            json=data_with_empty_windows,
            status=200
        )
        
        # Should raise ValueError due to no allocation data in windows
        with pytest.raises(ValueError) as exc_info:
            exporter.validate_data_availability(window="60m")
        
        assert "No allocation data found" in str(exc_info.value)

    @responses.activate
    def test_validate_data_availability_api_error(self, exporter):
        """Test data availability validation with API error"""
        responses.add(
            responses.GET,
            "http://test-opencost:9003/allocation",
            status=500
        )
        
        # Should raise RequestException
        with pytest.raises(Exception):
            exporter.validate_data_availability(window="60m")

    def test_validate_data_availability_invalid_window(self, exporter):
        """Test data availability validation with invalid window format"""
        # Should raise ValueError for invalid window format
        with pytest.raises(ValueError) as exc_info:
            exporter.validate_data_availability(window="invalid")
        
        assert "Invalid window format" in str(exc_info.value)

    def test_get_allocation_data_with_validation(self, exporter, sample_validation_data_success):
        """Test get_allocation_data with validation enabled"""
        with patch.object(exporter, 'validate_data_availability') as mock_validate, \
             patch.object(exporter.session, 'get') as mock_get:
            
            mock_response = Mock()
            mock_response.json.return_value = sample_validation_data_success
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            result = exporter.get_allocation_data(
                window="60m",
                validate_availability=True
            )
            
            # Verify validation was called with correct parameters
            mock_validate.assert_called_once_with("60m", "container")
            assert result == sample_validation_data_success

    def test_export_allocation_live_data_with_validation(self, exporter, sample_validation_data_success):
        """Test export_allocation_live_data with validation enabled"""
        with patch.object(exporter, 'get_allocation_data') as mock_get, \
             patch.object(exporter, 'export_to_kusto_format') as _mock_export, \
             patch('cost_analysis.opencost_live_exporter.datetime') as mock_datetime:
            
            mock_datetime.now.return_value = datetime(2025, 1, 1, 12, 0, 0)
            mock_get.return_value = sample_validation_data_success
            
            filename = exporter.export_allocation_live_data(
                window="60m",
                validate_availability=True
            )
            
            # Verify validation parameters were passed through
            mock_get.assert_called_once_with(
                window="60m",
                aggregate="container",
                validate_availability=True
            )
            
            assert filename == "opencost_live_container_60m_20250101_120000.json"


if __name__ == "__main__":
    pytest.main([__file__])
