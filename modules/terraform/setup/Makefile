
SHELL := /bin/bash

TF_INFRASTRUCTURE_DIR := infrastructure
TF_INFRASTRUCTURE_INPUT_FILE := infrastructure.tfvars
TF_PIPELINE_DIR := pipeline
TF_PIPELINE_INPUT_FILE := pipeline.tfvars
TF_TABLE_DATA_CONNECTION_DIR := table-data-connections
TF_TABLE_DATA_CONNECTION_INPUT_FILE := table-data-connections.tfvars
# Makefile targets
.DEFAULT_GOAL := help
# Help target to display usage
help:
	@echo "Usage:"
	@echo " make infrastructure_setup  - Setup a new infrastructure "
	@echo " make pipeline_setup - Setup a new pipeline"
	@echo " make table_dataconnection_setup - Create a new table and data connection"

all: infrastructure_setup pipeline_setup table_dataconnection_setup

infrastructure_setup:
	@echo "Setting up a new infrastructure"
	cd $(TF_INFRASTRUCTURE_DIR) && \
	terraform init && \
	terraform plan -var-file=$(TF_INFRASTRUCTURE_INPUT_FILE) && \
	terraform apply -var-file=$(TF_INFRASTRUCTURE_INPUT_FILE) --auto-approve

pipeline_setup:
	@echo "Setting up a new pipeline"
	cd $(TF_PIPELINE_DIR) && \
	terraform init && \
	terraform plan -var-file=$(TF_PIPELINE_INPUT_FILE) && \
	terraform apply -var-file=$(TF_PIPELINE_INPUT_FILE) --auto-approve

table_dataconnection_setup:
	@echo "Setting up a new table and data connection"
	source ./$(TF_TABLE_DATA_CONNECTION_DIR)/bash/script.sh && \
	cd $(TF_TABLE_DATA_CONNECTION_DIR) && \
	terraform init && \
	terraform plan -var-file=$(TF_TABLE_DATA_CONNECTION_INPUT_FILE) && \
	terraform apply -var-file=$(TF_TABLE_DATA_CONNECTION_INPUT_FILE) --auto-approve

