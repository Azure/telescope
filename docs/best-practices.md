# Best Practices for Telescope Test Scenarios

This guide provides comprehensive best practices and guidelines for creating, modifying, and maintaining test scenarios in Telescope.

## Development Best Practices

### 1. **Start Small and Iterate**
- Begin with existing scenarios and modify parameters before creating new ones
- Test with minimal resources first (e.g., 2-3 nodes) before scaling up
- Use `new-pipeline-test.yml` for validation before final deployment
- Validate configurations locally using instructions in [verify.md](verify.md)

### 2. **Reuse and Extend Components**
- Check existing pipelines that match your requirements and reuse their components
- Leverage existing engines and topologies whenever possible
- Extend rather than recreate infrastructure modules
- Follow established patterns from similar scenarios
- Check existing scenarios for components that match your needs

### 3. **Follow Naming Conventions**

#### Scenario Names
- Use descriptive names under 30 characters
- Format: `<component>-<test-type>-<scale>` (e.g., `cluster-autoscaler`, `apiserver-vn100pod10k`)
- Use kebab-case (hyphens) for scenario folder names

#### File Names
- Terraform inputs: `<cloud>.tfvars`, `<cloud>-<variant>.tfvars`
- Test inputs: `<cloud>.json`, `<cloud>-<variant>.json`
- Pipeline files: `<scenario-name>.yml`
- For each Terraform variable file, include a corresponding test input JSON file for validation

#### Stage Names
- Format: `<cloud>_<region>_<description>` (e.g., `azure_eastus2_large_scale`)
- Use underscores for stage names
- Include scale/variant descriptors


### 4. **Testing Strategy**

#### Local Validation
- Validate terraform configurations with `terraform plan`
- Test Python modules locally before pipeline integration
- Use terraform test inputs for parameter validation
- Verify all required parameters are defined

#### Pipeline Testing
- Always test in `new-pipeline-test.yml` first
- Start with manual triggers before adding schedules
- Test matrix variations incrementally
- Validate all conditional logic

## Security and Compliance

### 1. **Credential Management**
- Use `service_connection` credential type by default
- Never hardcode secrets in terraform files
- Use variable groups for sensitive data when needed
- Enable SSH keys only when creating Virtual Machines

### 2. **Data Protection**
- Avoid storing sensitive data in test scenarios
- Use synthetic data for testing
- Clean up any temporary data after tests
- Follow organization data retention policies

## Code Quality Standards

### 1. **Documentation**
- Include clear descriptions in pipeline files
- Maintain README files for complex scenarios
- Document any special requirements or dependencies

### 2. **Code Structure**
```
scenarios/perf-eval/<scenario-name>/
├── README.md                    # Scenario documentation
├── terraform-inputs/
│   ├── azure.tfvars            # Cloud-specific configurations
│   ├── aws.tfvars
│   └── azure-variant.tfvars    # Variant configurations
└── terraform-test-inputs/
    ├── azure.json              # Test validation inputs
    └── aws.json
```

### 3. **Parameter Management**
- Use descriptive parameter names
- Provide default values where appropriate
- Group related parameters logically
- Document parameter dependencies

### 4. **Error Handling**
- Set appropriate timeout values for different operations
- Plan for common failure scenarios
- Implement retry logic for transient failures
- Provide clear error messages

## Pipeline Best Practices

### 1. **Scheduling Strategy**
- **Daily**: Critical functionality and regression tests
- **Weekly**: Comprehensive performance tests
- **Bi-weekly**: Large-scale and expensive tests
- **Monthly**: Full regression and compatibility suites

### 2. **Matrix Configuration**
- Use meaningful matrix names that describe the test variant
- Limit matrix size to prevent resource exhaustion
- Group related variations logically
- Document matrix parameter purposes

## Troubleshooting and Debugging

### 1. **Debugging Strategy**
- Enable detailed logging for complex scenarios
- Use incremental testing approach
- Isolate issues by testing components separately
- Document known issues and workarounds

### 2. **Common Issues**
- **Resource quota limits**: Check cloud provider quotas
- **Network connectivity**: Verify firewall and routing rules
- **Authentication failures**: Validate credentials and permissions
- **Timeout issues**: Adjust timeouts based on scale and complexity

### 3. **Logging and Monitoring**
- Implement comprehensive logging in custom engines
- Monitor resource usage during tests
- Collect performance metrics consistently

## Version Control and Collaboration

### 1. **Branch Strategy**
- Use feature branches for any type of change
- Regularly sync with the main branch
- Test thoroughly before merging to main
- Use descriptive commit messages

### 2. **Code Review Process**
It's recommended to split your PR into small ones if you have a big change. For example:
- 1 PR to add terraform setup
- 1 PR for python module
- 1 PR for engine, topology and final yaml file
After your PR with final yaml file is merged, a new pipeline will be created for you.

This guide should be referenced throughout the development lifecycle to ensure consistent, reliable, and maintainable test scenarios.