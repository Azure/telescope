# Datapath Controller

The datapath controller watches Pods in your cluster, tracks their datapath readiness metrics, and persists results in `DatapathResult` CRDs. It also serves HTTP APIs for querying aggregated metrics.

## Prerequisites

### ACR Pull Permissions

The AKS kubelet identity needs permission to pull the controller image from the container registry.

```bash
az role assignment create \
  --assignee <KUBELET_IDENTITY_OBJECT_ID> \
  --role AcrPull \
  --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.ContainerRegistry/registries/<REGISTRY_NAME>
```

**Example:**
```bash
az role assignment create \
  --assignee 00000000-0000-0000-0000-000000000000 \
  --role AcrPull \
  --scope /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/acn-shared-resources/providers/Microsoft.ContainerRegistry/registries/acndev
```

To find your kubelet identity:
```bash
az aks show -g <RESOURCE_GROUP> -n <CLUSTER_NAME> --query identityProfile.kubeletidentity.objectId -o tsv
```

## Deployment

1. Apply the CRD:
   ```bash
   kubectl apply -f manifests/crd.yaml
   ```

2. Deploy the controller:
   ```bash
   kubectl apply -f manifests/deployment.yaml
   ```

3. Verify deployment:
   ```bash
   kubectl get pods -n datapath-observer
   kubectl logs -n datapath-observer deployment/datapath-controller
   ```

## API Endpoints

### Time to Start Metrics

```bash
GET /api/v1/time-to-start?topN=10&namespace=<ns>&labelSelector=<k=v,...>
```

Returns:
- Percentiles (p50, p90, p99)
- Total successful pods (with non-zero `startTs`)
- Total failed pods (missing/zero `startTs`)
- Top N worst performers
- Top N failed pods

### Time to Datapath Ready Metrics

```bash
GET /api/v1/time-to-datapath-ready?topN=10&namespace=<ns>&labelSelector=<k=v,...>
```

Returns:
- Percentiles (p50, p90, p99)
- Total successful pods (with non-zero `dpReadyTs`)
- Total failed pods (missing/zero `dpReadyTs`)
- Top N worst performers
- Top N failed pods

## Configuration

Environment variables:

- `NAMESPACE` - Namespace to watch for pods (default: all namespaces)
- `LABEL_SELECTOR` - Label selector for pods to track (default: empty, tracks all)
- `HTTP_PORT` - Port for HTTP API server (default: 8080)

## Building the Image

Build with [Dockerfile](Dockerfile) using date-based versioning:

```bash
# Tag format: YYYY.MM.DD.XX where XX is the version number for that day
# Example for first build on Jan 2, 2026:
docker build -t acndev.azurecr.io/datapath-controller:2026.01.14.02 .
docker push acndev.azurecr.io/datapath-controller:2026.01.14.02

# For subsequent builds on the same day, increment XX:
# 2026.01.02.02, 2026.01.02.03, etc.

# Optionally, also tag as latest for convenience:
docker tag acndev.azurecr.io/datapath-controller:2026.01.14.02 acndev.azurecr.io/datapath-controller:latest
docker push acndev.azurecr.io/datapath-controller:latest
```

**Note:** Always use the date-versioned tag in deployment manifests to ensure reproducibility and avoid overwriting previous images.

## RBAC Requirements

The controller requires:
- `watch`, `get`, `list` on Pods
- `create`, `update`, `get`, `list` on DatapathResult CRDs

See [DesignDoc-Controller.md](DesignDoc-Controller.md) for detailed technical documentation.
