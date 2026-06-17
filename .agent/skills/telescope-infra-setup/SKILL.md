---
name: telescope-infra-setup
description: >
  Provision Telescope V2 infrastructure from scratch on Azure: resource group,
  storage account, blob container, Azure Data Explorer (ADX/Kusto) cluster,
  database, table, ingestion mapping, and Event Grid data connection that
  automatically ingests blobs into ADX. Use this skill whenever setting up a
  new Telescope environment, onboarding a new region, or recreating Telescope
  infrastructure from scratch. Also trigger when the user asks to "set up
  Telescope", "create Telescope infra", "provision Telescope storage or ADX",
  or "wire up blob ingestion for Telescope".
---

# Telescope V2 Infrastructure Setup

## Overview

This skill provisions the full Telescope V2 data infrastructure on Azure:

```
Blob upload → <STORAGE_ACCOUNT>/<CONTAINER> container
    → Event Grid (BlobCreated)
    → Event Hub (<EH_NAMESPACE>/<EH_NAME>)
    → ADX data connection
    → Kusto table (<CLUSTER> cluster / <DATABASE> database / <TABLE> table)
```

---

## Prerequisites

- Azure CLI (`az`) installed and authenticated
- Contributor access on the target subscription
- The `kusto` CLI extension (auto-installs on first `az kusto` command)

---

## Step 1: Create Resource Group

Ask the user for:
- **Subscription ID**
- **Location** (e.g. `eastus`)
- **Resource group name**

```bash
az group create \
  --name <RESOURCE_GROUP> \
  --location <LOCATION> \
  --subscription <SUBSCRIPTION>
```

**Result:** Resource group `<RESOURCE_GROUP>` in `<LOCATION>`.

---

## Step 2: Create Storage Account

Ask the user for:
- **Storage account name** — lowercase alphanumeric only (no hyphens), 3–24 chars, globally unique

```bash
az storage account create \
  --name <STORAGE_ACCOUNT> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --location <LOCATION> \
  --sku Standard_RAGRS \
  --kind StorageV2
```

**Result:**
- Storage account: `<STORAGE_ACCOUNT>`
- SKU: `Standard_RAGRS` (geo-redundant with read access to secondary region)
- Blob endpoint: `https://<STORAGE_ACCOUNT>.blob.core.windows.net/`

---

## Step 3: Create Blob Container

Ask the user for:
- **Container name**

```bash
az storage container create \
  --name <CONTAINER> \
  --account-name <STORAGE_ACCOUNT> \
  --subscription <SUBSCRIPTION> \
  --auth-mode login
```

> `--auth-mode login` uses your AAD identity instead of storage account keys — more secure, follows least-privilege. Requires `Storage Blob Data Contributor` role on the account.

**Result:** Container `<CONTAINER>` in `<STORAGE_ACCOUNT>`.

---

## Step 4: Create Azure Data Explorer (ADX/Kusto) Cluster

Ask the user for:
- **ADX cluster name**

```bash
az kusto cluster create \
  --name <CLUSTER> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --location <LOCATION> \
  --sku name="Standard_D32d_v4" tier="Standard" capacity=2
```

**Result:**
- Cluster: `<CLUSTER>` (publicly accessible, AAD-authenticated)
- Query URI: `https://<CLUSTER>.<LOCATION>.kusto.windows.net`
- Ingest URI: `https://ingest-<CLUSTER>.<LOCATION>.kusto.windows.net`
- SKU: `Standard_D32d_v4`, 2 nodes, Standard tier

---

## Step 5: Create ADX Database and Table

### 5a. Create Database

Ask the user for:
- **Database name**

```bash
az kusto database create \
  --cluster-name <CLUSTER> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --database-name <DATABASE> \
  --read-write-database location=<LOCATION> soft-delete-period=P1000D hot-cache-period=P31D
```

> - `soft-delete-period=P1000D`: retain data for 1000 days before deletion
> - `hot-cache-period=P31D`: keep last 31 days on fast SSD cache; older data is read from cold storage (slower but cheaper)

**Result:** Database `<DATABASE>` — 1000-day retention, 31-day hot cache.

### 5b. Create Table

Ask the user for:
- **Table name**

```bash
az kusto script create \
  --cluster-name <CLUSTER> \
  --database-name <DATABASE> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --name create-<TABLE>-table \
  --script-content ".create table ['<TABLE>'] (['timestamp']:datetime, ['run_id']:string, ['run_url']:string, ['pipeline']:string, ['result']:dynamic)"
```

**Table schema:**

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | `datetime` | Collection time (UTC ISO-8601) |
| `run_id` | `string` | Pipeline run ID |
| `run_url` | `string` | URL to the pipeline run |
| `pipeline` | `string` | Name of the pipeline definition |
| `result` | `dynamic` | The result payload of each pipeline run |

---

## Step 6: Set Up Data Connection (Blob Storage → ADX)

Wires the `<CONTAINER>` blob container to automatically ingest new JSON blobs into the `<TABLE>` Kusto table via Event Grid + Event Hub.

### 6a. Create Event Hub Namespace

Ask the user for:
- **Event Hub namespace name**

```bash
az eventhubs namespace create \
  --name <EH_NAMESPACE> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --location <LOCATION> \
  --sku Standard
```

### 6b. Create Event Hub

Ask the user for:
- **Event Hub name**

```bash
az eventhubs eventhub create \
  --name <EH_NAME> \
  --namespace-name <EH_NAMESPACE> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --partition-count 4 \
  --cleanup-policy Delete \
  --retention-time-in-hours 168
```

### 6c. Create Event Grid Subscription

Forwards `BlobCreated` events from the `<CONTAINER>` container to the Event Hub. No new parameters needed.

```bash
STORAGE_ID=$(az storage account show \
  --name <STORAGE_ACCOUNT> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --query id -o tsv)

EH_ID=$(az eventhubs eventhub show \
  --name <EH_NAME> \
  --namespace-name <EH_NAMESPACE> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --query id -o tsv)

az eventgrid event-subscription create \
  --source-resource-id $STORAGE_ID \
  --name <CONTAINER>-blob-events \
  --endpoint-type eventhub \
  --endpoint $EH_ID \
  --included-event-types Microsoft.Storage.BlobCreated \
  --subject-begins-with /blobServices/default/containers/<CONTAINER>
```

### 6d. Create Ingestion Mapping in ADX

Maps JSON blob fields to the Kusto table columns. No new parameters needed.

```bash
az kusto script create \
  --cluster-name <CLUSTER> \
  --database-name <DATABASE> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --name create-<TABLE>-mapping \
  --script-content ".create table ['<TABLE>'] ingestion json mapping '<TABLE>_mapping' '[{\"column\":\"timestamp\",\"path\":\"$.timestamp\"},{\"column\":\"run_id\",\"path\":\"$.run_id\"},{\"column\":\"run_url\",\"path\":\"$.run_url\"},{\"column\":\"pipeline\",\"path\":\"$.pipeline\"},{\"column\":\"result\",\"path\":\"$.result\"}]'"
```

### 6e. Create ADX Data Connection

No new parameters needed.

```bash
az kusto data-connection event-grid create \
  --cluster-name <CLUSTER> \
  --database-name <DATABASE> \
  --resource-group <RESOURCE_GROUP> \
  --subscription <SUBSCRIPTION> \
  --data-connection-name <TABLE>-connection \
  --storage-account-resource-id $STORAGE_ID \
  --event-hub-resource-id $EH_ID \
  --consumer-group '$Default' \
  --table-name <TABLE> \
  --data-format MULTIJSON \
  --mapping-rule-name <TABLE>_mapping \
  --blob-storage-event-type Microsoft.Storage.BlobCreated
```

**Result:** Any JSON blob uploaded to `<STORAGE_ACCOUNT>/<CONTAINER>/` is automatically ingested into the `<TABLE>` table (~5 min latency).

---

## Step 7: Upload Sample Data and Verify

Generate the following sample fields based on existing input:
- **Run ID** (e.g. `99999999-sample01`)
- **Run URL** (e.g. `https://dev.azure.com/<your-org>/<your-project>/_build/results?buildId=99999999`)
- **Pipeline name** (e.g. `<your-pipeline-name>`)

Create a sample JSON record matching the `<TABLE>` table schema:

```bash
cat > /tmp/sample-run.json << 'EOF'
{
  "timestamp": "2026-03-22T08:00:00Z",
  "run_id": "<RUN_ID>",
  "run_url": "<RUN_URL>",
  "pipeline": "<PIPELINE_NAME>",
  "result": {
    "status": "succeeded",
    "duration_seconds": 512,
    "scenario": "<your-scenario>",
    "region": "<LOCATION>",
    "node_count": 10
  }
}
EOF
```

Upload to the `<CONTAINER>` container:

```bash
az storage blob upload \
  --account-name <STORAGE_ACCOUNT> \
  --subscription <SUBSCRIPTION> \
  --container-name <CONTAINER> \
  --name sample/run-<RUN_ID>.json \
  --file /tmp/sample-run.json \
  --auth-mode key
```

> In production pipelines use `--auth-mode login` with a service principal that has the `Storage Blob Data Contributor` role. `--auth-mode key` is used here as a fallback when the RBAC role is not yet assigned.

Wait ~5 minutes, then verify in ADX:

```kql
<TABLE>
| take 10
```
