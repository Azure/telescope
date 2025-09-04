# Telescope Local Development - Cloud Provisioning

This directory contains Jupyter notebooks for local development and testing of Telescope infrastructure on different cloud providers.

## 🚀 Quick Start

#### 1. Install Python Packages for Jupyter
```bash
# Create a new environment
python3 -m venv telescope-env
source telescope-env/bin/activate
# Install Jupyter and required packages
pip install jupyter notebook ipykernel bash_kernel
```

#### 3. Start Jupyter
```bash
# From this directory
jupyter notebook
```

### Running the Notebooks

#### For Azure Development
```bash
# Open in browser after starting jupyter
# Click on: azure.ipynb
```

#### For AWS Development
```bash
# Open in browser after starting jupyter
# Click on: aws.ipynb
```

## Interactive Notebooks

For easy local development and testing, we provide Jupyter notebooks for each cloud provider:

- **[Azure Notebook:](./azure/local.ipynb)** Interactive notebook for Azure telescope testing
- **[AWS Notebook:](./aws/local.ipynb)** Interactive notebook for AWS telescope testing

### Quick Start with Notebooks

```bash
# From the telescope repository root
jupyter notebook modules/terraform/azure/azure.ipynb   # For Azure
jupyter notebook modules/terraform/aws/aws.ipynb     # For AWS
```

The notebooks provide:
- Prerequisites checking and cloud authentication
- Step-by-step Terraform workflow (init, plan, apply, destroy)
- Variable configuration and customization options

## 📦 Required Python Packages

The `requirements.txt` file contains:

```
jupyter>=1.0.0          # Core Jupyter package
notebook>=6.0.0         # Jupyter Notebook interface
ipykernel>=6.0.0        # Python kernel for Jupyter
jupyterlab>=3.0.0       # Optional: Modern notebook interface
```

Install with:
```bash
pip install -r requirements.txt
```
