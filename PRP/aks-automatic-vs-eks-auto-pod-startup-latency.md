# AKS Automatic vs EKS Auto Mode Pod Startup Latency Test Scenario

## Overview
Create a new test scenario to measure and compare pod startup latency between AKS Automatic cluster and EKS Auto mode using clusterloader2 as the test engine and cri-resource-consume topology.

## Implementation Options

### Option 1: Extend Existing cri-resource-consume Scenario
**Pros:**
- Reuses existing infrastructure and configuration
- Minimal code changes required
- Consistent with current testing patterns

**Cons:**
- May not highlight specific automatic/auto-mode features
- Less targeted testing approach

### Option 2: Create New Dedicated Scenario
**Pros:**
- Dedicated focus on automatic cluster capabilities
- Can optimize configurations for auto-scaling scenarios
- Clear separation of concerns

**Cons:**
- More infrastructure code required
- Duplicate some existing patterns

### Option 3: Hybrid Approach (Recommended)
**Pros:**
- Leverages existing cri-resource-consume topology
- Creates dedicated scenario for automatic clusters
- Allows for auto-mode specific configurations

**Cons:**
- Moderate complexity increase

## Implementation Plan

### TODO Checklist

- [ ] **Step 1: Create scenario configuration**
  - [ ] Create `scenarios/perf-eval/auto-cluster-pod-startup/` directory
  - [ ] Add Azure AKS Automatic terraform inputs (`azure.tfvars`)
  - [ ] Add AWS EKS Auto mode terraform inputs (`aws.tfvars`)
  - [ ] Add corresponding test input validation files (`.json`)

- [ ] **Step 2: Pipeline configuration**
  - [ ] Create new pipeline YAML under CRI Benchmark category
  - [ ] Configure matrix for different pod counts and node configurations
  - [ ] Set appropriate timeouts for auto-scaling scenarios
  - [ ] Enable kubelet scraping for detailed metrics

- [ ] **Step 3: Test topology customization**
  - [ ] Verify cri-resource-consume topology works with automatic clusters
  - [ ] Adjust configurations if needed for auto-scaling behavior
  - [ ] Ensure proper node labeling and taints for automatic clusters

- [ ] **Step 4: Local verification**
  - [ ] Add to `new-pipeline-test.yml` for initial testing
  - [ ] Validate terraform configurations
  - [ ] Test pipeline execution locally
  - [ ] Verify metrics collection and reporting

- [ ] **Step 5: Create private branch and finalize**
  - [ ] Move pipeline from test to final location
  - [ ] Clean up test files
  - [ ] Create private branch for review

## Technical Details

### Scenario Configuration
- **Scenario Type**: perf-eval
- **Scenario Name**: auto-cluster-pod-startup
- **Engine**: clusterloader2 
- **Topology**: cri-resource-consume
- **Test Focus**: Pod startup latency comparison

### Key Measurements
- PodStartupLatency with threshold tuning for auto-scaling
- ResourceUsageSummary for cluster resource utilization
- WaitForControlledPodsRunning for deployment completion
- Kubelet metrics scraping for detailed container runtime metrics

### Matrix Configurations
- Different pod densities (30, 70, 110 pods per 10 nodes)
- Memory-focused workloads for consistent comparison
- Multiple Kubernetes versions (1.31, 1.32)
- Appropriate timeouts for auto-scaling scenarios

### Infrastructure Requirements
- **Azure**: AKS Automatic with zones 1,2,3 enabled
- **AWS**: EKS Auto mode with general purpose and system node pools
- Comparable VM/instance sizes for fair comparison
- Prometheus monitoring enabled for both platforms

## Expected Outcomes
- Quantitative comparison of pod startup latency between AKS Automatic and EKS Auto mode
- Insights into auto-scaling behavior impact on container startup performance
- Baseline metrics for future auto-cluster optimizations

## Dependencies
- clusterloader2 image: `ghcr.io/azure/clusterloader2:v20241016`
- Existing cri-resource-consume topology components
- Azure and AWS credential configurations
- Prometheus for metrics collection