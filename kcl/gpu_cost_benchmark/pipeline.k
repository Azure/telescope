import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.util

SUBSCRIPTION_ID = "f6e2f77f-9959-42ad-87f0-c30a6abc0133"
SERVICE_CONNECTION = const.DEFAULT_SERVICE_CONNECTION
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "australiaeast"
CLUSTER = "ai-inference-cost"
NAMESPACE = "vllm-benchmark"

GPU_POOL = "gpupool"
GPU_VM_SIZE = "Standard_NC40ads_H100_v5"
GPU_NODE_COUNT = 1
GPU_NODE_HOURLY_COST_USD = "6.98"

MODEL = "Qwen/Qwen2.5-7B-Instruct"
VLLM_IMAGE = "vllm/vllm-openai:latest"

REQUEST_RATE = 10
TARGET_DURATION_SECONDS = 60
CASE_TIMEOUT_SECONDS = 1200
INPUT_TOKENS = 1024
OUTPUT_TOKENS = 512
BENCHMARK_CASES = [
    "30:512:128",
    "35:512:128",
    "40:512:128",
    "5:1024:512",
    "10:1024:512",
    "15:1024:512",
    "1:2048:2048",
    "2:2048:2048",
    "3:2048:2048",
    "5:2048:2048",
]
BENCHMARK_CASE_SPECS = "30:512:128 35:512:128 40:512:128 5:1024:512 10:1024:512 15:1024:512 1:2048:2048 2:2048:2048 3:2048:2048 5:2048:2048"

createClusterScript = """
az version
az upgrade --yes --only-show-errors || echo "Azure CLI upgrade failed or is unavailable on this agent; continuing with installed CLI."
az config set extension.dynamic_install_allow_preview=true
az extension add --name aks-preview --upgrade --allow-preview true || az extension add --name aks-preview --upgrade || az extension update --name aks-preview || true
az version

GPU_NODEPOOL_FLAGS="--gpu-driver Install"
if az aks nodepool add --help 2>/dev/null | grep -q -- "--enable-managed-gpu"; then
  GPU_NODEPOOL_FLAGS="--enable-managed-gpu=true"
fi
echo "Using GPU node pool flags: $GPU_NODEPOOL_FLAGS"

az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --tier standard \\
  --nodepool-name systempool \\
  --node-count 3 \\
  --node-vm-size "Standard_D8s_v5" \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.64.0.0/10 \\
  --service-cidr 10.0.0.0/16 \\
  --dns-service-ip 10.0.0.10 \\
  --outbound-type managedNATGateway \\
  --enable-managed-identity \\
  --enable-aad \\
  --enable-azure-rbac \\
  --generate-ssh-keys

az aks nodepool add \\
  --cluster-name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --name "${GPU_POOL}" \\
  --node-vm-size "${GPU_VM_SIZE}" \\
  --node-count 0 \\
  --node-taints sku=gpu:NoSchedule \\
  $GPU_NODEPOOL_FLAGS

for i in $(seq 1 60); do
  GPU_POOL_STATE=$(az aks nodepool show \\
    --cluster-name "${CLUSTER}" \\
    --resource-group "${RESOURCE_GROUP}" \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --name "${GPU_POOL}" \\
    --query provisioningState -o tsv)
  CLUSTER_STATE=$(az aks show \\
    --name "${CLUSTER}" \\
    --resource-group "${RESOURCE_GROUP}" \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --query provisioningState -o tsv)
  echo "Cluster provisioningState: $CLUSTER_STATE; GPU nodepool provisioningState: $GPU_POOL_STATE"
  if [ "$CLUSTER_STATE" = "Succeeded" ] && [ "$GPU_POOL_STATE" = "Succeeded" ]; then
    break
  fi
  sleep 30
done

if [ "$CLUSTER_STATE" != "Succeeded" ] || [ "$GPU_POOL_STATE" != "Succeeded" ]; then
  echo "AKS cluster or GPU nodepool did not reach Succeeded before scale-out test."
  az aks nodepool show \\
    --cluster-name "${CLUSTER}" \\
    --resource-group "${RESOURCE_GROUP}" \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --name "${GPU_POOL}" -o json
  exit 1
fi
"""

deployAndBenchmarkScript = """
kubectl create namespace "${NAMESPACE}"

GPU_SCALE_START_SECONDS=$(date +%s)
SCALE_SUCCEEDED=false
for i in $(seq 1 20); do
  if az aks nodepool scale \\
    --cluster-name "${CLUSTER}" \\
    --resource-group "${RESOURCE_GROUP}" \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --name "${GPU_POOL}" \\
    --node-count ${GPU_NODE_COUNT}; then
    SCALE_SUCCEEDED=true
    break
  fi
  echo "GPU nodepool scale attempt $i failed, likely due to a transient AKS operation conflict. Retrying in 30s..."
  sleep 30
done

if [ "$SCALE_SUCCEEDED" != "true" ]; then
  echo "Failed to scale GPU nodepool after retries."
  az aks nodepool show \\
    --cluster-name "${CLUSTER}" \\
    --resource-group "${RESOURCE_GROUP}" \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --name "${GPU_POOL}" -o json
  exit 1
fi

wait_for_gpu_allocatable() {
  attempts="$1"
  GPU_ALLOCATABLE=""
  for i in $(seq 1 "$attempts"); do
    GPU_ALLOCATABLE=$(kubectl get nodes -l kubernetes.azure.com/agentpool="${GPU_POOL}" -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}' 2>/dev/null || true)
    echo "GPU allocatable on ${GPU_POOL}: $GPU_ALLOCATABLE"
    if [ "$GPU_ALLOCATABLE" = "1" ]; then
      GPU_READY_SECONDS=$(($(date +%s) - GPU_SCALE_START_SECONDS))
      return 0
    fi
    sleep 30
  done
  return 1
}

if ! wait_for_gpu_allocatable 20; then
  echo "GPU is not allocatable yet; installing the NVIDIA device plugin for self-managed GPU setup."
  kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.1/deployments/static/nvidia-device-plugin.yml
  kubectl -n kube-system patch daemonset nvidia-device-plugin-daemonset --type='merge' -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.azure.com/agentpool":"${GPU_POOL}"},"tolerations":[{"key":"sku","operator":"Equal","value":"gpu","effect":"NoSchedule"},{"key":"nvidia.com/gpu","operator":"Exists","effect":"NoSchedule"}]}}}}'
  kubectl -n kube-system rollout status daemonset/nvidia-device-plugin-daemonset --timeout=15m
  wait_for_gpu_allocatable 60
fi

if [ "$GPU_ALLOCATABLE" != "1" ]; then
  kubectl get nodes -l kubernetes.azure.com/agentpool="${GPU_POOL}" -o wide
  kubectl describe nodes -l kubernetes.azure.com/agentpool="${GPU_POOL}"
  kubectl -n kube-system get pods -l name=nvidia-device-plugin-ds -o wide
  kubectl -n kube-system logs daemonset/nvidia-device-plugin-daemonset --all-containers=true --tail=200 || true
  exit 1
fi

VLLM_DEPLOY_START_SECONDS=$(date +%s)
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  progressDeadlineSeconds: 1800
  selector:
    matchLabels:
      app: vllm
  template:
    metadata:
      labels:
        app: vllm
    spec:
      enableServiceLinks: false
      nodeSelector:
        kubernetes.azure.com/agentpool: ${GPU_POOL}
      tolerations:
      - key: sku
        operator: Equal
        value: gpu
        effect: NoSchedule
      containers:
      - name: vllm
        image: ${VLLM_IMAGE}
        args:
        - --model
        - ${MODEL}
        - --host
        - 0.0.0.0
        - --port
        - "8000"
        ports:
        - containerPort: 8000
        resources:
          limits:
            nvidia.com/gpu: 1
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 60
          periodSeconds: 15
---
apiVersion: v1
kind: Service
metadata:
  name: vllm
  namespace: ${NAMESPACE}
spec:
  selector:
    app: vllm
  ports:
  - port: 8000
    targetPort: 8000
EOF

if ! kubectl rollout status deployment/vllm --namespace="${NAMESPACE}" --timeout=35m; then
  kubectl get pods --namespace="${NAMESPACE}" -o wide
  kubectl get events --namespace="${NAMESPACE}" --sort-by=.lastTimestamp
  kubectl describe deployment/vllm --namespace="${NAMESPACE}"
  kubectl describe pods --namespace="${NAMESPACE}"
  kubectl logs --namespace="${NAMESPACE}" deployment/vllm --all-containers=true --tail=200 || true
  exit 1
fi
VLLM_READY_EPOCH=$(date +%s)
VLLM_READY_SECONDS=$((VLLM_READY_EPOCH - VLLM_DEPLOY_START_SECONDS))

VLLM_POD=$(kubectl get pod --namespace="${NAMESPACE}" -l app=vllm -o jsonpath='{.items[0].metadata.name}')
kubectl logs --namespace="${NAMESPACE}" "$VLLM_POD" > /tmp/vllm-server.log || true
kubectl get pod --namespace="${NAMESPACE}" "$VLLM_POD" -o json > /tmp/vllm-pod.json
kubectl get events --namespace="${NAMESPACE}" --field-selector involvedObject.name="$VLLM_POD" -o json > /tmp/vllm-pod-events.json || echo '{"items":[]}' > /tmp/vllm-pod-events.json
python3 kcl/gpu_cost_benchmark/scripts/startup_metrics.py \\
  --pod-events /tmp/vllm-pod-events.json \\
  --pod-json /tmp/vllm-pod.json \\
  --server-log /tmp/vllm-server.log \\
  --ready-epoch "$VLLM_READY_EPOCH" \\
  --output /tmp/startup-metrics.json

MODEL_LOAD_SECONDS=$(python3 kcl/gpu_cost_benchmark/scripts/model_load_seconds.py --startup-metrics /tmp/startup-metrics.json)
echo "GPU ready seconds: $GPU_READY_SECONDS"
echo "vLLM ready seconds: $VLLM_READY_SECONDS"
echo "Model load seconds: $MODEL_LOAD_SECONDS"

START_SECONDS=$(date +%s)

cat <<'EOF' | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: vllm-bench
  namespace: ${NAMESPACE}
spec:
  backoffLimit: 0
  template:
    spec:
      enableServiceLinks: false
      restartPolicy: Never
      containers:
      - name: bench
        image: ${VLLM_IMAGE}
        command:
        - bash
        - -lc
        - |
          set -euo pipefail
          echo "[]" > /tmp/vllm-bench-results.json
          for CASE_SPEC in ${BENCHMARK_CASE_SPECS}; do
            IFS=':' read -r CASE_RPS CASE_INPUT_TOKENS CASE_OUTPUT_TOKENS <<< "$CASE_SPEC"
            CASE_NAME="in\${CASE_INPUT_TOKENS}-out\${CASE_OUTPUT_TOKENS}-rps\${CASE_RPS}"
            CASE_RESULT="/tmp/vllm-bench-result-\${CASE_NAME}.json"
            CASE_NUM_PROMPTS=$((CASE_RPS * ${TARGET_DURATION_SECONDS}))
            CASE_START_SECONDS=$(date +%s)
            echo "Running benchmark case \${CASE_NAME}"
            set +e
            timeout ${CASE_TIMEOUT_SECONDS}s vllm bench serve \\
              --backend openai-chat \\
              --base-url http://vllm:8000 \\
              --endpoint /v1/chat/completions \\
              --model ${MODEL} \\
              --dataset-name random \\
              --random-input-len "$CASE_INPUT_TOKENS" \\
              --random-output-len "$CASE_OUTPUT_TOKENS" \\
              --request-rate "$CASE_RPS" \\
              --num-prompts "$CASE_NUM_PROMPTS" \\
              --save-result \\
              --result-filename "$CASE_RESULT"
            CASE_EXIT_CODE=$?
            set -e
            echo "__VLLM_CASE_JSON_BEGIN__ \${CASE_NAME} \${CASE_RPS} \${CASE_INPUT_TOKENS} \${CASE_OUTPUT_TOKENS} \${CASE_NUM_PROMPTS}"
            if [ "$CASE_EXIT_CODE" -eq 0 ] && [ -s "$CASE_RESULT" ]; then
              cat "$CASE_RESULT"
            else
              CASE_DURATION_SECONDS=$(($(date +%s) - CASE_START_SECONDS))
              printf '{"error":"benchmark_failed_or_timeout","exit_code":%s,"duration":%s,"completed":0,"failed":%s,"request_rate":%s,"request_throughput":0,"p99_ttft_ms":null}\\n' \\
                "$CASE_EXIT_CODE" "$CASE_DURATION_SECONDS" "$CASE_NUM_PROMPTS" "$CASE_RPS"
            fi
            printf '\\n__VLLM_CASE_JSON_END__\\n'
            if [ "$CASE_EXIT_CODE" -ne 0 ]; then
              echo "Stopping RPS sweep after \${CASE_NAME}; benchmark failed or timed out with exit code $CASE_EXIT_CODE."
              break
            fi
          done
EOF

kubectl wait --for=condition=complete job/vllm-bench --namespace="${NAMESPACE}" --timeout=120m

END_SECONDS=$(date +%s)
DURATION_SECONDS=$((END_SECONDS - START_SECONDS))

BENCH_POD=$(kubectl get pod --namespace="${NAMESPACE}" -l job-name=vllm-bench -o jsonpath='{.items[0].metadata.name}')
kubectl logs --namespace="${NAMESPACE}" "$BENCH_POD" > /tmp/vllm-bench.log
python3 kcl/gpu_cost_benchmark/scripts/parse_bench_results.py \\
  --log-file /tmp/vllm-bench.log \\
  --default-input-tokens ${INPUT_TOKENS} \\
  --default-output-tokens ${OUTPUT_TOKENS} \\
  --output /tmp/vllm-bench-results.json
cat /tmp/vllm-bench-results.json

if [ ! -s /tmp/vllm-bench-results.json ]; then
  echo "Benchmark results JSON was not found in the benchmark pod logs."
  echo "Full benchmark pod logs:"
  cat /tmp/vllm-bench.log
  exit 1
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
python3 kcl/gpu_cost_benchmark/scripts/aggregate_run_result.py \\
  --startup-metrics /tmp/startup-metrics.json \\
  --benchmark-results /tmp/vllm-bench-results.json \\
  --duration-seconds "$DURATION_SECONDS" \\
  --gpu-ready-seconds "$GPU_READY_SECONDS" \\
  --vllm-ready-seconds "$VLLM_READY_SECONDS" \\
  --model-load-seconds "$MODEL_LOAD_SECONDS" \\
  --gpu-node-count ${GPU_NODE_COUNT} \\
  --hourly-cost "${GPU_NODE_HOURLY_COST_USD}" \\
  --location "${LOCATION}" \\
  --cluster "${CLUSTER}" \\
  --model "${MODEL}" \\
  --gpu-vm-size "${GPU_VM_SIZE}" \\
  --target-duration-seconds ${TARGET_DURATION_SECONDS} \\
  --timestamp "$TIMESTAMP" \\
  --run-id "$(RUN_ID)" \\
  --run-url "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)" \\
  --pipeline-name "$(Build.DefinitionName)" \\
  --output /tmp/run-result.json

cat /tmp/run-result.json
"""

output = ap.Pipeline {
    name = "AI Inferencing Cost Efficiency Benchmark"

    trigger = ["v2"]
    pool = const.DEFAULT_POOL

    jobs = [
        job.Job {
            job = "vllm_qwen25_7b"
            displayName = "vLLM Qwen2.5 7B cost efficiency benchmark"
            timeoutInMinutes = 240

            steps = [
                common.SetRunId(),
                common.InstallPythonDependencies(),
                azure.Login(SERVICE_CONNECTION, SUBSCRIPTION_ID, LOCATION),
                azure.CreateResourceGroup(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    LOCATION,
                    SUBSCRIPTION_ID,
                    tags = "scenario=vllm-qwen25-7b-cost-efficiency"),
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Create AKS GPU benchmark cluster",
                    createClusterScript),
                azure.GetCredentials(
                    SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Deploy vLLM and run benchmark",
                    deployAndBenchmarkScript),
                common.UploadResult(
                    SERVICE_CONNECTION,
                    const.DEFAULT_STORAGE_ACCOUNT,
                    const.DEFAULT_STORAGE_SUBSCRIPTION_ID,
                    const.DEFAULT_STORAGE_CONTAINER),
                azure.DeleteResourceGroup(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
