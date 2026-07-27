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
# AzCli wraps this script with `set -exo pipefail`. Disable xtrace here so
# tracing an assignment like `log_output=$(kubectl logs ...)` doesn't dump
# the full captured log to stdout. Also disable errexit so we can accumulate
# failures and report them at the end.
set +ex

failures=0
fail() { echo "FAILED WORKLOAD CHECK: $*"; failures=$((failures + 1)); }

# check_controllers KIND DESIRED_PATH READY_PATH [NAME]
# If NAME is given, check just that one; otherwise check every instance of KIND.
check_controllers() {
  local kind=$1 desired_path=$2 ready_path=$3 name=$4
  local names
  if [ -n "$name" ]; then
    names="$name"
  else
    names=$(kubectl -n "${namespace}" get "$kind" -o jsonpath='{.items[*].metadata.name}')
  fi
  local n
  for n in $names; do
    # Probe existence first so a missing object / API error fails loudly
    # instead of silently defaulting desired/ready to 0.
    if ! kubectl -n "${namespace}" get "$kind" "$n" -o name >/dev/null 2>&1; then
      fail "$kind ${namespace}/$n: cannot read resource (missing or kubectl error)"
      continue
    fi
    local desired=$(kubectl -n "${namespace}" get "$kind" "$n" -o jsonpath="$desired_path")
    local ready=$(kubectl -n "${namespace}" get "$kind" "$n" -o jsonpath="$ready_path")
    [ -z "$ready" ] && ready=0
    [ -z "$desired" ] && desired=0
    echo "$kind ${namespace}/$n: ready=$ready desired=$desired"
    if [ "$ready" != "$desired" ]; then
      fail "$kind ${namespace}/$n not fully ready ($ready/$desired)"
    fi
  done
}

# check_pods PODS_JSON_FILE
# PODS_JSON_FILE is a file holding a `kubectl get pods -o json` document with
# exactly the pods to check. For each: status is Running (Ready condition True,
# all containers ready) or Succeeded, then scan its logs for errorPatterns.
# Every field is read from the file, so the pod view is a single consistent
# snapshot the caller fetched in one API call. Fails if the file has no pods.
check_pods() {
  local pods_file=$1
  local names=$(jq -r '.items[].metadata.name' "$pods_file")
  if [ -z "$names" ]; then
    fail "no pods found for ${desc}"
    return
  fi
  local pod
  for pod in $names; do
    echo "::: checking pod ${namespace}/$pod"
    local pod_json=$(jq -c --arg n "$pod" '.items[] | select(.metadata.name==$n)' "$pods_file")
    local phase=$(printf '%s' "$pod_json" | jq -r '.status.phase // ""')
    case "$phase" in
      Succeeded)
        # Finished cleanly; skip readiness checks, still scan logs below.
        ;;
      Running)
        local ready_cond=$(printf '%s' "$pod_json" \\
          | jq -r '.status.conditions[]? | select(.type=="Ready") | .status')
        if [ "$ready_cond" != "True" ]; then
          fail "pod ${namespace}/$pod Ready condition=$ready_cond (expected True)"
          continue
        fi
        local not_ready=$(printf '%s' "$pod_json" \\
          | jq -r '[.status.containerStatuses[]? | select(.ready==false) | .name] | join(" ")')
        if [ -n "$not_ready" ]; then
          fail "pod ${namespace}/$pod has not-ready containers: $not_ready"
          continue
        fi
        ;;
      *)
        fail "pod ${namespace}/$pod phase=$phase (expected Running or Succeeded)"
        continue
        ;;
    esac
    local log_output=$(kubectl -n "${namespace}" logs "$pod" --all-containers=true --prefix=true 2>&1)
    local matches=$(printf '%s\\n' "$log_output" | grep -wEi '${errorPatterns}')
    if [ -n "$matches" ]; then
      echo "--- error lines in ${namespace}/$pod ---"
      printf '%s\\n' "$matches"
      echo "--- end ---"
      fail "pod ${namespace}/$pod logs contain error pattern"
    fi
  done
}

# check_controller_pods KIND NAME
# Resolve the controller's pods via its matchLabels and scan them.
check_controller_pods() {
  local kind=$1 name=$2
  local selector=$(kubectl -n "${namespace}" get "$kind" "$name" \\
    -o go-template='{{range $k,$v := .spec.selector.matchLabels}}{{$k}}={{$v}},{{end}}' \\
    | sed 's/,$//')
  if [ -z "$selector" ]; then
    fail "$kind ${namespace}/$name has no matchLabels selector (matchExpressions not supported)"
    return
  fi
  # Dump only this controller's pods (label-filtered) to a file in one call,
  # then let check_pods read it back (avoids passing a huge JSON blob as an arg).
  kubectl -n "${namespace}" get pods -l "$selector" -o json > "$PODS_JSON_FILE"
  check_pods "$PODS_JSON_FILE"
}

# Reusable temp file for the pods snapshot: each check below writes only the
# pods it needs into it, then reads back from the file. Using a file avoids
# passing a potentially huge JSON blob through shell command substitution.
PODS_JSON_FILE=$(mktemp)
trap 'rm -f "$PODS_JSON_FILE"' EXIT

case "${kind}" in
  "*")
    check_controllers deployment  '{.spec.replicas}'                 '{.status.readyReplicas}'
    check_controllers statefulset '{.spec.replicas}'                 '{.status.readyReplicas}'
    check_controllers daemonset   '{.status.desiredNumberScheduled}' '{.status.numberReady}'
    # Wildcard genuinely needs every pod in the namespace.
    kubectl -n "${namespace}" get pods -o json > "$PODS_JSON_FILE"
    check_pods "$PODS_JSON_FILE"
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
