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
- 🏷️ **Custom Metadata** - Include other tracking information
- 🏗️ **Assets Support** - Export cloud infrastructure costs (disks, load balancers, etc.)
- 🔍 **Asset Filtering** - Filter by specific asset types for focused analysis

## Quick Start

## Prerequisites

This tool depends on OpenCost being deployed and running in your Kubernetes cluster. OpenCost provides the cost data that this exporter retrieves and processes.

### 1. Enabling OpenCost in AKS with Azure Cost Analysis

Azure Kubernetes Service (AKS) now includes built-in support for OpenCost to provide detailed cost analysis. Follow these steps to enable cost analysis:

1. **Enable Cost Analysis on a New AKS Cluster**:

   Use the Azure CLI to create a new AKS cluster with cost analysis enabled:

   ```bash
   export RANDOM_SUFFIX=$(openssl rand -hex 3)
   export RESOURCE_GROUP="AKSCostRG$RANDOM_SUFFIX"
   export CLUSTER_NAME="AKSCostCluster$RANDOM_SUFFIX"
   export LOCATION="WestUS2"

   az aks create \
       --resource-group $RESOURCE_GROUP \
       --name $CLUSTER_NAME \
       --location $LOCATION \
       --enable-managed-identity \
       --generate-ssh-keys \
       --tier standard \
       --enable-cost-analysis
   ```
2. **Enable Cost Analysis on an Existing AKS Cluster**:

   Update an existing AKS cluster to enable cost analysis:

   ```bash
   az aks update \
       --resource-group $RESOURCE_GROUP \
       --name $CLUSTER_NAME \
       --enable-cost-analysis
   ```

**Note**: Enabling cost analysis deploys an agent to your cluster, which consumes a small amount of CPU and memory resources. For more details, refer to the [Azure AKS Cost Analysis documentation](https://learn.microsoft.com/en-us/azure/aks/cost-analysis).

### 2. Setup Port Forwarding

```bash
# Forward OpenCost metrics port
kubectl port-forward -n opencost service/opencost 9003:9003

# Forward Victoria Metrics port (if needed)
kubectl port-forward -n kube-system service/victoria-metrics 8428:8428
```

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
  --scenario-name performance-benchmark \
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

### Output: Kusto Format (Azure Data Explorer Optimized)

- Optimized for Azure Data Explorer ingestion
- Native data types (datetime, real, int)
- Flattened data structure for analytics
- Best performance for cost analysis and reporting

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
--scenario-name SCENARIO_NAME  Scenario name for categorizing test runs
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
      --scenario-name $(SCENARIO_NAME) \
      --run-id $(BUILD_BUILDNUMBER) \
      --metadata environment=$(ENVIRONMENT) \
      --metadata cluster=$(CLUSTER_NAME) \
      --output $(BENCHMARK_NAME)_costs.json
```

### Kusto Integration

The Kusto format provides optimal integration with Azure Data Explorer for both allocation and assets data:

### 1. Create Tables and Mappings

```kql
// Create tables for allocation data
.create table OpenCostAllocation (
    Timestamp: datetime,
    CollectionTime: datetime,
    Source: string,
    RunId: string,
    ScenarioName: string,
    Metadata: dynamic,
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
    RunId: string,
    ScenarioName: string,
    Metadata: dynamic,
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

// Filter by specific run ID (now a dedicated field)
OpenCostAllocation
| where RunId == "test-run-123"
| summarize TotalCost = sum(TotalCost) by Namespace

// Query with additional metadata filtering
OpenCostAllocation
| where Timestamp > ago(1h)
| where RunId != ""  // Filter records with run ID
| extend Environment = tostring(Metadata.environment)
| where Environment == "production"
| summarize TotalCost = sum(TotalCost) by RunId

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

// Efficiency analysis by run ID
OpenCostAllocation
| where Timestamp > ago(1h) and RunId != ""
| summarize AvgCpuEff = avg(CpuEfficiency), AvgRamEff = avg(RamEfficiency) by RunId, Container

// Filter by scenario name for test categorization
OpenCostAllocation
| where ScenarioName == "pod-churn-50k"
| summarize TotalCost = sum(TotalCost), AvgEfficiency = avg(TotalEfficiency) by Namespace

// Compare costs across different scenarios
OpenCostAllocation
| where Timestamp > ago(6h) and ScenarioName != ""
| summarize TotalCost = sum(TotalCost) by ScenarioName
| order by TotalCost desc

// Analyze scenario performance with run tracking
OpenCostAllocation
| where ScenarioName in ("nap-benchmark", "cri-bottlerocket-benchmark")
| summarize 
    TotalCost = sum(TotalCost),
    AvgCpuEff = avg(CpuEfficiency),
    AvgRamEff = avg(RamEfficiency)
by ScenarioName, RunId
| order by ScenarioName, RunId
| order by AvgCpuEff desc
```

## Architecture

```
OpenCost → Port Forward → Collector → Kusto Adapter → Azure Data Explorer
  (9003)     (Regex)       (JSON)       (Kusto JSON)     (Analysis)
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

## Export Methods Comparison

### Daily CSV Export (Built-in OpenCost - Azure Cost Analysis)

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
