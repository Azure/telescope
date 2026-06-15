import lib.scenario
import lib.steps.azure

LOCATION = "westus2"
CLUSTER = "stg-H2-yaolei"

# SkipAKSCluster disables Gatekeeper on ephemeral clusters
requestBody = """
{
    "location": "${LOCATION}",
    "identity": { "type": "SystemAssigned" },
    "sku": {
      "name": "Base",
      "tier": "Standard"
    },
    "tags": {
      "SkipAKSCluster": "true",
      "SkipASMAzSecPackAutoConfig": "true",
      "SkipLinuxAzSecPack": "true"
    },
    "properties": {
      "controlPlaneScalingProfile": {"scalingSize": "H2"},
      "kubernetesVersion": "1.33.0",
      "dnsPrefix": "${CLUSTER}-dns",
      "agentPoolProfiles": [
        {
          "name": "systempool",
          "mode": "System",
          "count": 30,
          "vmSize": "Standard_D8S_v4",
          "osType": "Linux",
          "maxPods": 250
        }
      ],
    "networkProfile": {
       "networkPlugin": "azure",
       "networkPluginMode": "overlay",
       "podCidr": "10.64.0.0/10",
       "serviceCidr": "10.0.0.0/16",
       "dnsServiceIP": "10.0.0.10",
       "outboundType": "managedNATGateway",
       "natGatewayProfile": {
          "managedOutboundIPProfile": {
            "count": 10
          }
        }
      }
    }
  }"""

cl2ResultJson = """{
    "cl2_status": "\${STATUS}", 
    "region": "${LOCATION}"
  }"""

output = scenario.build(scenario.Cl2Benchmark {
    name = "Example Pipeline"
    location = LOCATION
    cluster = CLUSTER
    requestBody = requestBody

    nodePool = azure.NodePool {
        name = "cl2pool"
        sku = "Standard_D8S_v4"
        count = 4
        taintPrefix = "cl2pool"
    }

    kwokNodeCount = 100
    kwokNodeManifest = "$(Pipeline.Workspace)/s/kcl/example_pipeline/kwok-node.yaml"

    cl2Namespace = "clusterloader2"
    cl2Manifest = "kcl/example_pipeline/cl2.yaml"

    resultJson = cl2ResultJson
})
