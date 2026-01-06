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

## Test Workload

| Component | Value |
|-----------|-------|
| Registry | Azure Container Registry (`akscritelescope.azurecr.io`) |
| Image | `e2e-test-images/resource-consumer:1.13` |
| Image Size | ~50MB |

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

## Known Limitations

### Cannot Use histogram_quantile() Per Node

Using Prometheus `histogram_quantile()` on per-node throughput data always returns `10` (the maximum bucket boundary) regardless of actual throughput values. This happens because:

- The histogram has fixed bucket boundaries: `0.5, 1, 2, 4, 6, 8, 10` MB/s
- When actual throughput exceeds 10 MB/s, all samples fall into the `+Inf` bucket
- `histogram_quantile()` can only interpolate within defined buckets, so it caps at `10`

**Current Approach**: Instead of `histogram_quantile()` per node, we use weighted average (`_sum / _count`) per node, then compute percentiles across the node averages.

### Per-Node Metrics May Return "no samples"

The per-node metrics (`AvgPerNode`, `Perc50`, `Perc90`, `Perc99`) may return "no samples" while aggregate metrics (`Avg`, `Count`) work correctly. This is caused by Prometheus `rate()` function requiring **at least 2 data points** within the query window.

**Root Cause**: If image pulls complete faster than the Prometheus scrape interval (default 15s), only one data point is collected per pull operation. The `rate()` function cannot compute a rate from a single sample, resulting in empty per-node results.

**Why Aggregate Metrics Work**: `Avg` and `Count` use `sum()` which aggregates samples across all pods/nodes before applying `rate()`, accumulating enough data points within the window.

**Workaround Options**:
- Increase scrape frequency (may impact cluster performance)
- Use larger images that take longer to pull
- Rely on aggregate metrics (`Avg`, `Count`) for throughput analysis

### Metric Includes Unpack Time

The `containerd_cri_image_pulling_throughput` metric measures **total image size divided by total pull time**, which includes both:
- Image layer download time
- Image layer decompression/unpack time

This is not a pure network throughput metric. See [containerd source](https://github.com/containerd/containerd/blob/main/internal/cri/server/images/image_pull.go).

### verify_measurement() Cannot Check Containerd Metrics

The CRI module's `verify_measurement()` function only validates kubelet metrics (accessible via Kubernetes node proxy endpoint at `/api/v1/nodes/{node}/proxy/metrics`). Containerd metrics are only available through the Prometheus server and cannot be verified through this endpoint.

## References

- [Best Practices](../../../docs/best-practices.md)
- [Test Scenario Implementation Guide](../../../docs/test-scenario-implementation-guide.md)
