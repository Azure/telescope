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
NUM_PROMPTS = 1000
INPUT_TOKENS = 512
OUTPUT_TOKENS = 128

createClusterScript = """
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
  --generate-ssh-keys

az aks nodepool add \\
  --cluster-name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --name "${GPU_POOL}" \\
  --node-vm-size "${GPU_VM_SIZE}" \\
  --node-count ${GPU_NODE_COUNT} \\
  --node-taints sku=gpu:NoSchedule \\
  --gpu-driver Install
"""

deployAndBenchmarkScript = """
kubectl create namespace "${NAMESPACE}"

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

START_SECONDS=$(date +%s)

cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: vllm-bench
  namespace: ${NAMESPACE}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: bench
        image: ${VLLM_IMAGE}
        command:
        - bash
        - -lc
        - |
          vllm bench serve \\
            --backend openai-chat \\
            --base-url http://vllm:8000 \\
            --endpoint /v1/chat/completions \\
            --model ${MODEL} \\
            --dataset-name random \\
            --random-input-len ${INPUT_TOKENS} \\
            --random-output-len ${OUTPUT_TOKENS} \\
            --request-rate ${REQUEST_RATE} \\
            --num-prompts ${NUM_PROMPTS} \\
            --save-result \\
            --result-filename /tmp/vllm-bench-result.json
          cat /tmp/vllm-bench-result.json
EOF

kubectl wait --for=condition=complete job/vllm-bench --namespace="${NAMESPACE}" --timeout=60m

END_SECONDS=$(date +%s)
DURATION_SECONDS=$((END_SECONDS - START_SECONDS))

BENCH_POD=$(kubectl get pod --namespace="${NAMESPACE}" -l job-name=vllm-bench -o jsonpath='{.items[0].metadata.name}')
kubectl cp "${NAMESPACE}/\${BENCH_POD}:/tmp/vllm-bench-result.json" /tmp/vllm-bench-result.json

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
python3 - <<PY
import json

with open("/tmp/vllm-bench-result.json", "r", encoding="utf-8") as f:
    bench = json.load(f)

duration_seconds = int("$DURATION_SECONDS")
gpu_node_count = ${GPU_NODE_COUNT}
hourly_cost = float("${GPU_NODE_HOURLY_COST_USD}")
total_cost = gpu_node_count * hourly_cost * duration_seconds / 3600.0
total_tokens = ${NUM_PROMPTS} * (${INPUT_TOKENS} + ${OUTPUT_TOKENS})

result = {
    "scenario": "vllm-qwen25-7b-cost-efficiency",
    "region": "${LOCATION}",
    "cluster": "${CLUSTER}",
    "model": "${MODEL}",
    "runtime": "vllm",
    "gpu_vm_size": "${GPU_VM_SIZE}",
    "gpu_node_count": gpu_node_count,
    "request_rate": ${REQUEST_RATE},
    "num_prompts": ${NUM_PROMPTS},
    "input_tokens_per_prompt": ${INPUT_TOKENS},
    "output_tokens_per_prompt": ${OUTPUT_TOKENS},
    "duration_seconds": duration_seconds,
    "estimated_cost_usd": total_cost,
    "estimated_cost_per_1m_tokens_usd": total_cost * 1_000_000 / total_tokens,
    "vllm_benchmark": bench,
}

wrapped_result = {
    "timestamp": "$TIMESTAMP",
    "run_id": "$(RUN_ID)",
    "run_url": "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)",
    "pipeline": "$(Build.DefinitionName)",
    "result": result,
}

with open("/tmp/run-result.json", "w", encoding="utf-8") as f:
    json.dump(wrapped_result, f)
PY

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
