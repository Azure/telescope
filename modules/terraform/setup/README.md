# Setup Module

This folder contains Terraform modules for creating new infrastructure setup, pipelines, Data Connections, and Tables for Kusto databases.

## Modules
- [Infrastructure Setup](./infrastructure)
- [Pipeline Setup](./pipeline-)
- [Table and Data Connection Setup](./table-and-data-connection)

## Prerequisites
For all modules, you need to have the following prerequisites:
- Terraform CLI
- Azure CLI
- Azure DevOps CLI
- AWS CLI
- Azure login credentials
- Azure DevOps login credentials(PAT token)
- AWS Access Key ID and Secret Access Key
- Azure DevOps organization service URL

### Steps to setup the prerequisites
- Generate a PAT token from Azure DevOps and store it in the environment variable `AZDO_PERSONAL_ACCESS_TOKEN`
- Permissions for PAT token: 
  - Agent Pools (Read & Manage)
  - Build (Read & Execute)
  - Pipeline Resources (Use & Manage)
  - Service Connections (Read, Query & Manage)
  - Variable Groups (Read, Create & Manage)

- Set the Azure DevOps organization service URL in the environment variable `AZDO_ORG_SERVICE_URL`
- Set the AWS Access Key ID and Secret Access Key in the environment variable `AWS_ACCESS_KEY_ID` and `AWS_SECRET`
```bash
export AZDO_PERSONAL_ACCESS_TOKEN=<Personal Access Token>
export AZDO_ORG_SERVICE_URL=https://dev.azure.com/<Your Org Name>
```

## Infrastructure Setup
This module creates the following resources:
- Resource Group
- Service Principal and grant owner access to the subscription
- Azure Data Explorer Cluster
- Azure Data Explorer Database
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
make create_pipeline
```