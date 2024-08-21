#!/bin/bash
set -e
eval "$(jq -r '@sh "RESOURCE_GROUP_NAME=\(.RESOURCE_GROUP_NAME) KUSTO_TABLE_NAME=\(.KUSTO_TABLE_NAME)"')"
eventhub_namespaces=$(az eventhubs namespace list --resource-group $RESOURCE_GROUP_NAME --query '[].{Name:name}' --output tsv)
create_eventhub_namespace=false
for eventhub_namespace in $eventhub_namespaces; do
	eventhub_instances=$(az eventhubs eventhub list --namespace-name $eventhub_namespace --resource-group $RESOURCE_GROUP_NAME --query '[].{Name:name}' --output tsv)

	if [ $(echo $eventhub_instances | wc -w) -gt 1 ]; then
		create_eventhub_namespace=true
		eventhub_namespace=null
	else
		create_eventhub_namespace=false															
		break
	fi
done
result_file="./result.json"
table_script_path="../../../python/kusto"
table_creation_script=$(python3 $table_script_path/generate_commands.py "$KUSTO_TABLE_NAME" "$result_file")
jq -n --arg create_eventhub_namespace "$create_eventhub_namespace" --arg eventhub_namespace "$eventhub_namespace" --arg table_script "$table_creation_script" '{"create_eventhub_namespace":$create_eventhub_namespace,"eventhub_namespace":$eventhub_namespace, "table_creation_script":$table_script}'
