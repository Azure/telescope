scenario_type  = "perf-eval"
scenario_name  = "ccp-provisioning-H2"
deletion_delay = "2h"
owner          = "aks"

aks_rest_config_list = [
  {
    role                       = "client"
    aks_name                   = "ccp-provisioning-H2"
    sku_tier                   = "Standard"
    sku_name                   = "Base"
    kubernetes_version         = "1.33"
    method                     = "PUT"
    api_version                = "2026-01-02-preview" # to construct url
    headers                     = {
      "Content-Type" = "application/json"
    }
    body = "scenarios/perf-eval/ccp-provisioning/kubernetes/azure-H2-body.json"
  }
]
