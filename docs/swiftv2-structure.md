# Complete Structure Diagram: new-pipeline-test.yml Dependencies

This document provides a comprehensive overview of all files and dependencies referenced from `pipelines/system/new-pipeline-test.yml`.

## Pipeline Overview

The `new-pipeline-test.yml` pipeline orchestrates comprehensive performance testing for SwiftV2 cluster churn scenarios with both dynamic and static resource configurations, using ClusterLoader2 as the testing engine on Azure AKS clusters.

## Dependency Structure

```text
pipelines/system/new-pipeline-test.yml (Main Pipeline)
├── Variables:
│   ├── SCENARIO_TYPE: perf-eval
│   ├── SCENARIO_NAME: swiftv2-cluster-churn-feature
│   ├── OWNER: aks
│   ├── BASE_RUN_ID: timestamp-based identifier for shared identification across stages
│   └── Test Configuration Variables (cpu_per_node, max_pods, etc.)
│
├── Stage 1: dynamicres_gradual
│   └── Template: pipelines/system/matrices/swiftv2-dynamicres-gradual-matrix.yml
│       ├── Matrix Parameters (15 configurations):
│       │   ├── pps=20_nodes=100/200/500/750/1000
│       │   ├── pps=50_nodes=100/200/500/750/1000  
│       │   └── pps=100_nodes=200/500/750/1000
│       ├── References: cl2_config_file: swiftv2_deployment_dynamicres_scale_config.yaml
│       └── Base Run ID: $(BASE_RUN_ID) (each job gets unique 5-char suffix from System.JobId)
│
├── Stage 2: dynamicres_burst
│   └── Template: pipelines/system/matrices/swiftv2-dynamicres-burst-matrix.yml
│       ├── Matrix Parameters (7 configurations):
│       │   └── nodes=20/50/100/200/500/750/1000
│       ├── References: cl2_config_file: swiftv2_deployment_dynamicres_scale_config.yaml
│       └── Base Run ID: $(BASE_RUN_ID) (each job gets unique 5-char suffix from System.JobId)
│
├── Stage 3: staticres_gradual
│   └── Template: pipelines/system/matrices/swiftv2-staticres-gradual-matrix.yml
│       ├── References: cl2_config_file: swiftv2_deployment_staticres_scale_config.yaml
│       └── Base Run ID: $(BASE_RUN_ID) (each job gets unique 5-char suffix from System.JobId)
│
├── Stage 4: staticres_burst
│   └── Template: pipelines/system/matrices/swiftv2-staticres-burst-matrix.yml
│       ├── References: cl2_config_file: swiftv2_deployment_staticres_scale_config.yaml
│       └── Base Run ID: $(BASE_RUN_ID) (each job gets unique 5-char suffix from System.JobId)
│
└── All Matrix Templates Reference: jobs/competitive-test.yml
    ├── Parameters: cloud, regions, engine, topology, etc.
    ├── Strategy: Matrix execution with max_parallel=1
    └── Pipeline Steps:
        │
        ├── 1. Setup Tests
        │   └── Template: steps/setup-tests.yml
        │       ├── Set Run ID (custom RUN_ID parameter or auto-generated timestamp-based ID: 10-char base + separator + 5-char unique suffix from System.JobId)
        │       ├── Configure credentials and authentication
        │       ├── Setup test modules directory structure
        │       ├── SSH key setup (conditional: ssh_key_enabled=true)
        │       │   └── steps/ssh/setup-key.yml
        │       └── Cloud-specific login (conditional: credential_type)
        │           └── steps/cloud/azure/login.yml
        │
        ├── 2. Provision Resources  
        │   └── Template: steps/provision-resources.yml
        │       ├── Terraform Setup Phase:
        │       │   ├── steps/terraform/set-working-directory.yml → modules/terraform/azure/
        │       │   ├── steps/terraform/set-input-file.yml → scenarios/.../terraform-inputs/azure.tfvars
        │       │   ├── steps/terraform/set-user-data-path.yml
        │       │   └── steps/terraform/set-input-variables-azure.yml (run_id, region, aks configs)
        │       ├── Resource Group Creation:
        │       │   ├── Extract deletion_delay and owner from terraform input
        │       │   └── Create Azure RG with tags (run_id, scenario, owner, deletion_due_time)
        │       ├── Terraform Execution:
        │       │   ├── steps/terraform/run-command.yml (version)
        │       │   ├── steps/terraform/run-command.yml (init)
        │       │   └── steps/terraform/run-command.yml (apply)
        │       │       └── Provisions: modules/terraform/azure/{main.tf,network/,aks/,aks-cli/,public-ip/}
        │       ├── SwiftV2 Customer Resources (Conditional: CREATE_CUSTOMER_RESOURCES=true):
        │       │   └── swiftv2kubeobjects/runCustomerSetup.sh
        │       └── SwiftV2 PING Cluster (Conditional: CREATESWIFTV2PING=true):
        │           └── swiftv2kubeobjects/createclusterforping.sh
        │
        ├── 3. Validate Resources
        │   └── Template: steps/validate-resources.yml
        │       ├── Validate OWNER variable (condition: SKIP_RESOURCE_MANAGEMENT=true)
        │       └── Topology-specific: steps/topology/swiftv2-ds-churn/validate-resources.yml
        │           ├── steps/cloud/azure/update-kubeconfig.yml (role: slo)
        │           ├── steps/engine/clusterloader2/swiftv2/scale-cluster.yml
        │           │   ├── Scale cluster to NODE_COUNT nodes
        │           │   └── Set enable_autoscale=false
        │           └── steps/engine/clusterloader2/swiftv2/validate.yml
        │               └── Validation timeout: 10 minutes
        │
        ├── 4. Execute Tests
        │   └── Template: steps/execute-tests.yml
        │       └── Topology-specific: steps/topology/swiftv2-ds-churn/execute-clusterloader2.yml
        │           └── steps/engine/clusterloader2/slo/execute.yml
        │               ├── Set SLO_START_TIME timestamp
        │               ├── Python execution: modules/python/clusterloader2/slo/slo.py
        │               │   ├── configure: CPU_PER_NODE, NODE_COUNT, NODE_PER_STEP, MAX_PODS, etc.
        │               │   └── execute: CL2_IMAGE, CL2_CONFIG_DIR, CL2_REPORT_DIR, CL2_CONFIG_FILE
        │               ├── ClusterLoader2 Container: ghcr.io/azure/clusterloader2:v20250311
        │               └── Config Files: modules/python/clusterloader2/slo/config/
        │                   ├── swiftv2_deployment_dynamicres_scale_config.yaml
        │                   ├── swiftv2_deployment_staticres_scale_config.yaml
        │                   └── swiftv2_deployment_template.yaml
        │
        ├── 5. Publish Results
        │   └── Template: steps/publish-results.yml
        │       ├── steps/topology/swiftv2-ds-churn/collect-clusterloader2.yml
        │       │   ├── steps/engine/clusterloader2/slo/collect.yml
        │       │   └── Set unique Run ID for publishing
        │       └── steps/collect-telescope-metadata.yml
        │           ├── Collect cloud info and metadata
        │           ├── Generate telescope metadata JSON
        │           ├── steps/cloud/azure/collect-cloud-info.yml
        │           ├── steps/collect-terraform-operation-metadata.yml
        │           └── steps/cloud/azure/upload-storage-account.yml (conditional: credential_type)
        │
        └── 6. Cleanup Resources
            └── Template: steps/cleanup-resources.yml
                ├── steps/terraform/run-command.yml (destroy)
                │   ├── Terraform workspace cleanup per region
                │   └── Resource deletion with retry logic
                ├── Subnetdelegator cleanup (conditional: SwiftV2 resources)
                └── Error handling and retry mechanisms (5 attempts)
```

## Key Dependencies Summary

### Core Pipeline Files

- `pipelines/system/new-pipeline-test.yml` (Entry point)
- `jobs/competitive-test.yml` (Main job template)

### Matrix Configuration Files

- `pipelines/system/matrices/swiftv2-dynamicres-gradual-matrix.yml`
- `pipelines/system/matrices/swiftv2-dynamicres-burst-matrix.yml`  
- `pipelines/system/matrices/swiftv2-staticres-gradual-matrix.yml`
- `pipelines/system/matrices/swiftv2-staticres-burst-matrix.yml`

### Step Templates

- `steps/setup-tests.yml` - Initialize test environment and credentials
- `steps/provision-resources.yml` - Create infrastructure using Terraform
- `steps/validate-resources.yml` - Verify resources are ready for testing
- `steps/execute-tests.yml` - Run performance benchmarks
- `steps/publish-results.yml` - Collect and publish test results
- `steps/cleanup-resources.yml` - Clean up infrastructure resources

### Topology-Specific Files

- `steps/topology/swiftv2-ds-churn/validate-resources.yml`
- `steps/topology/swiftv2-ds-churn/execute-clusterloader2.yml`
- `steps/topology/swiftv2-ds-churn/collect-clusterloader2.yml`

### Engine-Specific Files

- `steps/engine/clusterloader2/slo/execute.yml`
- `steps/engine/clusterloader2/slo/collect.yml`
- `steps/engine/clusterloader2/swiftv2/scale-cluster.yml`
- `steps/engine/clusterloader2/swiftv2/validate.yml`

### Configuration and Scripts

- `modules/python/clusterloader2/slo/slo.py` (Main test execution script)
- `modules/python/clusterloader2/slo/config/swiftv2_deployment_dynamicres_scale_config.yaml`
- `modules/python/clusterloader2/slo/config/swiftv2_deployment_staticres_scale_config.yaml`
- `scenarios/perf-eval/swiftv2-cluster-churn-feature/terraform-inputs/azure.tfvars`

### SwiftV2 Infrastructure Scripts

- `swiftv2kubeobjects/runCustomerSetup.sh` (Customer resources and ping-target cluster setup)
- `swiftv2kubeobjects/createclusterforping.sh` (Large cluster with overlay networking setup)
- `swiftv2kubeobjects/nginx-deployment.yaml` (Nginx pod deployment for ping target - used by runCustomerSetup.sh)
- `swiftv2kubeobjects/pn.yaml` (Pod network configuration - used by createclusterforping.sh)

### Infrastructure Components

- `modules/terraform/azure/main.tf` (Main terraform configuration with locals, AKS configs)
- `modules/terraform/azure/network/` (Virtual networks, subnets, NAT gateways)
- `modules/terraform/azure/aks/` (AKS cluster terraform modules)
- `modules/terraform/azure/aks-cli/` (CLI-based AKS operations and configurations)
- `modules/terraform/azure/public-ip/` (Public IP address management)
- `steps/cloud/azure/update-kubeconfig.yml` (Kubeconfig setup)
- `steps/cloud/azure/login.yml` (Azure authentication)
- `steps/cloud/azure/collect-cloud-info.yml` (Cloud metadata collection)
- `steps/cloud/azure/upload-storage-account.yml` (Storage account operations)
- `steps/terraform/set-working-directory.yml` (Terraform workspace setup)
- `steps/terraform/set-input-file.yml` (Terraform input file mapping)
- `steps/terraform/set-input-variables-azure.yml` (Azure-specific terraform variables)
- `steps/terraform/set-user-data-path.yml` (User data path configuration)
- `steps/terraform/run-command.yml` (Terraform command execution wrapper)

## Test Configurations

### Pipeline Variables

- **SCENARIO_TYPE**: `perf-eval`
- **SCENARIO_NAME**: `swiftv2-cluster-churn-feature`
- **OWNER**: `aks`
- **cpu_per_node**: 4
- **max_pods**: 1
- **repeats**: 1
- **node_label**: `"slo=true"`
- **cilium_enabled**: False
- **scrape_containerd**: False
- **service_test**: False
- **ds_test**: True

### Test Stages

1. **Dynamic Gradual**: Tests gradual scaling with dynamic resource allocation (15 matrix configurations)
2. **Dynamic Burst**: Tests burst scaling with dynamic resource allocation (7 matrix configurations)
3. **Static Gradual**: Tests gradual scaling with static resource allocation
4. **Static Burst**: Tests burst scaling with static resource allocation

### Matrix Scale Configurations

- **Node Counts**: 20, 50, 100, 200, 500, 750, 1000
- **Pods Per Step**: 20, 50, 100 (for gradual), or all at once (for burst)
- **Timeouts**: 30m to 240m depending on scale

## Runtime Configuration

- **Cloud Provider**: Azure (AKS)
- **Engine**: ClusterLoader2
- **Container Image**: `ghcr.io/azure/clusterloader2:v20250311`
- **Topology**: `swiftv2-ds-churn`
- **Max Parallel Jobs**: 1
- **Timeout**: 2160 minutes (36 hours)
- **Credential Type**: Service Connection
- **SSH Key**: Disabled

## Purpose

This pipeline is designed to benchmark Kubernetes performance for SwiftV2 cluster churn scenarios across different scaling patterns (gradual vs burst) and resource allocation strategies (dynamic vs static) on Azure AKS clusters.

## Run ID Generation

The Run ID is a unique identifier used throughout the pipeline to track and organize resources, test results, and metadata for each pipeline execution. The SwiftV2 pipeline uses a shared base Run ID across all stages with job-specific unique suffixes to ensure every job has a completely unique identifier.

### Generation Process

The Run ID generation follows a two-tier approach:

#### 1. Base Run ID Generation (Pipeline Level)

At the pipeline level (`new-pipeline-test.yml`), a base Run ID is generated:

- **Base ID**: A timestamp-based identifier using Azure DevOps' `$(Date:MMddHHmmss)` format
- **Format**: `$(BASE_RUN_ID)` - 10 characters representing MonthDayHourMinuteSecond (e.g., `0722143045`)
- **Example**: For July 22 at 14:30:45, the base Run ID would be `0722143045`

#### 2. Job-Specific Unique Suffix (Job Level)

Each job in every stage matrix gets a unique 5-character suffix with separator:

- **Suffix Generation**: Generated in `jobs/competitive-test.yml` using `$[format('{0}-{1}', parameters.base_run_id, substring(variables['System.JobId'], 0, 5))]`
- **Suffix Source**: First 5 characters of the Azure DevOps `System.JobId` predefined variable
- **Final Run ID**: `$(BASE_RUN_ID)-<5-char suffix>` (e.g., `0722143045-f67ab`)
- **Total Length**: Always 16 characters (10 base + 1 separator + 5 unique)

#### 3. Final Run ID Resolution (Job Level)

In `steps/setup-tests.yml`, the final Run ID is resolved:

1. **Custom Run ID**: If a `run_id` parameter is explicitly provided (which it is from the job template), that value is used directly
2. **Auto-Generated Fallback**: If no custom `run_id` is provided, a timestamp-based ID with suffix is generated (10 base + separator + 5 suffix)

### Benefits of This Approach

This design provides several advantages:

- **Complete Uniqueness**: Every job across all stages and matrices has a completely unique Run ID
- **Shared Base**: All jobs from the same pipeline run share a common 10-character timestamp base for correlation
- **Readable Format**: The separator makes it easy to distinguish the base ID from the unique suffix and the timestamp format is human-readable
- **Resource Isolation**: Each job has unique resources (Azure Resource Groups, etc.) preventing conflicts
- **Traceability**: Results and metadata can be correlated across the entire pipeline run using the shared timestamp base
- **Scalability**: Supports unlimited matrix configurations without ID collisions

### Usage Throughout Pipeline

The Run ID serves multiple purposes:

- **Resource Naming**: Used as the Azure Resource Group name for all cloud resources
- **Resource Tagging**: Applied as a tag to all Azure resources for identification and cleanup
- **Test Organization**: Used in directory structures for test results and artifacts
- **Cleanup Operations**: Enables targeted cleanup of resources associated with specific jobs
- **Metadata Collection**: Included in test metadata and results for traceability

### Example Run IDs

For a pipeline run with base Run ID `0722143045` (July 22, 14:30:45):

- **Dynamic Gradual Job 1**: `0722143045-f67ab` (unique 5-char suffix: `f67ab`)
- **Dynamic Gradual Job 2**: `0722143045-c89de` (unique 5-char suffix: `c89de`)  
- **Dynamic Burst Job 1**: `0722143045-1234f` (unique 5-char suffix: `1234f`)
- **Static Gradual Job 1**: `0722143045-abcde` (unique 5-char suffix: `abcde`)

Each Run ID is exactly 16 characters and globally unique within the pipeline execution.

The Run ID is set as an Azure DevOps pipeline variable (`RUN_ID`) and made available to all subsequent steps in the pipeline execution.
