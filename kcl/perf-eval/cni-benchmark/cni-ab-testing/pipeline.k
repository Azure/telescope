import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.util

SUBSCRIPTION_ID = "$(AZURE_SUBSCRIPTION_ID)"
SERVICE_CONNECTION = "$(AZURE_SERVICE_CONNECTION)"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "swedencentral"
CLUSTER = "cri-resource-consume"
VNET = "cri-vnet"
SUBNET = "cri-subnet-1"
NODE_SKU = "Standard_D16ds_v4"
KUBERNETES_VERSION = "1.33"
CL2_IMAGE = "ghcr.io/azure/clusterloader2:v20241016"
ASSET_ROOT = "kcl/perf-eval/cni-benchmark/cni-ab-testing"
CL2_PYTHON_ROOT = "$(Pipeline.Workspace)/s/${ASSET_ROOT}/assets/python"
CL2_CONFIG_DIR = "${CL2_PYTHON_ROOT}/clusterloader2/cri/config"
CL2_REPORT_DIR = "$(Pipeline.Workspace)/cl2-results"
TEST_RESULTS_FILE = "$(Pipeline.Workspace)/cni-ab-results.jsonl"

JOB_CONDITION = "or(eq(variables['Build.Reason'], 'Manual'), and(eq(variables['Build.Reason'], 'Schedule'), eq(variables['Build.SourceBranchName'], 'main')))"
MANAGED_RESOURCE_CONDITION = "not(\${{ parameters.skip_resource_management }})"
BYO_RESOURCE_CONDITION = "\${{ parameters.skip_resource_management }}"
CLEANUP_CONDITION = "and(always(), not(\${{ parameters.skip_resource_management }}), not(and(\${{ parameters.skip_resource_deletion }}, eq(variables['Build.Reason'], 'Manual'))))"
SKIP_CLEANUP_CONDITION = "and(always(), not(\${{ parameters.skip_resource_management }}), \${{ parameters.skip_resource_deletion }}, eq(variables['Build.Reason'], 'Manual'))"

profileVariables = lambda maxPods: int, operationTimeout: str -> {str:str} {
    {
        NODE_COUNT = "10"
        MAX_PODS = str(maxPods)
        REPEATS = "1"
        OPERATION_TIMEOUT = operationTimeout
        LOAD_TYPE = "memory"
        SCRAPE_KUBELETS = "True"
        HOST_NETWORK = "False"
    }
}

createAzureClusterStep = lambda variant: str, useCustomHeaders: bool -> steps.Step {
    customHeaderEnv = {CUSTOM_HEADERS = "$(AKS_CLI_CUSTOM_HEADERS)"} if useCustomHeaders else Undefined
    customHeaderSetup = """
ADO_CUSTOM_HEADERS_LITERAL='$'\"(AKS_CLI_CUSTOM_HEADERS)\"
if [ "\${CUSTOM_HEADERS:-}" != "$ADO_CUSTOM_HEADERS_LITERAL" ] && [ -n "\${CUSTOM_HEADERS:-}" ]; then
  AKS_CUSTOM_FLAGS+=(--aks-custom-headers "$CUSTOM_HEADERS")
fi
""" if useCustomHeaders else ""
    azure.AzCli(SERVICE_CONNECTION, "Create ${variant} AKS cluster", """
AKS_CUSTOM_FLAGS=()
${customHeaderSetup}

SUBNET_ID=$(az network vnet subnet show \
  --resource-group "${RESOURCE_GROUP}" \
  --vnet-name "${VNET}" \
  --name "${SUBNET}" \
  --subscription "${SUBSCRIPTION_ID}" \
  --query id -o tsv)

az aks create \
  --name "${CLUSTER}" \
  --resource-group "${RESOURCE_GROUP}" \
  --subscription "${SUBSCRIPTION_ID}" \
  --location "${LOCATION}" \
  --kubernetes-version "${KUBERNETES_VERSION}" \
  --dns-name-prefix "cri" \
  --tier standard \
  --nodepool-name default \
  --node-count 3 \
  --node-vm-size "${NODE_SKU}" \
  --node-osdisk-type Ephemeral \
  --nodepool-taints CriticalAddonsOnly=true:NoSchedule \
  --max-pods 250 \
  --network-plugin azure \
  --network-plugin-mode overlay \
  --pod-cidr 10.0.0.0/9 \
  --service-cidr 192.168.0.0/16 \
  --dns-service-ip 192.168.0.10 \
  --vnet-subnet-id "$SUBNET_ID" \
  --enable-managed-identity \
  --generate-ssh-keys \
  --tags "run_id=$(RUN_ID)" "role=client" "scenario=perf-eval-cni-ab-testing" "cni_variant=${variant}" \
  "\${AKS_CUSTOM_FLAGS[@]}" \
  --no-wait
""", condition=MANAGED_RESOURCE_CONDITION, env=customHeaderEnv)
}

createAzureNodePoolsStep = lambda useCustomHeaders: bool -> steps.Step {
    customHeaderEnv = {CUSTOM_HEADERS = "$(AKS_CLI_CUSTOM_HEADERS)"} if useCustomHeaders else Undefined
    customHeaderSetup = """
ADO_CUSTOM_HEADERS_LITERAL='$'\"(AKS_CLI_CUSTOM_HEADERS)\"
if [ "\${CUSTOM_HEADERS:-}" != "$ADO_CUSTOM_HEADERS_LITERAL" ] && [ -n "\${CUSTOM_HEADERS:-}" ]; then
  AKS_CUSTOM_HEADER_FLAGS+=(--aks-custom-headers "$CUSTOM_HEADERS")
fi
""" if useCustomHeaders else ""
    azure.AzCli(SERVICE_CONNECTION, "Create CRI benchmark node pools", """
AKS_CUSTOM_HEADER_FLAGS=()
${customHeaderSetup}

SUBNET_ID=$(az network vnet subnet show \
  --resource-group "${RESOURCE_GROUP}" \
  --vnet-name "${VNET}" \
  --name "${SUBNET}" \
  --subscription "${SUBSCRIPTION_ID}" \
  --query id -o tsv)

az aks nodepool add \
  --cluster-name "${CLUSTER}" \
  --resource-group "${RESOURCE_GROUP}" \
  --subscription "${SUBSCRIPTION_ID}" \
  --name prompool \
  --node-count 1 \
  --node-vm-size "${NODE_SKU}" \
  --node-osdisk-type Ephemeral \
  --mode User \
  --labels prometheus=true \
  --max-pods 250 \
  --vnet-subnet-id "$SUBNET_ID" \
  "\${AKS_CUSTOM_HEADER_FLAGS[@]}"

az aks nodepool add \
  --cluster-name "${CLUSTER}" \
  --resource-group "${RESOURCE_GROUP}" \
  --subscription "${SUBSCRIPTION_ID}" \
  --name userpool0 \
  --node-count 10 \
  --node-vm-size "${NODE_SKU}" \
  --node-osdisk-type Ephemeral \
  --mode User \
  --labels cri-resource-consume=true \
  --node-taints cri-resource-consume=true:NoSchedule,cri-resource-consume=true:NoExecute \
  --max-pods 250 \
  --vnet-subnet-id "$SUBNET_ID" \
  "\${AKS_CUSTOM_HEADER_FLAGS[@]}"
""", condition=MANAGED_RESOURCE_CONDITION, env=customHeaderEnv)
}

azureResourceSetupSteps = lambda variant: str -> [steps.Step] {
    [
        steps.Bash {
            bash = """
set -euo pipefail
CREATION_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
DELETION_DUE_TIME=$(date -u -d "+2 hour" +'%Y-%m-%dT%H:%M:%SZ')
echo "##vso[task.setvariable variable=CREATION_DATE]$CREATION_DATE"
echo "##vso[task.setvariable variable=DELETION_DUE_TIME]$DELETION_DUE_TIME"
echo "##vso[task.setvariable variable=OWNER]aks"
"""
            displayName = "Set resource lifecycle tags"
            condition = MANAGED_RESOURCE_CONDITION
        }
        azure.AzCli(SERVICE_CONNECTION, "Create benchmark resource group", """
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --subscription "${SUBSCRIPTION_ID}" \
  --tags \
"run_id=$(RUN_ID)" \
"scenario=perf-eval-cni-ab-testing" \
"owner=aks" \
"creation_date=$(CREATION_DATE)" \
"deletion_due_time=$(DELETION_DUE_TIME)" \
"SkipAKSCluster=1" \
"SkipASB_Audit=true" \
"cni_variant=${variant}"
""", condition=MANAGED_RESOURCE_CONDITION)
        azure.AzCli(SERVICE_CONNECTION, "Create CRI benchmark network", """
az network vnet create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VNET}" \
  --address-prefixes 10.0.0.0/9 \
  --subscription "${SUBSCRIPTION_ID}"
az network vnet subnet create \
  --resource-group "${RESOURCE_GROUP}" \
  --vnet-name "${VNET}" \
  --name "${SUBNET}" \
  --address-prefixes 10.0.0.0/16 \
  --subscription "${SUBSCRIPTION_ID}"
""", condition=MANAGED_RESOURCE_CONDITION)
    ]
}

waitForAzureClusterStep = lambda -> steps.Step {
    azure.AzCli(SERVICE_CONNECTION, "Wait for AKS cluster to succeed", """
while true; do
  STATE=$(az aks show \
--name "${CLUSTER}" \
--resource-group "${RESOURCE_GROUP}" \
--subscription "${SUBSCRIPTION_ID}" \
--query provisioningState -o tsv)
  echo "AKS provisioning state: $STATE"
  case "$STATE" in
Succeeded) break ;;
Failed|Canceled) exit 1 ;;
  esac
  sleep 30
done
""", condition=MANAGED_RESOURCE_CONDITION)
}

waitForAzureNodePoolsStep = lambda -> steps.Step {
    azure.AzCli(SERVICE_CONNECTION, "Wait for AKS node pools to succeed", """
for POOL in prompool userpool0; do
  while true; do
STATE=$(az aks nodepool show \
  --cluster-name "${CLUSTER}" \
  --resource-group "${RESOURCE_GROUP}" \
  --subscription "${SUBSCRIPTION_ID}" \
  --name "$POOL" \
  --query provisioningState -o tsv)
echo "Node pool $POOL provisioning state: $STATE"
case "$STATE" in
  Succeeded) break ;;
  Failed|Canceled) exit 1 ;;
esac
sleep 30
  done
done
""", condition=MANAGED_RESOURCE_CONDITION)
}

azureCredentialsSteps = lambda -> [steps.Step] {
    [
        azure.AzCli(SERVICE_CONNECTION, "Get managed AKS credentials", """
az aks get-credentials \
  --name "${CLUSTER}" \
  --resource-group "${RESOURCE_GROUP}" \
  --subscription "${SUBSCRIPTION_ID}" \
  --overwrite-existing
""", condition=MANAGED_RESOURCE_CONDITION)
        azure.AzCli(SERVICE_CONNECTION, "Validate OWNER and get BYO AKS credentials", """
set -euo pipefail
OWNER="\${{ parameters.owner }}"
CLUSTER_NAME="\${{ parameters.byo_azure_cluster_name }}"
CLUSTER_RESOURCE_GROUP="\${{ parameters.byo_azure_resource_group }}"
if [ -z "$OWNER" ]; then
  echo "##vso[task.logissue type=error;] OWNER is not set."
  exit 1
fi
if [ -z "$CLUSTER_NAME" ] || [ -z "$CLUSTER_RESOURCE_GROUP" ]; then
  echo "##vso[task.logissue type=error;] BYO Azure cluster name and resource group are required."
  exit 1
fi
echo "##vso[task.setvariable variable=OWNER]$OWNER"
az aks get-credentials \
  --name "$CLUSTER_NAME" \
  --resource-group "$CLUSTER_RESOURCE_GROUP" \
  --subscription "${SUBSCRIPTION_ID}" \
  --overwrite-existing
""", condition=BYO_RESOURCE_CONDITION)
    ]
}

validateNodesStep = lambda -> steps.Step {
    steps.Bash {
        bash = """
set -euo pipefail

deadline=$((SECONDS + 600))
while [ "$SECONDS" -lt "$deadline" ]; do
  total=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
  ready=$(kubectl get nodes --no-headers 2>/dev/null | awk '$2 == "Ready" {count++} END {print count+0}')
  echo "Cluster nodes: $ready/$total Ready; expected 14"
  if [ "$total" -eq 14 ] && [ "$ready" -eq 14 ]; then
    kubectl get nodes -L agentpool,prometheus,cri-resource-consume
    exit 0
  fi
  sleep 30
done

echo "Expected exactly 14 Ready nodes within 10 minutes."
kubectl get nodes -o wide
exit 1
"""
        displayName = "Validate 14 Ready nodes"
        timeoutInMinutes = 11
    }
}

cloudInfoStep = lambda cloud: str, region: str, variant: str -> steps.Step {
    result = azure.AzCli(SERVICE_CONNECTION, "Collect AKS cloud info", """
CLUSTER_NAME="${CLUSTER}"
CLUSTER_RESOURCE_GROUP="${RESOURCE_GROUP}"
BYO="\${{ parameters.skip_resource_management }}"
if [ "\${BYO,,}" = "true" ]; then
  CLUSTER_NAME="\${{ parameters.byo_azure_cluster_name }}"
  CLUSTER_RESOURCE_GROUP="\${{ parameters.byo_azure_resource_group }}"
fi
AKS_INFO=$(az aks show \
  --resource-group "$CLUSTER_RESOURCE_GROUP" \
  --name "$CLUSTER_NAME" \
  --subscription "${SUBSCRIPTION_ID}" \
  --output json)
CLOUD_INFO=$(echo "$AKS_INFO" | jq -c \
  --arg variant "${variant}" \
  '{cloud:"azure", region:.location, cluster:.name, kubernetes_version:.currentKubernetesVersion, sku_tier:.sku.tier, network_profile:.networkProfile, cni_variant:$variant}')
echo "Cloud info: $CLOUD_INFO"
echo "##vso[task.setvariable variable=CLOUD_INFO]$CLOUD_INFO"
""") if cloud == "azure" else steps.Bash {
        bash = """
set -euo pipefail
CLUSTER_NAME="$(RUN_ID)"
BYO="\${{ parameters.skip_resource_management }}"
if [ "\${BYO,,}" = "true" ]; then
  CLUSTER_NAME="\${{ parameters.byo_aws_cluster_name }}"
fi
EKS_INFO=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "${region}")
CLOUD_INFO=$(echo "$EKS_INFO" | jq -c '{cloud:"aws", region:.cluster.arn | split(":")[3], cluster:.cluster.name, kubernetes_version:.cluster.version}')
echo "Cloud info: $CLOUD_INFO"
echo "##vso[task.setvariable variable=CLOUD_INFO]$CLOUD_INFO"
"""
        displayName = "Collect EKS cloud info"
    }
    result
}

benchmarkSteps = lambda cloud: str, region: str, variant: str -> [steps.Step] {
    provider = "aks" if cloud == "azure" else "aws"
    registry = "akscritelescope.azurecr.io"
    resultJson = """{
    "status": "\${STATUS}",
    "scenario_type": "perf-eval",
    "scenario_name": "cni-ab-testing",
    "owner": "\${{ parameters.owner }}",
    "engine": "clusterloader2",
    "topology": "cri-resource-consume",
    "engine_input": {"image": "${CL2_IMAGE}"},
    "byo_resources": "\${{ parameters.skip_resource_management }}",
    "cloud": "${cloud}",
    "region": "${region}",
    "cni_variant": "${variant}",
    "node_count": 10,
    "max_pods": $(MAX_PODS),
    "repeats": 1,
    "load_type": "memory",
    "host_network": false,
    "scrape_kubelets": true,
    "measurements": \${MEASUREMENTS}
  }"""
    [
        steps.Bash {
            bash = """
set -euo pipefail

rm -rf "$CL2_REPORT_DIR"
mkdir -p "$CL2_REPORT_DIR"
rm -f "$TEST_RESULTS_FILE"

PYTHONPATH="$(Pipeline.Workspace)/s/modules/python:$CL2_PYTHON_ROOT" \
python3 "$CL2_PYTHON_ROOT/clusterloader2/cri/cri.py" override \
  --node_count "$NODE_COUNT" \
  --node_per_step "$NODE_COUNT" \
  --max_pods "$MAX_PODS" \
  --repeats "$REPEATS" \
  --operation_timeout "$OPERATION_TIMEOUT" \
  --load_type "$LOAD_TYPE" \
  --scale_enabled False \
  --pod_startup_latency_threshold 15s \
  --provider "${provider}" \
  --registry_endpoint "${registry}" \
  --test_image e2e-test-images/resource-consumer:1.13 \
  --os_type linux \
  --scrape_kubelets "$SCRAPE_KUBELETS" \
  --scrape_containerd False \
  --containerd_scrape_interval 15s \
  --host_network "$HOST_NETWORK" \
  --cl2_override_file "$CL2_CONFIG_DIR/overrides.yaml"

PYTHONPATH="$(Pipeline.Workspace)/s/modules/python:$CL2_PYTHON_ROOT" \
python3 "$CL2_PYTHON_ROOT/clusterloader2/cri/cri.py" execute \
  --cl2_image "$CL2_IMAGE" \
  --cl2_config_dir "$CL2_CONFIG_DIR" \
  --cl2_report_dir "$CL2_REPORT_DIR" \
  --kubeconfig "$HOME/.kube/config" \
  --provider "${provider}" \
  --scrape_kubelets "$SCRAPE_KUBELETS" \
  --scrape_containerd False
"""
            displayName = "Run ClusterLoader2 CRI benchmark"
            env = {
                CL2_PYTHON_ROOT = CL2_PYTHON_ROOT
                CL2_CONFIG_DIR = CL2_CONFIG_DIR
                CL2_REPORT_DIR = CL2_REPORT_DIR
                TEST_RESULTS_FILE = TEST_RESULTS_FILE
                CL2_IMAGE = CL2_IMAGE
            }
        }
        cloudInfoStep(cloud, region, variant)
        steps.Bash {
            bash = """
set -euo pipefail

PYTHONPATH="$(Pipeline.Workspace)/s/modules/python:$CL2_PYTHON_ROOT" \
python3 "$CL2_PYTHON_ROOT/clusterloader2/cri/cri.py" collect \
  --node_count "$NODE_COUNT" \
  --max_pods "$MAX_PODS" \
  --repeats "$REPEATS" \
  --load_type "$LOAD_TYPE" \
  --cl2_report_dir "$CL2_REPORT_DIR" \
  --cloud_info "$CLOUD_INFO" \
  --run_id "$(RUN_ID)" \
  --run_url "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)" \
  --result_file "$TEST_RESULTS_FILE" \
  --scrape_kubelets "$SCRAPE_KUBELETS" \
  --registry_info ""
"""
            displayName = "Collect ClusterLoader2 results"
            env = {
                CL2_PYTHON_ROOT = CL2_PYTHON_ROOT
                CL2_REPORT_DIR = CL2_REPORT_DIR
                TEST_RESULTS_FILE = TEST_RESULTS_FILE
            }
        }
        azure.AzCli(SERVICE_CONNECTION, "Build Telescope result", """
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if [ -s "${TEST_RESULTS_FILE}" ]; then
  MEASUREMENTS=$(jq -s '.' "${TEST_RESULTS_FILE}")
  FAILED=$(echo "$MEASUREMENTS" | jq '[.[] | select(.status == "failure")] | length')
else
  MEASUREMENTS='[]'
  FAILED=1
fi
STATUS="succeeded"
if [ "$FAILED" -gt 0 ]; then
  STATUS="failed"
fi
cat > /tmp/run-result.json << EOF
${util.formatResult(resultJson)}
EOF
jq . /tmp/run-result.json
""")
        common.UploadResult(SERVICE_CONNECTION, const.DEFAULT_STORAGE_ACCOUNT, const.DEFAULT_STORAGE_SUBSCRIPTION_ID, const.DEFAULT_STORAGE_CONTAINER)
    ]
}

azureCleanupSteps = lambda -> [steps.Step] {
    [
        steps.Bash {
            bash = """
echo "##vso[task.logissue type=warning;] Resource deletion was skipped for this manual run."
echo "Delete manually with: az group delete --name $(RUN_ID) --subscription ${SUBSCRIPTION_ID} --yes"
"""
            displayName = "Report skipped cleanup"
            condition = SKIP_CLEANUP_CONDITION
        }
        azure.DeleteResourceGroup(SERVICE_CONNECTION, RESOURCE_GROUP, SUBSCRIPTION_ID, condition=CLEANUP_CONDITION)
    ]
}

makeAzureJob = lambda {
    jobName: str,
    variant: str,
    useCustomHeaders: bool,
    maxPods: int,
    operationTimeout: str,
} -> job.Job {
    job.Job {
        job = jobName
        displayName = "${variant}: 10 nodes x ${maxPods} pods"
        timeoutInMinutes = 120
        condition = JOB_CONDITION
        variables = profileVariables(maxPods, operationTimeout)
        steps = [
            common.SetRunId()
            common.InstallPythonDependencies()
            azure.Login(SERVICE_CONNECTION, SUBSCRIPTION_ID, LOCATION)
        ] + azureResourceSetupSteps(variant) + [
            createAzureClusterStep(variant, useCustomHeaders)
            waitForAzureClusterStep()
            createAzureNodePoolsStep(useCustomHeaders)
            waitForAzureNodePoolsStep()
        ] + azureCredentialsSteps() + [
            validateNodesStep()
        ] + benchmarkSteps("azure", LOCATION, variant) + azureCleanupSteps()
    }
}

awsLoginSteps = lambda region: str -> [steps.Step] {
    [
        steps.Task {
            task = "AWSShellScript@1"
            inputs = {
                awsCredentials = "\${{ parameters.aws_service_connection }}"
                regionName = region
                scriptType = "inline"
                inlineScript = """
echo "##vso[task.setvariable variable=AWS_ACCESS_KEY_ID;issecret=true]$AWS_ACCESS_KEY_ID"
echo "##vso[task.setvariable variable=AWS_SECRET_ACCESS_KEY;issecret=true]$AWS_SECRET_ACCESS_KEY"
if [ -n "\${AWS_SESSION_TOKEN:-}" ]; then
  echo "##vso[task.setvariable variable=AWS_SESSION_TOKEN;issecret=true]$AWS_SESSION_TOKEN"
fi
"""
            }
            displayName = "Get AWS credentials"
        }
        steps.Bash {
            bash = """
set -euo pipefail
mkdir -p "$HOME/.aws"
aws configure set aws_access_key_id "$AWS_ACCESS_KEY_ID"
aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY"
ADO_LITERAL='$'"(AWS_SESSION_TOKEN)"
if [ "\${AWS_SESSION_TOKEN:-}" = "$ADO_LITERAL" ]; then
  AWS_SESSION_TOKEN=""
fi
if [ -n "\${AWS_SESSION_TOKEN:-}" ]; then
  aws configure set aws_session_token "$AWS_SESSION_TOKEN"
fi
aws configure set default.region "${region}"
aws sts get-caller-identity
"""
            displayName = "Configure AWS CLI"
            env = {
                AWS_ACCESS_KEY_ID = "$(AWS_ACCESS_KEY_ID)"
                AWS_SECRET_ACCESS_KEY = "$(AWS_SECRET_ACCESS_KEY)"
                AWS_SESSION_TOKEN = "$(AWS_SESSION_TOKEN)"
            }
        }
    ]
}

createEksStep = lambda region: str -> steps.Step {
    steps.Bash {
        bash = """
set -euo pipefail

if ! command -v eksctl >/dev/null 2>&1; then
  version="0.215.0"
  arch=$(uname -m)
  case "$arch" in
    x86_64) arch=amd64 ;;
    aarch64) arch=arm64 ;;
    *) echo "Unsupported architecture: $arch"; exit 1 ;;
  esac
  curl -fsSL "https://github.com/eksctl-io/eksctl/releases/download/v\${version}/eksctl_Linux_\${arch}.tar.gz" |
    tar -xz -C /tmp
  sudo install -m 0755 /tmp/eksctl /usr/local/bin/eksctl
fi
eksctl version

cat > "$(Pipeline.Workspace)/eksctl-cni-ab.yaml" << EOF
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: $(RUN_ID)
  region: ${region}
  version: "${KUBERNETES_VERSION}"
vpc:
  cidr: 10.0.0.0/16
  nat:
    gateway: Single
managedNodeGroups:
  - name: default
    instanceType: m5.4xlarge
    desiredCapacity: 3
    minSize: 3
    maxSize: 3
    amiFamily: AmazonLinux2023
    privateNetworking: false
  - name: prompool
    instanceType: m5.4xlarge
    desiredCapacity: 1
    minSize: 1
    maxSize: 1
    amiFamily: AmazonLinux2023
    privateNetworking: false
    labels:
      prometheus: "true"
  - name: userpool0
    instanceType: m5.4xlarge
    desiredCapacity: 10
    minSize: 10
    maxSize: 10
    amiFamily: AmazonLinux2023
    privateNetworking: false
    labels:
      cri-resource-consume: "true"
      agentpool: userpool0
    taints:
      - key: cri-resource-consume
        value: "true"
        effect: NoSchedule
      - key: cri-resource-consume
        value: "true"
        effect: NoExecute
addons:
  - name: coredns
  - name: vpc-cni
  - name: kube-proxy
EOF

eksctl create cluster --config-file "$(Pipeline.Workspace)/eksctl-cni-ab.yaml"
aws eks update-kubeconfig --name "$(RUN_ID)" --region "${region}"
"""
        displayName = "Create EKS benchmark cluster"
        condition = MANAGED_RESOURCE_CONDITION
    }
}

awsByoCredentialsStep = lambda region: str -> steps.Step {
    steps.Bash {
        bash = """
set -euo pipefail
OWNER="\${{ parameters.owner }}"
CLUSTER_NAME="\${{ parameters.byo_aws_cluster_name }}"
if [ -z "$OWNER" ]; then
  echo "##vso[task.logissue type=error;] OWNER is not set."
  exit 1
fi
if [ -z "$CLUSTER_NAME" ]; then
  echo "##vso[task.logissue type=error;] BYO AWS cluster name is required."
  exit 1
fi
echo "##vso[task.setvariable variable=OWNER]$OWNER"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "${region}"
"""
        displayName = "Validate OWNER and get BYO EKS credentials"
        condition = BYO_RESOURCE_CONDITION
    }
}

awsCleanupSteps = lambda region: str -> [steps.Step] {
    [
        steps.Bash {
            bash = """
echo "##vso[task.logissue type=warning;] EKS deletion was skipped for this manual run."
echo "Delete manually with: eksctl delete cluster --name $(RUN_ID) --region ${region}"
"""
            displayName = "Report skipped cleanup"
            condition = SKIP_CLEANUP_CONDITION
        }
        steps.Bash {
            bash = """
set -euo pipefail
eksctl delete cluster --name "$(RUN_ID)" --region "${region}" --wait
"""
            displayName = "Delete EKS benchmark cluster"
            condition = CLEANUP_CONDITION
        }
    ]
}

makeAwsJob = lambda jobName: str, maxPods: int, operationTimeout: str -> job.Job {
    region = "eu-west-1"
    job.Job {
        job = jobName
        displayName = "aws: 10 nodes x ${maxPods} pods"
        timeoutInMinutes = 120
        condition = JOB_CONDITION
        variables = profileVariables(maxPods, operationTimeout)
        steps = [
            common.SetRunId()
            common.InstallPythonDependencies()
        ] + awsLoginSteps(region) + [
            createEksStep(region)
            awsByoCredentialsStep(region)
            validateNodesStep()
        ] + benchmarkSteps("aws", region, "aws-vpc-cni") + awsCleanupSteps(region)
    }
}

output = ap.Pipeline {
    name = "CNI AB Testing"
    trigger = "none"
    pool = const.DEFAULT_POOL
    parameters = [
        ap.Parameter {
            name = "aws_service_connection"
            displayName = "AWS service connection"
            type = "string"
            default = "AWS-for-Telescope"
        }
        ap.Parameter {
            name = "skip_resource_management"
            displayName = "Use an existing cluster"
            type = "boolean"
            default = False
        }
        ap.Parameter {
            name = "skip_resource_deletion"
            displayName = "Keep resources after a manual run"
            type = "boolean"
            default = False
        }
        ap.Parameter {
            name = "owner"
            displayName = "Resource owner"
            type = "string"
            default = "aks"
        }
        ap.Parameter {
            name = "byo_azure_cluster_name"
            displayName = "Existing AKS cluster name"
            type = "string"
            default = ""
        }
        ap.Parameter {
            name = "byo_azure_resource_group"
            displayName = "Existing AKS resource group"
            type = "string"
            default = ""
        }
        ap.Parameter {
            name = "byo_aws_cluster_name"
            displayName = "Existing EKS cluster name"
            type = "string"
            default = ""
        }
    ]
    schedules = [ap.Cron {
        cron = "0 1-23/4 * * *"
        displayName = "Every 4 Hour (1AM start)"
        branches = {include = ["main"]}
        always = True
    }]
    variables = {
        SCENARIO_TYPE = "perf-eval"
        SCENARIO_NAME = "cni-ab-testing"
        AZURE_SERVICE_CONNECTION = const.DEFAULT_SERVICE_CONNECTION
        AZURE_SUBSCRIPTION_ID = const.DEFAULT_SUBSCRIPTION_ID
        AZURE_TELESCOPE_STORAGE_ACCOUNT_NAME = const.DEFAULT_STORAGE_ACCOUNT
    }
    stages = [
        ap.Stage {
            stage = "azure_swedencentral_default"
            displayName = "Default-CNI custom configuration"
            dependsOn = []
            variables = [ap.Group {group = "Default-CNI"}]
            jobs = [
                makeAzureJob("default_n10_p300_memory", "default", True, 30, "3m")
                makeAzureJob("default_n10_p700_memory", "default", True, 70, "7m")
                makeAzureJob("default_n10_p1100_memory", "default", True, 110, "11m")
            ]
        }
        ap.Stage {
            stage = "azure_swedencentral_stateless"
            displayName = "Stock Azure CNI Overlay"
            dependsOn = []
            jobs = [
                makeAzureJob("stateless_n10_p300_memory", "stateless", False, 30, "3m")
                makeAzureJob("stateless_n10_p700_memory", "stateless", False, 70, "7m")
                makeAzureJob("stateless_n10_p1100_memory", "stateless", False, 110, "11m")
            ]
        }
        ap.Stage {
            stage = "aws_westeurope"
            displayName = "AWS VPC CNI"
            dependsOn = []
            jobs = [
                makeAwsJob("aws_n10_p300_memory", 30, "3m")
                makeAwsJob("aws_n10_p700_memory", 70, "7m")
                makeAwsJob("aws_n10_p1100_memory", 110, "11m")
            ]
        }
    ]
}
