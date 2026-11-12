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

### AKS image-pull pipeline checks

- Where Azure Policy requires Microsoft Entra authentication, set `aad_enabled: "true"`
  in the pipeline matrix. Registry `anonymous_pull` is independent of cluster authentication.
- Image-pull validation installs kubelogin, refreshes the Azure CLI login, converts
  kubeconfig to `azurecli` authentication, and checks node access before polling readiness.
  HTTP 401/403 errors fail immediately; the pipeline identity still needs permission to
  list nodes and manage the benchmark's Kubernetes resources.
- For a kubelogin kubeconfig, the CRI pipeline uses [Dockerfile.aks](../modules/python/clusterloader2/Dockerfile.aks)
  to build a cached local derivative of the selected Debian/Ubuntu benchmark image.
  It adds Azure CLI and kubelogin while retaining the benchmark binary and entrypoint.
  Credentials are supplied by the existing Azure CLI cache mount, not embedded in the image.
- Dependency setup skips APT when `bc` and `nc` are already available. Missing packages
  use a bounded 900-second dpkg lock wait; no package-manager processes or locks are removed.
  Agent repository signing-key warnings must be repaired in the agent image rather than
  bypassing signature verification.
- Resource creation and Terraform init/apply require successful preceding steps.
  Cleanup remains enabled after failures for resource groups that were created and
  Terraform applies that started.