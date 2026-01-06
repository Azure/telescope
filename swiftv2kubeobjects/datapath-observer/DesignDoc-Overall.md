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
- Serves HTTP APIs to return consolidated stats (p50/p90/p99), "top N worst" outliers, and success/failure counts for both metrics.
  - For **time-to-start**: successful pods have non-zero `startTs` in their DatapathResult CR; failed pods have missing or zero `startTs`
  - For **time-to-datapath-ready**: successful pods have non-zero `dpReadyTs` in their DatapathResult CR; failed pods have missing or zero `dpReadyTs`

Here, **datapath success** means the Pod can send/receive traffic as expected. Each Pod's reporter sidecar reports timestamps via annotations; the controller persists and aggregates results via the `DatapathResult` CRD.

## Goals

- Track **time-to-start** (Pod creation → workload ready)
- Track **time-to-datapath-ready** (Pod creation → first successful probe)
- Track **success/failure counts** for both metrics
- Persist results in CRDs for durability
- Serve HTTP APIs with percentiles (p50/p90/p99), worst performers, and success/failure counts

## Architecture

**Two independent components:**

1. **Reporter** - Init container in test Pods (validates datapath readiness before main containers start)
2. **Controller** - Standalone deployment (watches + aggregates + serves APIs)

**Data flow:**
```
Reporter (initContainer) → Pod annotations → Controller → DatapathResult CRD → HTTP APIs
```

**Annotations used:**
- `perf.github.com/azure-start-ts` - RFC3339 timestamp with millisecond precision
- `perf.github.com/azure-dp-ready-ts` - RFC3339 timestamp with millisecond precision

**API endpoints:**
- `GET /api/v1/time-to-start?topN=10&namespace=<ns>&labelSelector=<k=v,...>`
  - Returns percentiles (p50/p90/p99), total successful pods (with non-zero `startTs`), total failed pods (missing/zero `startTs`), top N worst performers, and top N failed pods
  - Percentile calculations only include CRs with non-zero `latStartMs`
- `GET /api/v1/time-to-datapath-ready?topN=10&namespace=<ns>&labelSelector=<k=v,...>`
  - Returns percentiles (p50/p90/p99), total successful pods (with non-zero `dpReadyTs`), total failed pods (missing/zero `dpReadyTs`), top N worst performers, and top N failed pods
  - Percentile calculations only include CRs with non-zero `latDpReadyMs`

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
    createdAt: "2025-12-17T21:19:50.123Z"
    startTs: "2025-12-17T21:19:56.234Z"
    dpReadyTs: "2025-12-17T21:20:10.345Z"
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
- Probes datapath until success or timeout, then exits to allow main containers to start
- Adds probe timeout duration to overall pod startup latency (acceptable tradeoff for validation)
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



## Getting Started

See [README.md](README.md) for quick start, deployment instructions, and usage examples.

## Implementation details

See the following documents for implementation specifics:

- [controller/README.md](controller/README.md) - Controller deployment and usage guide
- [controller/DesignDoc-Controller.md](controller/DesignDoc-Controller.md) - Controller implementation details
- [reporter/README.md](reporter/README.md) - Reporter deployment and usage guide
- [reporter/DesignDoc-Reporter.md](reporter/DesignDoc-Reporter.md) - Reporter sidecar container implementation details
