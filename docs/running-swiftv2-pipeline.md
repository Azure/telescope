# Running swiftv2 pipeline

Here is the pipeline [link](https://dev.azure.com/akstelescope/telescope/_build?definitionId=23&_a=summary).

## Pre-Requisites

1. For a given region, make sure the regional customer [RG + AKS + identities] exist. If not, run the regional customer setup script `swiftv2kubeobjects/runCustomerSetup.sh`. Further instructions on how to run the script are mentioned in the script file. This is a one time setup and the resources are preserved for 3 months.
2. For a given region, make sure the regional ACR exists with mirrored images. If not, run the regional ACR setup script `swiftv2kubeobjects/setup-regional-acr.sh`. This creates a dedicated ACR per region to avoid throttling on shared team ACR and mirrors required images.
3. For a given region + VM-SKU, Check if the subscription has quota for the scale target.

## Pipeline variables, branches and test matrix

- As of 11/11/2025, no pipeline variables need to be touched in ADO. All the variables are hardcoded in `pipelines/system/new-pipeline-test.yml`. For example, location, subscription, vm-sku, number of nics, etc.
- **Note:** Cluster cleanup behavior is controlled at the matrix level via `skip_cleanup` flags in each test entry, not via a global pipeline variable.
- This is the official branch - `feature/swiftv2GA/swiftv2scale`, and it has comprehensive test matrix. Not all of which needs to be run for a given objective.
- It is recomended to create a test branch and disable/comment out unnnecessary test cases.

## Disabling stages and removing test matrix entries

- If certain stages are not required for the perf run, in `pipelines/system/new-pipeline-test.yml` flip `condition` flag to `false`. At the moment both `burst` stages are set to false.
- Each stage has a matrix file here - `pipelines/system/matrices`, where different combinations of pods, nodes and pods-per-step are set. Comment out the matrix entries that are irrelevant for the enabled stages.

## Matrix configuration with reuse_cluster and skip_cleanup
. These flags provide fine-grained control over cluster creation and cleanup **at the individual test level** - there is no global cleanup variable.

- **`reuse_cluster`**: Whether to reuse an existing cluster (`true`) or create a new one (`false`)
- **`skip_cleanup`**: Whether to keep the cluster after tests complete (`true`) or delete it (`false`)

> ⚠️ Azure DevOps passes boolean variables to scripts as `True`/`False` strings. Normalize to lowercase before comparison in bash scripts.

### Typical pattern for gradual scale testing

- **First entry**: `reuse_cluster: false`, `skip_cleanup: true` - Creates a new cluster, keeps it
- **Middle entries**: `reuse_cluster: true`, `skip_cleanup: true` - Reuses existing cluster, keeps it
- **Last entry**: `reuse_cluster: true`, `skip_cleanup: false` - Reuses existing cluster, **cleans it up**

This pattern allows sequential test runs on the same cluster, saving time and resources by avoiding repeated cluster creation/deletion. Only the last test in the sequence performs cleanup
This pattern allows sequential test runs on the same cluster, saving time and resources by avoiding repeated cluster creation/deletion.

### Adding or removing matrix entries

When modifying the matrix, ensure the first and last entries have the appropriate flags:

```yaml
matrix:
  test_small:
    node_count: 10
    reuse_cluster: false  # Create new cluster
    skip_cleanup: true    # Keep it for next test
    # ... other params
  test_medium:
    node_count: 500
    reuse_cluster: true   # Reuse cluster
    skip_cleanup: true    # Keep it for next test
    # ... other params
  test_large:
    node_count: 1000
    reuse_cluster: true   # Reuse cluster
    skip_cleanup: false   # Clean up after completion
    # ... other params
```
### Running tests independently

To run tests independently (not reusing clusters), set `reuse_cluster: false` and `skip_cleanup: false` on all entries. Each test will create its own cluster and clean it up after completion.

### Emergency: Disable all cleanup

If you need to preserve clusters for debugging after a pipeline run, set `skip_cleanup: true` on all matrix entries. This overrides cleanup behavior for the entire pipeline run. Remember to manually delete clusters afterwards to avoid resource waste.

To run tests independently (not reusing clusters), set `reuse_cluster: false` and `skip_cleanup: false` on all entries.

### Cluster Creation and Reuse Logic

The pipeline uses the following logic for cluster lifecycle management:

1. **First job** (`reuse_cluster: false`):
   - Creates resource group
   - Runs `createclusterforping.sh` to create AKS cluster and initial nodepools (1 node each)
   - Runs `scale-cluster.sh` to scale nodepools to target size
   - Keeps cluster after test (`skip_cleanup: true`)

2. **Subsequent jobs** (`reuse_cluster: true`):
   - Reuses existing resource group (via `BASE_RUN_ID`)
   - **Skips** `createclusterforping.sh` (cluster already exists)
   - Runs `scale-cluster.sh` to scale existing nodepools to new target size
   - Keeps or cleans up cluster based on `skip_cleanup` flag

This design avoids redundant cluster creation attempts and consolidates all nodepool scaling logic in `scale-cluster.sh`.

### Result Storage and Run IDs

Each matrix job generates a unique `RUN_ID` (BASE_RUN_ID + job suffix) used for:
- Blob storage filenames: `$(RUN_ID).json`
- Individual job tracking and test result isolation

When `reuse_cluster: true`, jobs use `BASE_RUN_ID` for:
- **Azure cluster discovery**: Finding existing cluster via `run_id` tag
- Resource group name (shared across all matrix jobs)
- Azure resource tagging
- Correlating which jobs ran on the same cluster

**Results DO NOT overwrite** because each job uploads to its own unique `RUN_ID` filename. The telescope metadata now includes both `run_id` (unique per job) and `base_run_id` (shared across matrix jobs) to enable correlation in Kusto queries.

**How cluster discovery works:**
1. **First job** creates cluster with tag: `run_id=<BASE_RUN_ID>`
2. **Subsequent jobs** check `reuse_cluster` flag and use `BASE_RUN_ID` to query Azure:
   ```bash
   reuse_cluster="$(echo "${REUSE_CLUSTER:-false}" | tr '[:upper:]' '[:lower:]')"
   if [ "$reuse_cluster" = "true" ]; then
     CLUSTER_RUN_ID="$BASE_RUN_ID"
   else
     CLUSTER_RUN_ID="$RUN_ID"
   fi
   az resource list ... --query "[?(tags.run_id == '$CLUSTER_RUN_ID' && tags.role == 'slo')]"
   ```
3. This allows `update-kubeconfig.yml` and `scale-cluster.sh` to find the shared cluster
4. Each job keeps unique `RUN_ID` for result uploads (prevents overwrites)

## Kusto

cluster('telescopedata.eastus.kusto.windows.net').database('perf_eval')

```KQL
swiftv2_cluster_churn_feature_swiftv2scale
| where timestamp > ago(1d)
```
