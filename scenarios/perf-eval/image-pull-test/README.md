# Image Pull Performance Test

## Overview

Measures container image pull performance on AKS clusters using ClusterLoader2.

## Test Scenario

Creates 10 Deployments with 1 replica each (10 pods total), pulling a container image to measure:
- How fast images are pulled across cluster nodes
- Pod startup latency when pulling images
- Containerd throughput during parallel image pulls

## Metrics Collected

| Metric | Source | Description |
|--------|--------|-------------|
| Kubelet Image Pull Duration | kubelet:10250 | P50/P90/P99 latency per node |
| Containerd Throughput | containerd:10257 | MB/s, total data, pull count |
| Network Plugin Operations | containerd:10257 | Pod network setup/teardown time |
| Pod Startup Latency | API server | End-to-end pod scheduling time |

## Configuration

### Test Image

The test uses `akscritelescope.azurecr.io/e2e-test-images/resource-consumer:1.13` by default.

To change the image, edit `modules/python/clusterloader2/image_pull/config/image-pull.yaml`.

### Cluster Settings

Edit `scenarios/perf-eval/image-pull-test/terraform-inputs/azure.tfvars` for cluster configuration.

## Pipeline

The test runs via Azure DevOps pipeline:
- **Pipeline**: `pipelines/perf-eval/CRI Benchmark/image-pull.yml`
- **Engine**: `steps/engine/clusterloader2/image_pull/`
- **Topology**: `steps/topology/image-pull/`

## Files

| Path | Purpose |
|------|---------|
| `modules/python/clusterloader2/image_pull/` | Python module and CL2 config |
| `steps/engine/clusterloader2/image_pull/` | Pipeline engine steps |
| `steps/topology/image-pull/` | Pipeline topology steps |
| `pipelines/perf-eval/CRI Benchmark/image-pull.yml` | Pipeline definition |
| `scenarios/perf-eval/image-pull-test/terraform-inputs/` | Terraform configuration |
