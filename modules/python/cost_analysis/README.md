# OpenCost Live Exporter

A Python utility for exporting live cost allocation and assets data from OpenCost API without waiting for the 24-hour daily export delay.

## Overview

This module provides real-time access to OpenCost allocation and assets data in Kusto-optimized format.

## Key Features

- ⚡ **Live Data Access** - No 24-hour wait time, get current cost data instantly
- 📊 **Kusto-Optimized Format** - Ready for Azure Data Explorer ingestion
- 🔧 **Flattened Data Structure** - Optimized for analytics and reporting
- ⏰ **Flexible Time Windows** - From minutes to days (30m, 1h, 24h, today, yesterday)
- 📈 **Multiple Aggregations** - Container, pod, namespace, node, controller levels for allocations; type, account, project, service for assets
- ️ **CLI Interface** - Easy command-line usage and automation
- 🏷️ **Custom Metadata** - Include run_id, test names, and other tracking information
- 🏗️ **Assets Support** - Export cloud infrastructure costs (disks, load balancers, etc.)
- 🔍 **Asset Filtering** - Filter by specific asset types for focused analysis

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

### Basic Usage

```bash
# Export both allocation and assets data (default behavior - always exports both)
python opencost_live_exporter.py --window 1h --aggregate container
python opencost_live_exporter.py --window 30m --aggregate pod
python opencost_live_exporter.py --window 1d --aggregate namespace

# Export with custom output filenames
python opencost_live_exporter.py --window 1h --allocation-output allocation.json --assets-output assets.json

# Export with filtered asset types
python opencost_live_exporter.py --window 1h --aggregate container --filter-types "Disk,LoadBalancer"

# Export with metadata
python opencost_live_exporter.py --window 4h --run-id test-123 --metadata environment=production

# Export with custom filenames and metadata
python opencost_live_exporter.py \
  --window 4h \
  --aggregate container \
  --allocation-output allocation_4h.json \
  --assets-output assets_4h.json \
  --run-id export-demo \
  --metadata environment=production
```

### Custom OpenCost Endpoint

```bash
# Connect to remote OpenCost instance
python opencost_live_exporter.py --endpoint http://opencost.monitoring:9003
```

### Custom Metadata

```bash
# Include run ID for tracking
python opencost_live_exporter.py --run-id test-run-123

# Add multiple metadata fields
python opencost_live_exporter.py \
  --run-id perf-test-456 \
  --metadata environment=production \
  --metadata team=platform \
  --metadata cluster=east-us-1
```

### Programmatic Usage with Metadata

```python
from opencost_live_exporter import OpenCostLiveExporter

# Initialize with custom metadata
metadata = {
    'run_id': 'kubernetes-scale-test-001',
    'test_name': 'capacity-benchmark',
    'environment': 'staging',
    'cluster_size': '100-nodes'
}

exporter = OpenCostLiveExporter(
    endpoint="http://opencost.monitoring:9003",
    metadata=metadata
)

# Export allocation data with metadata included
allocation_filename = exporter.export_live_data(
    window="1h",
    aggregate="namespace"
)

# Export assets data with metadata
assets_filename = exporter.export_assets_live_data(
    window="1h",
    aggregate="type",
    filter_types="Disk,LoadBalancer"
)
```

### Custom OpenCost Endpoint

```bash
# Connect to remote OpenCost instance
python opencost_live_exporter.py --endpoint http://opencost.example.com:9003 --window 1h
```

### Simplified Export Behavior

The OpenCost Live Exporter now **always exports both allocation and assets data** in a single execution:

```bash
# Basic export (creates both allocation and assets files)
python opencost_live_exporter.py --window 1h --aggregate namespace

# Custom output filenames
python opencost_live_exporter.py \
  --window 4h \
  --aggregate container \
  --allocation-output allocation_4h.json \
  --assets-output assets_4h.json

# Filtered asset types with metadata
python opencost_live_exporter.py \
  --window 1d \
  --aggregate namespace \
  --filter-types "Disk,LoadBalancer,ClusterIP" \
  --run-id export-demo \
  --metadata environment=production
```

**Benefits:**
- Always gets both allocation and assets data in one execution
- Consistent time window and metadata across both exports
- Simplified CLI interface with fewer options
- Better performance compared to separate calls

## Export Format

### Kusto Format (Azure Data Explorer Optimized)
- Optimized for Azure Data Explorer ingestion
- Native data types (datetime, real, int)
- Flattened data structure for analytics
- Best performance for cost analysis and reporting

## Output Files

The tool generates:
- `data.json` - The actual data for ingestion

## API Reference

### OpenCostLiveExporter Class

```python
from opencost_live_exporter import OpenCostLiveExporter

# Initialize
exporter = OpenCostLiveExporter(endpoint="http://localhost:9003")

# Get allocation data
allocation_data = exporter.get_allocation_data(
    window="1h",           # Time window
    aggregate="container", # Aggregation level
    include_idle=False,   # Include idle allocations
    share_idle=False      # Share idle costs
)

# Get assets data
assets_data = exporter.get_assets_data(
    window="1h",           # Time window
    aggregate="type",      # Aggregation level (type, account, project, service)
    step="5m",            # Optional: time step for series data
    filter_types="Disk,LoadBalancer"  # Optional: filter specific asset types
)

# Export allocation data to Kusto format
exporter.export_to_kusto_format(allocation_data, "allocation_costs.json")

# Export assets data to Kusto format
exporter.export_assets_to_kusto_format(assets_data, "assets_costs.json")

# One-step export for allocations
allocation_filename = exporter.export_live_data(
    window="1h",
    aggregate="container",
    filename="live_costs.json"
)
```

## CLI Options

```
--endpoint ENDPOINT         OpenCost API endpoint (default: http://localhost:9003)
--window WINDOW            Time window: 30m, 1h, 24h, today, yesterday, etc.
--aggregate AGGREGATE      Aggregation: For allocations: container, pod, namespace, node, controller
                                       For assets: type, account, project, service
--data-type {allocation,assets}  Type of data to export (default: allocation)
--output OUTPUT            Output filename (auto-generated if not provided)
--include-idle            Include idle allocations in results (allocation only)
--share-idle              Share idle costs across allocations (allocation only)
--run-id RUN_ID           Run ID to include in exported data for tracking
--metadata METADATA       Additional metadata in key=value format (can be used multiple times)
--filter-types FILTER_TYPES Filter asset types (e.g., "Disk,LoadBalancer") - only for assets data type
```

## Integration with Telescope Benchmarking

### Pipeline Integration

```yaml
# In Azure DevOps pipeline step
- name: Export Live Cost Data
  script: |
    python modules/python/cost_analysis/opencost_live_exporter.py \
      --window $(BENCHMARK_DURATION) \
      --aggregate container \
      --output $(BENCHMARK_NAME)_costs.json
```

### Real-time Cost Monitoring

```bash
# Monitor costs during a 2-hour benchmark
python opencost_live_exporter.py \
  --window 2h \
  --aggregate namespace \
  --output benchmark_costs.json
```

## Kusto Integration

The Kusto format provides optimal integration with Azure Data Explorer for both allocation and assets data:

### 1. Create Tables and Mappings

```kql
// Create tables for allocation data
.create table OpenCostAllocation (
    Timestamp: datetime,
    CollectionTime: datetime,
    Source: string,
    AllocationName: string,
    WindowStart: string,
    WindowEnd: string,
    WindowMinutes: real,
    Namespace: string,
    Node: string,
    Container: string,
    Pod: string,
    Controller: string,
    ControllerKind: string,
    CpuCores: real,
    CpuCoreHours: real,
    CpuCost: real,
    CpuEfficiency: real,
    RamBytes: real,
    RamByteHours: real,
    RamCost: real,
    RamEfficiency: real,
    GpuCount: real,
    GpuHours: real,
    GpuCost: real,
    NetworkCost: real,
    LoadBalancerCost: real,
    PvCost: real,
    TotalCost: real,
    TotalEfficiency: real,
    ExternalCost: real,
    SharedCost: real,
    Properties: string
)

// Create tables for assets data  
.create table OpenCostAssets (
    Timestamp: datetime,
    CollectionTime: datetime,
    Source: string,
    AssetName: string,
    WindowStart: string,
    WindowEnd: string,
    WindowMinutes: real,
    Type: string,
    Account: string,
    Project: string,
    Service: string,
    Region: string,
    Category: string,
    Provider: string,
    ProviderID: string,
    Name: string,
    Cost: real,
    Adjustment: real,
    TotalCost: real,
    Bytes: real,
    Breakdown: string,
    Labels: string
)
```

### 2. Ingest Data

```kql
// Ingest allocation data
.ingest into table OpenCostAllocation (
    'https://storageaccount.blob.core.windows.net/container/allocation_costs.json'
) with (
    format='json',
    ingestionMappingReference='OpenCostAllocation_mapping'
)

// Ingest assets data
.ingest into table OpenCostAssets (
    'https://storageaccount.blob.core.windows.net/container/assets_costs.json'
) with (
    format='json', 
    ingestionMappingReference='OpenCostAssets_mapping'
)
```

### 3. Query Cost Data

```kql
// Allocation cost by namespace over time
OpenCostAllocation
| where Timestamp > ago(24h)
| summarize TotalCost = sum(TotalCost) by bin(Timestamp, 1h), Namespace
| render timechart

// Assets cost by type
OpenCostAssets
| where Timestamp > ago(24h)
| summarize TotalCost = sum(TotalCost) by Type
| order by TotalCost desc

// Combined infrastructure and workload costs
OpenCostAllocation
| where Timestamp > ago(1h)
| summarize WorkloadCost = sum(TotalCost) by bin(Timestamp, 5m)
| join kind=inner (
    OpenCostAssets
    | where Timestamp > ago(1h)
    | summarize InfraCost = sum(TotalCost) by bin(Timestamp, 5m)
) on Timestamp
| project Timestamp, WorkloadCost, InfraCost, TotalCost = WorkloadCost + InfraCost
| render timechart

// Efficiency analysis
OpenCostAllocation
| where Timestamp > ago(1h)
| summarize AvgCpuEff = avg(CpuEfficiency), AvgRamEff = avg(RamEfficiency) by Container
| order by AvgCpuEff desc
```

## Testing

Run the comprehensive test suite:

```bash
# Install test dependencies
pip install pytest pytest-mock responses

# Run all tests
pytest test_opencost_live_exporter.py -v

# Run specific test categories
pytest test_opencost_live_exporter.py::TestOpenCostLiveExporter -v
pytest test_opencost_live_exporter.py::TestCLI -v
```

## Error Handling

The tool includes robust error handling for:
- API connectivity issues
- Invalid time windows or aggregation levels
- File system errors
- Network timeouts
- Malformed API responses

## Performance Considerations

- **CSV Format**: Smaller files, requires type conversion during ingestion
- **Kusto Format**: Larger files (~5x), but much faster ingestion and queries
- **Time Windows**: Larger windows may result in significant data volumes
- **Aggregation**: Higher aggregation levels (namespace vs container) reduce data volume

## Files

- `opencost_live_exporter.py` - Main utility with CLI interface for allocation and assets data
- `test_opencost_live_exporter.py` - Comprehensive unit tests (40+ tests covering both allocations and assets)
- `requirements.txt` - Python dependencies
- `README.md` - This documentation
- `__init__.py` - Package initialization

## Contributing

1. Add new features to the `OpenCostLiveExporter` class
2. Include comprehensive unit tests
3. Update CLI argument parsing for new options
4. Document new functionality in this README

## License

This project is part of the Telescope benchmarking framework.
- **Production Ready**: Comprehensive error handling, logging, and unit tests

## Architecture

```
OpenCost → Port Forward → Collector → Kusto Adapter → Azure Data Explorer
  (9003)     (Regex)       (JSON)       (Kusto JSON)     (Analysis)
```

## Files

- `opencost_metrics_collector.py` - Main collector class with regex-based parsing
- `kusto_adapter.py` - Kusto transformation adapter with 3 output formats
- `test_opencost_metrics_collector.py` - Comprehensive unit tests (17 tests)
- `example_usage.py` - Usage examples and demonstrations
- `requirements.txt` - Python dependencies
- `README.md` - This comprehensive documentation
- `__init__.py` - Package initialization

## Quick Start

### 1. Setup Port Forwarding

```bash
# Forward OpenCost metrics port
kubectl port-forward -n opencost service/opencost 9003:9003

# Forward Victoria Metrics port (if needed)
kubectl port-forward -n kube-system service/victoria-metrics 8428:8428
```

### 2. Collect and Transform Metrics

```python
from opencost_metrics_collector import OpenCostMetricsCollector
from kusto_adapter import KustoMetricsAdapter

# Collect metrics
collector = OpenCostMetricsCollector()
metrics = collector.collect_metrics()

# Transform for Kusto
adapter = KustoMetricsAdapter(metrics)
adapter.save_all_formats()
```

### 3. Live Data Export (No 24-hour delay)

```python
from opencost_live_exporter import OpenCostLiveExporter

# Initialize exporter
exporter = OpenCostLiveExporter()

# Export live data
filename = exporter.export_live_data(
    window="1h",
    aggregate="container",
    output_format="kusto"
)
```

**Command Line Usage:**

```bash
# Export last 30 minutes of container data
python opencost_live_exporter.py --window 30m --aggregate container --format csv

# Export namespace costs for current benchmark run
python opencost_live_exporter.py --window 1h --aggregate namespace --format json
```

**Advantages over daily export:**
- ✅ **Instant access** - No 24-hour wait time
- ✅ **Flexible windows** - 30m, 1h, 24h, today, yesterday
- ✅ **Multiple formats** - CSV, JSON, Kusto-optimized
- ✅ **Real-time analysis** - Debug cost spikes immediately

```kql
// Create table (run once)
.create table OpenCostMetrics (
    Timestamp: datetime,
    CollectionTime: datetime,
    Source: string,
    MetricName: string,
    MetricValue: real,
    MetricType: string,
    MetricHelp: string,
    Labels: string,
    Container: string,
    Pod: string,
    Namespace: string,
    Node: string
    // ... additional columns
)

// Ingest data
.ingest into table OpenCostMetrics ('https://your-storage-account.blob.core.windows.net/container/opencost_metrics_flat.json') 
with (format='json', jsonMappingReference='OpenCostMetrics_mapping')
```

## Table Formats

### 1. Flat Table Format (Recommended)

**Use case**: Time-series analysis, general queries
**Schema**: Single table with all metrics as rows
**Advantages**: 
- Optimal for cost analysis queries
- Efficient storage and querying
- Works well with Kusto's columnar storage

```kql
// Sample queries
OpenCostMetrics 
| where Timestamp > ago(1h)
| summarize avg(MetricValue) by bin(Timestamp, 5m), MetricName
| render timechart

// Resource utilization by node
OpenCostMetrics
| where MetricName == "container_cpu_allocation"
| summarize avg(MetricValue) by Node, bin(Timestamp, 1h)
```

### 2. Cost-Focused Format

**Use case**: Cost analysis, billing optimization
**Schema**: Specialized for cost metrics with resource hierarchies
**Advantages**:
- Optimized for cost analysis queries
- Clear resource type categorization
- Currency and cost type tracking

```kql
// Cost analysis by namespace
OpenCostAnalysis
| where CostType == "compute"
| summarize TotalCost = sum(CostValue) by Namespace
| order by TotalCost desc

// Cost trends over time
OpenCostAnalysis
| where Timestamp > ago(7d)
| summarize DailyCost = sum(CostValue) by bin(Timestamp, 1d)
| render timechart
```

### 3. Wide Table Format

**Use case**: Dashboard creation, multi-metric analysis
**Schema**: Metrics as columns
**Advantages**:
- Easy dashboard creation
- Cross-metric correlation analysis
- Familiar SQL-like structure

```kql
// Multi-metric dashboard
OpenCostMetricsWide
| where Timestamp > ago(1h)
| project Timestamp, Node, container_cpu_allocation, container_memory_allocation
| render scatterchart with (xcolumn=container_cpu_allocation, ycolumn=container_memory_allocation)
```

## Metrics Collected

The collector gathers **44 OpenCost metrics** including:

### Core Metrics
- `container_cpu_allocation` - CPU usage percentage
- `container_memory_allocation` - Memory usage percentage
- `container_cpu_usage_seconds_total` - CPU usage counters
- `container_memory_usage_bytes` - Memory usage in bytes

### Cost Metrics
- `kubecost_cluster_info` - Cluster configuration
- `kubecost_cluster_management_cost` - Management costs
- `kubecost_http_requests_total` - API usage metrics

### Performance Metrics
- `kubecost_load_balancer_cost` - Load balancer costs
- `kubecost_network_internet_egress_cost` - Network egress costs
- `kubecost_network_region_egress_cost` - Regional network costs

### Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

```bash
# Collect metrics from localhost (port-forwarded OpenCost)
python opencost_metrics_collector.py

# Collect from cluster IP
python opencost_metrics_collector.py --host 192.168.1.100

# Show summary
python opencost_metrics_collector.py --summary
```

### Integration with Telescope

The collector can be integrated into Telescope pipelines and scenarios:

```python
from modules.python.cost_analysis import OpenCostMetricsCollector

# In a Telescope scenario
collector = OpenCostMetricsCollector(host="cluster-ip", port=9003)
metrics = collector.collect_metrics()
```

## Metrics Collected

The collector gathers 41 OpenCost-specific metrics including:

- **Container Resources**: CPU, memory, GPU allocation
- **Cost Metrics**: Hourly costs for compute, storage, network
- **Node Information**: Capacity, spot instance data
- **Storage**: PVC usage and costs
- **Network**: Cross-region/zone egress costs
- **Kubernetes Metadata**: Pod/node labels and ownership

## Testing

```bash
# Run all tests
python test_opencost_metrics_collector.py

# Run with verbose output
python test_opencost_metrics_collector.py -v
```

## Integration Points

### With Telescope Pipelines

The collector can be used in Azure DevOps pipelines:

```yaml
# In a pipeline step
- script: |
    cd modules/python/cost-analysis
    python opencost_metrics_collector.py --host $(CLUSTER_IP) --output $(Build.ArtifactStagingDirectory)/cost-metrics.json
  displayName: 'Collect OpenCost Metrics'
```

### With Scenarios

Include in scenario execution:

```python
# In scenario setup
from modules.python.cost_analysis import OpenCostMetricsCollector

def collect_baseline_costs():
    collector = OpenCostMetricsCollector(host=cluster_ip)
    return collector.collect_metrics()
```

### With Terraform

The collector works with Terraform-provisioned infrastructure:

```bash
# After terraform apply
CLUSTER_IP=$(terraform output cluster_ip)
python opencost_metrics_collector.py --host $CLUSTER_IP
```

## Output Format

Metrics are saved in structured JSON format:

```json
{
  "metadata": {
    "collection_time": "2025-07-17T10:30:00.000000",
    "source": "http://cluster-ip:9003",
    "total_metrics": 41
  },
  "metrics": {
    "container_cpu_allocation": {
      "help": "CPU usage per container",
      "type": "gauge",
      "values": [...]
    }
  }
}
```

## Error Handling

The collector includes robust error handling for:
- Network connectivity issues
- Authentication problems
- Parsing errors
- File I/O failures

## Contributing

When adding new features:

1. Add comprehensive tests
2. Update documentation
3. Ensure compatibility with existing Telescope infrastructure
4. Follow the existing code style

## Dependencies

- `requests` - HTTP client
- `urllib3` - URL handling

## License

This module is part of the Telescope project and follows the same licensing terms.

## Export Methods Comparison

### Daily CSV Export (Built-in OpenCost)

**Use when:**
- Long-term cost analysis
- Historical reporting  
- Automated billing
- Low-frequency analysis

**Characteristics:**
- 24-48 hour delay for first export
- Daily aggregation only
- Fixed schedule (00:10 UTC)
- Automatic cloud storage
- Low resource usage

### Live Data Export (This Module)

**Use when:**
- Real-time monitoring
- Telescope benchmarking
- Debugging cost spikes
- Interactive dashboards
- Custom time windows

**Characteristics:**
- Instant data access
- Flexible time windows (30m, 1h, 24h, etc.)
- Multiple aggregation levels
- Custom output formats
- Cost analysis and reporting

**Recommendation for Telescope:**
Use **Live Export** for benchmarking scenarios where you need immediate feedback and want to correlate costs with test phases.

```bash
# Compare the two approaches
python export_comparison.py
```

## Data Types

The exporter supports two types of OpenCost data:

### Allocation Data

**Use for:** Kubernetes workload cost analysis
- Container, pod, namespace, node, controller level costs
- CPU, memory, GPU, storage, network costs
- Resource efficiency metrics
- Idle cost allocation and sharing

**Aggregation levels:** `container`, `pod`, `namespace`, `node`, `controller`

**Example fields:** `cpuCost`, `ramCost`, `totalCost`, `cpuEfficiency`, `ramEfficiency`

### Assets Data  

**Use for:** Cloud infrastructure cost analysis
- Virtual machines, disks, load balancers, networking
- Account, project, service level costs
- Provider-specific resource tracking

**Aggregation levels:** `type`, `account`, `project`, `service`

**Example fields:** `type`, `category`, `provider`, `providerID`, `totalCost`, `bytes`

**Asset filtering:** Use `--filter-types` to focus on specific infrastructure:
```bash
# Only storage and networking assets
--filter-types "Disk,LoadBalancer,NetworkInterface"

# Only compute resources  
--filter-types "Node,Instance"
```
