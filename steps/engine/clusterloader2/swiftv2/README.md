# AKS Nodepool Scaling Scripts

Simplified scripts for scaling AKS nodepools and handling VM failures.

## Files

### Simplified Scripts (Recommended)

- **`scale-cluster-simple.sh`** - Streamlined scaling with basic VM repair
- **`vm-status-repair.sh`** - Dedicated VM status checking and repair tool
- **`scale-cluster.yml`** - Complete scaling template with integrated VM repair

### Shared Utilities

- **`aks-utils.sh`** - Common functions for cluster management and logging

### Legacy Scripts

- **`scale-cluster.sh`** - Original complex scaling script (kept for reference)
- **`vm-recovery.sh`** - Original VM recovery script (kept for reference)

## Usage

### Basic Scaling (Includes VM Repair)

The scaling template automatically handles VM repair as part of the scaling process:

```yaml
- template: steps/engine/clusterloader2/swiftv2/scale-cluster.yml
  parameters:
    region: "eastus2euap"
    role: "slo"
    nodes_per_nodepool: "500"
    enable_autoscale: "false"
```

This single step will:

1. Scale the nodepool to the target size
2. Wait 60 seconds for stabilization
3. Check VM status and list any failed VMs  
4. Automatically repair (reimage) any failed VMs

### Manual VM Troubleshooting (Optional)

For independent VM troubleshooting outside of scaling operations, you can run the script directly:

```bash
# Set environment variables
export REGION="eastus2euap"
export ROLE="slo"
export RUN_ID="your-run-id"

# Check VM status only
./vm-status-repair.sh status

# Repair failed VMs only
./vm-status-repair.sh repair

# Status and repair combined
./vm-status-repair.sh both
```

## Environment Variables

All scripts require:

- `REGION` - Azure region (e.g., "eastus2euap")
- `ROLE` - Resource role tag (e.g., "slo")
- `NODES_PER_NODEPOOL` - Target node count (for scaling operations)
- `RUN_ID` - Run identifier for resource filtering

## Key Improvements

The simplified scripts address production issues where complex retry logic caused operations to hang:

- **20-minute timeout** instead of complex retry loops
- **Clear VM status reporting** with detailed failure information
- **Separate VM repair tool** for troubleshooting
- **No background monitoring** to prevent hanging operations
- **Simple error handling** with basic retry only where needed

## Troubleshooting

### When Operations Get Stuck

1. Check logs for timeout messages
2. Use the VM status tool to identify failed VMs:

   ```bash
   # Set environment variables first
   export REGION="eastus2euap"
   export ROLE="slo"
   export RUN_ID="your-run-id"
   
   # Check VM status
   ./vm-status-repair.sh status
   ```

3. Run the repair tool to fix failed instances:

   ```bash
   ./vm-status-repair.sh repair
   ```

### Common Issues

- **Scale timeout (20 minutes)** - Usually indicates Azure infrastructure issues
- **Failed VMs after scaling** - Use repair tool to reimage failed instances
- **Nodes not joining cluster** - Check VM status and Kubernetes node conditions
