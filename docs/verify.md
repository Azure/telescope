# Verify

## Prerequisites

* [terraform](https://developer.hashicorp.com/terraform/install)
* [kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)
* [kwok/kwokctrl](https://kwok.sigs.k8s.io/docs/user/installation/)

## Verify Locally

### Python Module

```bash
# Navigate to Python modules directory
cd modules/python

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create kwok cluster for kwok tests
kwokctl create cluster --name kwok-test

# Run tests with coverage (minimum 70% required)
pytest --cov=. --cov-report=term-missing --cov-fail-under=70

# Run specific test module
pytest tests/clients/test_aks_client.py -v

# Run specific test categories
pytest tests/clients/ -v  # Client tests
pytest tests/crud/ -v     # CRUD operation tests
pytest tests/iperf3/ -v   # Network performance tests

# Deactivate virtual environment
deactivate
```

### Terraform Module

```bash
# Navigate to Terraform modules directory
cd modules/terraform

# Format check
terraform fmt --check -recursive

# Navigate to Azure modules directory
cd modules/terraform/azure
terraform init
terraform validate
```


### YAML Module

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install YAML Lint
pip install yamllint


# Run YAML Lint with warnings ignored
yamllint -c .yamllint . --no-warnings

# Deactivate virtual environment
deactivate
```

## Verify End-to-End

(TODO)