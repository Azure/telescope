# Pod Ready Watcher — Implementation Guide

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

### Container Image

Build with [Dockerfile](Dockerfile) using date-based versioning:

```bash
# Tag format: YYYY.MM.DD.XX where XX is the version number for that day
# Example for first build on Dec 29, 2025:
docker build -t acndev.azurecr.io/pod-datapath-watcher:2025.12.29.01 .
docker push acndev.azurecr.io/pod-datapath-watcher:2025.12.29.01

# For subsequent builds on the same day, increment XX:
# 2025.12.29.02, 2025.12.29.03, etc.

# Optionally, also tag as latest for convenience:
docker tag acndev.azurecr.io/pod-datapath-watcher:2025.12.29.01 acndev.azurecr.io/pod-datapath-watcher:latest
docker push acndev.azurecr.io/pod-datapath-watcher:latest
```

**Note:** Always use the date-versioned tag in deployment manifests to ensure reproducibility and avoid overwriting previous images.

## Configuration

The watcher accepts the following command-line arguments:

- `--namespace`: Target namespace to watch
- `--label-selector`: Label selector for filtering Pods
- `--slo-start`: SLO timeout for start metric (e.g., `30s`)
- `--slo-dpready`: SLO timeout for datapath ready metric (e.g., `60s`)

Query parameters for API endpoints:

- `topN`: Number of worst Pods to return (default: `10`)
- `namespace`: Filter by namespace (optional if specified in watcher config)
- `labelSelector`: Filter by label selector in format `key=value,key2=value2` (optional if specified in watcher config)

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

## Cleanup Policy

Consider implementing a cleanup mechanism for old DatapathResult CRs:
- TTL-based deletion after a configured period
- Periodic cleanup job (CronJob) to remove old CRs
- Retention policy based on Pod deletion events