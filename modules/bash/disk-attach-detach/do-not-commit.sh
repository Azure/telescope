set -eu
mkdir -p $RESULT_DIR/tmp
disks=$(az disk list --query "[?(tags.run_id == '${RUN_ID}')].name" -o tsv)

for file in $RESULT_DIR/*.json; do
    for disk in $disks; do
        if [[ $file =~ ${disk}_(attach|detach)_[0-9]+\.json ]]; then
            disk_info=$(az disk show --name $disk --resource-group $RUN_ID -o json)
            cat $file | jq --argjson disk_info "$disk_info" -c '.disk_info=$disk_info' > $RESULT_DIR/tmp/temp_file.json
            cat $RESULT_DIR/tmp/temp_file.json > $file
        fi
    done
done