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

### Attach/detach timeout and cleanup

The Azure CSI attach/detach engine accepts `engine_input.execution_timeout_minutes`.
The default is `0` (no process timeout); the QAD stage uses `60` minutes.
A process timeout fails the workload step instead of waiting for the whole job
to time out, leaving time for resource deletion.

On failure or timeout, the Azure workload step requests deletion of
`statefulset-local` and all PVCs in that execution's recorded test namespace.
It preserves the workload's failing exit code and reports Kubernetes cleanup
errors. Before allowing the step to finish, it waits up to 15 minutes for the
StatefulSet, pods, PVCs, namespace-associated PVs, and their VolumeAttachments
to disappear. It tracks PV names before deleting PVCs so attachment checks
remain scoped to this test, not other workloads. PV deletion relies on the
storage class reclaim policy and CSI finalizers for underlying disk deletion;
it is not a separate Azure disk-inventory check. Retained PVs or stuck
attachments cause an explicit cleanup error at the deadline, after which
cluster deletion runs as a fallback. Kubernetes requests have 30-second
timeouts and can extend the polling deadline slightly. This does not produce
successful detachment measurements. A forced agent termination can prevent
the cleanup trap from running.

Competitive jobs allow a 60-minute cancellation cleanup window. Terraform destroy
and Azure resource-group deletion run after failure or cancellation when their
setup variables are available, unless resource management or deletion was
explicitly skipped. Validate this behavior by running a short workload timeout
in a disposable pipeline run and confirming that both the cluster resource group
and AKS node resource group are deleted. Agent loss or exhaustion of the
cancellation window can still prevent cleanup; inspect Azure for remaining
resources in those cases.

To verify end-to-end functionality, you can run the E2E tests as described in the [E2E Testing Guide](e2e-testing.md). This will ensure that all components work together as expected across different cloud providers.