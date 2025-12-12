# Scenario: image-pull-n10

## Overview

This scenario measures container image pull throughput and performance on AKS clusters. It benchmarks how quickly nodes can pull container images from registries under various conditions.

## Infrastructure

| Component | Configuration |
|-----------|---------------|
| Cloud Provider | Azure |
| Cluster SKU | Standard |
| Network Plugin | Azure CNI Overlay |
| Default Node Pool | 3 x Standard_D4s_v3 |
| Prometheus Pool | 1 x Standard_D8s_v3 |
| User Pool | 10 x Standard_D4s_v3 |

## Node Pools

| Pool | Purpose | Node Count | VM Size | Labels |
|------|---------|------------|---------|--------|
| default | System/critical addons | 3 | Standard_D4s_v3 | - |
| prompool | Prometheus monitoring | 1 | Standard_D8s_v3 | `prometheus=true` |
| userpool | Image pull tests | 10 | Standard_D4s_v3 | `image-pull-test=true` |

## Network Configuration

- VNet: `10.0.0.0/9`
- Pod CIDR: `10.0.0.0/9`
- Service CIDR: `192.168.0.0/16`
- DNS Service IP: `192.168.0.10`

## Usage

Tests are executed on nodes labeled with `image-pull-test=true` in the user pool.

## References

- [Best Practices](../../../docs/best-practices.md)
- [Test Scenario Implementation Guide](../../../docs/test-scenario-implementation-guide.md)
