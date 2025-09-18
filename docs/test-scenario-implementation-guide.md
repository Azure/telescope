# Test Scenario Implementation Guide

This guide provides comprehensive approaches for implementing and modifying test scenarios in Telescope, from simple parameter changes to complex new infrastructure setups.

## Overview

Telescope supports multiple approaches to create and modify test scenarios, each suited for different use cases:

1. **Expand Existing Scenario** - Expand existing scenarios for different variants
2. **Create New Scenario with Custom Infrastructure** - Build completely new test infrastructure
3. **Matrix Parameter Variations & A/B Testing** - Test parameter combinations and compare configurations
4. **New Test Engine With Custom Topology Integration** - Add new testing tools with custom execution patterns
5. **Custom Topology with Existing Engine** - Create new test execution patterns using existing engines

## Implementation Approaches

### 1. Expand Existing Scenario

**Use Case**: Create variations of existing tests with different variants (e.g., node count, k8s version, capacity type, OS type)

**Steps**:
```bash
# Add new terraform variable files for different variants
# Example files:
scenarios/perf-eval/<scenario-name>/terraform-inputs/azure-2000nodes.tfvars
scenarios/perf-eval/<scenario-name>/terraform-inputs/aws-2000nodes.tfvars
scenarios/perf-eval/<scenario-name>/terraform-inputs/azure-spot.tfvars
scenarios/perf-eval/<scenario-name>/terraform-inputs/aws-spot.tfvars
scenarios/perf-eval/<scenario-name>/terraform-inputs/azure-windows.tfvars
scenarios/perf-eval/<scenario-name>/terraform-inputs/aws-windows.tfvars
```

# Add new pipeline stages with variant parameters

**Example Pipeline Addition**:
```yaml
- stage: azure_australiaeast_xlarge_scale
  condition: |
    or(
      eq(variables['Build.CronSchedule.DisplayName'], 'Weekly XLarge Scale'),
      eq(variables['Build.Reason'], 'Manual')
    )
  jobs:
    - template: /jobs/competitive-test.yml
      parameters:
        cloud: azure
        regions:
          - australiaeast
        terraform_input_file_mapping:
          - australiaeast: "scenarios/perf-eval/cluster-autoscaler/terraform-inputs/azure-2000nodes.tfvars"
        matrix:
          xlarge-scale-on-demand:
            node_count: 2001
            pod_count: 2001
            scale_up_timeout: "90m"
            scale_down_timeout: "90m"
```

### 2. Create New Scenario with Custom Infrastructure

**Use Case**: Implementing a completely new test scenario with unique infrastructure requirements

**Directory Structure**:
```
scenarios/perf-eval/<new-scenario-name>/
├── terraform-inputs/
│   ├── azure.tfvars
│   ├── aws.tfvars
│   └── gcp.tfvars (optional)
└── terraform-test-inputs/
    ├── azure.json
    ├── aws.json
    └── gcp.json (optional)
```

**Implementation Steps**:
1. **Create Scenario Structure**:
   ```bash
   mkdir -p scenarios/perf-eval/<new-scenario-name>/{terraform-inputs,terraform-test-inputs}
   ```

2. **Define Infrastructure** (using template):
   ```bash
   cp docs/templates/azure.tfvars scenarios/perf-eval/<new-scenario-name>/terraform-inputs/azure.tfvars
   # Customize the tfvars file for your specific requirements
   ```

3. **Create Pipeline Definition**:
  Use the following template to define your pipeline in `new-pipeline-test.yml` for validation:
   ```yaml
   variables:
     SCENARIO_TYPE: perf-eval
     SCENARIO_NAME: <new-scenario-name>
   
   stages:
     - stage: <cloud>_<region>_<description>
       jobs:
         - template: /jobs/competitive-test.yml
           parameters:
             cloud: <cloud>
             regions: [<region>]
             topology: <topology>
             engine: <engine>
             matrix:
               <test-case>:
                 <param1>: <value1>
                 <param2>: <value2>
   ```

### 3. Matrix Parameter Variations & A/B Testing

**Use Case**: Run the same infrastructure with different test parameters for comprehensive coverage, performance comparisons, or A/B testing

**Examples**:

**Scale Variations**:
```yaml
matrix:
  small_scale:
    node_count: 10
    pod_count: 100
    timeout: "15m"
  medium_scale:
    node_count: 100
    pod_count: 1000
    timeout: "30m"
  large_scale:
    node_count: 1000
    pod_count: 10000
    timeout: "60m"
```

**Version Comparisons**:
```yaml
matrix:
  k8s_1_28:
    aks_kubernetes_version: "1.28"
    k8s_machine_type: "Standard_D4s_v3"
  k8s_1_29:
    aks_kubernetes_version: "1.29"
    k8s_machine_type: "Standard_D4s_v3"
```

**Capacity Type Testing**:
```yaml
matrix:
  on_demand_nodes:
    capacity_type: on-demand
    scale_timeout: "30m"
  spot_nodes:
    capacity_type: spot
    scale_timeout: "45m"  # Longer timeout for spot instances
```

**A/B Configuration Comparisons**:
```yaml
matrix:
  baseline_config:
    test_variant: "baseline"
    feature_flag: false
    resource_limit: "2Gi"
  experimental_config:
    test_variant: "experimental" 
    feature_flag: true
    resource_limit: "4Gi"
```

**Data Collection Strategy**:
- Use identical infrastructure
- Vary only the test parameters
- Collect comparative metrics
- Implement statistical analysis

### 4. New Test Engine With Custom Topology Integration

**Use Case**: Adding new testing tools or benchmark engines

**Required Components**:
1. **Python Module** (`modules/python/<engine-name>/`)
2. **Engine YAML Files** (`steps/engine/<engine-name>/`)
3. **Topology Integration** (`steps/topology/`)

**Example Structure**:
```
modules/python/mybench/
├── __init__.py
├── benchmark.py
└── config/ [if needed]
    └── default.yaml

steps/engine/mybench/ # For engine-specific steps. Name files as needed
├── execute.yml
├── collect.yml
└── validate.yml

steps/topology/test-topology/ # Custom topology using the new engine
├── validate-resources.yml # use same file name
├── execute-mybench.yml # Use execute-<engine>.yml naming convention
└── collect-mybench.yml # Use collect-<engine>.yml naming convention
```

### 5. Custom Topology with Existing Engine

**Use Case**: New test execution patterns, resource validation, or data collection workflows

**Required Files**:
- `validate-resources.yml` - Infrastructure validation
- `execute-<engine>.yml` - Test execution logic  
- `collect-<engine>.yml` - Results collection

**Template Structure**:
```yaml
# steps/topology/<topology-name>/validate-resources.yml
steps:
- template: /steps/terraform/validate-<cloud>-resources.yml
  parameters:
    expected_resources:
      - resource_type: "kubernetes_cluster"
        count: 1
      - resource_type: "node_pool"
        count: "$(node_pool_count)"
```


## Best Practices

> **📋 For comprehensive best practices and guidelines**, see the [Best Practices Guide](best-practices.md) which covers development standards, security guidelines, performance optimization, troubleshooting, and maintenance practices.

## Implementation Checklist

### For New Scenarios:
- [ ] Create scenario directory structure
- [ ] Define terraform input variable files
- [ ] Create test input JSON files
- [ ] Implement or select engine
- [ ] Configure topology
- [ ] Create pipeline definition
- [ ] Test in `new-pipeline-test.yml`
- [ ] Validate locally using `verify.md` based on the modules used
- [ ] Move to appropriate category directory

### For Modifications:
- [ ] Identify existing components to modify
- [ ] Create new variable files if needed
- [ ] Test in `new-pipeline-test.yml` with E2E testing guide
- [ ] Validate locally using `verify.md` based on the modules used
- [ ] Update pipeline matrix parameters
- [ ] Test parameter variations
- [ ] Update documentation

This guide provides the foundation for implementing any test scenario modification or creation in Telescope. Choose the approach that best fits your testing requirements and follow the established patterns for consistency and maintainability.