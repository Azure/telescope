
SHELL := /bin/bash

TF_PIPELINE_DIR := pipeline
TF_PIPELINE_INPUT_FILE := pipeline/pipeline.tfvars
TF_INFRASTRUCTURE_DIR := infrastructure-setup
TF_INFRASTRUCTURE_INPUT_FILE := infrastructure/setup.tfvars
# Makefile targets
.DEFAULT_GOAL := help
# Help target to display usage
help:
  @echo "Usage:"
	@echo " make infrastructure_setup    - Create infrastructure setup"
  @echo " make create_pipeline        - Create a new pipeline"
# Target to create a new Azure Pipeline
create_pipeline:
	cd $(TF_PIPELINE_DIR) && terraform init && terraform plan -var-file=$(TF_PIPELINE_INPUT_FILE) && terraform apply -var-file=$(TF_PIPELINE_INPUT_FILE) --auto-approve

infrastructure_setup:
	cd $(TF_INFRASTRUCTURE_DIR) && terraform init && terraform plan -var-file=$(TF_INFRASTRUCTURE_INPUT_FILE) && terraform apply -var-file=$(TF_INFRASTRUCTURE_INPUT_FILE) --auto-approve




