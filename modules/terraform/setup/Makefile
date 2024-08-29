
SHELL := /bin/bash

TF_PIPELINE_DIR := pipeline
TF_PIPELINE_INPUT_FILE := pipeline.tfvars
TF_INFRASTRUCTURE_DIR := infrastructure
TF_INFRASTRUCTURE_INPUT_FILE := setup.tfvars
TF_TABLE_DATA_CONNECTION_DIR := table-data-connections
TF_TABLE_DATA_CONNECTION_INPUT_FILE := table-data-connections.tfvars
# Makefile targets
.DEFAULT_GOAL := help
# Help target to display usage
help:
	@echo "Usage:"
	@echo " make infrastructure_setup  - Create infrastructure setup"
	@echo " make create_pipeline - Create a new pipeline"
	@echo " make table_dataconnection_setup - Create a new table data connections setup"

infrastructure_setup:
	@echo "Creating infrastructure setup"
	cd $(TF_INFRASTRUCTURE_DIR) && \
	terraform init && \
	terraform plan -var-file=$(TF_INFRASTRUCTURE_INPUT_FILE) && \
	terraform apply -var-file=$(TF_INFRASTRUCTURE_INPUT_FILE)

create_pipeline:
	@echo "Creating a new pipeline"
	cd $(TF_PIPELINE_DIR) && \
	terraform init && \
	terraform plan -var-file=$(TF_PIPELINE_INPUT_FILE) && \
	terraform apply -var-file=$(TF_PIPELINE_INPUT_FILE)

table_dataconnection_setup:
	@echo "Creating a new table data ingestion setup"
	source ./$(TF_TABLE_DATA_CONNECTION_DIR)/bash/script.sh && \
	cd $(TF_TABLE_DATA_CONNECTION_DIR) && \
	terraform init && \
	terraform plan -var-file=$(TF_TABLE_DATA_CONNECTION_INPUT_FILE) && \
	terraform destroy -var-file=$(TF_TABLE_DATA_CONNECTION_INPUT_FILE)
