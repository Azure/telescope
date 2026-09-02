import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const


WORKLOAD_DIR = "$(Build.SourcesDirectory)/kcl/ccp_team/elastic_san_static_scale"
RUN_ROOT = "$(Agent.TempDirectory)/elastic-san-static/$(Build.BuildId)/$(System.StageName)"
RESULT_ROOT = "${RUN_ROOT}/results"
KUBECONFIG = "${RUN_ROOT}/kubeconfig"
PYTHON_DEPS = "${RUN_ROOT}/python-deps"


azCli = lambda displayName: str, script: str, env: {str:str} -> steps.Step {
    steps.Task {
        task = "AzureCLI@2"
        inputs = {
            azureSubscription = const.DEFAULT_SERVICE_CONNECTION
            scriptType = "bash"
            scriptLocation = "inlineScript"
            inlineScript = "set -exo pipefail\n" + script
        }
        displayName = displayName
        env = env
    }
}


publishArtifact = lambda path: str, name: str -> steps.Step {
    steps.Task {
        task = "PublishPipelineArtifact@1"
        displayName = "Publish ${name} results"
        condition = "always()"
        inputs = {
            targetPath = path
            artifact = name
        }
    }
}


resolveClusterFunction = """
resolve_cluster() {
    local cluster_id="$1"
    local output="$2"
    local cluster_id_lower
    local arm_subscription
    local cluster_name
    local resource_group
    local raw

    if [ -z "$cluster_id" ] || [ "$cluster_id" = "none" ]; then
        echo "cluster_id must be a full AKS ARM resource ID" >&2
        return 1
    fi

    raw=$(mktemp)
    cluster_id_lower=$(printf '%s' "$cluster_id" | tr '[:upper:]' '[:lower:]')
    if [[ ! "$cluster_id_lower" =~ ^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/microsoft.containerservice/managedclusters/[^/]+$ ]]; then
        echo "invalid AKS ARM resource ID: $cluster_id" >&2
        rm -f "$raw"
        return 1
    fi
    arm_subscription=$(printf '%s' "$cluster_id" | cut -d/ -f3)
    resource_group=$(printf '%s' "$cluster_id" | cut -d/ -f5)
    cluster_name=$(printf '%s' "$cluster_id" | cut -d/ -f9)
    az account set --subscription "$arm_subscription"
    az aks show \\
        --subscription "$arm_subscription" \\
        --resource-group "$resource_group" \\
        --name "$cluster_name" \\
        -o json > "$raw"

    jq --arg subscription_id "$arm_subscription" '{
        subscription_id: $subscription_id,
        name: .name,
        resource_group: .resourceGroup,
        node_resource_group: .nodeResourceGroup,
        location: .location,
        resource_uid: (.resourceUid // error("AKS resourceUid is missing")),
        subnet_ids: ([.agentPoolProfiles[]?.vnetSubnetId | select(. != null and . != "")] | unique | sort)
    }' "$raw" > "\${output}.tmp"
    mv "\${output}.tmp" "$output"
    rm -f "$raw"
}
"""


ensureResultDirectories = lambda -> steps.Step {
    steps.Bash {
        bash = "mkdir -p '${RESULT_ROOT}/resolve' '${RESULT_ROOT}/provision' '${RESULT_ROOT}/repair' '${RESULT_ROOT}/attach'"
        displayName = "Prepare result directories"
    }
}


cleanupAgent = lambda -> steps.Step {
    steps.Bash {
        bash = "rm -f '${KUBECONFIG}'"
        displayName = "Remove generated kubeconfig"
        condition = "always()"
    }
}


resolveScript = resolveClusterFunction + """
mkdir -p "${RESULT_ROOT}/resolve"
resolve_cluster \\
    "$PARAM_CLUSTER_ID" \\
    "${RESULT_ROOT}/resolve/cluster.json"
cat "${RESULT_ROOT}/resolve/cluster.json"
"""


prepareAgentScript = resolveClusterFunction + """
mkdir -p "${RESULT_ROOT}/provision" "${RESULT_ROOT}/attach"
resolve_cluster \\
    "$PARAM_CLUSTER_ID" \\
    "${RESULT_ROOT}/cluster.json"
CLUSTER_NAME=$(jq -r .name "${RESULT_ROOT}/cluster.json")
CLUSTER_RG=$(jq -r .resource_group "${RESULT_ROOT}/cluster.json")
CLUSTER_SUBSCRIPTION=$(jq -r .subscription_id "${RESULT_ROOT}/cluster.json")
az aks get-credentials \\
    --subscription "$CLUSTER_SUBSCRIPTION" \\
    --resource-group "$CLUSTER_RG" \\
    --name "$CLUSTER_NAME" \\
    --file "${KUBECONFIG}" \\
  --overwrite-existing
mkdir -p "${PYTHON_DEPS}"
python3 -m pip install --disable-pip-version-check \\
    --target "${PYTHON_DEPS}" \\
  -r "${WORKLOAD_DIR}/requirements.txt"
"""


provisionScript = """
mkdir -p "${RESULT_ROOT}/provision"
PYTHONPATH="${PYTHON_DEPS}" python3 "${WORKLOAD_DIR}/provision.py" \\
    --cluster-info "${RESULT_ROOT}/cluster.json" \\
    --san-prefix "tel-esan" \\
    --target-total-volumes "$PARAM_TARGET_TOTAL_VOLUMES" \\
    --volume-groups-per-san "$PARAM_VOLUME_GROUPS_PER_SAN" \\
    --volumes-per-group "$PARAM_VOLUMES_PER_GROUP" \\
    --volume-size-gib "$PARAM_VOLUME_SIZE_GIB" \\
    --base-size-tib "$PARAM_BASE_SIZE_TIB" \\
    --extended-size-tib "$PARAM_EXTENDED_SIZE_TIB" \\
    --availability-zone "$PARAM_AVAILABILITY_ZONE" \\
    --max-volume-writes-per-hour "$PARAM_MAX_VOLUME_WRITES_PER_HOUR" \\
    --max-volume-writes-per-burst "$PARAM_MAX_VOLUME_WRITES_PER_BURST" \\
    --burst-window-seconds "$PARAM_BURST_WINDOW_SECONDS" \\
    --batch-size "100" \\
    --batch-delay-seconds "1" \\
    --validation-timeout-seconds "1800" \\
    --kubeconfig "${KUBECONFIG}" \\
    --results-dir "${RESULT_ROOT}/provision" \\
    2>&1 | tee "${RESULT_ROOT}/provision/run.log"
"""


repairScript = """
mkdir -p "${RESULT_ROOT}/repair"
PYTHONPATH="${PYTHON_DEPS}" python3 "${WORKLOAD_DIR}/repair.py" \\
    --cluster-info "${RESULT_ROOT}/cluster.json" \\
    --kubeconfig "${KUBECONFIG}" \\
    --max-volume-writes-per-hour "$PARAM_MAX_VOLUME_WRITES_PER_HOUR" \\
    --max-volume-writes-per-burst "$PARAM_MAX_VOLUME_WRITES_PER_BURST" \\
    --burst-window-seconds "$PARAM_BURST_WINDOW_SECONDS" \\
    --target-total-volumes "$PARAM_TARGET_TOTAL_VOLUMES" \\
    --volume-groups-per-san "$PARAM_VOLUME_GROUPS_PER_SAN" \\
    --volumes-per-group "$PARAM_VOLUMES_PER_GROUP" \\
    --volume-size-gib "$PARAM_VOLUME_SIZE_GIB" \\
    --results-dir "${RESULT_ROOT}/repair" \\
    2>&1 | tee "${RESULT_ROOT}/repair/run.log"
"""


attachScript = """
mkdir -p "${RESULT_ROOT}/attach"
include_args=""
if [ -n "$PARAM_INCLUDE_SAN_NAMES" ]; then
  include_args="--include-san-name $PARAM_INCLUDE_SAN_NAMES"
fi
PYTHONPATH="${PYTHON_DEPS}" python3 "${WORKLOAD_DIR}/attach.py" \\
    --cluster-info "${RESULT_ROOT}/cluster.json" \\
    --kubeconfig "${KUBECONFIG}" \\
    --attach-limit "$PARAM_ATTACH_LIMIT" \\
    $include_args \\
    --workload-node-selector "kubernetes.azure.com/mode=user" \\
    --pods-per-node "$PARAM_PODS_PER_NODE" \\
    --pod-slot-headroom "10" \\
    --namespace-prefix "telescope-esan" \\
    --apply-batch-size "100" \\
    --pod-image "$PARAM_POD_IMAGE" \\
    --cpu-request "$PARAM_POD_CPU_REQUEST" \\
    --memory-request "$PARAM_POD_MEMORY_REQUEST" \\
    --wait-timeout-seconds "$PARAM_ATTACH_TIMEOUT_SECONDS" \\
    --results-dir "${RESULT_ROOT}/attach" \\
    2>&1 | tee "${RESULT_ROOT}/attach/run.log"
"""


output = ap.Pipeline {
    name = "Elastic SAN Static Scale"
    trigger = "none"
    pool = const.DEFAULT_POOL

    parameters = [
        ap.Parameter {
            name = "cluster_id"
            displayName = "Existing AKS ARM resource ID"
            type = "string"
            default = "none"
        }
        ap.Parameter {
            name = "run_provision"
            displayName = "Run static volume provisioning"
            type = "boolean"
            default = False
        }
        ap.Parameter {
            name = "run_repair"
            displayName = "Repair failed managed volumes"
            type = "boolean"
            default = False
        }
        ap.Parameter {
            name = "run_attach"
            displayName = "Attach currently unattached managed volumes"
            type = "boolean"
            default = False
        }
        ap.Parameter {
            name = "target_total_volumes"
            displayName = "Desired total ESAN volumes (existing cluster plus managed SANs)"
            type = "number"
            default = 40000
        }
        ap.Parameter {
            name = "volume_groups_per_san"
            displayName = "Volume groups per new SAN"
            type = "number"
            default = 200
        }
        ap.Parameter {
            name = "volumes_per_group"
            displayName = "Volumes per volume group"
            type = "number"
            default = 100
        }
        ap.Parameter {
            name = "volume_size_gib"
            displayName = "Volume size (GiB)"
            type = "number"
            default = 1
        }
        ap.Parameter {
            name = "base_size_tib"
            displayName = "New SAN base capacity (TiB)"
            type = "number"
            default = 3
        }
        ap.Parameter {
            name = "extended_size_tib"
            displayName = "New SAN extended capacity (TiB)"
            type = "number"
            default = 17
        }
        ap.Parameter {
            name = "availability_zone"
            displayName = "New SAN availability zone (empty disables zonal placement)"
            type = "string"
            default = "2"
        }
        ap.Parameter {
            name = "max_volume_writes_per_hour"
            displayName = "Client-side Elastic SAN write budget per rolling hour"
            type = "number"
            default = 3000
        }
        ap.Parameter {
            name = "max_volume_writes_per_burst"
            displayName = "Client-side Elastic SAN writes allowed per burst window"
            type = "number"
            default = 20
        }
        ap.Parameter {
            name = "burst_window_seconds"
            displayName = "Burst window length in seconds for the write limiter"
            type = "number"
            default = 1.1
        }
        ap.Parameter {
            name = "attach_limit"
            displayName = "Successful managed volumes to attach (0 means all)"
            type = "number"
            default = 0
        }
        ap.Parameter {
            name = "include_san_names"
            displayName = "Also attach an extra SAN by name (e.g. experiment SAN; empty to skip)"
            type = "string"
            default = ""
        }
        ap.Parameter {
            name = "pods_per_node"
            displayName = "Attachment Pods per node"
            type = "number"
            default = 150
        }
        ap.Parameter {
            name = "pod_image"
            displayName = "Attachment Pod image"
            type = "string"
            default = "ghcr.io/openclaw/openclaw:latest"
        }
        ap.Parameter {
            name = "pod_cpu_request"
            displayName = "Attachment Pod CPU request"
            type = "string"
            default = "300m"
        }
        ap.Parameter {
            name = "pod_memory_request"
            displayName = "Attachment Pod memory request"
            type = "string"
            default = "32Mi"
        }
        ap.Parameter {
            name = "attach_timeout_seconds"
            displayName = "Attachment readiness timeout"
            type = "number"
            default = 14400
        }
    ]

    stages = [
        ap.Stage {
            stage = "validate_cluster"
            displayName = "Validate existing AKS cluster"
            jobs = [job.Job {
                job = "resolve_cluster"
                displayName = "Resolve cluster resourceUid"
                timeoutInMinutes = 15
                steps = [
                    ensureResultDirectories(),
                    azCli(
                        "Resolve existing cluster",
                        resolveScript,
                        {PARAM_CLUSTER_ID = "\${{ parameters.cluster_id }}"}),
                    publishArtifact("${RESULT_ROOT}/resolve", "elastic-san-resolve"),
                ]
            }]
        }
        ap.Stage {
            stage = "provision"
            displayName = "Static Elastic SAN provision"
            dependsOn = ["validate_cluster"]
            condition = "and(succeeded(), \${{ parameters.run_provision }})"
            jobs = [job.Job {
                job = "provision_static_volumes"
                displayName = "Provision static volumes"
                timeoutInMinutes = 2880
                steps = [
                    ensureResultDirectories(),
                    azCli(
                        "Prepare cluster access and Python",
                        prepareAgentScript,
                        {PARAM_CLUSTER_ID = "\${{ parameters.cluster_id }}"}),
                    azCli(
                        "Plan or provision static volumes",
                        provisionScript,
                        {
                            PARAM_TARGET_TOTAL_VOLUMES = "\${{ parameters.target_total_volumes }}"
                            PARAM_VOLUME_GROUPS_PER_SAN = "\${{ parameters.volume_groups_per_san }}"
                            PARAM_VOLUMES_PER_GROUP = "\${{ parameters.volumes_per_group }}"
                            PARAM_VOLUME_SIZE_GIB = "\${{ parameters.volume_size_gib }}"
                            PARAM_BASE_SIZE_TIB = "\${{ parameters.base_size_tib }}"
                            PARAM_EXTENDED_SIZE_TIB = "\${{ parameters.extended_size_tib }}"
                            PARAM_AVAILABILITY_ZONE = "\${{ parameters.availability_zone }}"
                            PARAM_MAX_VOLUME_WRITES_PER_HOUR = "\${{ parameters.max_volume_writes_per_hour }}"
                            PARAM_MAX_VOLUME_WRITES_PER_BURST = "\${{ parameters.max_volume_writes_per_burst }}"
                            PARAM_BURST_WINDOW_SECONDS = "\${{ parameters.burst_window_seconds }}"
                        }),
                    publishArtifact("${RESULT_ROOT}/provision", "elastic-san-provision"),
                    cleanupAgent(),
                ]
            }]
        }
        ap.Stage {
            stage = "repair"
            displayName = "Repair failed Elastic SAN volumes"
            dependsOn = ["validate_cluster", "provision"]
            condition = "and(in(dependencies.validate_cluster.result, 'Succeeded', 'SucceededWithIssues'), in(dependencies.provision.result, 'Succeeded', 'SucceededWithIssues', 'Skipped'), \${{ parameters.run_repair }})"
            jobs = [job.Job {
                job = "repair_failed_volumes"
                displayName = "Repair failed managed volumes"
                timeoutInMinutes = 2880
                steps = [
                    ensureResultDirectories(),
                    azCli(
                        "Prepare cluster access and Python",
                        prepareAgentScript,
                        {PARAM_CLUSTER_ID = "\${{ parameters.cluster_id }}"}),
                    azCli(
                        "Repair failed static volumes",
                        repairScript,
                        {
                            PARAM_MAX_VOLUME_WRITES_PER_HOUR = "\${{ parameters.max_volume_writes_per_hour }}"
                            PARAM_MAX_VOLUME_WRITES_PER_BURST = "\${{ parameters.max_volume_writes_per_burst }}"
                            PARAM_BURST_WINDOW_SECONDS = "\${{ parameters.burst_window_seconds }}"
                            PARAM_TARGET_TOTAL_VOLUMES = "\${{ parameters.target_total_volumes }}"
                            PARAM_VOLUME_GROUPS_PER_SAN = "\${{ parameters.volume_groups_per_san }}"
                            PARAM_VOLUMES_PER_GROUP = "\${{ parameters.volumes_per_group }}"
                            PARAM_VOLUME_SIZE_GIB = "\${{ parameters.volume_size_gib }}"
                        }),
                    publishArtifact("${RESULT_ROOT}/repair", "elastic-san-repair"),
                    cleanupAgent(),
                ]
            }]
        }
        ap.Stage {
            stage = "attach"
            displayName = "Create PV/PVC and attach Pods"
            dependsOn = ["validate_cluster", "provision", "repair"]
            condition = "and(in(dependencies.validate_cluster.result, 'Succeeded', 'SucceededWithIssues'), in(dependencies.provision.result, 'Succeeded', 'SucceededWithIssues', 'Skipped'), in(dependencies.repair.result, 'Succeeded', 'SucceededWithIssues', 'Skipped'), \${{ parameters.run_attach }})"
            jobs = [job.Job {
                job = "attach_static_volumes"
                displayName = "Attach successful static volumes"
                timeoutInMinutes = 1440
                steps = [
                    ensureResultDirectories(),
                    azCli(
                        "Prepare cluster access and Python",
                        prepareAgentScript,
                        {PARAM_CLUSTER_ID = "\${{ parameters.cluster_id }}"}),
                    azCli(
                        "Plan or attach static volumes",
                        attachScript,
                        {
                            PARAM_ATTACH_LIMIT = "\${{ parameters.attach_limit }}"
                            PARAM_INCLUDE_SAN_NAMES = "\${{ parameters.include_san_names }}"
                            PARAM_PODS_PER_NODE = "\${{ parameters.pods_per_node }}"
                            PARAM_POD_IMAGE = "\${{ parameters.pod_image }}"
                            PARAM_POD_CPU_REQUEST = "\${{ parameters.pod_cpu_request }}"
                            PARAM_POD_MEMORY_REQUEST = "\${{ parameters.pod_memory_request }}"
                            PARAM_ATTACH_TIMEOUT_SECONDS = "\${{ parameters.attach_timeout_seconds }}"
                        }),
                    publishArtifact("${RESULT_ROOT}/attach", "elastic-san-attach"),
                    cleanupAgent(),
                ]
            }]
        }
    ]
}