# Image Pull Performance Test

## Overview

Measures container image pull performance on AKS clusters using ClusterLoader2.

## Test Scenario

Creates 10 Deployments with 1 replica each (10 pods total), pulling a large container image to measure:
- How fast images are pulled across cluster nodes
- Pod startup latency when pulling large images
- Containerd throughput during parallel image pulls

### Default Configuration

| Parameter | Value |
|-----------|-------|
| Deployments | 10 |
| Replicas per deployment | 1 |
| Total pods | 10 |
| QPS (deployment creation rate) | 10 |
| Pod startup timeout | 3 minutes |
| Metrics collection wait | 10 minutes |
| Test image | pytorch-large:2.0.0 (~15GB) |

To modify, edit `image-pull.yaml`:
- `replicasPerNamespace`: Number of deployments
- `Replicas`: Pods per deployment
- `qps`: Deployment creation rate

## Metrics Collected

| Metric | Source | Description |
|--------|--------|-------------|
| Kubelet Image Pull Duration | kubelet:10250 | P50/P90/P99 latency per node |
| Containerd Throughput | containerd:10257 | MB/s, total data, pull count |
| Network Plugin Operations | containerd:10257 | Pod network setup/teardown time |
| Pod Startup Latency | API server | End-to-end pod scheduling time |

## Prerequisites

- AKS cluster with containerd runtime
- Azure Container Registry with test image
- kubectl, terraform, az CLI, docker

## Configuration

### 1. Set your container image

Edit `image-pull.yaml` line 37:
```yaml
Image: <your-acr>.azurecr.io/<your-image>:<tag>
```

### 2. Set your ACR (in notebook)

Edit `run_locally.ipynb` cell 9:
```bash
export ACR_NAME=<your-acr-name>
export ACR_SUBSCRIPTION_ID=<your-acr-subscription>  # if different from AKS subscription
```

### 3. Attach ACR to AKS

The notebook handles this automatically, or run manually:
```bash
az aks update -g <rg> -n <cluster> --attach-acr <acr-name>
```

## Usage

### Run via Notebook
```bash
# Open and run cells sequentially
jupyter notebook run_locally.ipynb
```

### Run via CLI
```bash
export ROOT_DIR=$(git rev-parse --show-toplevel)
./run_cl2.sh              # Run test
./analyze_results.sh      # Analyze results
```

## Files

| File | Purpose |
|------|---------|
| `image-pull.yaml` | CL2 test config - defines workload and measurements |
| `deployment.yaml` | Pod template for image pull test |
| `containerd-measurements.yaml` | Prometheus queries for containerd metrics |
| `run_cl2.sh` | Shell wrapper to run test |
| `analyze_results.sh` | Shell wrapper to analyze results |
| `run_locally.ipynb` | Interactive notebook for local testing |
| `terraform-inputs/azure.tfvars` | AKS cluster configuration |

## Output

Results are written to `results/` directory:
- `junit.xml` - Test pass/fail status
- `PodStartupLatency_*.json` - Pod startup metrics
- `GenericPrometheusQuery_*.json` - Prometheus metric snapshots
