from textwrap import dedent


def generate_workspace_script() -> str:
    return dedent(
        """if terraform workspace list | grep -q "$region"; then
              terraform workspace select $region
            else
              terraform workspace new $region
              terraform workspace select $region
            fi
        """
    ).strip()


def generate_apply_or_destroy_script(
    command: str, arguments: str, regions: list[str], cloud: str
) -> str:
    workspace_script = generate_workspace_script()
    error_handling_script = generate_error_handling_script(command, cloud)

    return dedent(
        f"""
        set -e

        # Navigate to the Terraform working directory
        cd $TERRAFORM_WORKING_DIRECTORY

        for region in $(echo "{regions}" | jq -r '.[]'); do
            echo "Processing region: $region"
            
            {workspace_script}
            
            # Retrieve input file and variables
            terraform_input_file=$(echo $TERRAFORM_REGIONAL_CONFIG | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_FILE')
            terraform_input_variables=$(echo $TERRAFORM_REGIONAL_CONFIG | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_VARIABLES')

            # Run Terraform {command} command
            set +e
            terraform {command} --auto-approve {arguments} -var-file $terraform_input_file -var json_input="$terraform_input_variables"
            exit_code=$?
            set -e

            # Handle errors
            if [[ $exit_code -ne 0 ]]; then
                echo "Terraform {command} failed for region: $region"
                {error_handling_script}
                exit 1
            fi
          
        done
        """
    ).strip()


def generate_error_handling_script(command: str, cloud: str) -> str:
    if command == "apply" and cloud == "azure":
        return dedent(
            """echo "Deleting resources and removing state file before retrying"
                ids=$(az resource list --location $region --resource-group $RUN_ID --query [*].id -o tsv)
                az resource delete --ids $ids --verbose
                rm -r terraform.tfstate.d/$region
            """
        ).strip()
    elif command == "destroy" and cloud == "aws":
        return dedent(
            """echo "Cleaning up AWS resources before retrying"
                # Detach and delete network interfaces
                subnet_ids=$(aws ec2 describe-subnets --query "Subnets[?Tags[?Key=='run_id' && Value=='$RUN_ID']].SubnetId" --output text)
                for subnet_id in $subnet_ids; do
                    echo "Detaching Subnet: $subnet_id Network Interfaces ..."
                    network_interfaces_attachment_id=$(aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=$subnet_id --query "NetworkInterfaces[].Attachment.AttachmentId" --output text)
                    for network_interface_attachment_id in $network_interfaces_attachment_id; do
                        echo "Detaching Network Interface attachment id: $network_interface_attachment_id"
                        if ! aws ec2 detach-network-interface --attachment-id $network_interface_attachment_id; then
                        echo "##vso[task.logissue type=error;] Failed to detach Network Interface attachment id: $network_interface_attachment_id"
                        fi
                    done
                    echo "Deleting Subnet: $subnet_id Network Interfaces ..."
                    network_interfaces=$(aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=$subnet_id --query "NetworkInterfaces[].NetworkInterfaceId" --output text)
                    for network_interface in $network_interfaces; do
                        echo "Deleting Network Interface: $network_interface"
                        if ! aws ec2 delete-network-interface --network-interface-id $network_interface; then
                        echo "##vso[task.logissue type=error;] Failed to delete Network Interface: $network_interface"
                        fi
                    done
                done

                # Delete security groups
                vpc_id=$(aws ec2 describe-vpcs --query "Vpcs[?Tags[?Key=='run_id' && Value=='$RUN_ID']].VpcId" --output text)
                security_group_ids=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values=$vpc_id --query "SecurityGroups[].GroupId" --output text)
                for security_group_id in $security_group_ids; do
                    aws ec2 delete-security-group --group-id $security_group_id || echo "Failed to delete security group: $security_group_id"
                done
            """
        ).strip()
    else:
        return ""


def generate_generic_script(command: str, arguments: str) -> str:
    return dedent(
        f"""
        set -e
        
        # Navigate to the Terraform working directory
        cd $TERRAFORM_WORKING_DIRECTORY

        # Run Terraform {command} command
        terraform {command} {arguments}
        """
    ).strip()
