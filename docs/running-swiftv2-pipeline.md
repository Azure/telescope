# Running swiftv2 pipeline

Here is the pipeline [link](https://dev.azure.com/akstelescope/telescope/_build?definitionId=23&_a=summary).

## Pre-Requisites

1. For a given region, make sure the regional customer [RG + AKS + ACR] exist. If not, run the regional customer setup script `swiftv2kubeobjects/runCustomerSetup.sh`. Further instructions on how to run the script are mentioned in the script file. This is a one time setup and the resources are preserved for 3 months.
2. For a given region + VM-SKU, Check if the subscription has quota for the scale target.

## Pipeline variables, branches and test matrix

- As of 11/11/2025, no pipeline variables need to be touched in ADO. All the variables are hardcoded in `pipelines/system/new-pipeline-test.yml`. For example, location, subscription, vm-sku, number of nics, CLEANUP_RESOURCES etc.
- This is the official branch - `feature/swiftv2GA/swiftv2scale`, and it has comprehensive test matrix. Not all of which needs to be run for a given objective.
- It is recomended to create a test branch and disable/comment out unnnecessary test cases.

## Disabling stages and removing test matrix entries

- If certain stages are not required for the perf run, in `pipelines/system/new-pipeline-test.yml` flip `condition` flag to `false`. At the moment both `burst` stages are set to false.
- Each stage has a matrix file here - `pipelines/system/matrices`, where different combinations of pods, nodes and pods-per-step are set. Comment out the matrix entries that are irrelevant for the enabled stages.

## Kusto

cluster('telescopedata.eastus.kusto.windows.net').database('perf_eval')

```KQL
swiftv2_cluster_churn_feature_swiftv2scale
| where timestamp > ago(1d)
```
