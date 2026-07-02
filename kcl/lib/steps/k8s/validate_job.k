import azure_pipelines.ap.steps
import lib.steps.azure

# ValidateJobRunning validates that a Kubernetes Job is currently running:
# .status.active >= 1 AND .status.conditions[type=Failed].status != "True".
# Requires kubectl on the agent and a kubeconfig already in place (e.g. via
# GetCredentials).
ValidateJobRunning = lambda \
    serviceConnection: str, \
    name: str, \
    namespace: str = "default", \
    displayName: str = "", \
    continueOnError: bool = Undefined \
    -> steps.Step {
    assert name != "", "name must be non-empty"
    title = displayName if displayName else "Validate job/${name} running"
    script = """
set +e

failures=0
fail() { echo "FAILED JOB CHECK: $*"; failures=$((failures + 1)); }

if ! kubectl -n "${namespace}" get job "${name}" -o name >/dev/null 2>&1; then
  fail "job ${namespace}/${name}: cannot read resource (missing or kubectl error)"
  exit 1
fi

active=$(kubectl -n "${namespace}" get job "${name}" -o jsonpath='{.status.active}')
failed_cond=$(kubectl -n "${namespace}" get job "${name}" \\
  -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}')

echo "job ${namespace}/${name}: active='$active' failed_cond='$failed_cond'"

if [ "$failed_cond" = "True" ]; then
  fail "job ${namespace}/${name} marked Failed"
fi
# Empty active means K8s `omitempty` dropped a zero, i.e. no active pods.
if [ -z "$active" ] || [ "$active" = "0" ]; then
  fail "job ${namespace}/${name} has no active pods"
fi

if [ "$failures" -gt 0 ]; then
  echo "Validation failed with $failures error(s) for job ${namespace}/${name}"
  exit 1
fi
echo "job ${namespace}/${name} is running"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}

# ValidateJobCompleted validates that a Kubernetes Job has completed
# successfully: .status.succeeded >= .spec.completions AND
# .status.conditions[type=Complete].status == "True".
ValidateJobCompleted = lambda \
    serviceConnection: str, \
    name: str, \
    namespace: str = "default", \
    displayName: str = "", \
    continueOnError: bool = Undefined \
    -> steps.Step {
    assert name != "", "name must be non-empty"
    title = displayName if displayName else "Validate job/${name} completed"
    script = """
set +e

failures=0
fail() { echo "FAILED JOB CHECK: $*"; failures=$((failures + 1)); }

if ! kubectl -n "${namespace}" get job "${name}" -o name >/dev/null 2>&1; then
  fail "job ${namespace}/${name}: cannot read resource (missing or kubectl error)"
  exit 1
fi

completions=$(kubectl -n "${namespace}" get job "${name}" -o jsonpath='{.spec.completions}')
succeeded=$(kubectl -n "${namespace}" get job "${name}" -o jsonpath='{.status.succeeded}')
complete_cond=$(kubectl -n "${namespace}" get job "${name}" \\
  -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')

echo "job ${namespace}/${name}: succeeded='$succeeded' completions='$completions' complete_cond='$complete_cond'"

if [ -z "$completions" ]; then
  fail "job ${namespace}/${name}: .spec.completions is missing; cannot evaluate completion"
  echo "Validation failed for job ${namespace}/${name}"
  exit 1
fi
# Empty succeeded means K8s `omitempty` dropped a zero, i.e. nothing succeeded yet.
[ -z "$succeeded" ] && succeeded=0
if [ "$succeeded" -lt "$completions" ]; then
  fail "job ${namespace}/${name} succeeded=$succeeded < completions=$completions"
fi
if [ "$complete_cond" != "True" ]; then
  fail "job ${namespace}/${name} Complete condition='$complete_cond' (expected True)"
fi

if [ "$failures" -gt 0 ]; then
  echo "Validation failed with $failures error(s) for job ${namespace}/${name}"
  exit 1
fi
echo "job ${namespace}/${name} completed successfully"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
