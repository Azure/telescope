# Setup Module

This folder contains Terraform modules for creating new infrastructure setup, pipelines, Data Connections, and Tables for Kusto databases.

## Quick Start
1. Setup test framework by running commands as follows:
```bash
az login
aws configure

export AZDO_PERSONAL_ACCESS_TOKEN=<Azure DevOps Personal Access Token>
export AZDO_ORG_SERVICE_URL=https://dev.azure.com/<Azure DevOps Org Name>
export AZDO_GITHUB_SERVICE_CONNECTION_PAT=<GitHub Personal Access Token>
export TF_VAR_resource_group_name=<Resource Group Name>
export TF_VAR_storage_account_name=<Storage Account Name>
export TF_VAR_kusto_cluster_name=<Kusto Cluster Name>

make all
```

2. Run pipeline or wait for scheduled run on Azure DevOps
![pipeline](../../../docs/imgs/pipeline.jpeg)

3. Import [dashboard](../../..//dashboards/example.json) and check test results on Azure Data Explorer
![results](../../..//docs/imgs/results.jpeg)

## Modules
- [Infrastructure Setup](./infrastructure/main.tf)
- [Pipeline Setup](./pipeline/main.tf)
- [Table and Data Connection Setup](./table-data-connections)
- [Data Ingestion](#Data-Ingestion)

## Prerequisites
For all modules, you need to have the following prerequisites:
- Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
- Install [Azure CLI - 2.57.0](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
- Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)
- Install [AWS CLI - 2.15.19](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html)

### Steps to setup the prerequisites
- Generate a PAT token from Azure DevOps and store it in the environment variable `AZDO_PERSONAL_ACCESS_TOKEN`
- Permissions for PAT token:
  - Agent Pools (Read & Manage)
  - Build (Read & Execute)
  - Pipeline Resources (Use & Manage)
  - Service Connections (Read, Query & Manage)
  - Variable Groups (Read, Create & Manage)
  - Code (Read) - For pipeline setup, if the pipeline is in ADO repository

- Set the Azure DevOps organization service URL in the environment variable `AZDO_ORG_SERVICE_URL`
```bash
export AZDO_PERSONAL_ACCESS_TOKEN=<Azure DevOps Personal Access Token>
export AZDO_ORG_SERVICE_URL=https://dev.azure.com/<Azure DevOps Org Name>
export AZDO_GITHUB_SERVICE_CONNECTION_PAT=<GitHub Personal Access Token>
export TF_VAR_resource_group_name=<Resource Group Name>
export TF_VAR_storage_account_name=<Storage Account Name>
export TF_VAR_kusto_cluster_name=<Kusto Cluster Name>
```

## Infrastructure Setup
This module creates the following resources:
- Resource Group
- Service Principal and grant owner access to the subscription
- Azure Data Explorer Cluster
- Azure Data Explorer Database
- Azure Event Hub Namespace
- Azure Storage Account
- Azure Storage Container
- Azure Service Connection
- AWS Service Connection
- AWS IAM User and Access Key's
- Azure DevOps Variable Groups

All the resources are created based on the input tfvars file which is located here [setup.tfvars](./infrastructure/setup.tfvars)

### Usage
Run make command to create the infrastructure setup after setting up the prerequisites
```bash
make infrastructure_setup
```

## Pipeline Setup
This module creates a new pipeline in Azure DevOps based on the input tfvars file located here [pipeline.tfvars](./pipeline/pipeline.tfvars)

Operations supported by this module:
- Create a new pipeline from the existing YAML file in Azure DevOps or GitHub
- Create new variables for the pipeline
- Attach/Link existing Variable Groups to the pipeline
- Authroize the pipeline to use the existing Service Connections listed in the tfvars file
- Authorize the pipeline to use the agent pool

### Usage
Run make command to create the pipeline setup after setting up the prerequisites
```bash
make pipeline_setup
```

## Table and Data Connection Setup
This module creates the following resources:
- Azure Data Explorer Table and Data Connection
- Event Hub Namespace, Event Hub  and Event Hub Subscription
- Consumer Group for Event Hub

All the resources are created based on the input tfvars file which is located here [table-data-connections.tfvars](./table-data-connections/table-data-connections.tfvars)

### Usage
Run make command to create the table and data connection setup after setting up the prerequisites
```bash
make table_dataconnection_setup
```

## Data-Ingestion
This module will ingest data into the Azure Data Explorer Table created in the previous step. The data is ingested from azure storage account blob container to the Azure Data Explorer Table.

## Prerequisites
- Kusto LightIngest tool - [Download](https://github.com/Azure/Kusto-Lightingest/releases/tag/12.1.2)
- Azure Data Explorer Cluster and Database
- Azure Storage Account and Container
- Azure Login credentials

### Input Variables
```bash
KUSTO_CLUSTER_NAME=<Kusto Cluster Name>
KUSTO_CLUSTER_REGION=<Kusto Cluster Region>
KUSTO_DATABASE_NAME=<Kusto Database Name>
KUSTO_TABLE_NAME=<Kusto Table Name>
STORAGE_ACCOUNT_NAME=<Storage Account Name>
STORAGE_CONTAINER_NAME=<Storage Container Name>
CONTAINER_PREFIX=<Container Prefix>
```
### Usage
- Login to Azure using CLI
- Download the Kusto LightIngest tool from the above link and extract the zip file and make the binary executable.
- Run the below script to ingest data into the Kusto Table. The script will ingest data from the azure storage account blob container to the Kusto Table.
```bash
set -eu

echo "Get Kusto Access Token"
access_token=$(az account get-access-token --resource https://${KUSTO_CLUSTER_NAME}.${KUSTO_CLUSTER_REGION}.kusto.windows.net --query 'accessToken' -o tsv)

echo "Get Storage Access Token"
storage_access_token=$(az account get-access-token --resource https://storage.azure.com --query accessToken -o tsv)

echo "Data Ingestion started from ${STORAGE_CONTAINER_NAME} container with ${CONTAINER_PREFIX} container prefix into ${KUSTO_TABLE_NAME} kusto table in ${KUSTO_DATABASE_NAME} database."

ingestion_response=$(./LightIngest "https://ingest-${KUSTO_CLUSTER_NAME}.${KUSTO_CLUSTER_REGION}.kusto.windows.net;Fed=True;AppToken=${access_token}" \
-db:${KUSTO_DATABASE_NAME} \
-table:${KUSTO_TABLE_NAME} \
-source:"https://${STORAGE_ACCOUNT_NAME}.blob.core.windows.net/${STORAGE_CONTAINER_NAME};token=${storage_access_token}" \
-prefix:"${CONTAINER_PREFIX}" \
-pattern:"*.json" \
-format:multijson \
-ignoreFirst:false \
-ingestionMappingRef:${KUSTO_TABLE_NAME}_mapping \
-ingestTimeout:180 \
-dontWait:false)

echo "$ingestion_response"
```

## References

* [Terraform AWS Provider](https://www.terraform.io/docs/providers/aws/index.html)
* [Terraform Azure Provider](https://www.terraform.io/docs/providers/azurerm/index.html)
* [Terraform Azure DevOps Provider](https://registry.terraform.io/providers/microsoft/azuredevops/latest/docs)
* [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
* [AWS CLI](https://docs.aws.amazon.com/cli/latest/)
* [Kusto LightIngest](https://learn.microsoft.com/en-us/azure/data-explorer/lightingest)
* [Make Utility](https://www.gnu.org/software/make/manual/make.html)
* [Azure DevOps Authentication Guide](https://registry.terraform.io/providers/microsoft/azuredevops/latest/docs/guides/authenticating_using_the_personal_access_token)