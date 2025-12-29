# Reporter — Design

**Author:** Isaac Swamidasan  
**Date:** Dec 17, 2025  
**Component:** reporter (init container for datapath readiness reporting)

See [../DesignDoc-Overall.md](../DesignDoc-Overall.md) for the complete system architecture and goals.

## Overview

The reporter is a Kubernetes init container that reports its start time and datapath readiness by patching its own Pod annotations. The controller consumes these annotations to calculate and aggregate performance metrics.

## Responsibilities

1. **Record start timestamp** - Captures `time.Now()` when the application workload begins
2. **Probe external target** - Continuously probes configured endpoint (HTTP/HTTPS/TCP) until success or timeout
3. **Record datapath ready timestamp** - Captures timestamp on first successful probe
4. **Patch Pod annotations** - Writes timestamps to its own Pod's annotations using Kubernetes API
5. **Idempotent patching** - Checks for existing annotations to prevent duplicate writes

## Annotation Contract

The reporter writes these annotations to its own Pod object:

- `perf.github.com/Azure/start-ts`: RFC3339 timestamp when application workload begins
- `perf.github.com/Azure/dp-ready-ts`: RFC3339 timestamp when first probe succeeds

The controller reads these annotations and calculates latency metrics (time-to-start and time-to-datapath-ready) based on these timestamps and the Pod's creation time.

## Configuration

Required environment variables (provided via downward API):

- `MY_POD_NAME`: Pod name
- `MY_POD_NAMESPACE`: Pod namespace
- `PROBE_TARGET`: Target endpoint for datapath validation (HTTP/HTTPS/TCP)

Optional environment variables:

- `PROBE_TIMEOUT`: Maximum seconds to wait for probe success (default: 60)
- `PROBE_INTERVAL`: Seconds between probe attempts (default: 2)

## Probe Support

The reporter supports multiple probe types:

- **HTTP/HTTPS**: Performs HTTP GET, considers 2xx-3xx status codes as success
- **TCP**: Performs TCP dial to specified address

## RBAC Requirements

The reporter requires these permissions:

- `get` on Pods (to read current annotations for idempotency)
- `patch` on Pods (to write timestamp annotations)

See [manifests/rbac.yaml](manifests/rbac.yaml) for the complete RBAC configuration.

## Deployment

The following is a generic example. For Telescope deployment refer to [swiftv2_deployment_template](modules/python/clusterloader2/swiftv2-slo/config/swiftv2_deployment_template.yaml)

### Kubernetes Manifests

- **RBAC:** [manifests/rbac.yaml](manifests/rbac.yaml)
  - ServiceAccount, Role (Pods get/patch), RoleBinding
  
- **Deployment:** [manifests/deployment.yaml](manifests/deployment.yaml)
  - Used as init container in workload Pods
  - Environment variables: pod name, namespace, probe target, timeout, interval

### Container Image

Build with [Dockerfile](Dockerfile) using date-based versioning:

```bash
# Tag format: YYYY.MM.DD.XX where XX is the version number for that day
# Example for first build on Dec 29, 2025:
docker build -t acndev.azurecr.io/telescope-reporter:2025.12.29.01 .
docker push acndev.azurecr.io/telescope-reporter:2025.12.29.01

# For subsequent builds on the same day, increment XX:
# 2025.12.29.02, 2025.12.29.03, etc.

# Optionally, also tag as latest for convenience:
docker tag acndev.azurecr.io/telescope-reporter:2025.12.29.01 acndev.azurecr.io/telescope-reporter:latest
docker push acndev.azurecr.io/telescope-reporter:latest
```

**Note:** Always use the date-versioned tag in deployment manifests to ensure reproducibility and avoid overwriting previous images.

## Implementation

See [README.md](README.md) for build and deployment instructions. The implementation is in [main.go](main.go).
