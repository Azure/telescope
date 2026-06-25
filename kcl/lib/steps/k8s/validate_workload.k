import azure_pipelines.ap.steps
import lib.steps.azure

# ValidateWorkloadHealth validates that a Kubernetes workload (Deployment,
# StatefulSet, DaemonSet, Job, or Pod) is healthy. It first checks the
# resource/pod status, then scans the full container logs for error patterns.
# Requires kubectl on the agent and a kubeconfig already in place (e.g. via
# GetCredentials).
#
# For Jobs, healthy means succeeded >= completions (all done) OR active>0
# without a Failed condition (still in progress). Anything else fails.
#
# kind="*" is a wildcard: enumerate every Deployment/StatefulSet/DaemonSet/Job
# in `namespace` and check each, then check every pod. Use it for namespaces
# you own; avoid for system namespaces.
ValidateWorkloadHealth = lambda \
    serviceConnection: str, \
    kind: str, \
    name: str = "", \
    namespace: str = "default", \
    errorPatterns: str = "panic|fatal", \
    displayName: str = "", \
    continueOnError: bool = Undefined \
    -> steps.Step {
    assert kind in ["deployment", "statefulset", "daemonset", "job", "pod", "*"], \
        "kind must be one of: deployment, statefulset, daemonset, job, pod, * (got ${kind})"
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
fail() { echo "FAIL: $*"; failures=$((failures + 1)); }

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

# check_jobs [NAME]
# Healthy = succeeded >= completions (done) OR active>0 without Failed condition
# (still running). Otherwise (Failed=True, or stalled with active=0 and not
# enough successes) fail.
check_jobs() {
  local name=$1
  local n names completions succeeded active failed_cond
  if [ -n "$name" ]; then
    names="$name"
  else
    names=$(kubectl -n "${namespace}" get jobs -o jsonpath='{.items[*].metadata.name}')
  fi
  for n in $names; do
    completions=$(kubectl -n "${namespace}" get job "$n" -o jsonpath='{.spec.completions}')
    succeeded=$(kubectl -n "${namespace}" get job "$n" -o jsonpath='{.status.succeeded}')
    active=$(kubectl -n "${namespace}" get job "$n" -o jsonpath='{.status.active}')
    failed_cond=$(kubectl -n "${namespace}" get job "$n" \\
      -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}')
    [ -z "$completions" ] && completions=1
    [ -z "$succeeded" ] && succeeded=0
    [ -z "$active" ] && active=0
    echo "job ${namespace}/$n: succeeded=$succeeded/$completions active=$active failed=$failed_cond"
    if [ "$failed_cond" = "True" ]; then
      fail "job ${namespace}/$n failed"
    elif [ "$succeeded" -lt "$completions" ] && [ "$active" = "0" ]; then
      fail "job ${namespace}/$n stalled (succeeded=$succeeded/$completions, no active pods)"
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

# 1. Resolve target controllers and pod set.
case "${kind}" in
  "*")
    check_controllers deployment  '{.spec.replicas}'                 '{.status.readyReplicas}'
    check_controllers statefulset '{.spec.replicas}'                 '{.status.readyReplicas}'
    check_controllers daemonset   '{.status.desiredNumberScheduled}' '{.status.numberReady}'
    check_jobs ""
    pods=$(kubectl -n "${namespace}" get pods -o jsonpath='{.items[*].metadata.name}')
    ;;
  pod)
    pods="${name}"
    ;;
  deployment|statefulset|daemonset|job)
    case "${kind}" in
      daemonset)
        check_controllers daemonset '{.status.desiredNumberScheduled}' '{.status.numberReady}' "${name}" ;;
      deployment|statefulset)
        check_controllers "${kind}" '{.spec.replicas}' '{.status.readyReplicas}' "${name}" ;;
      job)
        check_jobs "${name}" ;;
    esac
    # Resolve the controller's pods via its matchLabels.
    selector=$(kubectl -n "${namespace}" get "${kind}" "${name}" \\
      -o go-template='{{range $k,$v := .spec.selector.matchLabels}}{{$k}}={{$v}},{{end}}' \\
      | sed 's/,$//')
    if [ -z "$selector" ]; then
      fail "${kind} ${namespace}/${name} has no matchLabels selector (matchExpressions not supported)"
      pods=""
    else
      pods=$(kubectl -n "${namespace}" get pods -l "$selector" -o jsonpath='{.items[*].metadata.name}')
    fi
    ;;
esac

if [ -z "$pods" ]; then
  fail "no pods found for ${desc}"
fi

# 2. For each pod, check status and scan full logs.
for pod in $pods; do
  check_pod "$pod"
done

if [ "$failures" -gt 0 ]; then
  echo "Validation failed with $failures error(s) for ${desc}"
  exit 1
fi
echo "Validation passed for ${desc}"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
