# AKS Nodepool Scaling Scripts

A modular collection of scripts for scaling AKS nodepools with robust error handling and VM failure recovery.

## Overview

The original monolithic `scale-cluster.sh` script has been refactored into three focused, maintainable modules:

## File Structure

### 1. `aks-utils.sh` - Core Utilities Library
Contains common functions for AKS cluster management:

- **Logging Functions**: `log_info()`, `log_warning()`, `log_error()`
- **Cluster Discovery**: `find_aks_cluster()` - finds AKS clusters by region and role tags
- **Nodepool Management**: 
  - `get_user_nodepools()` - discovers user nodepools (excludes system/test pools)
  - `get_nodepool_count()` - retrieves current node count
- **Azure Resource Queries**:
  - `get_node_resource_group()` - gets node resource group for cluster
  - `get_vmss_name()` - finds VMSS name for nodepool

### 2. `vm-recovery.sh` - VM Failure Detection and Recovery
Handles VM failure scenarios and recovery operations:

- **VM Health Monitoring**: `check_failed_vms()` - detects failed VMs in nodepool VMSS
- **Recovery Operations**:
  - `reimage_failed_vms()` - attempts to reimage failed VM instances
  - `cleanup_failed_vms()` - removes persistent failed VMs
- **Status Reporting**: `show_vmss_status()` - displays VMSS instance status for debugging

### 3. `scale-cluster.sh` - Main Scaling Orchestration
The primary script that orchestrates the scaling process:

- **Scaling Operations**:
  - `scale_nodepool_with_timeout()` - scales individual nodepool with timeout protection
  - `scale_nodepool()` - orchestrates scaling with retry logic and VM recovery
- **Node Readiness Verification**:
  - `verify_node_readiness()` - ensures nodes are ready in Kubernetes
  - `diagnose_node_issues()` - diagnoses persistent readiness issues
  - `handle_readiness_timeout()` - handles timeout scenarios with diagnostics
- **Main Orchestration**: Environment validation, cluster discovery, and scaling coordination

## Usage

### Prerequisites
- Azure CLI (`az`) configured with appropriate permissions
- `kubectl` configured (handled automatically by the script)
- `jq` for JSON parsing
- Required environment variables set

### Environment Variables
The following environment variables must be set:

```bash
export REGION="eastus"                    # Azure region where AKS cluster is located
export ROLE="cluster"                     # Role tag for resource identification
export NODES_PER_NODEPOOL="20"          # Target node count per nodepool
export RUN_ID="benchmark-run-001"        # Run identifier tag for resource filtering
```

### Running the Script
```bash
./scale-cluster.sh
```

The script will:
1. Validate environment variables
2. Discover AKS cluster using tags
3. Identify user nodepools to be scaled
4. Scale each nodepool (with VM failure recovery if needed)
5. Verify all nodes are ready in Kubernetes

## Key Features

### 🔧 **Modular Design**
- Separated concerns into focused, reusable modules
- Clear function boundaries and responsibilities
- Easy to test and maintain individual components

### 🛡️ **Robust Error Handling**
- Timeout protection for all Azure operations (30-minute max per operation)
- Retry logic with exponential backoff
- Comprehensive error reporting and diagnostics

### ⚡ **VM Failure Recovery**
- Automatic detection of failed VM instances in VMSS
- Recovery strategies: reimage failed VMs, delete persistent failures
- Scale-down-then-scale-up approach for stuck VM scenarios

### 📊 **Enhanced Monitoring**
- Detailed progress logging with structured output
- Azure DevOps integration with warning/error annotations
- VMSS status reporting for troubleshooting
- Dynamic timeouts based on node count

### 🎯 **Smart Nodepool Selection**
- Filters out system nodepools (`System` mode)
- Excludes monitoring nodepools (`promnodepool`)
- Skips development/test nodepools (`devtest` in name)

## Architecture Benefits

### Before (Monolithic)
- Single 387-line file with mixed responsibilities
- Difficult to test individual components
- Hard to understand the flow and debug issues
- Duplicated utility functions

### After (Modular)
- Three focused files with clear responsibilities
- Reusable utility functions in separate library
- Self-documenting code with clear function names
- Easy to extend and maintain
- Better error isolation and handling

## Integration

This script is designed to integrate with the Telescope benchmarking framework:

- **Pipeline Integration**: Can be called from Azure DevOps pipelines
- **Logging Compatibility**: Uses ADO-compatible log formats
- **Tag-based Discovery**: Works with Telescope's resource tagging strategy
- **Environment Variable**: Compatible with existing pipeline variable patterns

## Troubleshooting

### Common Issues
1. **Missing Environment Variables**: Check that all required variables are set
2. **Azure Permission Issues**: Ensure service principal has Contributor access to AKS and VMSS resources
3. **Network Connectivity**: Verify connection to Azure APIs and Kubernetes cluster
4. **VM Provisioning Failures**: Check Azure resource quotas and regional capacity

### Debug Mode
The script runs with `-x` flag for detailed execution tracing. Monitor the logs for:
- Azure CLI command outputs
- VM failure detection results
- Scaling operation progress
- Node readiness status checks

## Future Enhancements

Potential improvements to consider:
- [ ] Parallel nodepool scaling for faster execution
- [ ] Configurable timeout values via environment variables
- [ ] Metrics collection and reporting integration
- [ ] Support for mixed nodepool sizes per cluster
- [ ] Integration with cluster autoscaler for intelligent scaling
