# Datapath Reporter

The datapath reporter is an init container that measures Pod startup time and datapath readiness, then writes the results to Pod annotations. After probing until success or timeout, the reporter exits and allows the main containers to start.

## Prerequisites

### ACR Pull Permissions

The AKS kubelet identity needs permission to pull the reporter image from the container registry.

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

## Usage

Add the reporter as an init container to your test Pods:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
  labels:
    app: perf-test
spec:
  serviceAccountName: reporter-sa
  initContainers:
  - name: datapath-reporter
    image: acndev.azurecr.io/datapath-reporter:latest
    env:
    - name: PROBE_TARGET
      value: "http://example.com"
    - name: PROBE_TIMEOUT
      value: "60"
    - name: MY_POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: MY_POD_NAMESPACE
      valueFrom:
        fieldRef:
          fieldPath: metadata.namespace
  containers:
  - name: main
    image: nginx:latest
```

## Configuration

Environment variables:

- `PROBE_TARGET` (required) - Target URL or host:port for datapath probe
- `PROBE_PROTOCOL` - Protocol to use: `http`, `https`, or `tcp` (default: `http`)
- `PROBE_TIMEOUT` - Timeout in seconds for datapath probe (default: `60`)
- `PROBE_INTERVAL` - Interval between probe attempts in seconds (default: `1`)

## Annotations Written

The reporter writes two annotations to the Pod:

- `perf.github.com/azure-start-ts` - RFC3339 timestamp with millisecond precision when init container started
- `perf.github.com/azure-dp-ready-ts` - RFC3339 timestamp with millisecond precision when first successful probe completed

Note: As an init container, the reporter validates datapath readiness before the main containers start, adding the probe timeout duration to overall pod startup latency.

## Building the Image

Build with [Dockerfile](Dockerfile) using date-based versioning:

```bash
# Tag format: YYYY.MM.DD.XX where XX is the version number for that day
# Example for first build on Dec 29, 2025:
docker build -t acndev.azurecr.io/datapath-reporter:2026.01.05.01 .
docker push acndev.azurecr.io/datapath-reporter:2026.01.05.01

# For subsequent builds on the same day, increment XX:
# 2025.12.29.02, 2025.12.29.03, etc.

# Optionally, also tag as latest for convenience:
docker tag acndev.azurecr.io/datapath-reporter:2026.01.05.01 acndev.azurecr.io/datapath-reporter:latest
docker push acndev.azurecr.io/datapath-reporter:latest
```

**Note:** Always use the date-versioned tag in deployment manifests to ensure reproducibility and avoid overwriting previous images.

## RBAC Requirements

The reporter requires:
- `get`, `patch` on its own Pod only (via downward API)

See [DesignDoc-Reporter.md](DesignDoc-Reporter.md) for detailed technical documentation.
