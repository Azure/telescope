#!/bin/bash
set -eu

echo "Get Kusto Access Token"
access_token=$(az account get-access-token --resource https://"${KUSTO_CLUSTER_NAME}"."${KUSTO_CLUSTER_REGION}".kusto.windows.net --query 'accessToken' -o tsv)

echo "Get Storage Access Token"
storage_access_token=$(az account get-access-token --resource https://storage.azure.com --query accessToken -o tsv)

echo "Data Ingestion started from ${STORAGE_CONTAINER_NAME} container with ${CONTAINER_PREFIX} container prefix into ${KUSTO_TABLE_NAME} kusto table in ${KUSTO_DATABASE_NAME} database."

ingestion_response=$(./LightIngest "https://ingest-${KUSTO_CLUSTER_NAME}.${KUSTO_CLUSTER_REGION}.kusto.windows.net;Fed=True;AppToken=${access_token}" \
-db:"${KUSTO_DATABASE_NAME}" \
-table:"${KUSTO_TABLE_NAME}" \
-source:"https://${STORAGE_ACCOUNT_NAME}.blob.core.windows.net/${STORAGE_CONTAINER_NAME};token=${storage_access_token}" \
-prefix:"${CONTAINER_PREFIX}" \
-pattern:"*.json" \
-format:multijson \
-ignoreFirst:false \
-ingestionMappingRef:"${KUSTO_TABLE_NAME}"_mapping \
-ingestTimeout:180 \
-dontWait:false)

echo "$ingestion_response"
