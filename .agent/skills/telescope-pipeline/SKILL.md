---
name: telescope-pipeline
description: Use when user asks to create an Azure DevOps pipeline for a Telescope benchmark. Trigger whenever the user wants to set up, register, or wire up a pipeline for running benchmarks in Azure DevOps, even if they don't use the exact word "pipeline".
allowed-tools: Read, Bash(az --version), Bash(az login), Bash(az pipelines*), Bash(az devops*), Bash(az account*), Bash(az extension*), Bash(az repos*)
---

# Function

Create Azure DevOps pipelines for Telescope benchmarks using Azure CLI.

## Prerequisites

Before creating pipelines, verify prerequisites:

### 1. Azure CLI Installation

```bash
az --version
```

If not installed, install az cli using: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

### 2. Azure DevOps Extension

```bash
az extension list --query "[?name=='azure-devops'].version" -o tsv
```

If not installed:
```bash
az extension add --name azure-devops
```

### 3. Authentication

Check if logged in:
```bash
az account show
```

If not authenticated:
```bash
az login
```

---

## Pipeline Creation Workflow

### Step 1: Gather Requirements

Ask the user for pipeline configuration:

| Parameter | Description | Example |
|-----------|-------------|---------|
| **Pipeline Name** | Display name for the pipeline | `"<your-pipeline-name>"` |
| **Description** | Pipeline description | `"<your-description>"` |
| **Organization** | Azure DevOps organization URL | `https://dev.azure.com/<your-org>` |
| **Project** | Azure DevOps project name | `<your-project>` |
| **Repository** | GitHub repository URL | `<your-repo>` |
| **Branch** | Target branch | `main` |
| **YAML Path** | Path to pipeline YAML file in the repo | `<path-to-your-pipeline.yaml>` |

Collect all required values from the user before proceeding. If any value is unclear, ask for clarification — do not guess at organization URLs, project names, or subscription IDs.

### Step 2: Verify Configuration

Before creating the pipeline, verify that the organization and project exist:

```bash
az devops project show --project "<your-project>" --org "https://dev.azure.com/<your-org>"
```

Optionally verify repository accessibility:
```bash
az repos list --org "https://dev.azure.com/<your-org>" --project "<your-project>"
```

Also confirm with the user that the YAML file exists at the specified path in the repository.

### Step 3: Create the Pipeline

Execute the pipeline creation command:

```bash
az pipelines create \
  --name "<your-pipeline-name>" \
  --org "https://dev.azure.com/<your-org>" \
  --project "<your-project>" \
  --description "<your-description>" \
  --repository "<your-repo>" \
  --repository-type github \
  --branch main \
  --yaml-path "<path-to-your-pipeline.yaml>"
```

Set `--repository-type` properly. Use `tfsgit` for Azure repositories and `github` for GitHub repositories.

### Step 4: Handle Authentication Prompts

The command may prompt for:
- **GitHub authentication**: Follow the device code flow or PAT token prompt
- **Service connection**: Approve creation of Azure DevOps ↔ GitHub connection
- **First-run consent**: Accept permissions for the Azure DevOps extension

Guide the user through any interactive prompts that appear.

### Step 5: Verify Pipeline Creation

After creation, confirm the pipeline was registered:

```bash
# List pipelines to confirm
az pipelines list \
  --org "https://dev.azure.com/<your-org>" \
  --project "<your-project>" \
  --query "[?name=='<your-pipeline-name>'].{Name:name, ID:id, Status:status}" \
  -o table

# Get full pipeline details
az pipelines show \
  --org "https://dev.azure.com/<your-org>" \
  --project "<your-project>" \
  --name "<your-pipeline-name>"
```

### Step 6: Provide Pipeline URL

Generate the direct link to the newly created pipeline:
```
https://dev.azure.com/<your-org>/<your-project>/_build?definitionId=<pipeline-id>
```

Present to the user:
- ✅ Pipeline created successfully
- **Name**: `<your-pipeline-name>`
- **ID**: `<pipeline-id>`
- **URL**: `https://dev.azure.com/<your-org>/<your-project>/_build?definitionId=<pipeline-id>`
- **Branch**: `main`
- **YAML**: `<path-to-your-pipeline.yaml>`
