# image-pull-n10

## Overview

Measures containerd image pulling throughput (MB/s) and network plugin operation metrics using the CRI module with `scrape_containerd: True`. Uses the `cri-resource-consume` topology.

## Infrastructure

| Component | Configuration |
|-----------|---------------|
| Cloud Provider | Azure |
| Cluster SKU | Standard |
| Network Plugin | Azure CNI Overlay |
| Default Node Pool | 3 x Standard_D4s_v3 |
| Prometheus Pool | 1 x Standard_D8s_v3 |
| User Pool | 10 x Standard_D4s_v3 |

## Metrics Collected

### ContainerdCriImagePullingThroughput

Image pull throughput (MB/s) with the following aggregations:

| Metric | Description |
|--------|-------------|
| **Avg** | Weighted average throughput per image pull |
| **AvgPerNode** | Unweighted average - each node contributes equally |
| **Count** | Total number of image pulls |
| **Perc50** | 50th percentile (median) throughput across nodes |
| **Perc90** | 90th percentile throughput across nodes |
| **Perc99** | 99th percentile throughput across nodes |

## References

- [Best Practices](../../../docs/best-practices.md)
- [Test Scenario Implementation Guide](../../../docs/test-scenario-implementation-guide.md)
