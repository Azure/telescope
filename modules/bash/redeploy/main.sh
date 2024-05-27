#!/bin/bash

__dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${__dir}/utils.sh"
source "${__dir}/azure.sh"

if ! (return 0 2>/dev/null); then
    # A better class of script...
    set -o errexit  # Exit on most errors (see the manual)
    set -o nounset  # Disallow expansion of unset variables
    set -o pipefail # Use last non-zero exit code in a pipeline
fi

# Enable errtrace or the error trap handler will not work as expected
set -o errtrace # Ensure the error trap handler is inherited

# DESC: Main function to run the compete scenario
# ARGS: Uses environment variables for arguments
#       $RESULTS_TELESCOPE (required): The path to the directory where the results will be written
#       $RUN_ID (required): The run id of the compete scenario 
# OUTS: None
# NOTE: This function is used to run the compete scenario. 
#       It calls the redeploy_vm function and writes the json to the results file. 
function main() {
    local error_file="$RESULTS_TELESCOPE/vm-redeploy-error.txt"
    local result_file_template="$RESULTS_TELESCOPE/vm-redeploy-results-%s.json"
    local operation_info="vm-redeploy"
    local cloud=${CLOUD:-"azure"}
    local region=${REGION:-"eastus"}

    mkdir -p "$RESULTS_TELESCOPE"
    trap 'script_trap_err $? $LINENO $operation_info $cloud $region $error_file $result_file_template' ERR

    local run_id=$RUN_ID

    local vm_names=($(get_vm_instances_name_by_run_id "$run_id"))

    for index in "${!vm_names[@]}"; do
        vm_name="${vm_names[$index]}"
        (
            local execution_time="$(redeploy_vm "$vm_name" "$run_id" "$error_file")"
            local data_json="$(build_data_json "$(get_vm_instance_view_json "$run_id" "$vm_name")")"
            local json_output="$(get_json_output "$operation_info" "$execution_time" "true" "$cloud" "$region" "$data_json")"
            echo "$json_output" > "$(printf "$result_file_template" $index)"
        ) &
    done
    wait
}