scenario_type  = "perf-eval"
scenario_name  = "ccp-provisioning-H2"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "client"
    aks_name           = "ccp-provisioning-H2"
    sku_tier           = "standard"
    kubernetes_version = "1.33"
    use_az_rest        = true
    rest_call_config = {
      method      = "PUT"
      api_version = "2026-01-02-preview"
      body        = <<-EOF
        {
          "location": "$${location}",
          "identity": {
            "type": "SystemAssigned"
          },
          "sku": {
            "name": "Base",
            "tier": "Standard"
          },
          "properties": {
            "kubernetesVersion": "1.33.0",
            "dnsPrefix": "ccp-provisioning-H2-test",
            "agentPoolProfiles": [
              {
                "name": "nodepool1",
                "count": 3,
                "vmSize": "Standard_DS2_v2",
                "osType": "Linux",
                "mode": "System"
              }
            ],
            "networkProfile": {
              "networkPlugin": "azure",
              "networkPluginMode": "overlay",
              "podCidr": "10.244.0.0/16"
            },
            "controlPlaneScalingProfile": {
              "scalingSize": "H2"
            }
          }
        }
      EOF
    }
  }
]
