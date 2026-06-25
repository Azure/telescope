#!/bin/bash
# CL2 ready-sentinel writer for Scenario #3 (Node Churn / IP Churn).
#
# Why a separate script and not inline `bash -c` in the CL2 yaml:
# The first iteration used `command: [bash, -c, |<inline>]` in the CL2
# Method:Exec block, with `CTX=$(kubectl config current-context)`. Build
# 67114 showed `kubectl config current-context` returning EMPTY in the CL2
# docker image's environment (verified by `Exec command output: wrote
# sentinel ready-` — context suffix was empty). Both clusters then wrote
# the SAME path (sentinels/ready-) and one overwrote the other → barrier
# saw 1/2 sentinels → quorum never reached → scenario aborted.
#
# This script is mounted into the CL2 container at
# /root/perf-tests/clusterloader2/config/write-ready-sentinel.sh by virtue
# of being a sibling of pod-churn-killer.sh / annotate-namespaces.sh /
# apiserver-failure-killer.sh (the CL2_CONFIG_DIR bind-mount). Same
# pattern, proven across scenarios #2/#4/#5/#7.
#
# Context-name resolution (multi-fallback for robustness):
#   1. Parse `current-context:` from /root/.kube/config directly (the
#      file is bind-mounted by run_cl2_command from the host's per-cluster
#      kubeconfig). YAML-safe grep + awk; no kubectl dependency.
#   2. `kubectl config current-context` via PATH kubectl.
#   3. Pre-staged kubectl at /root/perf-tests/clusterloader2/config/kubectl.
#   4. Hash of the kubeconfig server URL — guaranteed unique across
#      clusters in this mesh (different AKS APIServer URLs).
#   5. Hostname of the pod (CL2 pods get pod-name-suffixed). Last resort.
#
# All diagnostic output goes to STDERR so CL2 streamOutput captures it for
# postmortem. STDOUT only emits the final sentinel path.
#
# Positional args:
#   $1 SENTINEL_DIR   (required) absolute path; sentinel file lands here

set -uo pipefail

SENTINEL_DIR="${1:?sentinel dir required}"
mkdir -p "$SENTINEL_DIR"

KUBECONFIG_PATH="${KUBECONFIG:-/root/.kube/config}"
PRE_STAGED_KUBECTL="/root/perf-tests/clusterloader2/config/kubectl"

dbg() {
  # Diagnostic logging to stderr — captured by CL2 streamOutput.
  echo "write-ready-sentinel: $*" >&2
}

CTX=""
RESOLVED_BY=""

# Method 1: parse kubeconfig directly.
if [ -f "$KUBECONFIG_PATH" ]; then
  CTX=$(grep -E '^current-context:' "$KUBECONFIG_PATH" 2>/dev/null \
    | head -1 | awk '{print $2}' | tr -d '"' | tr -d "'" || echo "")
  if [ -n "$CTX" ]; then
    RESOLVED_BY="kubeconfig-parse"
  fi
fi

# Method 2: PATH kubectl.
if [ -z "$CTX" ] && command -v kubectl >/dev/null 2>&1; then
  CTX=$(kubectl config current-context 2>/dev/null || echo "")
  if [ -n "$CTX" ]; then
    RESOLVED_BY="kubectl-PATH"
  fi
fi

# Method 3: pre-staged kubectl.
if [ -z "$CTX" ] && [ -x "$PRE_STAGED_KUBECTL" ]; then
  CTX=$("$PRE_STAGED_KUBECTL" config current-context 2>/dev/null || echo "")
  if [ -n "$CTX" ]; then
    RESOLVED_BY="kubectl-prestaged"
  fi
fi

# Method 4: hash of server URL (deterministic per cluster; collision-safe
# across the mesh because every AKS has a unique FQDN).
if [ -z "$CTX" ] && [ -f "$KUBECONFIG_PATH" ]; then
  _server=$(grep -E '^\s*server:' "$KUBECONFIG_PATH" 2>/dev/null | head -1 \
    | awk '{print $2}' || echo "")
  if [ -n "$_server" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
      _hash=$(echo -n "$_server" | sha256sum | cut -c1-8)
    elif command -v md5sum >/dev/null 2>&1; then
      _hash=$(echo -n "$_server" | md5sum | cut -c1-8)
    else
      _hash=$(echo -n "$_server" | od -A n -t x1 | tr -d ' \n' | cut -c1-8)
    fi
    CTX="srv-${_hash}"
    RESOLVED_BY="server-hash"
  fi
fi

# Method 5: pod hostname (CL2 runs each cluster's CL2 in a separate
# docker container with a unique hostname).
if [ -z "$CTX" ]; then
  CTX="$(hostname 2>/dev/null || echo "unknown-$$")"
  RESOLVED_BY="hostname"
fi

# DIAGNOSTIC DUMP — always print state so postmortem on quorum failure
# can identify why context was hard to resolve.
dbg "===== CL2 ready-sentinel diagnostic ====="
dbg "resolved context = '${CTX}' via ${RESOLVED_BY}"
dbg "KUBECONFIG=${KUBECONFIG_PATH} exists=$( [ -f "$KUBECONFIG_PATH" ] && echo yes || echo no )"
if [ -f "$KUBECONFIG_PATH" ]; then
  dbg "kubeconfig current-context line: $(grep -E '^current-context:' "$KUBECONFIG_PATH" | head -1 || echo '(none)')"
  dbg "kubeconfig server line: $(grep -E '^\s*server:' "$KUBECONFIG_PATH" | head -1 || echo '(none)')"
fi
dbg "PATH=${PATH:-}"
dbg "PATH kubectl: $(command -v kubectl || echo '(none)')"
dbg "pre-staged kubectl exists+exec: $( [ -x "$PRE_STAGED_KUBECTL" ] && echo yes || echo no )"
dbg "hostname: $(hostname 2>/dev/null || echo '(none)')"
dbg "sentinel dir: ${SENTINEL_DIR}"
dbg "================================================"

# Guard: empty context after every fallback would still cause a path
# collision. Emit a unique fallback name using $$ (PID, unique-per-process).
if [ -z "$CTX" ]; then
  CTX="unresolved-$$"
  dbg "ERROR: every fallback returned empty; using ${CTX}"
fi

SENTINEL_FILE="${SENTINEL_DIR}/ready-${CTX}"
touch "$SENTINEL_FILE"
dbg "wrote sentinel ${SENTINEL_FILE}"
echo "$SENTINEL_FILE"
exit 0
