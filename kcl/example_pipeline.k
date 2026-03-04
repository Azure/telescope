import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure

createClusterScript = """SUBSCRIPTION_ID="b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RG="telescope-v2-test"
CLUSTER="stg-H2-yaolei"
LOCATION="westus2"

az cloud update --endpoint-resource-manager https://eastus2euap.management.azure.com/
az rest \\
  --method put \\
  --uri "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG/providers/Microsoft.ContainerService/managedClusters/$CLUSTER?api-version=2026-01-02-preview" \\
  --body "{
    \\"location\\": \\"$LOCATION\\",
    \\"identity\\": { \\"type\\": \\"SystemAssigned\\" },
    \\"sku\\": {
      \\"name\\": \\"Base\\",
      \\"tier\\": \\"Standard\\"
    },
    \\"tags\\": {
      \\"exempted_by_qi\\": \\"36609072\\",
      \\"SkipAKSCluster\\": \\"true\\",
      \\"SkipASMAzSecPackAutoConfig\\": \\"true\\",
      \\"SkipLinuxAzSecPack\\": \\"true\\"
    },
    \\"properties\\": {
      \\"controlPlaneScalingProfile\\": {\\"scalingSize\\": \\"H2\\"},
      \\"kubernetesVersion\\": \\"1.33.0\\",
      \\"dnsPrefix\\": \\"$(CLUSTER)-dns\\",
      \\"agentPoolProfiles\\": [
        {
          \\"name\\": \\"systempool\\",
          \\"mode\\": \\"System\\",
          \\"count\\": 3,
          \\"vmSize\\": \\"Standard_D16S_v6\\",
          \\"osType\\": \\"Linux\\"
        }
      ],
    \\"networkProfile\\": {
       \\"networkPlugin\\": \\"azure\\",
       \\"networkPluginMode\\": \\"overlay\\",
       \\"podCidr\\": \\"10.64.0.0/10\\",
       \\"serviceCidr\\": \\"10.0.0.0/16\\",
       \\"dnsServiceIP\\": \\"10.0.0.10\\",
       \\"outboundType\\": \\"managedNATGateway\\",
       \\"natGatewayProfile\\": {
          \\"managedOutboundIPProfile\\": {
            \\"count\\": 10
          }
        }
      }
    }
  }"
"""

output = ap.Pipeline {
    name = "Example Pipeline"

    trigger =  ["v2"]
    pool = const.DEFAULT_POOL

    jobs = [
        job.Job {
            job = "deploy_to_azure"
            displayName = "Deploy to Azure"

            steps = [
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "b8ceb4e5-f05b-4562-a9f5-14acb1f24219",
                    "westus2"
                ),
                azure.AzCli(const.DEFAULT_SERVICE_CONNECTION,"Create cluster", createClusterScript)
            ]
        }
    ]
}
