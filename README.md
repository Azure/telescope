# Telescope V2

Telescope V2 uses [KCL](https://kcl-lang.io/) to define Azure DevOps benchmark pipelines as code. You write your pipeline logic in `.k` files, generate YAML from them, and register the resulting pipeline in Azure DevOps.

## Prerequisites

### Install KCL

```bash
wget -q https://kcl-lang.io/script/install-cli.sh -O - | /bin/bash
```

Verify the installation:

```bash
kcl version
```

## Scenario 1: Write a Pipeline in Your Own Repo

Use this approach when you want to keep your pipeline definitions in a separate repository.

### 1. Initialize a KCL module

In your repo, create a directory for your pipeline and initialize a KCL module:

```bash
mkdir -p my-benchmark
cd my-benchmark
kcl mod init
```

This creates a `kcl.mod` file. Add the Telescope library and the Azure Pipelines schema as dependencies:

```bash
kcl mod add azure_pipelines --git https://github.com/Azure/kcl-azure-pipelines --tag 1.0.0
```

### 2. Write your pipeline

Create a `.k` file (e.g. `my-benchmark/pipeline.k`) and import the schemas you need. See the [Pipeline Example](#pipeline-example) section below.

## Scenario 2: Write a Pipeline in This Repo

Use this approach when you want to pushlish your benchmarks to the public.

### 1. Create a pipeline folder

Create a new directory under `kcl/`:

```bash
mkdir kcl/my-pipeline
```

The `kcl.mod` at `kcl/kcl.mod` already has the dependencies configured, so your new pipeline can immediately import from `lib`.

### 2. Write your pipeline

Create `kcl/my-pipeline/pipeline.k` and import the library schemas.

The `lib/` directory provides reusable steps you can compose into your pipeline:

| Category | Function | Description |
|----------|----------|-------------|
| **Common** | `common.SetRunId()` | Generate a unique run ID for the pipeline |
| | `common.InstallPythonDependencies()` | Install Python deps from `modules/python/requirements.txt` |
| | `common.InstallKcl()` | Install the KCL CLI |
| | `common.UploadResult(...)` | Upload result JSON to Azure Blob Storage |
| **Azure** | `azure.Login(...)` | Authenticate and set subscription/region |
| | `azure.AzCli(...)` | Run any Azure CLI script |
| | `azure.CreateResourceGroup(...)` | Create a resource group |
| | `azure.DeleteResourceGroup(...)` | Delete a resource group (runs on `always()`) |
| | `azure.CreateNodePool(...)` | Add a node pool to a cluster |
| | `azure.GetCredentials(...)` | Download kubeconfig for a cluster |
| | `azure.WaitForClusterSucceeded(...)` | Poll until cluster is provisioned |
| | `azure.WaitForNodePoolSucceeded(...)` | Poll until node pool is provisioned |
| **Kubernetes** | `k8s.CreateKwokNodes(...)` | Create simulated nodes with KWOK |
| | `k8s.RunClusterLoader2(...)` | Deploy and run ClusterLoader2 workload |
| | `k8s.PrintCl2PodLogs(...)` | Print logs from CL2 pods |
| **Utilities** | `util.formatResult(resultJson)` | Wrap results in the Telescope ADX schema |
| | `util.escapeStr(s)` | Escape backslashes and quotes for shell embedding |

For a complete working example, see [`kcl/example_pipeline/pipeline.k`](kcl/example_pipeline/pipeline.k).

## Generate Pipeline YAML

Once your `.k` file is ready, generate the Azure DevOps YAML with the `/generate_yaml` skill, defined in the `.claude` folder.

## Register the Pipeline in Azure DevOps

After generating the YAML, register it as an Azure DevOps pipeline using the Azure CLI. You can use the `/telescope-pipeline` skill in the `.claude` folder.

# Store Results in Your Own Kusto Tables

If you want the results automatically ingested into your own Azure Data Explorer (Kusto) tables for querying and dashboarding, you can use the `/telescope-infra-setup` skill in the `.claude` folder to provision the full ingestion pipeline in your Azure subscription.
