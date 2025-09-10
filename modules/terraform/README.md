# Terraform Modules

This folder contains Terraform modules for provisioning various resources on cloud providers. Below is the list of modules currently supported for AWS and Azure:

## AWS Modules

- **[EKS:](./aws/eks/README.md)** Module for setting up Amazon Elastic Kubernetes Service (EKS) clusters.
- **[Virtual Network:](./aws/virtual-network/README.md)** Module for configuring networking resources on AWS including a VPC, subnets, security groups, route tables, and associated resources.

## Azure Modules

- **[AKS:](./azure/aks/README.md)** Module for setting up Azure Kubernetes Service (AKS) clusters.
- **[AKS CLI:](./azure/aks-cli/README.md)** Module for setting up Azure Kubernetes Service (AKS) clusters using the Azure CLI.

## Usage
Each module contains its own README with specific instructions on usage and configuration.

## Interactive Notebooks

For easy local development and testing, we provide Jupyter notebooks for each cloud provider:
-**[Azure Notebook:](./azure/azure.ipynb)** Interactive notebook for Azure telescope testing
-**[AWS Notebook:](./aws/aws.ipynb)** Interactive notebook for AWS telescope testing

### Install Python Packages for Jupyter (if not already installed)
```bash
pip install jupyter notebook ipykernel bash_kernel
python -m bash_kernel.install
```
You can install the Jupyter Extension from the VS Code marketplace: https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter

