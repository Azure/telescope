# Pod Datapath Readiness System — Overall Design

**Author:** Isaac Swamidasan  
**Date:** Dec 17, 2025  
**Scope:** AKS (Azure Kubernetes Service) and generic Kubernetes clusters

## Background and problem statement

In performance tests and large-scale rollouts, we must verify **datapath success** for Pods (i.e., the Pod can send/receive traffic as expected) and measure how long it takes to achieve that state.

Existing options have limitations:

- **ClusterLoader2 (CL2) PodPeriodicCommand:** periodically execs into a Pod; can fail in some environments (for example, due to kube-proxy tunneling issues).
- **ClusterLoader2 (CL2) custom measurement:** precise, but tightly coupled to CL2, making reuse hard in non-CL2 scenarios.
- **Pod self-annotation + pipeline scraping:** fragile—Pods may be deleted/recreated (losing history); stuck Pods leave incomplete signals; nodes may restart before results are gathered.

We need an independent system that:

- Observes Pods (by namespace/labels) and detects **start** and **datapath readiness**.
- Measures **time-to-start** (useful as a cross-check against CL2) and **time-to-datapath-ready**.
- Persists results in a CRD so data survives restarts and Pod churn.
- Serves HTTP APIs to return consolidated stats (p50/p90/p99) and "top N worst" outliers for both metrics.

Here, **datapath success** means the Pod can send/receive traffic as expected. Each Pod's reporter init container reports timestamps via annotations; the controller persists and aggregates results via the `DatapathResult` CRD.

## Goals

- Track **time-to-start** (Pod creation → workload ready)
- Track **time-to-datapath-ready** (Pod creation → first successful probe)
- Persist results in CRDs for durability
- Serve HTTP APIs with percentiles (p50/p90/p99) and worst performers

## Architecture

**Two independent components:**

1. **Reporter** - Init container in test Pods (measures + writes annotations)
2. **Controller** - Standalone deployment (watches + aggregates + serves APIs)

**Data flow:**
```
Reporter (init container) → Pod annotations → Controller → DatapathResult CRD → HTTP APIs
```

**Annotations used:**
- `perf.github.com/azure-start-ts` - RFC3339 timestamp
- `perf.github.com/azure-dp-ready-ts` - RFC3339 timestamp

**API endpoints:**
- `GET /api/v1/time-to-start?topN=10&namespace=<ns>&labelSelector=<k=v,...>`
- `GET /api/v1/time-to-datapath-ready?topN=10&namespace=<ns>&labelSelector=<k=v,...>`

## Data model

### DatapathResult CRD

Define a `DatapathResult` with typed fields:

```yaml
apiVersion: perf.github.com/Azure/v1
kind: DatapathResult
metadata:
  name: dpresult-<pod-uid>
spec:
  podRef:
    namespace: perf-ns
    name: perf-sut-abc123
    uid: d6f4-...
  timestamps:
    createdAt: "2025-12-17T21:19:50Z"
    startTs: "2025-12-17T21:19:56Z"
    dpReadyTs: "2025-12-17T21:20:10Z"
  metrics:
    latStartMs: 6000
    latDpReadyMs: 14000
  labels:
    app: perf-sut
    scenario: burst
```

## Component Responsibilities

| Responsibility | Reporter | Controller |
|---------------|----------|------------|
| Measure timestamps | ✓ | |
| Probe datapath | ✓ | |
| Write Pod annotations | ✓ | |
| Watch Pod events | | ✓ |
| Calculate latencies | | ✓ |
| Create/manage CRDs | | ✓ |
| Aggregate metrics | | ✓ |
| Serve HTTP APIs | | ✓ |

### Reporter (Init Container)

- Records start timestamp and probes external target (HTTP/HTTPS/TCP)
- Writes timestamps to Pod annotations with idempotent patching
- RBAC: `get`/`patch` on its own Pod only

### Controller (Standalone Deployment)

- Watches Pods, creates `DatapathResult` CRD per Pod (keyed by UID)
- Calculates latencies from annotations and Pod `creationTimestamp`
- Serves HTTP APIs with aggregated percentiles and worst performers
- RBAC: `watch`/`get`/`list` on Pods, `create`/`update`/`get`/`list` on CRDs





## Design Considerations

**Tracking by UID:** Pods are tracked by UID, not name. Recreations produce separate `DatapathResult` records.

**Clock skew:** Controller uses Pod `creationTimestamp` from API server for latency calculations to avoid node clock differences.

**Scale:** Controller uses predicates to filter events and implements rate limiting. Reporter timeout (default 60s) prevents indefinite blocking.

**Idempotency:** Both components check existing state before updates.

**HA:** Single-replica deployment sufficient initially. Add leader election for zero-downtime in production.

**Security:** Restrict controller APIs to ClusterIP with optional token auth.



## Implementation details

See the following documents for implementation specifics:

- [controller/DesignDoc-Controller.md](controller/DesignDoc-Controller.md) - Controller implementation details
- [reporter/DesignDoc-Reporter.md](reporter/DesignDoc-Reporter.md) - Reporter init container implementation details
