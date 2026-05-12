# ACL CRI Resource Consume

This scenario is the first Telescope v1 harness for ACL AKS node performance validation. It reuses the existing `cri-resource-consume` topology and ClusterLoader2 runner, then publishes the raw ClusterLoader2 JUnit file into Azure DevOps test results.

## Pipeline

Register this YAML in Azure DevOps:

```text
pipelines/perf-eval/CRI Benchmark/acl-resource-consume.yml
```

Queue it manually for the first validation run.

## Azure DevOps Inputs

The pipeline follows the existing Telescope v1 style and keeps defaults as YAML variables rather than queue-time parameters:

| Variable | Default | Purpose |
|---|---|---|
| `ACL_IMAGE_SUBSCRIPTION_ID` | `b3e01d89-bd55-414f-bbb4-cdfeb2628caa` | Subscription containing the ACL Beta BYOI image. |
| `ACL_IMAGE_RESOURCE_GROUP` | `ACL-IMAGES` | Resource group containing the ACL Beta BYOI image. |
| `ACL_IMAGE_GALLERY` | `acl` | Gallery containing the ACL Beta BYOI image. |
| `ACL_IMAGE_NAME` | `acl-aks` | ACL image definition. Use `acl-aks-arm64` for ARM64. |
| `ACL_IMAGE_VERSION` | `1.1775601122.6691` | ACL image version to test. |

The New Pipeline Test environment must provide `AZURE_SERVICE_CONNECTION`, `AZURE_SUBSCRIPTION_ID`, and `AZURE_TELESCOPE_STORAGE_ACCOUNT_NAME`. The service connection identity needs Contributor on the subscription for temporary resource groups and Storage Blob Data Contributor on the result storage account. Ensure the storage account has a `perf-eval` container, because Telescope uploads results to a container named after `SCENARIO_TYPE`.

For temporary testing, override these as Azure DevOps variables when queuing the New Pipeline Test instead of changing the scenario file.

## ACL OS Selector And Image

The current Terraform input uses the AKS CLI path and sets `--os-sku AzureContainerLinux`. For ACL Beta BYOI, the pipeline composes `AKS_CLI_CUSTOM_HEADERS` from the ACL image variables and Telescope passes those headers into both `az aks create` and `az aks nodepool add`.

The fields prepared for that are in `terraform-inputs/azure.tfvars`:

```hcl
use_aks_preview_cli_extension = true
aks_custom_headers            = []
optional_parameters           = [...]
```

For ACL Alpha, queue the run with `AKS_CLI_CUSTOM_HEADERS` set to an empty value and use an AKS/RP region where `--os-sku AzureContainerLinux` is already available. With empty custom headers, Telescope passes `aks_custom_headers = []` to Terraform and the AKS CLI module does not emit `--aks-custom-headers`.

For ACL Beta ARM64, queue with an ARM64-capable region/SKU setup and override:

```text
ACL_IMAGE_NAME=acl-aks-arm64
ACL_IMAGE_VERSION=1.1776195556.10516
```

## First Run

The initial matrix intentionally runs only `n10-p300-memory`. After it creates an AKS cluster, runs ClusterLoader2, publishes JUnit, uploads results, and cleans up reliably, add the higher pressure cases from `azurelinux-resource-consume`.