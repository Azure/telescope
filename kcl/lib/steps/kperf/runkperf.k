import azure_pipelines.ap.steps
import lib.steps.azure

# Default constants for kperf data ingestion
DEFAULT_QPS = 80
DEFAULT_BURST = 80
DEFAULT_SIZE_BYTES = 524288  # 0.5 MiB per object
DEFAULT_GROUP_SIZE = 80
BATCH_SIZE = 2000  # Internal batch size, not configurable by caller
BYTES_PER_GIB = 1073741824

InstallRunkperf = lambda runnerImage: str -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

temp_dir=$(mktemp -p /tmp -d kperfinstall.XXXX)
docker rmi ${runnerImage} 2>/dev/null || true
docker pull ${runnerImage}
docker run --rm -v $temp_dir:/install-dir \\
  ${runnerImage} bash -c "set -x; install /kperf /runkperf /install-dir"

sudo install $temp_dir/kperf $temp_dir/runkperf /usr/local/bin
rm -rf $temp_dir
docker rmi ${runnerImage} 2>/dev/null || true
"""
        displayName = "Install runkperf binary"
    }
}

# RunKperfDataIngest creates objects in fixed-size batches (BATCH_SIZE) to be
# resilient to failures — if a batch fails, only that batch needs to be retried, and the
# local in-memory counter stays accurate since each successful batch represents a known
# quantity. This avoids using kubectl get to count existing objects, which would OOM
# the pipeline agent by fetching full object bodies.
RunKperfDataIngest = lambda dataType: str, namespace: str, name: str, totalGiB: str, qps: int = DEFAULT_QPS, burst: int = DEFAULT_BURST, size: int = DEFAULT_SIZE_BYTES, groupSize: int = DEFAULT_GROUP_SIZE -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

TOTAL_OBJECTS_COUNT=$(( ${totalGiB} * ${BYTES_PER_GIB} / ${size} ))
TOTAL_BATCHES=$(( (TOTAL_OBJECTS_COUNT + ${BATCH_SIZE} - 1) / ${BATCH_SIZE} ))

kubectl create namespace ${namespace} 2>/dev/null || true

echo "Ingesting $TOTAL_OBJECTS_COUNT ${dataType}s in $TOTAL_BATCHES batches of ${BATCH_SIZE}..."

completed=0
for batch in $(seq 1 $TOTAL_BATCHES); do
  REMAINING=$((TOTAL_OBJECTS_COUNT - completed))
  COUNT=${BATCH_SIZE}
  if [ "$REMAINING" -lt "$COUNT" ]; then
    COUNT=$REMAINING
  fi

  echo "Batch $batch/$TOTAL_BATCHES: creating $COUNT ${dataType}s..."
  run_batch() {
    runkperf data ${dataType} \\
      --namespace ${namespace} \\
      add ${name}-b$batch-$1 \\
      --qps ${qps} \\
      --burst ${burst} \\
      --total $COUNT \\
      --size ${size} \\
      --group-size ${groupSize}
  }
  run_batch first || run_batch retry

  completed=$((completed + COUNT))
  STORAGE_GIB=$(awk 'BEGIN{printf "%.1f", '$completed' * ${size} / ${BYTES_PER_GIB}}')
  echo "Progress: $completed / $TOTAL_OBJECTS_COUNT ${dataType}s created (~$STORAGE_GIB GiB)"
done

echo "Ingest complete: $completed ${dataType}s created."
"""
        displayName = "Ingest ${dataType} data (${totalGiB} GiB)"
        condition = "and(succeeded(), ne('${totalGiB}', '0'))"
    }
}

# RunKperfBenchmark runs runkperf bench with the given subcommand and flow control settings.
# Results are written to resultPath (default /tmp/tmp_results.json) for collection by CollectKperfResult.
RunKperfBenchmark = lambda runnerImage: str, benchmarkSubcmd: str, benchmarkSubcmdArgs: str, kubeconfig: str, flowcontrol: str = "exempt:5", resultPath: str = "/tmp/tmp_results.json", target: str = None -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

export PATH="/:$PATH"

runkperf -v 3 bench \\
  --kubeconfig=${kubeconfig} \\
  --runner-image="${runnerImage}" \\
  --runner-flowcontrol="${flowcontrol}" \\
  --result ${resultPath} \\
  ${benchmarkSubcmd} ${benchmarkSubcmdArgs}
"""
        displayName = "Run kperf benchmark (${benchmarkSubcmd}, flowcontrol=${flowcontrol})"
        target = target
    }
}

# CollectKperfResult collects cloud info via az aks show, checks error rate,
# and writes the formatted result to outputPath for upload.
CollectKperfResult = lambda serviceConnection: str, flowcontrol: str, benchmarkSubcmdArgs: str, cluster: str, resourceGroup: str, subscription: str, inputPath: str = "/tmp/tmp_results.json", outputPath: str = "/tmp/run-result.json", errorRateThreshold: float = 0.1 -> steps.Step {
    azure.AzCli(serviceConnection, "Collect kperf benchmark result", """
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Collect cloud info
aks_info=$(az aks show --resource-group "${resourceGroup}" --name "${cluster}" --subscription "${subscription}" --output json)
cloud_info=$(jq -n \\
  --arg cloud "azure" \\
  --arg region "$(echo $aks_info | jq -r .location)" \\
  --arg fqdn "$(echo $aks_info | jq -r .fqdn)" \\
  --arg private_fqdn "$(echo $aks_info | jq -r '.privateFqdn // empty')" \\
  --arg k8s_version "$(echo $aks_info | jq -r .currentKubernetesVersion)" \\
  --arg sku_tier "$(echo $aks_info | jq -r .sku.tier)" \\
  --arg subscription "${subscription}" \\
  --arg cluster_id "$(echo $aks_info | jq -r .resourceUid)" \\
  '{
    cloud: $cloud,
    region: $region,
    fqdn: $fqdn,
    private_fqdn: $private_fqdn,
    k8s_version: $k8s_version,
    sku_tier: $sku_tier,
    subscription: $subscription,
    cluster_id: $cluster_id
  }')

# Check for errors and print error details if error rate exceeds threshold
errors_number=$(jq -r '.result.errors | length' ${inputPath})
error_rate_too_high=$(jq -r '(1 - .result.total / (.loadSpec.count * .loadSpec.loadProfile.spec.total)) > ${errorRateThreshold}' ${inputPath})
if [[ "$errors_number" != "0" && "$error_rate_too_high" == "true" ]]; then
  echo "Error rate exceeds ${errorRateThreshold}, printing error details:"
  jq -r ".result.errors | map(. + {run_id: \\"$(RUN_ID)\\", cloud: \\"azure\\"}) | .[]" ${inputPath}
fi

# Collect final result
cat ${inputPath} \\
  | jq 'del(.result.errors)' \\
  | jq -c --argjson ci "$cloud_info" '{ cloud: $ci.cloud, region: $ci.region, fqdn: $ci.fqdn, private_fqdn: $ci.private_fqdn, k8s_version: $ci.k8s_version, sku_tier: $ci.sku_tier, subscription: $ci.subscription, cluster_id: $ci.cluster_id, flowcontrol: "${flowcontrol}", benchmarkSubcmdArgs: "${benchmarkSubcmdArgs}" } + .result | { result: . }' \\
  | jq -c '. + { timestamp: "'"$TIMESTAMP"'", run_id: "$(RUN_ID)", run_url: "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)", pipeline: "$(Build.DefinitionName)" }' \\
  > ${outputPath}

echo "Collected result:"
cat ${outputPath} | jq .
""")
}
