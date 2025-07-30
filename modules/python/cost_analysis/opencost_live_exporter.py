"""
OpenCost Live Data Exporter

This module provides live data export from OpenCost API, bypassing the need to wait
for daily CSV exports. It extracts allocation and assets data in Kusto-optimized format.

Key advantages over the built-in CSV export:
- Live data access (no 24-hour wait)
- Flexible time windows (minutes, hours, days)
- Multiple aggregation levels
- Kusto-optimized output format
- Real-time cost analysis
- Support for both allocation and assets data

Usage:
    # Export both allocation and assets data (default behavior)
    python opencost_live_exporter.py --window 1h --aggregate container
    python opencost_live_exporter.py --window 30m --aggregate pod
    python opencost_live_exporter.py --window 1d --aggregate namespace
    
    # Export with custom output filenames
    python opencost_live_exporter.py --window 1h --allocation-output allocation.json --assets-output assets.json
    
    # Export with filtered asset types
    python opencost_live_exporter.py --window 1h --aggregate container --filter-types "Disk,LoadBalancer"
    
    # Export with metadata
    python opencost_live_exporter.py --window 4h --run-id test-123 --scenario-name nap-benchmark --metadata environment=production
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import logging
import re
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SUPPORTED_WINDOW_FORMATS = [
    "30s", "1m", "1h", "1d", "today", "yesterday"
]

class OpenCostLiveExporter:
    """Live data exporter for OpenCost API"""

    def __init__(self, endpoint: str = "http://localhost:9003", run_id: str = "", scenario_name: str = "", metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize the OpenCost Live Exporter
        
        Args:
            endpoint: OpenCost API endpoint
            run_id: Run ID for tracking exports across multiple calls
            scenario_name: Scenario name for categorizing test runs
            metadata: Optional metadata to include in exports (e.g., test_name, environment, etc.)
        """
        self.endpoint = endpoint.rstrip('/')
        self.run_id = run_id
        self.scenario_name = scenario_name
        self.metadata = metadata or {}

        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'OpenCost-Live-Exporter/1.0'
        })

    @staticmethod
    def validate_window_format(window: str) -> bool:
        """
        Validate window format against OpenCost API requirements
        Raises:
            ValueError: If window format is invalid
        """
        if not window or not isinstance(window, str):
            logger.error("Window must be a non-empty string")
            raise ValueError(f"Window must be a non-empty string, got: {type(window).__name__}")

        window = window.strip()

        # Check if empty after stripping
        if not window:
            logger.error("Window cannot be empty or whitespace only")
            raise ValueError("Window cannot be empty or whitespace only")

        # Check special formats first
        special_formats = ['today', 'yesterday', 'week', 'month', 'year']
        if window.lower() in special_formats:
            return True

        # Check simple duration formats (1h, 30m, 7d, etc.)
        simple_pattern = r'^(\d+)([smhd])$'
        simple_match = re.match(simple_pattern, window, re.IGNORECASE)
        if simple_match:
            number = int(simple_match.group(1))
            if number == 0:
                logger.error("Window cannot be zero: '%s'", window)
                raise ValueError(f"Window cannot be zero: '{window}'")
            return True

        # Check compound formats (1h30m, 2d12h, etc.)
        compound_pattern = r'^(\d+)([hd])(\d+)([mh])$'
        compound_match = re.match(compound_pattern, window, re.IGNORECASE)
        if compound_match:
            num1 = int(compound_match.group(1))
            num2 = int(compound_match.group(3))
            if num1 == 0 or num2 == 0:
                logger.error("Window cannot have zero values: '%s'", window)
                raise ValueError(f"Window cannot have zero values: '{window}'")
            return True

        logger.error("Invalid window format: '%s'", window)
        raise ValueError(f"Invalid window format: '{window}'")

    @staticmethod
    def _parse_window_to_minutes(window: str) -> int:
        """
        Parse window string to minutes for validation
        
        Args:
            window: Window string (e.g., '60m', '1h', '2d')
            
        Returns:
            Number of minutes in the window
            
        Raises:
            ValueError: If window format cannot be parsed
        """
        window = window.strip().lower()

        # Handle special formats
        if window == 'today':
            # Today from midnight to now
            now = datetime.now()
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return int((now - midnight).total_seconds() / 60)
        if window == 'yesterday':
            return 24 * 60  # 24 hours
        if window == 'week':
            return 7 * 24 * 60  # 7 days
        if window == 'month':
            return 30 * 24 * 60  # 30 days
        if window == 'year':
            return 365 * 24 * 60  # 365 days

        # Handle simple duration formats
        simple_pattern = r'^(\d+)([smhd])$'
        simple_match = re.match(simple_pattern, window)
        if simple_match:
            number = int(simple_match.group(1))
            unit = simple_match.group(2)
  
            if unit == 's':
                return number / 60  # Convert seconds to minutes
            if unit == 'm':
                return number
            if unit == 'h':
                return number * 60
            if unit == 'd':
                return number * 24 * 60
        
        # Handle compound formats (1h30m, 2d12h, etc.)
        compound_pattern = r'^(\d+)([hd])(\d+)([mh])$'
        compound_match = re.match(compound_pattern, window)
        if compound_match:
            num1 = int(compound_match.group(1))
            unit1 = compound_match.group(2)
            num2 = int(compound_match.group(3))
            unit2 = compound_match.group(4)
            
            minutes = 0
            if unit1 == 'h':
                minutes += num1 * 60
            if unit1 == 'd':
                minutes += num1 * 24 * 60
                
            if unit2 == 'm':
                minutes += num2
            if unit2 == 'h':
                minutes += num2 * 60
                
            return minutes
        
        raise ValueError(f"Cannot parse window to minutes: '{window}'")

    def validate_data_availability(self,
                                 window: str,
                                 aggregate: str = "namespace") -> bool:
        """
        Validate that OpenCost has data available for the specified window
        by checking if data exists at the window start time
        
        Args:
            window: Time window to validate (e.g., '60m', '1h')
            aggregate: Aggregation level for validation query
            
        Returns:
            True if data is available for the window
            
        Raises:
            ValueError: If data is not available for the specified window
            requests.exceptions.RequestException: If API call fails
        """
        # Validate window format first
        self.validate_window_format(window)
        
        # Calculate the start time of the requested window
        try:
            window_minutes = self._parse_window_to_minutes(window)
        except ValueError as e:
            logger.error("Cannot validate data availability: %s", e)
            raise
        
        # Calculate expected start time (current_time - window_duration)
        now = datetime.now()
        expected_start = now - timedelta(minutes=window_minutes)
        
        logger.info("Validating data availability for window '%s' (%s minutes)", 
                   window, window_minutes)
        logger.info("Expected start time: %s", expected_start.isoformat())
        
        # Query for a 1-minute window starting at the expected start time
        # Format: start_time=expected_start, end_time=expected_start+1min
        start_time_str = expected_start.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time = expected_start + timedelta(minutes=1)
        end_time_str = end_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        url = f"{self.endpoint}/allocation"
        params = {
            'window': f'{start_time_str},{end_time_str}',  # Specific time range in ISO format
            'aggregate': aggregate
        }
        
        try:
            logger.info("Checking data availability at start time: %s?%s",
                       url, self._format_params(params))
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get('data') or len(data['data']) == 0:
                raise ValueError(
                    f"No allocation data available at window start time for '{window}'. "
                    f"Expected data at {expected_start.isoformat()}"
                )
            
            # Check if we have any allocation data in the response
            has_data = False
            for window_data in data['data']:
                if window_data and len(window_data) > 0:
                    has_data = True
                    break
            
            if not has_data:
                raise ValueError(
                    f"No allocation data found at window start time for '{window}'. "
                    f"Expected data at {expected_start.isoformat()}"
                )
            
            logger.info("Data availability validated successfully for window '%s' at start time %s", 
                       window, expected_start.isoformat())
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error("Failed to validate data availability: %s", e)
            raise

    def get_allocation_data(self,
                          window: str = "1h",
                          aggregate: str = "container",
                          include_idle: bool = False,
                          share_idle: bool = False,
                          validate_availability: bool = False) -> Dict[str, Any]:
        """
        Get allocation data from OpenCost API
        
        Args:
            window: Time window (30m, 1h, 1d, today, yesterday, etc.)
            aggregate: Aggregation level (container, pod, namespace, node, etc.)
            include_idle: Include idle allocations
            share_idle: Share idle costs across allocations
            validate_availability: Validate data availability before fetching (default: False)
            
        Returns:
            Raw allocation data from OpenCost API
            
        Raises:
            ValueError: If window format is invalid or data not available (when validation enabled)
        """
        # Validate window format
        self.validate_window_format(window)

        # Validate data availability if requested
        if validate_availability:
            self.validate_data_availability(window, aggregate)

        url = f"{self.endpoint}/allocation"
        params = {
            'window': window,
            'aggregate': aggregate,
            'includeIdle': str(include_idle).lower(),
            'shareIdle': str(share_idle).lower()
        }

        try:
            logger.info("Fetching allocation data: %s?%s",
                       url, self._format_params(params))
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            logger.info("Successfully fetched %s allocation windows",
                       len(data.get('data', [])))
            return data

        except requests.exceptions.RequestException as e:
            logger.error("Failed to fetch allocation data: %s", e)
            raise

    @staticmethod
    def _format_params(params: Dict[str, str]) -> str:
        """Format parameters for logging"""
        return "&".join(f"{k}={v}" for k, v in params.items())

    def export_to_kusto_format(self, data: Dict[str, Any], filename: str) -> None:
        """
        Export allocation data in Kusto-optimized format
        
        Args:
            data: Raw allocation data from OpenCost API
            filename: Output filename
        """
        if not data.get('data'):
            logger.warning("No data to export")
            return

        # Flatten for Kusto ingestion
        kusto_rows = []
        collection_time = datetime.now()

        for window_data in data['data']:
            for allocation_name, allocation_data in window_data.items():
                row = {
                    'Timestamp': datetime.now().isoformat(),
                    'CollectionTime': collection_time.isoformat(),
                    'Source': self.endpoint,
                    'RunId': self.run_id,  # Use self.run_id attribute
                    'ScenarioName': self.scenario_name,  # Use self.scenario_name attribute
                    'Metadata': self.metadata if self.metadata else {},  # Metadata as object for Kusto dynamic type
                    'AllocationName': allocation_name,
                    'WindowStart': allocation_data.get('start', ''),
                    'WindowEnd': allocation_data.get('end', ''),
                    'WindowMinutes': allocation_data.get('minutes', 0),
                    'Namespace': allocation_data.get('properties', {}).get('namespace', ''),
                    'Node': allocation_data.get('properties', {}).get('node', ''),
                    'Container': allocation_data.get('properties', {}).get('container', ''),
                    'Pod': allocation_data.get('properties', {}).get('pod', ''),
                    'Controller': allocation_data.get('properties', {}).get('controller', ''),
                    'ControllerKind': allocation_data.get('properties', {}).get('controllerKind', ''),
                    'CpuCores': allocation_data.get('cpuCores', 0),
                    'CpuCoreHours': allocation_data.get('cpuCoreHours', 0),
                    'CpuCost': allocation_data.get('cpuCost', 0),
                    'CpuEfficiency': allocation_data.get('cpuEfficiency', 0),
                    'RamBytes': allocation_data.get('ramBytes', 0),
                    'RamByteHours': allocation_data.get('ramByteHours', 0),
                    'RamCost': allocation_data.get('ramCost', 0),
                    'RamEfficiency': allocation_data.get('ramEfficiency', 0),
                    'GpuCount': allocation_data.get('gpuCount', 0),
                    'GpuHours': allocation_data.get('gpuHours', 0),
                    'GpuCost': allocation_data.get('gpuCost', 0),
                    'NetworkCost': allocation_data.get('networkCost', 0),
                    'LoadBalancerCost': allocation_data.get('loadBalancerCost', 0),
                    'PvCost': allocation_data.get('pvCost', 0),
                    'TotalCost': allocation_data.get('totalCost', 0),
                    'TotalEfficiency': allocation_data.get('totalEfficiency', 0),
                    'ExternalCost': allocation_data.get('externalCost', 0),
                    'SharedCost': allocation_data.get('sharedCost', 0),
                    'Properties': allocation_data.get('properties', {})  # Properties as object for Kusto dynamic type
                }
                kusto_rows.append(row)

        # Save as NDJSON (newline-delimited JSON) for Kusto ingestion
        with open(filename, 'w', encoding='utf-8') as jsonfile:
            for row in kusto_rows:
                json.dump(row, jsonfile, ensure_ascii=False)
                jsonfile.write('\n')

        logger.info("Exported %s rows to %s in Kusto NDJSON format",
                   len(kusto_rows), filename)

    def export_allocation_live_data(self,
                        window: str = "1h",
                        aggregate: str = "container",
                        filename: Optional[str] = None,
                        validate_availability: bool = False) -> str:
        """
        Export live OpenCost allocation data in Kusto format
        
        Args:
            window: Time window for data
            aggregate: Aggregation level
            filename: Output filename (auto-generated if not provided)
            validate_availability: Validate data availability before fetching (default: False)
            
        Returns:
            Generated filename
        """
        # Get data from OpenCost API
        data = self.get_allocation_data(
            window=window,
            aggregate=aggregate,
            validate_availability=validate_availability
        )

        # Generate filename if not provided
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"opencost_live_{aggregate}_{window}_{timestamp}.json"

        # Export in Kusto format
        self.export_to_kusto_format(data, filename)

        return filename

    def get_assets_data(self,
                       window: str = "1h",
                       aggregate: str = "type",
                       filter_types: Optional[str] = None) -> Dict[str, Any]:
        """
        Get assets data from OpenCost API
        
        Args:
            window: Time window (30m, 1h, 1d, today, yesterday, etc.)
            aggregate: Aggregation level (type, account, project, service, etc.)
            filter_types: Filter by asset types (e.g., "Disk,LoadBalancer")
            
        Returns:
            Raw assets data from OpenCost API
            
        Raises:
            ValueError: If window format is invalid
        """
        # Validate window format
        self.validate_window_format(window)

        url = f"{self.endpoint}/assets"
        params = {
            'window': window,
            'aggregate': aggregate
        }

        if filter_types:
            params['filterTypes'] = filter_types

        try:
            logger.info(f"Fetching assets data: {url}?{self._format_params(params)}")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            logger.info(f"Successfully fetched {len(data.get('data', []))} asset windows")
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch assets data: {e}")
            raise

    def export_assets_to_kusto_format(self, data: Dict[str, Any], filename: str) -> None:
        """
        Export assets data in Kusto-optimized format
        
        Args:
            data: Raw assets data from OpenCost API
            filename: Output filename
        """
        if not data.get('data'):
            logger.warning("No assets data to export")
            return

        # Flatten for Kusto ingestion - assets API returns different structure
        kusto_rows = []
        collection_time = datetime.now()
        assets_data = data['data']

        for asset_name, asset_data in assets_data.items():
            row = {
                'Timestamp': datetime.now().isoformat(),
                'CollectionTime': collection_time.isoformat(),
                'Source': f"{self.endpoint}/assets",
                'RunId': self.run_id,  # Use self.run_id attribute
                'ScenarioName': self.scenario_name,  # Use self.scenario_name attribute
                'Metadata': self.metadata if self.metadata else {},  # Metadata as object for Kusto dynamic type
                'AssetName': asset_name,
                'WindowStart': asset_data.get('start', ''),
                'WindowEnd': asset_data.get('end', ''),
                'WindowMinutes': asset_data.get('minutes', 0),
                'Type': asset_data.get('type', ''),
                'Account': asset_data.get('properties', {}).get('account', ''),
                'Project': asset_data.get('properties', {}).get('project', ''),
                'Service': asset_data.get('properties', {}).get('service', ''),
                'Region': asset_data.get('properties', {}).get('region', ''),
                'Category': asset_data.get('properties', {}).get('category', ''),
                'Provider': asset_data.get('properties', {}).get('provider', ''),
                'ProviderID': asset_data.get('properties', {}).get('providerID', ''),
                'Name': asset_data.get('properties', {}).get('name', ''),
                'Cost': asset_data.get('cost', 0),
                'Adjustment': asset_data.get('adjustment', 0),
                'TotalCost': asset_data.get('totalCost', 0),
                'Bytes': asset_data.get('bytes', 0),
                'Breakdown': json.dumps(asset_data.get('breakdown', {})),
                'Labels': json.dumps(asset_data.get('labels', {}))
            }
            kusto_rows.append(row)

        # Save as NDJSON (newline-delimited JSON) for Kusto ingestion
        with open(filename, 'w', encoding='utf-8') as jsonfile:
            for row in kusto_rows:
                json.dump(row, jsonfile, ensure_ascii=False)
                jsonfile.write('\n')

        logger.info("Exported %s asset rows to %s in Kusto NDJSON format",
                   len(kusto_rows), filename)

    def export_assets_live_data(self,
                               window: str = "1h",
                               aggregate: str = "type",
                               filename: Optional[str] = None,
                               filter_types: Optional[str] = None) -> str:
        """
        Export live OpenCost assets data in Kusto format
        
        Args:
            window: Time window for data
            aggregate: Aggregation level
            filename: Output filename (auto-generated if not provided)
            filter_types: Filter by asset types
            
        Returns:
            Generated filename
        """
        # Get data from OpenCost Assets API
        data = self.get_assets_data(window=window, aggregate=aggregate, filter_types=filter_types)

        # Generate filename if not provided
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filter_suffix = f"_{filter_types.replace(',', '_')}" if filter_types else ""
            filename = f"opencost_assets_{aggregate}_{window}{filter_suffix}_{timestamp}.json"

        # Export in Kusto format
        self.export_assets_to_kusto_format(data, filename)

        return filename


def main():
    """Main CLI function"""
    parser = argparse.ArgumentParser(
        description='OpenCost Live Data Exporter - Export live cost allocation and assets data without waiting 24 hours. Always exports both allocation and assets data in one call.'
    )

    parser.add_argument(
        '--endpoint',
        default='http://localhost:9003',
        help='OpenCost API endpoint (default: http://localhost:9003)'
    )

    parser.add_argument(
        '--port',
        type=int,
        help='OpenCost API port (overrides port in endpoint if specified)'
    )

    parser.add_argument(
        '--window',
        default='1h',
        help='Time window for data (default: 1h). Examples: 30m, 1h, 24h, today, yesterday'
    )

    parser.add_argument(
        '--aggregate',
        default='container',
        help='Aggregation level (default: container). For allocations: container, pod, namespace, node, controller. For assets: type, account, project, service'
    )

    parser.add_argument(
        '--allocation-output',
        help='Output filename for allocation data (auto-generated if not provided)'
    )

    parser.add_argument(
        '--assets-output',
        help='Output filename for assets data (auto-generated if not provided)'
    )

    parser.add_argument(
        '--include-idle',
        action='store_true',
        help='Include idle allocations'
    )

    parser.add_argument(
        '--share-idle',
        action='store_true',
        help='Share idle costs across allocations'
    )

    parser.add_argument(
        '--run-id',
        help='Unique identification of a test (benchmark) run'
    )

    parser.add_argument(
        '--scenario-name',
        help='Scenario name for categorizing test runs'
    )

    parser.add_argument(
        '--metadata',
        action='append',
        help='Additional metadata in key=value format (can be used multiple times)'
    )

    parser.add_argument(
        '--filter-types',
        help='Filter asset types (e.g., "Disk,LoadBalancer")'
    )

    parser.add_argument(
        '--validate-availability',
        action='store_true',
        help='Validate data availability for the specified window before fetching data'
    )

    args = parser.parse_args()

    try:
        # Validate window format
        try:
            OpenCostLiveExporter.validate_window_format(args.window)
        except ValueError as e:
            logger.error("Invalid window format: %s", e)
            logger.info("Supported window formats: %s...",
                       ', '.join(SUPPORTED_WINDOW_FORMATS[:10]))
            sys.exit(1)

        # Process metadata
        metadata = {}

        # Process additional metadata (run_id will be passed separately)
        if args.metadata:
            for meta_item in args.metadata:
                if '=' in meta_item:
                    key, value = meta_item.split('=', 1)
                    metadata[key] = value
                else:
                    logger.warning(f"Invalid metadata format: {meta_item}. Expected key=value")

        # Handle port parameter - override endpoint if port is specified
        endpoint = args.endpoint
        if args.port:
            # Extract protocol and host from endpoint
            match = re.match(r'(https?://)([^:]+)(:\d+)?', endpoint)
            if match:
                protocol = match.group(1)
                host = match.group(2)
                endpoint = f"{protocol}{host}:{args.port}"
            else:
                endpoint = f"http://localhost:{args.port}"

        exporter = OpenCostLiveExporter(
            endpoint=endpoint,
            run_id=args.run_id or "",
            scenario_name=args.scenario_name or "",
            metadata=metadata
        )

        # Always export both allocation and assets data
        logger.info("Exporting both allocation and assets data")

        # Export allocation data
        allocation_filename = exporter.export_allocation_live_data(
            window=args.window,
            aggregate=args.aggregate,
            filename=args.allocation_output,
            validate_availability=args.validate_availability
        )

        # Export assets data
        assets_filename = exporter.export_assets_live_data(
            window=args.window,
            aggregate=args.aggregate,
            filename=args.assets_output,
            filter_types=args.filter_types
        )

        logger.info(f"Successfully exported live OpenCost allocation data to: {allocation_filename}")
        logger.info(f"Successfully exported live OpenCost assets data to: {assets_filename}")
        logger.info(f"Window: {args.window}")
        logger.info(f"Aggregation: {args.aggregate}")
        logger.info("Format: Kusto (JSON)")
        if args.filter_types:
            logger.info(f"Filtered asset types: {args.filter_types}")

    except Exception as e:
        logger.error(f"Export failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
