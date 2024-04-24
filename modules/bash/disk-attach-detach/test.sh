set -x
role="vm-role"
mkdir -p $RESULT_DIR/tmp
vm_ids_list=$(az vm list --resource-group "$RUN_ID" --query "[?tags.role=='$role'].id" --output tsv)
for vm_id in $vm_ids_list; do
    echo "Collecting info for the vm with id: $vm_id"
    vm_info=$(az vm show --ids $vm_id --output json)
    info_column=$(echo "$vm_info" | jq -r '.tags.info_column_name')
    if [[ -z $info_column ]]; then
        continue
    fi
    for file in $RESULT_DIR/*.json; do
        cat $file | jq --arg info_path $info_column --argjson vm_info "$vm_info" -c '. | setpath($info_path / "."; $vm_info)' > $RESULT_DIR/tmp/temp_file.json
        cat $RESULT_DIR/tmp/temp_file.json > $file
    done
done