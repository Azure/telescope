import azure_pipelines.ap.steps
import lib.steps.azure as azure

ASI_MANAGED_CLUSTER_URL = "https://asi.azure.ms/services/AKS/pages/Managed%20Cluster"
ASI_API_SERVER_ANALYZER_URL = "https://asi.azure.ms/services/AKS/pages/API%20Server%20Analyzer"

PrintAsiDashboardUrl = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscriptionId: str, startTime: str, endTime: str = "" -> steps.Step {
    azure.AzCli(
        serviceConnection,
        "Print ASI dashboard URL",
        """
RESOURCE_UID=$(az aks show \\
  --resource-group "${resourceGroup}" \\
  --name "${cluster}" \\
  --subscription "${subscriptionId}" \\
  --query "resourceUid" -o tsv)

if [ -z "$RESOURCE_UID" ]; then
  echo "##[warning]Failed to fetch resourceUid, skipping ASI URL"
  exit 1
fi

END_TIME="${endTime}"
if [ -z "$END_TIME" ]; then
  END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
fi

FROM_ENCODED=$(echo "${startTime}" | sed 's/:/%3A/g')
TO_ENCODED=$(echo "$END_TIME" | sed 's/:/%3A/g')

ASI_MC_URL="${ASI_MANAGED_CLUSTER_URL}?clusterVersion=$RESOURCE_UID&globalFrom=$FROM_ENCODED&globalTo=$TO_ENCODED"
APISERVER_ANALYZER_URL="${ASI_API_SERVER_ANALYZER_URL}?clusterVersion=$RESOURCE_UID&globalFrom=$FROM_ENCODED&globalTo=$TO_ENCODED"

echo "============================================"
echo "ASI Managed Cluster Dashboard URL:"
echo "$ASI_MC_URL"
echo ""
echo "ASI API Server Analyzer URL:"
echo "$APISERVER_ANALYZER_URL"
echo "============================================"
""",
        continueOnError=True)
}
