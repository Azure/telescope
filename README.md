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

### Install Telescope skills
#### Checkout Telescope v2
```bash
cd <REPOSITORY BASE>
git clone https://github.com/Azure/telescope.git
cd telescope
git checkout -b v2 origin/v2
```

#### Create a new repo
```bash
cd <REPOSITORY BASE>
mkdir my-benchmark
cd my-benchmark
git init
```

#### Create symbolic link to skills 
```bash
mkdir .agent
ln -s <REPOSITORY BASE>/telescope/.agent/skills .agent/skills
```

## Scenario 1: Write a Pipeline in Your Own Repo

Use this approach when you want to keep your pipeline definitions in a separate repository.

### 1. Initialize a KCL module

In your repo, create a directory for your pipeline and initialize a KCL module:

```bash
kcl mod init
```

Add the Telescope library as dependencies:

```bash
kcl mod add telescope --git https://github.com/Azure/telescope --branch v2
```

### 2. Write your pipeline

Create a `.k` file (e.g. `my-benchmark/pipeline.k`) and import the schemas you need. See the [Example Pipeline](kcl/example_pipeline) for details.

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
| | `azure.DeleteResourceGroupAsync(...)` | Submit deletion asynchronously, then poll and recover from blocking VMSS upgrades |
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

### Resource-group deletion recovery

Use `DeleteResourceGroupAsync` as a single cleanup step: it submits deletion with
`--no-wait`, then polls until the group and its discovered AKS node resource
groups disappear. **Async describes the Azure request, not the pipeline step: the
step waits for cleanup to finish.** Each poll checks remaining VMSS resources and
cancels active (`RollingForward`) upgrades, including platform-initiated upgrades
on scale sets with a `Manual` upgrade policy. It waits for cancellation before
continuing. Associated node groups are eligible only when all their captured AKS
clusters are deleting or have disappeared. Clusters in `Failed` or any other
non-deleting state are excluded from node-group upgrade cancellation.
An ambiguous `NotFound` from the rolling-upgrade endpoint is treated as absence
only after a separate VMSS read confirms the scale set has disappeared.

The underlying [Python script](kcl/lib/steps/azure/resource_group.py) requires an
explicit `delete` subcommand (`python3 .../resource_group.py delete ...`).
There is no default action; omitting the subcommand is an argument error.

```python
azure.DeleteResourceGroupAsync(
    const.DEFAULT_SERVICE_CONNECTION,
    RESOURCE_GROUP,
    SUBSCRIPTION_ID,
    timeoutSeconds = 2700,
    pollIntervalSeconds = 30)
```

The overall `timeoutSeconds` defaults to 2700 and `pollIntervalSeconds` to 30.
Set the pipeline job timeout to leave enough time for cleanup and diagnostics.
The helper submits resource-group deletion once and attempts to unblock it by
cancelling active upgrades; it does not resubmit a failed deletion or directly
delete AKS-managed VMSS, NICs, or node resource groups. It does not query Activity
Log for deletion failures; if the groups remain, polling continues until timeout.
Unexpected API errors, unknown upgrade states, and timeout fail the step rather
than reporting cleanup success. An already absent target group is a no-op; node groups
cannot be rediscovered from an absent cluster, so start recovery before deleting it.

`DeleteResourceGroup` keeps its original blocking Azure CLI behavior. Recovery
requires no separate cancellation step or enable flag. Both steps default to
`condition = "always()"`.

`DeleteResourceGroupAsync` requires a Linux agent, Python 3.10+, Azure CLI, and a
Telescope checkout at `$(Build.SourcesDirectory)`; no additional Python packages
are needed. The service connection needs resource-group delete/read, AKS and
VMSS read and rolling-upgrade read/cancel permissions,
including access to associated node resource groups. The hyperscale
pod-scheduling pipeline uses this integrated cleanup step.

## Generate Pipeline YAML

Once your `.k` file is ready, generate the Azure DevOps YAML with the `/generate-yaml` skill, defined in the `.agent` folder.

## Register the Pipeline in Azure DevOps

After generating the YAML, register it as an Azure DevOps pipeline using the Azure CLI. You can use the `/telescope-pipeline` skill in the `.agent` folder.

## Split Large Pipeline YAML

Azure DevOps enforces a 2 MB limit on a single pipeline YAML file. If the generated YAML exceeds the limit, use `scripts/split_pipeline.py` to split it into smaller template files that reference each other.

The splitter walks the pipeline tree (`stages` → `jobs` → `steps`), finds the deepest oversized subtree, and greedily extracts items into sibling `*_N.yaml` files referenced via ADO template syntax (`$(Pipeline.Workspace)/s/<path>`).

```bash
python3 scripts/split_pipeline.py path/to/pipeline.yaml --repo-root .
```

Arguments:

| Flag | Description |
|------|-------------|
| `filepath` | Path to the pipeline YAML file to split (modified in place; new `*_N.yaml` files are written alongside it). |
| `--repo-root` | **Required.** Root of the repo. Template references are emitted as paths relative to this directory. |
| `--max-size` | Max file size in bytes. Defaults to `1048576` (1 MB). |
| `--max-files` | Max number of split files to produce. Defaults to `100`. |

The script raises an error (and cleans up any partial output) if the input is already under the limit or cannot be split further (e.g. a single step exceeds the limit).

# Store Results in Your Own Kusto Tables

If you want the results automatically ingested into your own Azure Data Explorer (Kusto) tables for querying and dashboarding, you can use the `/telescope-infra-setup` skill in the `.agent` folder to provision the full ingestion pipeline in your Azure subscription.
