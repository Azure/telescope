
SHELL := /bin/bash
# Azure DevOps project and organization details
ORG_NAME ?= "akstelescope"
PROJECT_NAME ?= telescope
PIPELINE_NAME ?= "Create Pipeline Test"
REPO_ID ?= https://github.com/Azure/telescope/tree/anson-open-source
YAML_PATH ?= pipelines/system/create-new-pipeline.yaml
BRANCH ?= sumanth/test
DESCRIPTION ?= "Pipeline create using script"
FOLDER_PATH ?= "/perf-eval"

CONFIG_FILE ?= "config.json"

# Makefile targets
.DEFAULT_GOAL := help
# Help target to display usage
help:
  @echo "Usage:"
	@echo " make terraform_init          - Initialize Terraform"
	@echo " make terraform_plan          - Plan Terraform"
	@echo " make terraform_apply         - Apply Terraform"
  @echo "  make create_pipeline        - Create a new pipeline"
  @echo "  make create_variables       - Create variables for the pipeline"
  @echo "  make create_variable_groups - Create variable groups for the pipeline"
  @echo "  make all                    - Create pipeline, variables, and agent pool"


# Target to initialize Terraform
terraform_init:
	@terraform init
	@echo "Terraform initialized successfully."
# Target to plan Terraform
terraform_plan:
	@terraform plan
	@echo "Terraform planned successfully."
# Target to apply Terraform	
terraform_apply:
	@terraform apply -auto-approve
	@echo "Terraform applied successfully."

# Target to create variables for the pipeline
create_variables:
  @az pipelines variable create --name "AZURE_SUBSCRIPTION_ID" --pipeline-name $(PIPELINE_NAME) --value "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
  @az pipelines variable create --name "SKIP_RESOURCE_MANAGEMENT" --pipeline-name $(PIPELINE_NAME) --value "false"
  @echo "Variables created successfully."


