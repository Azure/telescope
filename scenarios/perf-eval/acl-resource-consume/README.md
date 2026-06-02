# ACL CRI Resource Consume

This scenario runs ACL AKS node performance validation through Telescope v1.

## Pipeline

Register this YAML in Azure DevOps:

```text
pipelines/perf-eval/CRI Benchmark/acl-resource-consume.yml
```

Queue it manually for validation runs.

## Azure DevOps Inputs

The pipeline environment must provide `AZURE_SERVICE_CONNECTION`, `AZURE_SUBSCRIPTION_ID`, and `AZURE_TELESCOPE_STORAGE_ACCOUNT_NAME`. The service connection identity needs Contributor on the subscription for temporary resource groups and Storage Blob Data Contributor on the result storage account. Ensure the storage account has a `perf-eval` container, because Telescope uploads results to a container named after `SCENARIO_TYPE`.

## ACL OS Selector

The current Terraform input uses the AKS CLI path and sets `--os-sku AzureContainerLinux` for the cluster and ACL node pools.