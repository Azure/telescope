# Telescope Local Development - Cloud Provisioning

This directory contains Jupyter notebooks for local development and testing of Telescope infrastructure on different cloud providers.

## 🚀 Quick Start

#### 1. Install Python Packages for Jupyter
```bash
pip install jupyter notebook ipykernel bash_kernel
```
You can install Jupyter Extension from here in the VS code: https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter

## Interactive Notebooks

For easy local development and testing, we provide Jupyter notebooks for each cloud provider:

- **[Azure Notebook:](./azure.ipynb)** Interactive notebook for Azure telescope testing
- **[AWS Notebook:](./aws.ipynb)** Interactive notebook for AWS telescope testing

### Quick Start with Notebooks

```bash
# From the telescope repository root
cd local-development/provisioning
jupyter notebook azure.ipynb   # For Azure
jupyter notebook aws.ipynb     # For AWS
```
Once you run the command go to this http://localhost:8888/tree to access the Jupyter Notebook UI

The notebooks provide:
- Prerequisites checking and cloud authentication
- Step-by-step Terraform workflow (init, plan, apply, destroy)
- Variable configuration and customization options
```
