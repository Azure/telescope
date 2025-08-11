# Verify

## Prerequisites

* [terraform](https://developer.hashicorp.com/terraform/install)
* [kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)
* [kwok/kwokctrl](https://kwok.sigs.k8s.io/docs/user/installation/)

## Verify Locally

### Python Module

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Navigate to Python modules directory
pushd modules/python

# Install dependencies
pip install -r requirements.txt

# Run tests with coverage (minimum 80% required)
pytest --cov=. --cov-report=term-missing --cov-fail-under=80

# Run specific test module
pytest tests/clients/test_aks_client.py -v

# Run specific test categories
pytest tests/clients/ -v  # Client tests
pytest tests/crud/ -v     # CRUD operation tests
pytest tests/iperf3/ -v   # Network performance tests

# Go back to root directory
popd

# Run lint
pylint --rcfile=.pylintrc --ignore=site-packages modules/python

# Deactivate virtual environment
deactivate
```

### Terraform Module

```bash
# Navigate to Terraform modules directory
pushd modules/terraform

# Format check
terraform fmt --check -recursive

# Navigate to Azure modules directory
pushd azure
terraform init
terraform validate
popd

# Navigate back to root directory
popd
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

To verify end-to-end functionality, you can run the E2E tests as described in the [E2E Testing Guide](e2e-testing.md). This will ensure that all components work together as expected across different cloud providers.