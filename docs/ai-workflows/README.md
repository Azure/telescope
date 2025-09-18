# AI Test Scenario Generation

Generate Telescope test scenarios using structured JSON prompts.

## Quick Start

1. **Copy the template** below
2. **Fill in your requirements** 
3. **Submit to AI** for processing
4. **Get generated Telescope files**

## JSON Template

```json
{
  "schema_version": "1.0",
  "scenarios": [
    {
      "test_objective": "What you want to test",
      "scenario_name": "my-test-name",
      "test_type": "performance",
      "component": "autoscaler", 
      "owner": "my-team",
      "variations": [
        {
          "name": "test-variation",
          "cloud": "azure",
          "region": "eastus2",
          "schedule": "weekly",
          "config": {}
        }
      ]
    }
  ]
}
```

## Required vs Optional Fields

### Required Fields
- `test_objective` - What you're testing
- `scenario_name` - Unique name for your test
- `owner` - Team/person responsible
- `variations` - At least one variation required
- `name`, `cloud`, `region`, `schedule` - Required for each variation

### Optional Fields  
- `test_type` - Defaults to "performance"
- `component` - Helps AI select appropriate tools
- `config` - Any additional configuration for the variation

## Supported Values

| Field | Options |
|-------|---------|
| `test_type` | `performance`, `functionality`, `reliability` |
| `cloud` | `azure`, `aws` |
| `schedule` | `daily`, `weekly`, `monthly`, `on-demand` |
| `component` | `autoscaler`, `networking`, `storage`, `api-server`, `scheduler`, `gpu` |

**Azure regions**: `eastus2`, `westus2`, `australiaeast`, `westeurope`  
**AWS regions**: `us-east-2`, `us-west-2`, `ap-southeast-2`, `eu-west-1`

## Common Config Options

The `config` object in variations can include any test-specific parameters:

- `scale`: `small`, `medium`, `large` - Infrastructure size
- `vm_size`: `Standard_D4s_v3`, `Standard_D8s_v3` - VM specifications  
- `k8s_version`: `1.28`, `1.29`, `1.30` - Kubernetes versions
- `capacity_type`: `on-demand`, `spot` - Instance types
- `node_count`: `5`, `50`, `200` - Specific node counts
- `timeout`: `30m`, `60m`, `120m` - Custom timeouts
- Any other test-specific parameters

## Examples

### Basic Test
```json
{
  "scenarios": [{
    "test_objective": "Test cluster autoscaler basic functionality",
    "scenario_name": "autoscaler-test",
    "component": "autoscaler",
    "owner": "my-team", 
    "variations": [{
      "name": "azure-basic",
      "cloud": "azure", 
      "region": "eastus2",
      "schedule": "daily",
      "config": {}
    }]
  }]
}
```

### Multi-Cloud Comparison
```json
{
  "scenarios": [{
    "test_objective": "Compare network performance across clouds",
    "scenario_name": "cross-cloud-network",
    "component": "networking",
    "owner": "network-team",
    "variations": [
      {
        "name": "azure-test",
        "cloud": "azure",
        "region": "eastus2", 
        "schedule": "weekly",
        "config": {}
      },
      {
        "name": "aws-test", 
        "cloud": "aws",
        "region": "us-east-2",
        "schedule": "weekly",
        "config": {}
      }
    ]
  }]
}
```

### Scale Variations
```json
{
  "scenarios": [{
    "test_objective": "Test storage at different scales",
    "scenario_name": "storage-scale-test",
    "component": "storage",
    "owner": "storage-team",
    "variations": [
      {"name": "small", "cloud": "azure", "region": "eastus2", "schedule": "daily", "config": {"scale": "small"}},
      {"name": "large", "cloud": "azure", "region": "australiaeast", "schedule": "weekly", "config": {"scale": "large"}}
    ]
  }]
}
```

### VM Size Comparison
```json
{
  "scenarios": [{
    "test_objective": "Compare different VM sizes",
    "scenario_name": "vm-comparison",
    "component": "autoscaler",
    "owner": "perf-team",
    "variations": [
      {"name": "small-vm", "cloud": "azure", "region": "eastus2", "schedule": "weekly", "config": {"vm_size": "Standard_D4s_v3"}},
      {"name": "large-vm", "cloud": "azure", "region": "eastus2", "schedule": "weekly", "config": {"vm_size": "Standard_D8s_v3"}}
    ]
  }]
}
```

## What AI Generates

- **Terraform files**: `scenarios/perf-eval/{name}/terraform-inputs/{cloud}-{region}.tfvars`
- **Test files**: `scenarios/perf-eval/{name}/terraform-test-inputs/{cloud}-{region}.json`
- **Pipeline**: `pipelines/perf-eval/{category}/{name}.yml`
- **README**: Setup and usage instructions

## Component → Tool Mapping

| Component | Engine | Topology | Category |
|-----------|--------|----------|----------|
| autoscaler | clusterloader2 | cluster-autoscaler | Autoscale Benchmark |
| networking | iperf3 | pod-to-pod | Network Benchmark |
| storage | fio | csi-attach-detach | Storage Benchmark |
| api-server | kperf | kperf | API Server Benchmark |
| scheduler | clusterloader2 | kwok | Scheduler Benchmark |
| gpu | crud | k8s-crud-gpu | GPU Benchmark |

That's it! Keep it simple and let AI handle the complexity.