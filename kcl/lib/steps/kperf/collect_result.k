import azure_pipelines.ap.steps
import lib.steps.azure

# CollectKperfResult collects cloud info via az aks show, checks error rate,
# and writes the formatted result to outputPath for upload.
CollectKperfResult = lambda benchmarkSubcmdArgs: str, flowcontrol: str, cluster: str, resourceGroup: str, subscription: str, serviceConnection: str, inputPath: str = "/tmp/tmp_results.json", outputPath: str = "/tmp/run-result.json", errorRateThreshold: float = 0.1 -> steps.Step {
    azure.AzCli(serviceConnection, "Collect kperf benchmark result", """
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Collect cloud info
aks_info=$(az aks show --resource-group "${resourceGroup}" --name "${cluster}" --subscription "${subscription}" --output json)
cloud_info=$(jq -n \\
  --arg cloud "azure" \\
  --arg region "$(echo $aks_info | jq -r .location)" \\
  --arg fqdn "$(echo $aks_info | jq -r .fqdn)" \\
  --arg k8s_version "$(echo $aks_info | jq -r .currentKubernetesVersion)" \\
  --arg sku_tier "$(echo $aks_info | jq -r .sku.tier)" \\
  --arg subscription "${subscription}" \\
  --arg cluster_id "$(echo $aks_info | jq -r .resourceUid)" \\
  '{
    cloud: $cloud,
    region: $region,
    fqdn: $fqdn,
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
  | jq -c --argjson ci "$cloud_info" '{ cloud: $ci.cloud, region: $ci.region, fqdn: $ci.fqdn, k8s_version: $ci.k8s_version, sku_tier: $ci.sku_tier, subscription: $ci.subscription, cluster_id: $ci.cluster_id, flowcontrol: "${flowcontrol}", benchmarkSubcmdArgs: "${benchmarkSubcmdArgs}" } + .result | { result: . }' \\
  | jq -c '. + { timestamp: "'"$TIMESTAMP"'", run_id: "$(RUN_ID)", run_url: "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)", pipeline: "$(Build.DefinitionName)" }' \\
  > ${outputPath}

echo "Collected result:"
cat ${outputPath} | jq .
""")
}
