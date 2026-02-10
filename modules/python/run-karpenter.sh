#!/bin/bash
set -euo pipefail
set -x

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${REPO_ROOT}/.venv/bin/python"
SCENARIO_TYPE="perf-eval"
SCENARIO_NAME="nap-complex"
CLOUD="azure"

# ============================
# Step 1: Validate - Apply Karpenter NodePool
# ============================
echo "=== Validate: Applying Karpenter NodePool ==="

KARPENTER_NODEPOOL_FILE="${REPO_ROOT}/scenarios/${SCENARIO_TYPE}/${SCENARIO_NAME}/kubernetes/karpenter_nodepool.${CLOUD}.yml"

kubectl apply -f "$KARPENTER_NODEPOOL_FILE"

kubectl get nodepool default -o yaml
kubectl get nodepool spot -o yaml

echo "=== Validate complete ==="

# ============================
# Step 2: Execute - Run ClusterLoader2
# ============================
echo "=== Execute: Running ClusterLoader2 ==="

PYTHON_SCRIPT_FILE="${REPO_ROOT}/modules/python/clusterloader2/autoscale/autoscale.py"
CL2_IMAGE="ghcr.io/azure/clusterloader2:v20250912"
CL2_CONFIG_DIR="${REPO_ROOT}/modules/python/clusterloader2/autoscale/config"
CL2_REPORT_DIR="${REPO_ROOT}/modules/python/clusterloader2/autoscale/results"
CL2_CONFIG_FILE="ms_complex_config.yaml"
KUBECONFIG_PATH="${HOME}/.kube/config"

# Test parameters from pipeline matrix
POD_COUNT=5000
POD_CPU_REQUEST=16
POD_MEMORY_REQUEST="60Gi"
SCALE_UP_TIMEOUT="900s"
SCALE_DOWN_TIMEOUT="900s"
NODE_SELECTOR="{karpenter.sh/nodepool: default}"
NODE_LABEL_SELECTOR=""
LOOP_COUNT=1
WARMUP_DEPLOYMENT="true"
WARMUP_DEPLOYMENT_TEMPLATE="warmup_deployment.yaml"
ENABLE_PROMETHEUS="True"
SCRAPE_KUBELETS="True"
SCRAPE_KSM="True"
CPU_PER_NODE=0

cd "${REPO_ROOT}/modules/python"

# Override config
PYTHONPATH="${REPO_ROOT}/modules/python:${PYTHONPATH:-}" $PYTHON "$PYTHON_SCRIPT_FILE" override \
  ${CPU_PER_NODE} 0 ${POD_COUNT} \
  ${SCALE_UP_TIMEOUT} ${SCALE_DOWN_TIMEOUT} \
  ${LOOP_COUNT} "${NODE_LABEL_SELECTOR}" "${NODE_SELECTOR}" "${CL2_CONFIG_DIR}/overrides.yaml" ${WARMUP_DEPLOYMENT} "${CL2_CONFIG_DIR}" \
  --os_type linux \
  --warmup_deployment_template "${WARMUP_DEPLOYMENT_TEMPLATE}" \
  --deployment_template "" \
  --pod_cpu_request ${POD_CPU_REQUEST} \
  --pod_memory_request "${POD_MEMORY_REQUEST}" \
  --cl2_config_file "${CL2_CONFIG_FILE}" \
  --enable_prometheus ${ENABLE_PROMETHEUS}

# Clean up conflicting ServiceMonitor if prometheus is enabled
if [ "${ENABLE_PROMETHEUS}" = "True" ]; then
  echo "Removing conflicting master ServiceMonitor..."
  kubectl delete servicemonitor master -n monitoring --ignore-not-found=true || true
  sleep 2
fi

# Execute clusterloader2
PYTHONPATH="${REPO_ROOT}/modules/python:${PYTHONPATH:-}" $PYTHON "$PYTHON_SCRIPT_FILE" execute \
  "${CL2_IMAGE}" "${CL2_CONFIG_DIR}" "${CL2_REPORT_DIR}" "${KUBECONFIG_PATH}" aks \
  --cl2_config_file "${CL2_CONFIG_FILE}" \
  --enable_prometheus ${ENABLE_PROMETHEUS} \
  --scrape_kubelets ${SCRAPE_KUBELETS} \
  --scrape_ksm ${SCRAPE_KSM}

echo "=== Execute complete ==="