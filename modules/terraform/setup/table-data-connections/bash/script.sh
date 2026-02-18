#!/bin/bash
set -e

eventhub_namespaces=$(az eventhubs namespace list --resource-group $TF_VAR_resource_group_name --query '[].{Name:name}' --output tsv)
if [ -z "$eventhub_namespaces" ]; then
  create_eventhub_namespace=true
  eventhub_namespace=null
else
  create_eventhub_namespace=false
  for eventhub_namespace in $eventhub_namespaces; do
    eventhub_instances=$(az eventhubs eventhub list --namespace-name $eventhub_namespace --resource-group $TF_VAR_resource_group_name --query '[].{Name:name}' --output tsv)
    
    # Check if eventhub_instances is empty
    if [ -z "$eventhub_instances" ]; then
      create_eventhub_namespace=true
      eventhub_namespace=null
      break
    fi

    if [ $(echo $eventhub_instances | wc -w) -eq 10 ]; then
      create_eventhub_namespace=true
      eventhub_namespace=null
    else
      create_eventhub_namespace=false
      break
    fi
  done
fi
export TF_VAR_create_eventhub_namespace=$create_eventhub_namespace
export TF_VAR_eventhub_namespace=$eventhub_namespace