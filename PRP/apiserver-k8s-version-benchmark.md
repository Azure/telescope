# API Server Kubernetes Version Benchmark Plan

## Overview
Create an Azure test scenario to benchmark API server performance with 10 virtual nodes and 100 pods, comparing Kubernetes versions 1.32 vs 1.33 on AKS clusters.

## Implementation Options

### Option 1: Separate Scenarios for Each K8s Version
**Pros:**
- Clear separation of concerns
- Easy to manage independently
- Follows existing pattern in codebase

**Cons:**
- More code duplication
- Two separate pipeline runs needed

### Option 2: Single Scenario with K8s Version Matrix
**Pros:**
- Single scenario manages both versions
- Direct comparison in same pipeline run
- Less code duplication

**Cons:**
- More complex pipeline configuration
- Harder to debug individual versions

### Option 3: Pipeline-level Matrix (Recommended)
**Pros:**
- Leverages existing competitive-test.yml template
- Clean separation at pipeline level
- Easy to add more K8s versions later
- Follows telescope framework patterns

**Cons:**
- Requires understanding of matrix parameters

## Selected Approach: Option 3 - Pipeline-level Matrix

## TODO Checklist

- [x] Understand existing codebase structure and test scenario patterns
- [x] Examine existing API server benchmark scenarios
- [x] Design test scenario for API server benchmark with 10 VN + 100 pods
- [ ] Create scenario terraform configuration files
- [ ] Create pipeline configuration for K8s version comparison (1.32 vs 1.33)
- [ ] Implement the test scenario code
- [ ] Verify scenario locally
- [ ] Create private branch and push changes
- [ ] Verify end-to-end using mcp-ado mcp server

## Design Details

### Scenario Structure
- **Scenario Name**: `apiserver-vn10pod100-k8s-comp`
- **Location**: `scenarios/perf-eval/apiserver-vn10pod100-k8s-comp/`
- **Engine**: kperf (API server benchmarking tool)
- **Topology**: kperf

### Infrastructure Configuration
- **AKS Cluster**: 
  - 2 default nodes (Standard_D2s_v3)
  - 5 virtual nodes (Standard_D8s_v3) 
  - 3 runner nodes (Standard_D16s_v3)
- **K8s Versions**: 1.32.x and 1.33.x
- **Benchmark**: 10 virtual nodes, 100 pods, 1000 total requests

### Pipeline Configuration
- Two stages: k8s_1_32 and k8s_1_33
- Each stage runs identical tests on different K8s versions
- Uses competitive-test.yml template
- Matrix testing for workload-low and exempt flow control

### Files to Create/Modify
1. `scenarios/perf-eval/apiserver-vn10pod100-k8s-comp/terraform-inputs/azure.tfvars`
2. `scenarios/perf-eval/apiserver-vn10pod100-k8s-comp/terraform-test-inputs/azure.json`
3. Pipeline definition in `new-pipeline-test.yml` (for testing)
4. Final pipeline in `pipelines/perf-eval/API Server Benchmark/`

## Testing Strategy
1. Local verification using telescope framework
2. Private branch testing
3. End-to-end validation with mcp-ado server
4. Performance comparison analysis between K8s versions

## Success Criteria
- Successful deployment of AKS clusters with different K8s versions
- Successful execution of kperf benchmarks on both versions
- Collection of performance metrics for comparison
- Clean resource cleanup after testing