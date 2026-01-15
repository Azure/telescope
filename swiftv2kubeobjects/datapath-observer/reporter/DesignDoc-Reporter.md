# Reporter — Design

**Author:** Isaac Swamidasan  
**Date:** Dec 17, 2025  
**Updated:** Jan 06, 2026 (Changed from sidecar to init container)  
**Component:** reporter (init container for datapath readiness validation)

See [../DesignDoc-Overall.md](../DesignDoc-Overall.md) for the complete system architecture and goals.

## Overview

The reporter is a Kubernetes init container that validates datapath readiness by probing a configured target before allowing main containers to start. It reports start time and datapath readiness by patching its own Pod annotations. The controller consumes these annotations to calculate and aggregate performance metrics. The reporter probes the datapath until success or timeout, then exits cleanly to allow the main containers to proceed.

### Why Init Container?

The reporter is designed as an init container rather than a sidecar because:
- It performs a **one-time validation task** (datapath readiness check)
- It completes successfully and exits (would cause CrashLoopBackOff as a sidecar)
- It measures **true pod startup time** including datapath readiness before workload starts
- The probe timeout adds to pod startup latency, but this is an acceptable tradeoff for accurate validation and measurement

## Responsibilities

1. **Record start timestamp** - Captures `time.Now()` when the application workload begins
2. **Probe external target** - Continuously probes configured endpoint (HTTP/HTTPS/TCP) until success or timeout
3. **Record datapath ready timestamp** - Captures timestamp on first successful probe
4. **Patch Pod annotations** - Writes timestamps to its own Pod's annotations using Kubernetes API
5. **Idempotent patching** - Checks for existing annotations to prevent duplicate writes

## Annotation Contract

The reporter writes these annotations to its own Pod object:

- `perf.github.com/azure-start-ts`: RFC3339Nano timestamp (nanosecond precision) when application workload begins
- `perf.github.com/azure-dp-ready-ts`: RFC3339Nano timestamp (nanosecond precision) when first probe succeeds

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
  - Example also available in Telescope: [swiftv2_deployment_template.yaml](../../../../modules/python/clusterloader2/swiftv2-slo/config/swiftv2_deployment_template.yaml)

For build instructions, see [README.md](README.md#building-the-image).

## Implementation

The implementation is in [main.go](main.go).
