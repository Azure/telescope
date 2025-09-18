# AI Processing Guide

This guide provides AI systems with processing instructions for Telescope test scenario generation. **Refer to existing comprehensive documentation rather than duplicating content.**

## Quick Processing Steps

1. **Validate JSON** against [test-scenario-schema.json](test-scenario-schema.json)
2. **Process each scenario** in the variations array
3. **Use existing templates and mappings** from comprehensive docs
4. **Generate files** following established patterns

## Essential References

### Component to Tool Mapping
See comprehensive mappings in [Test Scenario Implementation Guide](../test-scenario-implementation-guide.md#implementation-approaches):
- **autoscaler** → clusterloader2 engine with multiple topology options (cluster-autoscaler, karpenter, cluster-automatic)
- **networking** → iperf3 engine with various topologies (pod-to-pod, service-churn, network-policy-scale, etc.)
- **storage** → fio engine (csi-attach-detach, k8s-os-disk topologies)
- **api-server** → kperf engine (kperf topology)
- **scheduler** → clusterloader2 engine (kwok topology)
- **gpu** → crud engine (k8s-crud-gpu topology)
- **cri** → clusterloader2 engine (various cri-* topologies)

### File Generation Templates
Use existing templates instead of recreating:
- **Pipeline Structure**: [docs/templates/pipeline.yml](../templates/pipeline.yml)
- **Terraform Config**: [docs/templates/azure.tfvars](../templates/azure.tfvars) and [docs/templates/aws.tfvars](../templates/aws.tfvars)
- **Implementation Patterns**: [Test Scenario Implementation Guide](../test-scenario-implementation-guide.md)

### Validation and Best Practices
Follow established guidelines:
- **Naming Conventions**: [Best Practices Guide](../best-practices.md#follow-naming-conventions)
- **Validation Rules**: [Best Practices Guide](../best-practices.md#testing-strategy)
- **Development Workflow**: [Contribute Guide](../contribute.md)

## AI Processing Logic

```python
def process_ai_prompt(prompt_data):
    """Process AI prompt using existing Telescope patterns"""
    
    # 1. Validate against schema
    validate_json_schema(prompt_data)
    
    # 2. For each variation, use established mappings
    for variation in prompt_data['variations']:
        component = prompt_data.get('component')
        
        # Use component mappings from implementation guide
        engine, topology_options = get_component_mapping(component)
        topology = select_topology(topology_options, variation.get('test_type'))
        
        # Generate using existing templates
        generate_files_from_templates(variation, engine, topology)
    
    # 3. Reference existing documentation for complex scenarios
    return "See test-scenario-implementation-guide.md for detailed examples"
```

## Key Principles

- **Don't duplicate existing comprehensive documentation**
- **Reference established patterns and templates**
- **Follow existing naming conventions and validation rules**
- **Use the wealth of examples in existing scenarios**

For detailed implementation examples, matrix configurations, terraform setups, and comprehensive guidance, AI systems should reference the existing documentation rather than relying on this simplified processing guide.