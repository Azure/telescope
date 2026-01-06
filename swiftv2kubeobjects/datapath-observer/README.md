# Pod Datapath Readiness System

A system for tracking Pod startup time and datapath readiness in Kubernetes clusters, with a focus on performance testing and large-scale deployments.

## Overview

This system consists of two independent components:

1. **[Reporter](reporter/)** - Sidecar container that measures timestamps, probes datapath once, then exits
2. **[Controller](controller/)** - Standalone deployment that watches Pods, aggregates metrics, and serves HTTP APIs

## Quick Start

### 1. Prerequisites

Ensure your AKS kubelet identity has permission to pull images from your container registry:

```bash
# Find your kubelet identity
KUBELET_IDENTITY=$(az aks show -g <RESOURCE_GROUP> -n <CLUSTER_NAME> \
  --query identityProfile.kubeletidentity.objectId -o tsv)

# Grant ACR pull permissions
az role assignment create \
  --assignee $KUBELET_IDENTITY \
  --role AcrPull \
  --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.ContainerRegistry/registries/<REGISTRY_NAME>
```

### 2. Deploy Controller

```bash
cd controller
kubectl apply -f manifests/crd.yaml
kubectl apply -f manifests/deployment.yaml
```

### 3. Add Reporter to Test Pods

Add the reporter as a sidecar container to your test Pods:

```yaml
containers:
- name: datapath-reporter
  image: acndev.azurecr.io/datapath-reporter:latest
  env:
  - name: PROBE_TARGET
    value: "http://your-target.com"
  - name: PROBE_TIMEOUT
    value: "60"
```

### 4. Query Metrics

```bash
# Port-forward to controller
kubectl port-forward -n datapath-observer svc/datapath-controller 8080:8080

# Get time-to-start metrics
curl "http://localhost:8080/api/v1/time-to-start?topN=10&namespace=perf-test"

# Get time-to-datapath-ready metrics
curl "http://localhost:8080/api/v1/time-to-datapath-ready?topN=10&namespace=perf-test"
```

## Metrics Tracked

### Time to Start
Time from Pod creation to sidecar container ready (workload start). Tracks:
- Percentiles (p50, p90, p99)
- Success/failure counts
- Worst performers

### Time to Datapath Ready
Time from Pod creation to first successful network probe. Tracks:
- Percentiles (p50, p90, p99)
- Success/failure counts
- Worst performers

## Architecture

```
Reporter (sidecar) → Pod annotations → Controller → DatapathResult CRD → HTTP APIs
```

Data is persisted in `DatapathResult` CRDs keyed by Pod UID, surviving Pod restarts and node failures.

## Documentation

- [DesignDoc-Overall.md](DesignDoc-Overall.md) - Overall system architecture and design
- [controller/](controller/) - Controller component (watches Pods, serves APIs)
- [reporter/](reporter/) - Reporter component (sidecar container)

## Use Cases

- Performance testing and benchmarking
- Large-scale cluster rollouts
- CNI and network policy validation
- Pod startup latency analysis
- Datapath readiness verification

## License

See [LICENSE](../../LICENSE)
