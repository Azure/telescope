#!/usr/bin/env bash
# attrition-check.sh — NON-FATAL liveness check for the mock-cilium-agent layer.
#
# Compares the number of *Running* mock-cilium-agents against the KWOK virtual
# nodes they are meant to serve (1 agent per node) and reports any gaps:
#   - virtual nodes with NO Running agent serving them (lost coverage), and
#   - agent pods that are not Running (Pending / CrashLoopBackOff / Failed / ...).
#
# By design this NEVER fails the caller: it always exits 0 and only prints
# OK / WARN lines, so it is safe to drop into a scale-test loop or cron without
# aborting the run on transient attrition. (Mock agents are bare Pods, so a lost
# pod or a failed real-VM does NOT self-heal — re-run provision-kwok-layer.sh.)
#
# Usage:
#   KUBECONFIG_FILE=~/.kube/mockmesh3-1 ./attrition-check.sh
#   # several clusters in one pass:
#   KUBECONFIG_FILES="$HOME/.kube/mockmesh3-1 $HOME/.kube/mockmesh3-2" ./attrition-check.sh
#
# Optional:
#   AGENT_NS      agent namespace                   (default mock-clustermesh)
#   AGENT_LABEL   agent pod label selector          (default app=mock-cilium-agent)
#   NODE_LABEL    KWOK node label selector          (default type=kwok)
#   SERVES_LABEL  per-agent "serves node" label key (default mock-clustermesh/serves-node)
#
# Deliberately NO `set -e`: this check must never abort whatever invoked it.
set -uo pipefail

AGENT_NS="${AGENT_NS:-mock-clustermesh}"
AGENT_LABEL="${AGENT_LABEL:-app=mock-cilium-agent}"
NODE_LABEL="${NODE_LABEL:-type=kwok}"
SERVES_LABEL="${SERVES_LABEL:-mock-clustermesh/serves-node}"

# Resolve the set of kubeconfigs to check.
if [[ -n "${KUBECONFIG_FILES:-}" ]]; then
  read -r -a KCS <<< "${KUBECONFIG_FILES}"
elif [[ -n "${KUBECONFIG_FILE:-}" ]]; then
  KCS=("${KUBECONFIG_FILE}")
else
  echo "WARN: set KUBECONFIG_FILE=<path> (or KUBECONFIG_FILES=\"<p1> <p2>\"). Nothing to check."
  exit 0   # non-fatal even on misconfiguration
fi

overall_gap=0

for KC in "${KCS[@]}"; do
  KC="${KC/#\~/$HOME}"                          # expand a leading ~
  K() { kubectl --kubeconfig="$KC" "$@"; }
  CTX="$(basename "$KC")"

  if ! K version --request-timeout=10s >/dev/null 2>&1; then
    echo "── ${CTX} ───────────────────────────────"
    echo "   WARN: cluster unreachable via ${KC} (skipping, not failing)."
    overall_gap=1
    continue
  fi

  # Expected = KWOK virtual nodes.
  mapfile -t NODES < <(K get nodes -l "${NODE_LABEL}" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | sed '/^$/d' | sort)
  expected="${#NODES[@]}"

  # Served = distinct nodes that currently have a Running agent.
  mapfile -t SERVED < <(K -n "${AGENT_NS}" get pods -l "${AGENT_LABEL}" \
      --field-selector=status.phase=Running \
      -o jsonpath="{range .items[*]}{.metadata.labels['${SERVES_LABEL}']}{\"\n\"}{end}" 2>/dev/null \
      | sed '/^$/d' | sort -u)
  running="${#SERVED[@]}"

  # Agent pods that are NOT Running.
  mapfile -t NOTREADY < <(K -n "${AGENT_NS}" get pods -l "${AGENT_LABEL}" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.status.phase}{"\n"}{end}' 2>/dev/null \
      | grep -v '=Running$' | sed '/^$/d')

  echo "── ${CTX} ───────────────────────────────"
  echo "   KWOK nodes (expected agents) : ${expected}"
  echo "   agents Running (node served) : ${running}"

  if (( running >= expected )) && (( ${#NOTREADY[@]} == 0 )); then
    echo "   OK: every virtual node has a Running agent."
  else
    overall_gap=1
    declare -A have=()
    for s in "${SERVED[@]}"; do have["$s"]=1; done
    missing=()
    for n in "${NODES[@]}"; do [[ -z "${have[$n]:-}" ]] && missing+=("$n"); done
    if (( ${#missing[@]} > 0 )); then
      echo "   WARN: ${#missing[@]} node(s) with NO Running agent: ${missing[*]}"
      echo "         -> re-run provision-kwok-layer.sh to restore coverage."
    fi
    if (( ${#NOTREADY[@]} > 0 )); then
      echo "   WARN: ${#NOTREADY[@]} agent pod(s) not Running: ${NOTREADY[*]}"
    fi
    unset have
  fi
done

if (( overall_gap == 0 )); then
  echo "attrition-check: all clusters healthy."
else
  echo "attrition-check: gaps detected (see WARN above) — NOT failing run (exit 0)."
fi
exit 0
