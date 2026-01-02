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
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-def456",
      "uid": "f8a2b9d3-c456-7890-abcd-ef0123456789",
      "value": 14521
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-ghi789",
      "uid": "a1b2c3d4-e5f6-7890-abcd-ef0123456789",
      "value": 13892
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-jkl012",
      "uid": "b2c3d4e5-f6a7-8901-bcde-f01234567890",
      "value": 13456
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-mno345",
      "uid": "c3d4e5f6-a7b8-9012-cdef-012345678901",
      "value": 13001
    }
  ],
  "failedPods": [
    {
      "namespace": "perf-ns",
      "name": "perf-sut-failed-001",
      "uid": "f1a2b3c4-d5e6-7890-abcd-ef0123456789"
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-failed-002",
      "uid": "a2b3c4d5-e6f7-8901-bcde-f01234567890"
    }
  ]
}
```

**Field Descriptions:**
- `count`: Number of DatapathResult CRs with non-zero `latStartMs` (used for percentile calculations)
- `totalSuccessful`: Number of DatapathResult CRs with non-zero `startTs` timestamp
- `totalFailed`: Number of DatapathResult CRs with missing or zero `startTs` timestamp
- `p50`, `p90`, `p99`: Percentiles calculated from the `count` CRs with valid `latStartMs` values
- `worstPods`: Top N pods with highest latencies (sorted descending)
- `failedPods`: Top N pods that failed to start (missing or zero `startTs`)

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
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-uvw456",
      "uid": "d4e5f6a7-b8c9-0123-4567-89abcdef0123",
      "value": 32145
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-rst123",
      "uid": "c3d4e5f6-a7b8-9012-3456-789abcdef012",
      "value": 29876
    }
  ],
  "failedPods": [
    {
      "namespace": "perf-ns",
      "name": "perf-sut-dp-failed-001",
      "uid": "b1c2d3e4-f5a6-7890-bcde-f01234567890"
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-dp-failed-002",
      "uid": "c2d3e4f5-a6b7-8901-cdef-012345678901"
    },
    {
      "namespace": "perf-ns",
      "name": "perf-sut-dp-failed-003",
      "uid": "d3e4f5a6-b7c8-9012-def0-123456789012"
    }
  ]
}
```

**Field Descriptions:**
- `count`: Number of DatapathResult CRs with non-zero `latDpReadyMs` (used for percentile calculations)
- `totalSuccessful`: Number of DatapathResult CRs with non-zero `dpReadyTs` timestamp
- `totalFailed`: Number of DatapathResult CRs with missing or zero `dpReadyTs` timestamp
- `p50`, `p90`, `p99`: Percentiles calculated from the `count` CRs with valid `latDpReadyMs` values
- `worstPods`: Top N pods with highest latencies (sorted descending)
- `failedPods`: Top N pods that failed to achieve datapath readiness (missing or zero `dpReadyTs`)

**Note:** The `count` (used for percentiles) may differ from `totalSuccessful` because:
- Pods may have a timestamp but zero latency (edge case)
- The controller may not have calculated the latency yet for recently annotated pods

## Cleanup Policy

Consider implementing a cleanup mechanism for old DatapathResult CRs:
- TTL-based deletion after a configured period
- Periodic cleanup job (CronJob) to remove old CRs
- Retention policy based on Pod deletion events