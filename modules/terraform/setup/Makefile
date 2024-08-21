
SHELL := /bin/bash

TF_PIPELINE_DIR := pipeline
TF_PIPELINE_INPUT_FILE := pipeline.tfvars
TF_INFRASTRUCTURE_DIR := infrastructure
TF_INFRASTRUCTURE_INPUT_FILE := setup.tfvars
TF_TABLE_DATA_INGESTION_DIR := table-data-ingestion
TF_TABLE_DATA_INGESTION_INPUT_FILE := table-data-ingestion.tfvars
# Makefile targets
.DEFAULT_GOAL := help
# Help target to display usage
help:
	@echo "Usage:"
	@echo " make infrastructure_setup  - Create infrastructure setup"
	@echo " make create_pipeline - Create a new pipeline"

infrastructure_setup:
	cd $(TF_INFRASTRUCTURE_DIR) && terraform init && terraform plan -var-file=$(TF_INFRASTRUCTURE_INPUT_FILE) && terraform apply -var-file=$(TF_INFRASTRUCTURE_INPUT_FILE)

create_pipeline:
	@echo "Creating a new pipeline"
	cd $(TF_PIPELINE_DIR) && terraform init && terraform plan -var-file=$(TF_PIPELINE_INPUT_FILE) && terraform apply -var-file=$(TF_PIPELINE_INPUT_FILE)

create_table_data_ingestion_setup:
	@echo "Creating a new table data ingestion setup"
	cd $(TF_TABLE_DATA_INGESTION_DIR) && terraform init && terraform plan -var-file=$(TF_TABLE_DATA_INGESTION_INPUT_FILE) && terraform apply -var-file=$(TF_TABLE_DATA_INGESTION_INPUT_FILE)
