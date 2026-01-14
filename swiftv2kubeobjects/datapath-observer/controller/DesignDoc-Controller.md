# Controller — Implementation Guide

**Component:** controller

See [DesignDoc-Overall.md](../DesignDoc-Overall.md) for system architecture and design rationale.

## Implementation

### Controller

See [controllers/pod_controller.go](controllers/pod_controller.go) for the reconciliation logic that:
- Watches Pods with annotation and status predicates
- Creates/updates DatapathResult CRs
- Computes latencies and timeout flags

### API Server

See [pkg/server/server.go](pkg/server/server.go) for HTTP API implementation that:
- Queries DatapathResult CRs with filtering
- Computes percentiles (p50, p90, p99)
- Returns aggregated stats and worst N Pods
- Implements caching to reduce API server load

## Deployment

### Kubernetes Manifests

- **RBAC:** [manifests/rbac.yaml](manifests/rbac.yaml)
  - ServiceAccount, Role (Pods + DatapathResult CRs), RoleBinding
  
- **Deployment:** [manifests/deployment.yaml](manifests/deployment.yaml)
  - 2 replicas recommended for HA
  - Port 8080 for HTTP API
  - Command-line args: namespace, label selector, SLO timeouts

For build instructions, see [README.md](README.md#building-the-image).

## Configuration

The controller accepts the following command-line arguments:

- `--namespace`: Target namespace to watch
- `--label-selector`: Label selector for filtering Pods
- `--slo-start`: SLO timeout for start metric (e.g., `30s`)
- `--slo-dpready`: SLO timeout for datapath ready metric (e.g., `60s`)

Query parameters for API endpoints:

- `topN`: Number of worst Pods to return (default: `10`)
- `namespace`: Filter by namespace (optional if specified in controller config)
- `labelSelector`: Filter by label selector in format `key=value,key2=value2` (optional if specified in controller config)

## DatapathResult CRD Storage

- All results are persisted as `DatapathResult` custom resources in etcd
- Each Pod gets a unique DatapathResult CR named `dpresult-<pod-uid>`
- CRs are stored in the same namespace as the Pod
- Consider implementing a cleanup policy for old DatapathResult CRs (e.g., TTL or periodic cleanup job)
### Command-line Arguments

- `--namespace`: Target namespace to watch
- `--label-selector`: Label selector for filtering Pods
- `--slo-start`: SLO timeout for start metric (e.g., `30s`)
- `--slo-dpready`: SLO timeout for datapath ready metric (e.g., `60s`)

### API Query Parameters

- `topN`: Number of worst Pods to return (default: `10`)
- `namespace`: Filter by namespace (optional)
- `labelSelector`: Filter by label selector in format `key=value,key2=value2` (optional)

## API Response Examples

### GET /api/v1/time-to-start?topN=5

```json
{
  "metric": "time-to-start",
  "unit": "ms",
  "count": 150,
  "totalSuccessful": 148,
  "totalFailed": 2,
  "p50": 4230,
  "p90": 8950,
  "p99": 12340,
  "worstPods": [
    {
      "namespace": "perf-ns",
      "name": "perf-sut-abc123",
      "uid": "d6f4a8c1-e234-4567-89ab-cdef01234567",
      "value": 15678
    }
  ],
  "failedPods": [
    {
      "namespace": "perf-ns",
      "name": "perf-sut-failed-001",
      "uid": "f1a2b3c4-d5e6-7890-abcd-ef0123456789"
    }
  ]
}
```

**Field Descriptions:**
- `count`: Number of DatapathResult CRs with non-zero `latStartMs` (used for percentile calculations)
- `totalSuccessful`: Number of DatapathResult CRs with both timestamp AND non-zero latency
- `totalFailed`: Number of DatapathResult CRs with missing timestamp OR zero latency
- `p50`, `p90`, `p99`: Percentiles calculated from successful measurements
- `worstPods`: Top N pods with highest latencies (sorted descending)
- `failedPods`: Top N pods that failed to start

### GET /api/v1/time-to-datapath-ready?topN=3&namespace=perf-ns

Similar structure to time-to-start but measuring datapath readiness latency.

### GET /api/v1/pod-health?topN=10&namespace=slo-1&labelSelector=podgroup=deployment-churn

```json
{
  "namespace": "slo-1",
  "labelSelector": "podgroup=deployment-churn",
  "desiredReplicas": 7055,
  "runningPods": 6998,
  "pendingPods": 2,
  "failedPods": 55,
  "successPct": 99.19,
  "pendingPodList": [
    {
      "namespace": "slo-1",
      "name": "deployment-churn-0-8-6d46cdc97c-abc123",
      "uid": "e5f6a7b8-c9d0-1234-5678-9abcdef01234",
      "nodeName": "",
      "phase": "Pending",
      "reason": "Unschedulable",
      "message": "0/10 nodes available: insufficient cpu"
    }
  ],
  "failedPodList": [
    {
      "namespace": "slo-1",
      "name": "deployment-churn-0-5-6d46cdc97c-xyz789",
      "uid": "d4e5f6a7-b8c9-0123-4567-89abcdef0123",
      "nodeName": "aks-nodepool1-vmss000001",
      "phase": "Failed",
      "reason": "Error",
      "message": "Back-off pulling image"
    }
  ]
}
```

**Field Descriptions:**
- `desiredReplicas`: Total number of pods matching the filter (Running + Pending + Failed)
- `runningPods`: Count of pods in Running phase
- `pendingPods`: Count of pods in Pending phase
- `failedPods`: Count of pods in Failed phase
- `successPct`: Percentage of running pods (`runningPods * 100 / desiredReplicas`)
- `pendingPodList`: Top N pending pods with details (reason, message)
- `failedPodList`: Top N failed pods with details (reason, message)

**Note:** This API queries actual Kubernetes Pod objects, providing real-time pod health status separate from historical DatapathResult metrics.

### GET /api/v1/time-to-datapath-ready?topN=3&namespace=perf-ns

```json
{
  "metric": "time-to-datapath-ready",
  "unit": "ms",
  "count": 142,
  "totalSuccessful": 145,
  "totalFailed": 5,
  "p50": 8450,
  "p90": 18920,
  "p99": 28340,
  "worstPods": [
    {
      "namespace": "perf-ns",
      "name": "perf-sut-xyz789",
      "uid": "e5f6a7b8-c9d0-1234-5678-9abcdef01234",
      "value": 35678
    }
  ],
  "failedPods": [
    {
      "namespace": "perf-ns",
      "name": "perf-sut-dp-failed-001",
      "uid": "b1c2d3e4-f5a6-7890-bcde-f01234567890"
    }
  ]
}
```

**Field Descriptions:**
- `count`: Number of DatapathResult CRs with non-zero `latDpReadyMs` (used for percentile calculations)
- `totalSuccessful`: Number of DatapathResult CRs with both timestamp AND non-zero latency
- `totalFailed`: Number of DatapathResult CRs with missing timestamp OR zero latency
- `p50`, `p90`, `p99`: Percentiles calculated from successful measurements
- `worstPods`: Top N pods with highest latencies (sorted descending)
- `failedPods`: Top N pods that failed to achieve datapath readiness

## Cleanup Policy

Consider implementing a cleanup mechanism for old DatapathResult CRs:
- TTL-based deletion after a configured period
- Periodic cleanup job (CronJob) to remove old CRs
- Retention policy based on Pod deletion events