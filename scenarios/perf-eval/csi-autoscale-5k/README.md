# CSI autoscale 5K

## Overview

Measures AKS Cluster Autoscaler scale-up and scale-down with one stateful pod
and one dynamically provisioned Azure Disk per target node. The workload writes
to every mounted disk and fails readiness if the data cannot be read.

The pipeline provides two profiles:

| Profile | Nodes | Pods and PVCs | Purpose |
|---------|------:|--------------:|---------|
| `smoke` | 10 | 10 | Validate provisioning, measurement, and cleanup |
| `qualification5k` | 5,000 | 5,000 | Run the full qualification |

Run the smoke profile before requesting quota and capacity for the 5K profile.

## Measurements

- Node and pod scale-up P50, P70, P90, P99, and P100
- Pod and node scale-down P50, P70, P90, P99, and P100
- Remaining PVC, PV, and VolumeAttachment counts after cleanup
- Kubernetes warning events and Azure Disk CSI logs

The test fails if its Kubernetes storage resources remain after the configured
cleanup timeout.

## Pipeline

Use `pipelines/perf-eval/CSI Benchmark/csi-autoscale-5k.yml` and select the
required `scaleProfile` when manually queuing the Azure DevOps pipeline.
