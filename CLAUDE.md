# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telescope is a framework for testing and comparing cloud products and services, focusing on evaluating Kubernetes scalability and performance across Azure, AWS, and GCP. The project enables data-driven decisions for multi-cloud strategies through comprehensive benchmarking.

## Architecture

The framework consists of three main components:

1. **Terraform Modules** (`modules/terraform/`) - Cloud infrastructure provisioning
2. **Python Test Modules** (`modules/python/`) - Test execution and tooling integration
3. **Pipeline Definitions** (`pipelines/`, `jobs/`, `steps/`) - CI/CD workflows

### Key Directories

- `modules/terraform/` - Infrastructure as Code organized by cloud provider (aws/, azure/, gcp/)
- `modules/python/` - Python libraries for test execution, client interactions, and data processing
- `scenarios/` - Test scenario configurations with Terraform variables and test inputs
- `pipelines/` - Azure DevOps pipeline definitions for different benchmark categories
- `steps/` - Reusable pipeline step templates
- `jobs/` - Job templates for competitive testing workflows

## Development Commands

### Python Development

```bash
# Navigate to Python modules directory
cd modules/python

# Install dependencies
pip install -r requirements.txt

# Run tests with coverage (minimum 70% required)
pytest --cov=. --cov-report=term-missing --cov-fail-under=70

# Run specific test module
pytest tests/clients/test_aks_client.py -v

# Run linting
pylint **/*.py

# Run specific test categories
pytest tests/clients/ -v  # Client tests
pytest tests/crud/ -v     # CRUD operation tests
pytest tests/iperf3/ -v   # Network performance tests
```

### Terraform Development

```bash
# Navigate to Terraform modules directory
cd modules/terraform

# Format and validate
terraform fmt -check -recursive
terraform validate

# Run tests
terraform test

# Run specific test
terraform test -filter=test_eks_auto_mode.tftest.hcl

# Provider-specific operations
# AWS
terraform plan -var-file="scenarios/aws.tfvars"

# Azure
terraform plan -var-file="scenarios/azure.tfvars"

# GCP
terraform plan -var-file="scenarios/gcp.tfvars"
```

## Test Framework Architecture

### Python Testing
- **Framework**: pytest with unittest base classes
- **Coverage**: 70% minimum requirement enforced in CI
- **Mocking**: Extensive use of unittest.mock for external dependencies
- **Test Data**: Realistic fixtures in `tests/mock_data/` from actual API responses
- **Kubernetes Testing**: KWOK (Kubernetes WithOut Kubelet) for lightweight cluster simulation

### Terraform Testing
- **Native Testing**: `.tftest.hcl` files for module validation
- **Mock Providers**: `data.tfmock.hcl` for testing without real resources
- **Input Validation**: JSON schema validation for each cloud provider
- **Test Categories**: Auto mode, machine types, network configuration, CLI commands

## Key Patterns and Conventions

### Resource Management
- **Tagging Strategy**: All resources tagged with owner, scenario, run_id, creation_time, deletion_due_time
- **Garbage Collection**: Automatic cleanup based on deletion_due_time tags
- **Resource Accountability**: Owner tracking for cost and resource management

### Configuration Management
- **Role-Based Organization**: Resources organized by role (client, server, etc.)
- **Dynamic Configuration**: Extensive use of for_each and locals for dynamic resource creation
- **Input Validation**: Strong typing with object() and list() type constraints

### Test Execution Flow
1. **Provision Resources** - Create cloud infrastructure via Terraform
2. **Validate Resources** - Verify resource availability and configuration
3. **Execute Tests** - Run performance benchmarks using integrated tools
4. **Cleanup Resources** - Remove test infrastructure
5. **Publish Results** - Store results in data analytics pipeline

## Integrated Testing Tools

The framework integrates with these performance testing tools:
- **kperf** - Kubernetes performance testing
- **kwok** - Kubernetes simulation without kubelet
- **clusterloader2** - Kubernetes cluster performance testing
- **resource-consumer** - Resource utilization testing
- **iperf3** - Network performance testing
- **fio** - Storage I/O performance testing

## Cloud Provider Modules

### AWS (`modules/terraform/aws/`)
- **EKS Module**: Auto Mode support with custom NodeClass and NodePools
- **Scaling**: Cluster Autoscaler and Karpenter integration
- **Network**: VPC, subnets, security groups, routing

### Azure (`modules/terraform/azure/`)
- **AKS Module**: Both Terraform-native and CLI-based deployment
- **Network**: Multi-policy support (Azure, Cilium)
- **Auto-scaling**: Built-in cluster autoscaler profile configuration

### GCP (`modules/terraform/gcp/`)
- **GKE Module**: Basic cluster with node pool management
- **Network**: VPC and subnet integration

## Version Requirements
- **Terraform**: >=1.5.6
- **Python**: >=3.10
- **AWS Provider**: <= 6.2.0
- **Azure Provider**: <= 4.35.0