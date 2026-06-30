import azure_pipelines.ap.steps
import lib.steps.azure

# ValidateWorkloadHealth validates that a Kubernetes controller workload
# (Deployment, StatefulSet, or DaemonSet) is healthy. It first checks the
# resource status, then scans the full container logs of its pods for error
# patterns. Requires kubectl on the agent and a kubeconfig already in place
# (e.g. via GetCredentials).
#
# Job is intentionally not handled here -- use ValidateJobRunning /
# ValidateJobCompleted in validate_job.k instead.
#
# kind="*" is a wildcard: enumerate every Deployment/StatefulSet/DaemonSet in
# `namespace` and check each, then check every pod. Use it for namespaces you
# own; avoid for system namespaces.
ValidateWorkloadHealth = lambda \
    serviceConnection: str, \
    kind: "deployment" | "statefulset" | "daemonset" | "*", \
    name: str = "", \
    namespace: str = "default", \
    errorPatterns: str = "panic|fatal", \
    displayName: str = "", \
    continueOnError: bool = Undefined \
    -> steps.Step {
    assert (kind == "*" and name == "") or (kind != "*" and name != ""), \
        "name must be empty when kind=='*' and non-empty otherwise (got kind='${kind}', name='${name}')"
    assert "'" not in errorPatterns, \
        "errorPatterns must not contain single quotes (got ${errorPatterns})"

    defaultTitle = "Validate all workloads in ${namespace}" if kind == "*" else "Validate ${kind}/${name}"
    title = displayName if displayName else defaultTitle
    desc = "all workloads in ${namespace}" if kind == "*" else "${kind} ${namespace}/${name}"
    script = """
set +e

failures=0
fail() { echo "FAILED WORKLOAD CHECK: $*"; failures=$((failures + 1)); }

# check_controllers KIND DESIRED_PATH READY_PATH [NAME]
# If NAME is given, check just that one; otherwise check every instance of KIND.
check_controllers() {
  local kind=$1 desired_path=$2 ready_path=$3 name=$4
  local n desired ready names
  if [ -n "$name" ]; then
    names="$name"
  else
    names=$(kubectl -n "${namespace}" get "$kind" -o jsonpath='{.items[*].metadata.name}')
  fi
  for n in $names; do
    # Probe existence first so a missing object / API error fails loudly
    # instead of silently defaulting desired/ready to 0.
    if ! kubectl -n "${namespace}" get "$kind" "$n" -o name >/dev/null 2>&1; then
      fail "$kind ${namespace}/$n: cannot read resource (missing or kubectl error)"
      continue
    fi
    desired=$(kubectl -n "${namespace}" get "$kind" "$n" -o jsonpath="$desired_path")
    ready=$(kubectl -n "${namespace}" get "$kind" "$n" -o jsonpath="$ready_path")
    [ -z "$ready" ] && ready=0
    [ -z "$desired" ] && desired=0
    echo "$kind ${namespace}/$n: ready=$ready desired=$desired"
    if [ "$ready" != "$desired" ] || [ "$desired" = "0" ]; then
      fail "$kind ${namespace}/$n not fully ready ($ready/$desired)"
    fi
  done
}

check_pod() {
  local pod=$1
  echo "::: checking pod ${namespace}/$pod"
  local phase ready_cond not_ready log_output matches
  phase=$(kubectl -n "${namespace}" get pod "$pod" -o jsonpath='{.status.phase}' 2>/dev/null)
  case "$phase" in
    Succeeded)
      # Job pod that finished cleanly; skip readiness checks, still scan logs.
      ;;
    Running)
      ready_cond=$(kubectl -n "${namespace}" get pod "$pod" \\
        -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
      if [ "$ready_cond" != "True" ]; then
        fail "pod ${namespace}/$pod Ready condition=$ready_cond (expected True)"
        return
      fi
      not_ready=$(kubectl -n "${namespace}" get pod "$pod" \\
        -o jsonpath='{range .status.containerStatuses[?(@.ready==false)]}{.name} {end}')
      if [ -n "$not_ready" ]; then
        fail "pod ${namespace}/$pod has not-ready containers: $not_ready"
        return
      fi
      ;;
    *)
      fail "pod ${namespace}/$pod phase=$phase (expected Running or Succeeded)"
      return
      ;;
  esac
  log_output=$(kubectl -n "${namespace}" logs "$pod" --all-containers=true --prefix=true 2>&1)
  matches=$(printf '%s\\n' "$log_output" | grep -wEi '${errorPatterns}')
  if [ -n "$matches" ]; then
    echo "--- error lines in ${namespace}/$pod ---"
    printf '%s\\n' "$matches"
    echo "--- end ---"
    fail "pod ${namespace}/$pod logs contain error pattern"
  fi
}

# check_pods POD_LIST
# Scan each pod in a whitespace-separated list. Fails if the list is empty.
check_pods() {
  local pods=$1 pod
  if [ -z "$pods" ]; then
    fail "no pods found for ${desc}"
    return
  fi
  for pod in $pods; do
    check_pod "$pod"
  done
}

# check_controller_pods KIND NAME
# Resolve the controller's pods via its matchLabels and scan them.
check_controller_pods() {
  local kind=$1 name=$2 selector
  selector=$(kubectl -n "${namespace}" get "$kind" "$name" \\
    -o go-template='{{range $k,$v := .spec.selector.matchLabels}}{{$k}}={{$v}},{{end}}' \\
    | sed 's/,$//')
  if [ -z "$selector" ]; then
    fail "$kind ${namespace}/$name has no matchLabels selector (matchExpressions not supported)"
    return
  fi
  check_pods "$(kubectl -n "${namespace}" get pods -l "$selector" -o jsonpath='{.items[*].metadata.name}')"
}

case "${kind}" in
  "*")
    check_controllers deployment  '{.spec.replicas}'                 '{.status.readyReplicas}'
    check_controllers statefulset '{.spec.replicas}'                 '{.status.readyReplicas}'
    check_controllers daemonset   '{.status.desiredNumberScheduled}' '{.status.numberReady}'
    check_pods "$(kubectl -n "${namespace}" get pods -o jsonpath='{.items[*].metadata.name}')"
    ;;
  deployment|statefulset)
    check_controllers "${kind}" '{.spec.replicas}' '{.status.readyReplicas}' "${name}"
    check_controller_pods "${kind}" "${name}"
    ;;
  daemonset)
    check_controllers daemonset '{.status.desiredNumberScheduled}' '{.status.numberReady}' "${name}"
    check_controller_pods "${kind}" "${name}"
    ;;
esac

if [ "$failures" -gt 0 ]; then
  echo "Validation failed with $failures error(s) for ${desc}"
  exit 1
fi
echo "Validation passed for ${desc}"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
