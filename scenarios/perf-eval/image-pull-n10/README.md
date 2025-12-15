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

- `ContainerdCriImagePullingThroughput` - Image pull throughput (MB/s)
- `ContainerdCriNetworkPluginOperations` - Network plugin operation duration
- `ContainerdCriSandboxCreateNetwork` - Sandbox network creation time
- `ContainerdCriSandboxDeleteNetwork` - Sandbox network deletion time

## References

- [Best Practices](../../../docs/best-practices.md)
- [Test Scenario Implementation Guide](../../../docs/test-scenario-implementation-guide.md)
