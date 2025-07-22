# SwiftV2 ClusterLoader2 Configuration Guide

This document explains the ClusterLoader2 configuration files used for SwiftV2 cluster churn performance testing, detailing the steps, measurements, and resource allocation strategies.

## Overview

The SwiftV2 performance tests use two main ClusterLoader2 configuration files:
- `swiftv2_deployment_dynamicres_scale_config.yaml` - Dynamic resource allocation strategy
- `swiftv2_deployment_staticres_scale_config.yaml` - Static resource allocation strategy

Both configurations test pod deployment churn scenarios with network connectivity validation while using different Pod Network Instance (PNI) allocation approaches.

## Configuration Parameters

### Global Template Variables

Both configurations use the same set of template variables that are populated at runtime:

```yaml
{{$nodesPerStep := DefaultParam .CL2_NODES_PER_STEP 100}}    # Pods to deploy per step
{{$nodes := DefaultParam .CL2_NODES 1000}}                  # Total target pods
{{$steps := DivideInt $nodes $nodesPerStep}}                # Number of deployment steps
{{$latencyPodCpu := DefaultParam .CL2_LATENCY_POD_CPU 10}}  # CPU request per pod (m)
{{$latencyPodMemory := DefaultParam .CL2_LATENCY_POD_MEMORY 50}} # Memory request per pod (M)
{{$podStartupLatencyThreshold := DefaultParam .CL2_POD_STARTUP_LATENCY_THRESHOLD "60s"}} # SLO threshold
{{$operationTimeout := DefaultParam .CL2_OPERATION_TIMEOUT "120s"}} # Operation timeout
{{$groupName := DefaultParam .CL2_GROUP_NAME "deployment-churn"}} # Deployment group identifier
```

### Namespace Configuration

```yaml
namespace:
  number: 1                           # Single namespace for all deployments
  prefix: slo                         # Namespace name: "slo"
  deleteStaleNamespaces: false        # Preserve existing namespaces
  deleteAutomanagedNamespaces: false  # Don't auto-delete namespaces
  enableExistingNamespaces: false     # Create new namespace if needed
```

### QPS Tuning Sets

```yaml
tuningSets:
  - name: DeploymentCreatePNIQps      # PNI creation rate limiting
    qpsLoad:
      qps: 1                          # 1 PNI creation per second
  - name: DeploymentCreateQps         # Deployment creation rate limiting
    qpsLoad:
      qps: 1                          # 1 deployment per second
```

## Dynamic Resource Allocation Configuration

### Test Flow Overview

The dynamic configuration follows this sequence:

1. **Setup Phase**: Create single dynamic PNI for all pods
2. **Scaling Phase**: Deploy pods in batches, all using the shared PNI
3. **Validation Phase**: Test network connectivity from each pod batch
4. **Measurement Phase**: Collect performance metrics

### Step-by-Step Breakdown

#### 1. Initialization
```yaml
- name: Log - steps={{$steps}}, nodes={{$nodes}}
  measurements:
  - Identifier: Dummy
    Method: Sleep
    Params:
      action: start
      duration: 1ms
```
- **Purpose**: Log the test configuration parameters
- **Action**: Minimal sleep to initialize logging

#### 2. Create Dynamic PNI
```yaml
- name: "Create PNI"
  phases:
  - namespaceRange:
      min: 1
      max: 1
    replicasPerNamespace: 1
    tuningSet: DeploymentCreatePNIQps
    objectBundle:
    - basename: pod-network-instance
      objectTemplatePath: pni_dynamic_template.yaml
```
- **Purpose**: Create a single Pod Network Instance for dynamic resource allocation
- **Template**: Uses `pni_dynamic_template.yaml` with `podNetwork: pn100`
- **Rate Limiting**: 1 QPS via `DeploymentCreatePNIQps`

#### 3. PNI Registration Wait
```yaml
- name: Wait for PNI to be created and nodes to be registered
  measurements:
    - Identifier: Dummy
      Method: Sleep
      Params:
        duration: 60s
```
- **Purpose**: Allow time for PNI creation and node registration
- **Duration**: 60 seconds wait period

#### 4. Start Global Pod Startup Latency Measurement
```yaml
- name: Starting Pod Startup Latency Measurements
  measurements:
  - Identifier: PodStartupLatency
    Method: PodStartupLatency
    Params:
      action: start
      labelSelector: podgroup={{$groupName}}
      threshold: {{$podStartupLatencyThreshold}}
```
- **Purpose**: Begin measuring pod startup latency across all deployment batches
- **Selector**: Tracks all pods with `podgroup=deployment-churn`
- **Threshold**: 60s SLO for pod startup time

#### 5. Iterative Deployment Loop
For each step (batch) from 0 to `$steps`:

##### 5a. Start Deployment Measurements
```yaml
- name: Starting Deployment Latency Measurements -{{$j}}
  measurements:
  - Identifier: WaitForControlledPodsRunning-{{$j}}
    Method: WaitForControlledPodsRunning
    Params:
      action: start
      apiVersion: apps/v1
      kind: Deployment
      labelSelector: group={{$groupName}}-{{$j}}
      operationTimeout: {{$operationTimeout}}
```
- **Purpose**: Begin measuring deployment readiness for current batch
- **Selector**: `group=deployment-churn-{step_number}`
- **Timeout**: 120s operation timeout

##### 5b. Create Deployments
```yaml
- name: Create Deployments {{$j}}
  phases:
    - namespaceRange:
        min: 1
        max: 1
      replicasPerNamespace: 1
      tuningSet: DeploymentCreateQps
      objectBundle:
        - basename: deployment-churn-{{$j}}
          objectTemplatePath: swiftv2_deployment_template.yaml
          templateFillMap:
            Replicas: {{$nodesPerStep}}
            PodGroup: {{$groupName}}
            Group: {{$groupName}}-{{$j}}
            CpuRequest: {{$latencyPodCpu}}m
            MemoryRequest: {{$latencyPodMemory}}M
            deploymentLabel: start
            pniName: pod-network-instance-0
```
- **Purpose**: Deploy a batch of pods using the shared dynamic PNI
- **Template**: `swiftv2_deployment_template.yaml`
- **Key Parameters**:
  - `Replicas`: Number of pods per batch (default: 100)
  - `CpuRequest`: CPU request per pod (default: 10m)
  - `MemoryRequest`: Memory request per pod (default: 50M)
  - `pniName`: All deployments use `pod-network-instance-0`

##### 5c. Wait for Deployment Readiness
```yaml
- name: Wait for all Deployments to be Running -{{$j}}
  measurements:
  - Identifier: WaitForControlledPodsRunning-{{$j}}
    Method: WaitForControlledPodsRunning
    Params:
      action: gather
      apiVersion: apps/v1
      kind: Deployment
      labelSelector: group={{$groupName}}-{{$j}}
      operationTimeout: {{$operationTimeout}}
```
- **Purpose**: Wait for all pods in current batch to be running
- **Action**: Gather results from the measurement started in step 5a

##### 5d. Network Readiness Wait
```yaml
- name: Wait for network readiness -{{$j}}
  measurements:
  - Identifier: NetworkReadiness-{{$j}}
    Method: Sleep
    Params:
      action: start
      duration: 30s
```
- **Purpose**: Allow additional time for network setup after pod startup
- **Duration**: 30 seconds

##### 5e. Start Network Connectivity Test
```yaml
- name: Starting measurement Pod Curl Command -{{$j}}
  measurements:
  - Identifier: PodPeriodicCommand-{{$j}}
    Method: PodPeriodicCommand
    Params:
      action: start
      labelSelector: group={{$groupName}}-{{$j}}
      interval: 300s
      container: deployment-churn
      limit: {{$nodesPerStep}}
      failOnCommandError: true
      failOnExecError: true
      failOnTimeout: true
      commands:
      - name: CustPodCurl
        command: ["/bin/sh", "-c", "curl --retry 5 --retry-delay 15 --max-time 30 172.27.0.30"]
        timeout: 180s
```
- **Purpose**: Test network connectivity from each pod to the ping target
- **Target**: `172.27.0.30` (nginx service from `swiftv2kubeobjects/nginx-deployment.yaml`)
- **Configuration**:
  - `interval`: 300s between curl attempts
  - `limit`: Test up to `$nodesPerStep` pods
  - Curl retry logic: 5 retries, 15s delay, 30s max time per attempt
  - Total timeout: 180s per curl command

##### 5f. Wait for Connectivity Test
```yaml
- name: Wait for curl command to be done -{{$j}}
  measurements:
  - Identifier: Curl_Dummy-{{$j}}
    Method: Sleep
    Params:
      action: start
      duration: 250s
```
- **Purpose**: Allow time for curl commands to complete
- **Duration**: 250 seconds (longer than the 180s curl timeout)

##### 5g. Gather Connectivity Results
```yaml
- name: Ending measurement Pod Curl Command -{{$j}}
  measurements:
  - Identifier: PodPeriodicCommand-{{$j}}
    Method: PodPeriodicCommand
    Params:
      action: gather
      labelSelector: group={{$groupName}}-{{$j}}
```
- **Purpose**: Collect results from the network connectivity tests
- **Critical Note**: The `Identifier: PodPeriodicCommand-{{$j}}` must exactly match the identifier used in step 5e's `action: start`. ClusterLoader2 uses the identifier to link measurement start and gather actions - they form a measurement pair that tracks the same operation lifecycle.

#### 6. Final Measurement Collection
```yaml
- name: Gather Pod Startup Latency Measurements
  measurements:
  - Identifier: PodStartupLatency
    Method: PodStartupLatency
    Params:
      action: gather
      labelSelector: podgroup={{$groupName}}
```
- **Purpose**: Collect final pod startup latency metrics for all deployed pods

## Static Resource Allocation Configuration

### Key Differences from Dynamic Configuration

The static configuration differs primarily in PNI allocation strategy:

#### 1. PNI Creation Per Step
Instead of creating one shared PNI, the static configuration creates a dedicated PNI for each deployment batch:

```yaml
- name: Create PNI -{{$j}}
  phases:
  - namespaceRange:
      min: 1
      max: 1
    replicasPerNamespace: 1
    tuningSet: DeploymentCreatePNIQps
    objectBundle:
    - basename: pod-network-instance-{{$j}}
      objectTemplatePath: pni_static_template.yaml
      templateFillMap:
            ReservationSize: {{$nodesPerStep}}
```

**Key Differences**:
- **Template**: Uses `pni_static_template.yaml` instead of `pni_dynamic_template.yaml`
- **Basename**: Each PNI has unique name `pod-network-instance-{step_number}`
- **ReservationSize**: Pre-allocates IP addresses for `$nodesPerStep` pods

#### 2. PNI Reference in Deployments
```yaml
templateFillMap:
  # ... other parameters ...
  pniName: pod-network-instance-{{$j}}-0  # Uses step-specific PNI
```

**Comparison**:
- **Dynamic**: All deployments use `pod-network-instance-0`
- **Static**: Each deployment batch uses `pod-network-instance-{step_number}-0`

**Note on `-0` Suffix**: The `-0` suffix is automatically appended by ClusterLoader2's object naming convention. When ClusterLoader2 creates objects with a `basename`, it appends `-{replica_index}` to ensure unique naming. Since `replicasPerNamespace: 1` is used in both configurations, the first (and only) replica gets the `-0` suffix. This naming pattern supports ClusterLoader2's ability to create multiple replicas of the same object template when needed.

**Examples**:
- Dynamic config: `basename: pod-network-instance` → actual name: `pod-network-instance-0`
- Static config: `basename: pod-network-instance-{{$j}}` (where `$j=2`) → actual name: `pod-network-instance-2-0`

#### 3. Step Ordering
The static configuration moves pod startup latency measurement initialization to occur before the loop, while PNI creation happens within each step iteration.

## Resource Allocation Strategy Comparison

### Dynamic Resource Allocation
- **Approach**: Single shared PNI for all pods
- **Advantages**:
  - Lower resource overhead (one PNI)
  - Simpler network topology
  - Faster initial setup
- **Use Cases**: 
  - High-density pod deployments
  - Scenarios where network resources are abundant
  - Testing with uniform network requirements

### Static Resource Allocation  
- **Approach**: Dedicated PNI per deployment batch
- **Advantages**:
  - Predictable resource allocation
  - Better isolation between deployment batches
  - More realistic multi-tenant scenarios
- **Use Cases**:
  - Multi-tenant workload simulation
  - Testing network resource limitations
  - Scenarios requiring network isolation

## Network Connectivity Validation

Both configurations validate network connectivity by:

1. **Target**: Curl requests to `172.27.0.30` (nginx service)
2. **Reliability**: 5 retries with 15-second delays
3. **Timeout**: 30 seconds per curl, 180 seconds total per pod
4. **Scope**: Tests all pods in each deployment batch
5. **Failure Handling**: Fails the test on curl errors, exec errors, or timeouts

## Performance Measurements

### ClusterLoader2 Measurement Lifecycle

ClusterLoader2 uses a two-phase measurement approach with `start` and `gather` actions:

1. **Start Action**: Initiates the measurement with `action: start`
2. **Gather Action**: Collects results with `action: gather` 
3. **Identifier Matching**: The `Identifier` field must be identical between start and gather actions to link them as a measurement pair

**Example Pattern**:
```yaml
# Start measurement
- Identifier: PodPeriodicCommand-0
  Method: PodPeriodicCommand
  Params:
    action: start
    # ... other parameters

# Later: Gather results  
- Identifier: PodPeriodicCommand-0    # Must match exactly!
  Method: PodPeriodicCommand
  Params:
    action: gather
    # ... same parameters as start
```

**Critical Requirements**:
- Identifiers must match exactly (case-sensitive)
- Same measurement method must be used for both actions
- Parameters should generally match between start and gather
- Each measurement pair tracks one operation lifecycle

### Pod Startup Latency
- **Metric**: Time from pod creation to running state
- **Threshold**: 60 seconds (configurable)
- **Scope**: All pods across all deployment batches
- **Collection**: Start at test beginning, gather at test end

### Deployment Readiness
- **Metric**: Time for deployments to reach desired replica count
- **Timeout**: 120 seconds per batch
- **Scope**: Per deployment batch
- **Collection**: Start before deployment creation, gather after

### Network Connectivity
- **Metric**: Success/failure of curl commands from pods
- **Interval**: 300 seconds between attempts per pod
- **Scope**: All pods in each deployment batch
- **Validation**: Ensures pods can reach external services

## Template Dependencies

### Required Templates
- `swiftv2_deployment_template.yaml`: Pod deployment template
- `pni_dynamic_template.yaml`: Dynamic PNI template (shared resource)
- `pni_static_template.yaml`: Static PNI template (per-batch resource)

### External Dependencies
- SwiftV2 nginx service at `172.27.0.30` (deployed via `swiftv2kubeobjects/nginx-deployment.yaml`)
- Pod Network (pn100) configuration
- Azure SwiftV2 networking components

## Usage in Pipeline Context

These configurations are used by:
1. **Matrix Jobs**: Different node counts and scaling patterns
2. **Python Controller**: `modules/python/clusterloader2/slo/slo.py`
3. **ClusterLoader2 Container**: `ghcr.io/azure/clusterloader2:v20250311`
4. **Pipeline Variables**: Populated from matrix parameters and environment variables

The configurations support testing different scaling scenarios (gradual vs burst) and node counts (20 to 1000) while maintaining consistent measurement and validation approaches.
