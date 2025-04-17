from textwrap import dedent

from pipeline import Script

run_command = lambda command, arguments='', regions='', cloud='', retry_attempt_count=3, credential_type="managed_identity": Script(
    display_name=f"Run Terraform {command.capitalize()} Command",
    script=dedent(
        f"""
        set -e

        # Navigate to the Terraform working directory
        cd $TERRAFORM_WORKING_DIRECTORY

        # Handle apply or destroy commands
        if [[ "{command}" == "apply" || "{command}" == "destroy" ]]; then
          for region in $(echo "$REGIONS" | jq -r '.[]'); do
            echo "Processing region: $region"

            # Select or create Terraform workspace
            if terraform workspace list | grep -q "$region"; then
              terraform workspace select $region
            else
              terraform workspace new $region
              terraform workspace select $region
            fi

            # Retrieve input file and variables
            terraform_input_file=$(echo $TERRAFORM_REGIONAL_CONFIG | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_FILE')
            terraform_input_variables=$(echo $TERRAFORM_REGIONAL_CONFIG | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_VARIABLES')

            # Run Terraform command
            set +e
            terraform {command} --auto-approve {arguments} -var-file $terraform_input_file -var json_input="$terraform_input_variables"
            exit_code=$?
            set -e

            # Handle errors
            if [[ $exit_code -ne 0 ]]; then
              echo "Terraform {command} failed for region: $region"
              if [[ "{command}" == "apply" && "$CLOUD" == "azure" ]]; then
                echo "Deleting resources and removing state file before retrying"
                ids=$(az resource list --location $region --resource-group $RUN_ID --query [*].id -o tsv)
                az resource delete --ids $ids --verbose
                rm -r terraform.tfstate.d/$region
              elif [[ "{command}" == "destroy" && "$CLOUD" == "aws" ]]; then
                echo "Cleaning up AWS resources before retrying"
                # Detach and delete network interfaces
                subnet_ids=$(aws ec2 describe-subnets --query "Subnets[?Tags[?Key=='run_id' && Value=='$RUN_ID']].SubnetId" --output text)
                for subnet_id in $subnet_ids; do
                  echo "Detaching network interfaces for subnet: $subnet_id"
                  network_interfaces=$(aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=$subnet_id --query "NetworkInterfaces[].NetworkInterfaceId" --output text)
                  for network_interface in $network_interfaces; do
                    aws ec2 delete-network-interface --network-interface-id $network_interface || echo "Failed to delete network interface: $network_interface"
                  done
                done

                # Delete security groups
                vpc_id=$(aws ec2 describe-vpcs --query "Vpcs[?Tags[?Key=='run_id' && Value=='$RUN_ID']].VpcId" --output text)
                security_group_ids=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values=$vpc_id --query "SecurityGroups[].GroupId" --output text)
                for security_group_id in $security_group_ids; do
                  aws ec2 delete-security-group --group-id $security_group_id || echo "Failed to delete security group: $security_group_id"
                done
              fi
              exit 1
            fi
          done
        else
          # Run other Terraform commands
          terraform {command} {arguments}
        fi
        """
    ).strip(),
    condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    retryCountOnTaskFailure=retry_attempt_count,
    env={
        "REGIONS": regions,
        "CLOUD": cloud,
        "ARM_SUBSCRIPTION_ID": "$(AZURE_SUBSCRIPTION_ID)",
        **(
            {
                "ARM_USE_MSI": "true",
                "ARM_TENANT_ID": "$(AZURE_MI_TENANT_ID)",
                "ARM_CLIENT_ID": "$(AZURE_MI_CLIENT_ID)",
            }
            if credential_type == "managed_identity"
            else {}
        ),
    },
)