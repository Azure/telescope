#!/bin/bash

# Set variables
TFVARS_FILE="../../../scenarios/perf-eval/nap/terraform-inputs/azure-cli.tfvars"
REGION="eastus2"
RUN_ID="nap-test-$(date +%s)"

# Create JSON input for terraform
JSON_INPUT=$(cat <<EOF
{
  "region": "$REGION",
  "run_id": "$RUN_ID"
}
EOF
)
az login --service-principal --tenant $(TENANT_ID) -u $(SP_CLIENT_ID) --federated-token $(SP_ID_TOKEN) --allow-no-subscriptions
# Initialize Terraform
echo "Initializing Terraform..."
terraform init

# Validate configuration
echo "Validating Terraform configuration..."
terraform validate

# Create or select workspace
echo "Setting up workspace for region: $REGION"
if terraform workspace list | grep -q "$REGION"; then
  terraform workspace select $REGION
else
  terraform workspace new $REGION
fi

# Plan the deployment
echo "Running Terraform plan..."
terraform plan \
  -var-file="$TFVARS_FILE" \
  -var="json_input=$JSON_INPUT" \
  -out=tfplan

echo ""
echo "✅ Plan complete! Review the output above."
echo ""
echo "To apply the changes, run:"
echo "  terraform apply tfplan"
echo ""
echo "To destroy later, run:"
echo "  terraform workspace select $REGION"
echo "  terraform destroy -var-file=\"$TFVARS_FILE\" -var=\"json_input=$JSON_INPUT\""

