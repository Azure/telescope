# Running swiftv2 pipeline

Here is the pipeline [link](https://dev.azure.com/akstelescope/telescope/_build?definitionId=23&_a=summary).

## Pre-Requisites

1. For a given region, make sure the regional customer [RG + AKS + identities] exist. If not, run the regional customer setup script `swiftv2kubeobjects/runCustomerSetup.sh`. Further instructions on how to run the script are mentioned in the script file. This is a one time setup and the resources are preserved for 3 months.
2. For a given region, make sure the regional ACR exists with mirrored images. If not, run the regional ACR setup script `swiftv2kubeobjects/setup-regional-acr.sh`. This creates a dedicated ACR per region to avoid throttling on shared team ACR and mirrors required images.
3. For a given region + VM-SKU, check if the subscription has quota for the scale target.

## Pipeline variables, branches and test matrix

- All pipeline variables are hardcoded in `pipelines/system/new-pipeline-test.yml` (location, subscription, vm-sku, etc.)
- Set `CLEANUP: "false"` to preserve resources after pipeline completes (useful for debugging)
- Official branch: `feature/swiftv2GA/swiftv2scale`
- Recommended: Create a test branch and comment out unnecessary test cases

## Disabling stages and matrix entries

- To disable stages, set `condition: false` in `pipelines/system/new-pipeline-test.yml` (burst stages are disabled by default)
- Matrix files are in `pipelines/system/matrices/` - comment out entries that are not needed

## Pipeline Architecture

Each stage has:
1. **`generate_run_id` job**: Creates a unique `BASE_RUN_ID` with stage prefix (sg, dg, sb, db)
2. **Matrix jobs**: Run tests using the shared `BASE_RUN_ID` for resource group naming
3. **`cleanup` job**: Runs after all matrix jobs complete (controlled by `CLEANUP` variable)

### Run ID and Job Isolation

- **`BASE_RUN_ID`**: Shared across all jobs in a stage, used for resource group naming and cluster tagging
- **`RUN_ID`**: Unique per job (BASE_RUN_ID + job suffix), used for result storage
- **`CL2_JOB_INDEX`**: Derived from `System.JobId`, used to isolate CL2 resources (namespaces, deployments, PNIs) across parallel jobs

This ensures test results don't overwrite each other while sharing infrastructure.

### Cleanup Behavior

Cleanup runs at the end of each stage and:
1. Deletes swiftv2 workloads (deployments, pods)
2. Removes nodepools sequentially  
3. Deletes Azure resources (NAT gateways, NSGs, public IPs)
4. Destroys the resource group

To preserve resources for debugging, set `CLEANUP: "false"` in the pipeline variables.

## Kusto

cluster('telescopedata.eastus.kusto.windows.net').database('perf_eval')

```KQL
swiftv2_cluster_churn_feature_swiftv2scale
| where timestamp > ago(1d)
```
