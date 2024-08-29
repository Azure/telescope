#!/bin/bash
set -e

eventhub_namespaces=$(az eventhubs namespace list --resource-group $RESOURCE_GROUP_NAME --query '[].{Name:name}' --output tsv)
create_eventhub_namespace=false
for eventhub_namespace in $eventhub_namespaces; do
	eventhub_instances=$(az eventhubs eventhub list --namespace-name $eventhub_namespace --resource-group $RESOURCE_GROUP_NAME --query '[].{Name:name}' --output tsv)

	if [ $(echo $eventhub_instances | wc -w) -eq 10 ]; then
		create_eventhub_namespace=true
		eventhub_namespace=null
	else
		create_eventhub_namespace=false															
		break
	fi
done
export TF_VAR_create_eventhub_namespace=$create_eventhub_namespace
export TF_VAR_eventhub_namespace=$eventhub_namespace